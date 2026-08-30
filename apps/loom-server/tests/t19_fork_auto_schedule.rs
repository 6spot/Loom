//! SCHD-T19 — prove a Timeline forked after startup is auto-scheduled.
//!
//! This is deliberately a black-box process test. The server is started with
//! no Scheduler target environment variables, all World operations cross the
//! HTTP boundary through `LoomClient`, and semantic assertions use only the
//! public service contracts. SQL is limited to provisioning/tearing down the
//! isolated `PostgreSQL` database and checking that the live service is PG18.

#![allow(clippy::too_many_lines)]

use std::{
    fs,
    net::TcpListener,
    path::{Path, PathBuf},
    process::{self, Child, Command, Stdio},
    sync::atomic::{AtomicU64, Ordering},
    time::{Duration, Instant},
};

use loom_api::{
    ActionInvocation, ActionRequest, ActionService, ActionTypeId, AdminService, AdminWorkStatus,
    CatalogService, CreateWorldFromTemplateRequest, EventQuery, FacetOwner, FacetQuery,
    HistoryService, QueryService, TimelineService, TimelineTarget, WorldInstant, WorldService,
    WorldTemplateDescriptor,
};
use loom_client::LoomClient;
use loom_neutral::{
    COUNTER_CAPABILITY, COUNTER_FACET, COUNTER_INCREMENT_ACTION, COUNTER_SEED_ACTION,
};
use loom_storage::PgStorage;
use serde_json::{Value, json};
use sqlx::{AssertSqlSafe, PgPool};
use url::Url;
use uuid::Uuid;

const DEFAULT_POSTGRES_CONTROL_URL: &str = "postgresql://loom:loom@127.0.0.1:15432/loom_control";
const SERVER_ADMIN_TOKEN: &str = "me-328-t19-admin";
const SERVER_POLL_MILLIS: &str = "1000";

static NEXT_DATABASE: AtomicU64 = AtomicU64::new(1);
static NEXT_DATA_DIR: AtomicU64 = AtomicU64::new(1);

#[derive(Debug)]
struct TestDatabase {
    control_pool: PgPool,
    database_name: String,
    database_url: String,
}

impl TestDatabase {
    async fn provision(label: &str) -> Self {
        let (control_url, uses_repository_default) = postgres_control_url();
        let control_pool = connect_control_database(&control_url, uses_repository_default).await;
        assert_postgres_18(&control_pool).await;

        let database_name = unique_database_name(label);
        let create_sql = format!("CREATE DATABASE {}", quote_identifier(&database_name));
        sqlx::query(AssertSqlSafe(create_sql))
            .execute(&control_pool)
            .await
            .expect("controlled PostgreSQL role should create an isolated T19 database");

        let database_url = child_database_url(&control_url, &database_name);
        let storage = PgStorage::connect(&database_url)
            .await
            .expect("isolated T19 PostgreSQL database should accept connections");
        if let Err(error) = storage.migrate().await {
            storage.close().await;
            drop_database(&control_pool, &database_name).await;
            panic!("isolated T19 database migrations should succeed: {error}");
        }
        storage.close().await;

        Self {
            control_pool,
            database_name,
            database_url,
        }
    }

    async fn cleanup(self) {
        drop_database(&self.control_pool, &self.database_name).await;
        self.control_pool.close().await;
    }
}

#[derive(Debug)]
struct ServerProcess {
    child: Child,
    base_url: String,
    data_dir: PathBuf,
}

impl ServerProcess {
    fn start(database_url: &str) -> Self {
        let port = free_loopback_port();
        let data_dir = unique_data_dir();
        let bind_addr = format!("127.0.0.1:{port}");
        let base_url = format!("http://{bind_addr}");

        let mut command = Command::new(env!("CARGO_BIN_EXE_loom-server"));
        command
            // Clearing the inherited environment proves that no ambient
            // LOOM_SCHEDULER_* target can affect this run.
            .env_clear()
            .env("LOOM_DATABASE_URL", database_url)
            .env("LOOM_BIND_ADDR", bind_addr)
            .env("LOOM_DATA_DIR", &data_dir)
            .env("LOOM_WORKER_POLL_MS", SERVER_POLL_MILLIS)
            .env("LOOM_WORKER_LEASE_MS", "5000")
            .env("LOOM_WORKER_RETRY_BACKOFF_MS", "0")
            .env("LOOM_WORKER_SCHEDULER_POLL_LIMIT", "16")
            .stdout(Stdio::null())
            .stderr(Stdio::null());

        let child = command
            .spawn()
            .expect("real loom-server binary should spawn");
        Self {
            child,
            base_url,
            data_dir,
        }
    }

