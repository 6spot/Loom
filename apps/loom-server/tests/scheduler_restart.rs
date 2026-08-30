use std::{
    env, fs,
    net::TcpListener,
    path::{Path, PathBuf},
    process::{Child, Command, ExitStatus, Stdio},
    str::FromStr,
    time::{Duration, Instant},
};

use futures_util::FutureExt;
use loom_api::{
    ActionInvocation, ActionRequest, ActionService, AdminService, AdminTimelineLogicalStatus,
    AdminWorkStatus, CreateWorldFromTemplateRequest, EventQuery, EventTypeId, FacetOwner,
    FacetQuery, FacetTypeId, HistoryService, QueryService, TimelineTarget, WorldInstant,
    WorldService, WorldTemplateDescriptor,
};
use loom_client::LoomClient;
use loom_neutral::{
    COUNTER_FACET, COUNTER_INCREMENT_ACTION, COUNTER_INCREMENTED_EVENT, COUNTER_SEED_ACTION,
    COUNTER_SEEDED_EVENT,
};
use serde_json::json;
use sqlx::postgres::{PgConnectOptions, PgPoolOptions};
use url::Url;
use uuid::Uuid;

const DEFAULT_POSTGRES_URL: &str = "postgresql://loom:loom@127.0.0.1:15432/loom_control";
const SERVER_REVISION_ID: &str = "loom-server";
const SERVER_BUILD_REF: &str = "loom-server-0.1.0";

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn postgres_url() -> Result<String, String> {
    if let Ok(url) = env::var("LOOM_TEST_POSTGRES_URL")
        && !url.trim().is_empty()
    {
        return Ok(url);
    }

    let status = Command::new("bash")
        .arg(repo_root().join("tools/postgres-test.sh"))
        .arg("up")
        .stdout(Stdio::null())
        .status()
        .map_err(|error| format!("failed to start the controlled PostgreSQL service: {error}"))?;
    if !status.success() {
        return Err(format!(
            "controlled PostgreSQL service failed to start with status {status}"
        ));
    }

    Ok(DEFAULT_POSTGRES_URL.to_owned())
}

fn free_port() -> Result<u16, String> {
    TcpListener::bind(("127.0.0.1", 0))
        .map_err(|error| format!("failed to reserve a server port: {error}"))?
        .local_addr()
        .map(|address| address.port())
        .map_err(|error| format!("failed to inspect the reserved server port: {error}"))
}

struct EphemeralDatabase {
    admin_url: String,
    name: String,
    url: String,
}

impl EphemeralDatabase {
    async fn create(base_url: &str) -> Result<Self, String> {
        let name = format!("loom_t20_{}", Uuid::new_v4().simple());
        // Database creation is test infrastructure isolation only. All
        // acceptance observations below use Loom's public HTTP contracts.
        let admin_options = PgConnectOptions::from_str(base_url)
            .map_err(|error| format!("invalid PostgreSQL test URL: {error}"))?
            .database("postgres");
        let admin_pool = PgPoolOptions::new()
            .max_connections(1)
            .connect_with(admin_options)
            .await
            .map_err(|error| format!("failed to connect to PostgreSQL admin database: {error}"))?;
        let create_database = format!("CREATE DATABASE \"{name}\"");
        sqlx::query(sqlx::AssertSqlSafe(create_database))
            .execute(&admin_pool)
            .await
            .map_err(|error| format!("failed to create isolated PostgreSQL database: {error}"))?;
        admin_pool.close().await;

        let mut application_url = Url::parse(base_url)
            .map_err(|error| format!("invalid PostgreSQL test URL: {error}"))?;
        application_url.set_path(&format!("/{name}"));

        Ok(Self {
            admin_url: base_url.to_owned(),
            name,
            url: application_url.to_string(),
        })
    }