    async fn wait_ready(&mut self, client: &LoomClient) {
        let deadline = Instant::now() + Duration::from_secs(30);
        loop {
            match self.child.try_wait() {
                Ok(Some(status)) => {
                    panic!("loom-server exited before readiness with status {status}")
                }
                Ok(None) => {}
                Err(error) => panic!("loom-server readiness check failed: {error}"),
            }

            if client.catalog().is_ok() {
                return;
            }
            assert!(
                Instant::now() < deadline,
                "loom-server did not expose its public catalog before the readiness deadline"
            );
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    }

    fn stop(&mut self) {
        terminate_child(&mut self.child);
    }
}

impl Drop for ServerProcess {
    fn drop(&mut self) {
        terminate_child(&mut self.child);
        let _ = fs::remove_dir_all(&self.data_dir);
    }
}

#[derive(Debug)]
struct Observation {
    snapshot: loom_api::TimelineSnapshot,
    logical: loom_api::AdminTimelineLogicalStatus,
    history: Vec<loom_api::CommittedEvent>,
    facet: Option<loom_api::FacetSnapshot>,
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn timeline_forked_after_startup_is_discovered_and_progressed() {
    let database = TestDatabase::provision("t19-fork").await;
    let mut server = ServerProcess::start(&database.database_url);
    let base_url = server_base_url(&server);
    let client = LoomClient::builder(base_url)
        .admin_token(SERVER_ADMIN_TOKEN)
        .expect("T19 admin token should be a valid HTTP header")
        .build()
        .expect("T19 client should build");
    server.wait_ready(&client).await;

    let entity_id = loom_api::EntityId::new(Uuid::new_v4());
    let seed_event_id = loom_api::EventId::new(Uuid::new_v4());
    let created = client
        .create_world_from_template(CreateWorldFromTemplateRequest::new(
            WorldTemplateDescriptor::new("scheduler-discovery.t19.fork", 1, WorldInstant::new(0))
                .requires_capability(COUNTER_CAPABILITY, "^0.1.0")
                .with_bootstrap_action(ActionInvocation::new(
                    ActionTypeId::from(COUNTER_SEED_ACTION),
                    json!({
                        "event_id": seed_event_id.to_string(),
                        "entity_id": entity_id.to_string(),
                        "value": 1,
                    }),
                )),
        ))
        .await
        .expect("source World should be created through the public HTTP API");
    let parent_target = created.target;
    let parent_before = observe(&client, parent_target, entity_id).await;
    assert_eq!(counter_value(&parent_before), 1);
    assert_eq!(parent_before.history.len(), 1);
    assert!(parent_before.logical.works.is_empty());

    // The fork is requested after the real server is ready and through the
    // formal Timeline API. No child identity is supplied to configuration.
    let forked = client
        .fork(loom_api::ForkTimelineRequest::new(parent_target))
        .await
        .expect("Timeline fork should succeed through the public HTTP API");
    assert_eq!(forked.target.world_id, parent_target.world_id);
    assert_ne!(forked.target.timeline_id, parent_target.timeline_id);
    assert_eq!(
        forked.ancestry.parent_timeline_id,
        Some(parent_target.timeline_id)
    );
    assert_eq!(
        forked.ancestry.fork_parent_version,
        Some(parent_before.snapshot.version)
    );

    let child_before = observe(&client, forked.target, entity_id).await;
    assert_eq!(child_before.snapshot, forked);
    assert_eq!(child_before.history, parent_before.history);
    assert_eq!(child_before.facet, parent_before.facet);
    assert!(child_before.logical.works.is_empty());

    // This Action is branch-local. Its reaction creates the representative
    // Pending Work that the already-running target-neutral Supervisor must
    // discover; the test never calls a driver or injects the child target.
    let child_event_id = loom_api::EventId::new(Uuid::new_v4());
    let action_result = client
        .invoke(ActionRequest::new(
            forked.target,
            ActionInvocation::new(
                ActionTypeId::from(COUNTER_INCREMENT_ACTION),
                json!({
                    "event_id": child_event_id.to_string(),
                    "entity_id": entity_id.to_string(),
                    "amount": 1,
                }),
            ),
        ))
        .await
        .expect("child increment should commit through the public HTTP API");
    assert!(action_result.is_committed());

    let child_after_action = observe(&client, forked.target, entity_id).await;
    assert!(
        child_after_action.logical.works.iter().any(|work| {
            matches!(
                work.status,
                AdminWorkStatus::Pending | AdminWorkStatus::Completed
            )
        }),
        "child action should expose a Scheduler obligation through Admin reads"
    );

    let child_final = wait_for_scheduler_progress(&client, forked.target, entity_id).await;
    assert!(
        counter_value(&child_final) >= 3,
        "child must include the direct increment and at least one automatic Work increment: {child_final:?}"
    );
    assert!(
        child_final.history.len() >= parent_before.history.len() + 2,
        "child history should expose both the direct action and automatic Work progression"
    );
    assert!(
        child_final
            .logical
            .works
            .iter()
            .any(|work| work.status == AdminWorkStatus::Completed),
        "child Scheduler Work should reach Completed through automatic discovery"
    );
    assert!(
        child_final.logical.logical_commit_count > child_before.logical.logical_commit_count,
        "child logical Admin status should advance after automatic Work progression"
    );

    let parent_after = observe(&client, parent_target, entity_id).await;
    assert_eq!(
        parent_after.snapshot, parent_before.snapshot,
        "child progression must not change the parent Timeline snapshot"
    );
    assert_eq!(
        parent_after.logical, parent_before.logical,
        "child progression must not change the parent logical Work status"
    );
    assert_eq!(
        parent_after.history, parent_before.history,
        "child progression must not append parent history"
    );
    assert_eq!(
        parent_after.facet, parent_before.facet,
        "child progression must not mutate the parent Facet"
    );

    assert!(
        server
            .child
            .try_wait()
            .expect("server process should be queryable")
            .is_none(),
        "the live server should remain running after the dynamic discovery proof"
    );
    server.stop();
    database.cleanup().await;
}

async fn observe(
    client: &LoomClient,
    target: TimelineTarget,
    entity_id: loom_api::EntityId,
) -> Observation {
    Observation {
        snapshot: client
            .inspect_timeline(target)
            .await
            .expect("formal Timeline inspect should succeed"),
        logical: client
            .timeline_logical_status(target)
            .await
            .expect("formal Admin logical status should succeed"),
        history: client
            .list_events(EventQuery::all(target))
            .await
            .expect("formal History read should succeed"),
        facet: client
            .get_facet(FacetQuery::new(
                target,
                FacetOwner::entity(entity_id),
                COUNTER_FACET.into(),
            ))
            .await
            .expect("formal Facet read should succeed"),
    }
}

fn counter_value(observation: &Observation) -> i64 {
    observation
        .facet
        .as_ref()
        .and_then(|facet| facet.value.get("value"))
        .and_then(Value::as_i64)
        .expect("counter Facet should expose an integer value")
}

async fn wait_for_scheduler_progress(
    client: &LoomClient,
    target: TimelineTarget,
    entity_id: loom_api::EntityId,
) -> Observation {
    let deadline = Instant::now() + Duration::from_secs(15);
    loop {
        let observation = observe(client, target, entity_id).await;
        let has_completed_work = observation
            .logical
            .works
            .iter()
            .any(|work| work.status == AdminWorkStatus::Completed);
        if counter_value(&observation) >= 3 && has_completed_work {
            return observation;
        }
        assert!(
            Instant::now() < deadline,
            "child Timeline did not progress automatically before the deadline: {observation:?}"
        );
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
}

fn server_base_url(server: &ServerProcess) -> String {
    server.base_url.clone()
}

fn free_loopback_port() -> u16 {
    let listener =
        TcpListener::bind(("127.0.0.1", 0)).expect("T19 should reserve a free loopback port");
    listener
        .local_addr()
        .expect("T19 loopback listener should expose its address")
        .port()
}

fn unique_data_dir() -> PathBuf {
    let counter = NEXT_DATA_DIR.fetch_add(1, Ordering::Relaxed);
    std::env::temp_dir().join(format!("loom-me328-t19-{}-{counter}", process::id()))
}

fn terminate_child(child: &mut Child) {
    if let Ok(Some(_)) = child.try_wait() {
        return;
    }
    let _ = child.kill();
    let _ = child.wait();
}

fn postgres_control_url() -> (String, bool) {
    match std::env::var("LOOM_TEST_POSTGRES_URL") {
        Ok(url) if !url.trim().is_empty() => (url, false),
        _ => (DEFAULT_POSTGRES_CONTROL_URL.to_owned(), true),
    }
}

async fn connect_control_database(control_url: &str, uses_repository_default: bool) -> PgPool {
    match PgPool::connect(control_url).await {
        Ok(pool) => pool,
        Err(error) if uses_repository_default => {
            start_repository_postgres(&error);
            PgPool::connect(control_url).await.unwrap_or_else(|retry_error| {
                panic!(
                    "repository-managed PostgreSQL test service is still unreachable after startup: {retry_error}"
                )
            })
        }
        Err(error) => panic!(
            "PostgreSQL control database from LOOM_TEST_POSTGRES_URL is unavailable: {error}"
        ),
    }
}

fn start_repository_postgres(initial_error: &sqlx::Error) {
    let script = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tools/postgres-test.sh");
    let status = Command::new("bash").arg(&script).arg("up").status();
    match status {
        Ok(status) if status.success() => {}
        Ok(status) => panic!(
            "default PostgreSQL control database was unreachable ({initial_error}); `{}` exited with {status}",
            script.display()
        ),
        Err(error) => panic!(
            "default PostgreSQL control database was unreachable ({initial_error}); failed to start `{}`: {error}",
            script.display()
        ),
    }
}

async fn assert_postgres_18(pool: &PgPool) {
    let server_version: i32 =
        sqlx::query_scalar("SELECT current_setting('server_version_num')::integer")
            .fetch_one(pool)
            .await
            .expect("controlled PostgreSQL should report its server version");
    assert!(
        (180_000..190_000).contains(&server_version),
        "T19 requires controlled PostgreSQL 18, got server_version_num={server_version}"
    );
}

fn child_database_url(control_url: &str, database_name: &str) -> String {
    let mut url = Url::parse(control_url).expect("LOOM_TEST_POSTGRES_URL should be a valid URL");
    url.set_path(&format!("/{database_name}"));
    url.to_string()
}

fn unique_database_name(label: &str) -> String {
    let label = label
        .chars()
        .filter(char::is_ascii_alphanumeric)
        .take(20)
        .collect::<String>()
        .to_ascii_lowercase();
    let counter = NEXT_DATABASE.fetch_add(1, Ordering::Relaxed);
    format!("loom_{label}_{}_{}", process::id(), counter)
}

fn quote_identifier(identifier: &str) -> String {
    debug_assert!(
        identifier
            .chars()
            .all(|character| character.is_ascii_lowercase()
                || character.is_ascii_digit()
                || character == '_')
    );
    format!("\"{identifier}\"")
}

async fn drop_database(control_pool: &PgPool, database_name: &str) {
    let drop_sql = format!(
        "DROP DATABASE IF EXISTS {} WITH (FORCE)",
        quote_identifier(database_name)
    );
    sqlx::query(AssertSqlSafe(drop_sql))
        .execute(control_pool)
        .await
        .expect("isolated T19 PostgreSQL database should be droppable");
}