    async fn cleanup(&self) -> Result<(), String> {
        let admin_options = PgConnectOptions::from_str(&self.admin_url)
            .map_err(|error| format!("invalid PostgreSQL test URL during cleanup: {error}"))?
            .database("postgres");
        let admin_pool = PgPoolOptions::new()
            .max_connections(1)
            .connect_with(admin_options)
            .await
            .map_err(|error| {
                format!("failed to reconnect to PostgreSQL for database cleanup: {error}")
            })?;
        let drop_database = format!("DROP DATABASE IF EXISTS \"{}\"", self.name);
        let result = sqlx::query(sqlx::AssertSqlSafe(drop_database))
            .execute(&admin_pool)
            .await;
        admin_pool.close().await;
        result
            .map(|_| ())
            .map_err(|error| format!("failed to drop isolated PostgreSQL database: {error}"))
    }
}

struct TestDataDir(PathBuf);

impl TestDataDir {
    fn new() -> Self {
        Self(
            repo_root()
                .join("target")
                .join(format!("scheduler-t20-restart-{}", Uuid::new_v4())),
        )
    }

    fn path(&self) -> &Path {
        &self.0
    }
}

impl Drop for TestDataDir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

struct ServerProcess {
    child: Child,
    port: u16,
}

impl ServerProcess {
    fn start(
        port: u16,
        database_url: &str,
        data_dir: &Path,
        revision_id: &str,
        build_ref: &str,
    ) -> Result<Self, String> {
        let child = Command::new(env!("CARGO_BIN_EXE_loom-server"))
            .current_dir(repo_root())
            .env("LOOM_DATABASE_URL", database_url)
            .env("LOOM_BIND_ADDR", format!("127.0.0.1:{port}"))
            .env("LOOM_DATA_DIR", data_dir)
            .env("LOOM_RUNTIME_REVISION_ID", revision_id)
            .env("LOOM_CORE_BUILD_REF", build_ref)
            .env("LOOM_WORKER_POLL_MS", "120000")
            .env("LOOM_WORKER_SCHEDULER_POLL_LIMIT", "1")
            .env("LOOM_RUNTIME_MAX_CHRONOLOGY_COMPLETIONS", "1")
            .env_remove("LOOM_SCHEDULER_WORLD_ID")
            .env_remove("LOOM_SCHEDULER_TIMELINE_ID")
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|error| format!("failed to start loom-server: {error}"))?;

        Ok(Self { child, port })
    }

    fn client(&self, timeout: Duration) -> Result<LoomClient, String> {
        LoomClient::builder(format!("http://127.0.0.1:{}", self.port))
            .timeout(timeout)
            .admin_token("validator-test-admin")
            .map_err(|error| format!("failed to configure test client: {error}"))?
            .build()
            .map_err(|error| format!("failed to build test client: {error}"))
    }

    async fn wait_until_ready(&mut self) -> Result<(), String> {
        let client = self.client(Duration::from_millis(500))?;

        for _ in 0..300 {
            if let Some(status) = self
                .child
                .try_wait()
                .map_err(|error| format!("failed to inspect loom-server: {error}"))?
            {
                return Err(format!(
                    "loom-server exited before readiness with status {status}"
                ));
            }

            if let Ok(Some(_)) = client.active_runtime_revision().await {
                return Ok(());
            }

            tokio::time::sleep(Duration::from_millis(50)).await;
        }

        Err("loom-server did not become ready within 15 seconds".to_owned())
    }

    fn stop(&mut self) -> Result<ExitStatus, String> {
        if let Some(status) = self
            .child
            .try_wait()
            .map_err(|error| format!("failed to inspect loom-server before stop: {error}"))?
        {
            return Ok(status);
        }

        terminate_child(&mut self.child)?;
        self.child
            .wait()
            .map_err(|error| format!("failed to wait for loom-server shutdown: {error}"))
    }
}

impl Drop for ServerProcess {
    fn drop(&mut self) {
        let running = self.child.try_wait().ok().flatten().is_none();
        if running {
            let _ = terminate_child(&mut self.child);
            let _ = self.child.wait();
        }
    }
}

fn terminate_child(child: &mut Child) -> Result<(), String> {
    #[cfg(unix)]
    {
        let pid = child.id().to_string();
        let signal_status = Command::new("kill")
            .args(["-TERM", pid.as_str()])
            .status()
            .map_err(|error| format!("failed to send SIGTERM to loom-server: {error}"))?;
        if signal_status.success() {
            return Ok(());
        }
    }

    child
        .kill()
        .map_err(|error| format!("failed to terminate loom-server: {error}"))
}

async fn wait_for_completed(
    process: &mut ServerProcess,
    client: &LoomClient,
    target: TimelineTarget,
    work_id: loom_api::WorkId,
) -> Result<AdminTimelineLogicalStatus, String> {
    let deadline = Instant::now() + Duration::from_secs(15);

    loop {
        if let Some(status) = process
            .child
            .try_wait()
            .map_err(|error| format!("failed to inspect restarted loom-server: {error}"))?
        {
            return Err(format!(
                "restarted loom-server exited while recovering work with status {status}"
            ));
        }

        let status = client
            .timeline_logical_status(target)
            .await
            .map_err(|error| format!("failed to read logical timeline status: {error}"))?;
        if status
            .works
            .iter()
            .any(|work| work.work_id == work_id && work.status == AdminWorkStatus::Completed)
        {
            return Ok(status);
        }

        if Instant::now() >= deadline {
            return Err(format!(
                "work {work_id} was not completed after the restart within 15 seconds"
            ));
        }

        tokio::time::sleep(Duration::from_millis(50)).await;
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn scheduler_pending_work_is_rediscovered_after_real_server_restart() -> Result<(), String> {
    let base_url = postgres_url()?;
    let database = EphemeralDatabase::create(&base_url).await?;
    let scenario_result = std::panic::AssertUnwindSafe(run_restart_scenario(&database.url))
        .catch_unwind()
        .await;
    let cleanup_result = database.cleanup().await;
    match scenario_result {
        Ok(result) => {
            result?;
            cleanup_result
        }
        Err(panic) => {
            cleanup_result?;
            std::panic::resume_unwind(panic);
        }
    }
}

#[expect(
    clippy::too_many_lines,
    reason = "the integration scenario keeps the restart evidence assertions together"
)]
async fn run_restart_scenario(database_url: &str) -> Result<(), String> {
    let data_dir = TestDataDir::new();
    let port = free_port()?;
    let revision_id = SERVER_REVISION_ID;
    let build_ref = SERVER_BUILD_REF;
    let entity_id = loom_api::EntityId::from(Uuid::new_v4());
    let seed_event_id = loom_api::EventId::from(Uuid::new_v4());
    let increment_event_id = loom_api::EventId::from(Uuid::new_v4());

    let mut first =
        ServerProcess::start(port, database_url, data_dir.path(), revision_id, build_ref)?;
    first.wait_until_ready().await?;
    let first_client = first.client(Duration::from_secs(5))?;

    // Let the one initial discovery cycle observe the empty database. The long poll interval
    // keeps this process from driving the Work created below before the intentional restart.
    tokio::time::sleep(Duration::from_millis(250)).await;

    let target = first_client
        .create_world_from_template(CreateWorldFromTemplateRequest::new(
            WorldTemplateDescriptor::new("scheduler.t20.restart", 1, WorldInstant::new(0))
                .requires_capability("neutral.counter", "^0.1.0")
                .with_bootstrap_action(ActionInvocation::new(
                    loom_api::ActionTypeId::from(COUNTER_SEED_ACTION),
                    json!({
                        "event_id": seed_event_id,
                        "entity_id": entity_id,
                        "value": 0,
                    }),
                )),
        ))
        .await
        .map_err(|error| format!("failed to create restart test world: {error}"))?
        .target;

    let increment = first_client
        .invoke(ActionRequest::new(
            target,
            ActionInvocation::new(
                loom_api::ActionTypeId::from(COUNTER_INCREMENT_ACTION),
                json!({
                    "event_id": increment_event_id,
                    "entity_id": entity_id,
                    "amount": 1,
                }),
            ),
        ))
        .await
        .map_err(|error| format!("failed to create pending scheduler Work: {error}"))?;
    assert!(matches!(
        increment,
        loom_api::ExecutionResult::Committed { .. }
    ));

    let before_status = first_client
        .timeline_logical_status(target)
        .await
        .map_err(|error| format!("failed to read pre-restart logical status: {error}"))?;
    let pending_work = before_status
        .works
        .iter()
        .find(|work| work.status == AdminWorkStatus::Pending)
        .ok_or_else(|| "the increment reaction did not persist a pending Work".to_owned())?;
    let pending_work_id = pending_work.work_id;
    assert_eq!(before_status.chronology_budget.consumed, 0);

    let before_events = first_client
        .list_events(EventQuery::all(target))
        .await
        .map_err(|error| format!("failed to read pre-restart history: {error}"))?;
    assert_eq!(before_events.len(), 2);
    assert!(before_events.iter().any(|event| event.id == seed_event_id));
    assert!(
        before_events
            .iter()
            .any(|event| event.id == increment_event_id)
    );

    let before_facet = first_client
        .get_facet(FacetQuery::new(
            target,
            FacetOwner::entity(entity_id),
            FacetTypeId::from(COUNTER_FACET),
        ))
        .await
        .map_err(|error| format!("failed to read pre-restart counter facet: {error}"))?
        .ok_or_else(|| "counter facet was not persisted before restart".to_owned())?;
    assert_eq!(before_facet.value["value"].as_i64(), Some(1));

    let first_pid = first.child.id();
    let first_exit = first.stop()?;
    assert!(
        first_exit.success(),
        "first loom-server did not shut down cleanly: {first_exit}"
    );
    drop(first_client);

    // This is a fresh OS process with a fresh SchedulerSupervisor and no copied discovery cursor.
    let mut second =
        ServerProcess::start(port, database_url, data_dir.path(), revision_id, build_ref)?;
    let second_pid = second.child.id();
    assert_ne!(first_pid, second_pid);
    second.wait_until_ready().await?;
    let second_client = second.client(Duration::from_secs(5))?;

    let after_status =
        wait_for_completed(&mut second, &second_client, target, pending_work_id).await?;
    let after_events = second_client
        .list_events(EventQuery::all(target))
        .await
        .map_err(|error| format!("failed to read post-restart history: {error}"))?;
    let after_facet = second_client
        .get_facet(FacetQuery::new(
            target,
            FacetOwner::entity(entity_id),
            FacetTypeId::from(COUNTER_FACET),
        ))
        .await
        .map_err(|error| format!("failed to read post-restart counter facet: {error}"))?
        .ok_or_else(|| "counter facet disappeared after restart".to_owned())?;

    let recovered_work = after_status
        .works
        .iter()
        .find(|work| work.work_id == pending_work_id)
        .ok_or_else(|| "the pre-restart Work disappeared from Admin status".to_owned())?;
    assert_eq!(recovered_work.status, AdminWorkStatus::Completed);
    assert!(after_status.version.state_revision > before_status.version.state_revision);
    assert!(after_status.logical_commit_count > before_status.logical_commit_count);
    assert_eq!(after_status.chronology_budget.consumed, 1);
    assert_eq!(after_events.len(), 3);
    assert!(
        after_events
            .iter()
            .any(|event| event.event_type == EventTypeId::from(COUNTER_SEEDED_EVENT))
    );
    assert_eq!(
        after_events
            .iter()
            .filter(|event| event.event_type == EventTypeId::from(COUNTER_INCREMENTED_EVENT))
            .count(),
        2
    );
    assert_eq!(after_facet.value["value"].as_i64(), Some(2));
    assert_eq!(
        after_status
            .works
            .iter()
            .filter(|work| work.status == AdminWorkStatus::Pending)
            .count(),
        1
    );

    let second_exit = second.stop()?;
    assert!(
        second_exit.success(),
        "restarted loom-server did not shut down cleanly: {second_exit}"
    );

    println!(
        "T20 restart evidence: backend=controlled-postgresql-18 server_boundary_restart=true first_pid={first_pid} first_stop={first_exit} second_pid={second_pid} second_stop={second_exit} target={target:?} recovered_work={pending_work_id} history=2->{} counter=1->2 cursor_reused=false scheduler_target_configured=false",
        after_events.len(),
    );

    Ok(())
}
