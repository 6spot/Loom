use std::{
    fs,
    net::TcpListener,
    path::{Path, PathBuf},
    process::{Child, Command, ExitStatus, Stdio},
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
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
use loom_runtime::{PlatformTime, WorkError, WorkLease, WorkStatus};
use loom_storage::test_support::TestDatabase;
use serde_json::json;
use uuid::Uuid;

const SERVER_REVISION_ID: &str = "loom-server";
const SERVER_BUILD_REF: &str = "loom-server-0.1.0";
const WORKER_POLL_MS: u64 = 120_000;
const INITIAL_LEASE_MS: i64 = 10_000;
const RETRY_BACKOFF_MS: i64 = 250;
const RECLAIM_LEASE_MS: i64 = 250;

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn free_port() -> Result<u16, String> {
    TcpListener::bind(("127.0.0.1", 0))
        .map_err(|error| format!("failed to reserve a server port: {error}"))?
        .local_addr()
        .map(|address| address.port())
        .map_err(|error| format!("failed to inspect the reserved server port: {error}"))
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
            .env("LOOM_WORKER_POLL_MS", WORKER_POLL_MS.to_string())
            .env("LOOM_WORKER_LEASE_MS", "30000")
            .env("LOOM_WORKER_RETRY_BACKOFF_MS", RETRY_BACKOFF_MS.to_string())
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
    let database = TestDatabase::provision("scheduler-t20").await;
    let scenario_result = std::panic::AssertUnwindSafe(run_restart_scenario(&database))
        .catch_unwind()
        .await;
    match scenario_result {
        Ok(result) => {
            result?;
            database.cleanup().await;
            Ok(())
        }
        Err(panic) => {
            database.cleanup().await;
            std::panic::resume_unwind(panic);
        }
    }
}

fn platform_now() -> PlatformTime {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("platform clock should be after Unix epoch")
        .as_millis();
    PlatformTime::new(i64::try_from(millis).expect("platform time should fit i64"))
}

fn platform_after(now: PlatformTime, duration_ms: i64) -> PlatformTime {
    PlatformTime::new(
        now.value()
            .checked_add(duration_ms)
            .expect("test platform time should not overflow"),
    )
}

async fn wait_until_platform_time(deadline: PlatformTime) {
    while platform_now() < deadline {
        let remaining = deadline.value() - platform_now().value();
        let sleep_ms = u64::try_from(remaining.min(50)).unwrap_or(1).max(1);
        tokio::time::sleep(Duration::from_millis(sleep_ms)).await;
    }
}

#[expect(
    clippy::too_many_lines,
    reason = "the integration scenario keeps the restart evidence assertions together"
)]
async fn run_restart_scenario(database: &TestDatabase) -> Result<(), String> {
    let data_dir = TestDataDir::new();
    let port = free_port()?;
    let revision_id = SERVER_REVISION_ID;
    let build_ref = SERVER_BUILD_REF;
    let entity_id = loom_api::EntityId::from(Uuid::new_v4());
    let seed_event_id = loom_api::EventId::from(Uuid::new_v4());
    let increment_event_id = loom_api::EventId::from(Uuid::new_v4());

    let mut first = ServerProcess::start(
        port,
        database.database_url(),
        data_dir.path(),
        revision_id,
        build_ref,
    )?;
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

    // Arrange the persisted operational states through the storage-owned Work
    // port. The application never drives Scheduler manually: after the real
    // process boundary below, the fresh server must reclaim and execute this
    // same logical Work through its normal discovery cycle.
    let first_claim_now = platform_now();
    let first_claim = database
        .claim_work(
            target.timeline_id,
            pending_work_id,
            first_claim_now,
            platform_after(first_claim_now, INITIAL_LEASE_MS),
        )
        .await
        .map_err(|error| format!("failed to arrange claimed Work state: {error}"))?;
    let claimed_work = database
        .read_work(target.timeline_id, pending_work_id)
        .await
        .map_err(|error| format!("failed to read claimed Work state: {error}"))?
        .ok_or_else(|| "claimed Work disappeared from storage".to_owned())?;
    assert_eq!(claimed_work.status, WorkStatus::Pending);
    assert_eq!(claimed_work.attempt_count, 1);
    assert_eq!(claimed_work.claim_generation, first_claim.fence());
    assert_eq!(
        claimed_work.lease.map(WorkLease::fence),
        Some(first_claim.fence())
    );

    let retry_available_at = platform_after(first_claim_now, RETRY_BACKOFF_MS);
    let retried_work = database
        .retry_work(
            &first_claim,
            platform_now(),
            retry_available_at,
            Some("restart-fixture technical retry".to_owned()),
        )
        .await
        .map_err(|error| format!("failed to arrange retryable Work state: {error}"))?;
    assert_eq!(retried_work.id, pending_work_id);
    assert_eq!(retried_work.status, WorkStatus::Pending);
    assert_eq!(retried_work.attempt_count, 1);
    assert_eq!(retried_work.claim_generation, first_claim.fence());
    assert!(retried_work.lease.is_none());
    assert_eq!(
        retried_work.last_error.as_deref(),
        Some("restart-fixture technical retry")
    );
    assert_eq!(
        retried_work.logical_schedule_order,
        pending_work.logical_schedule_order
    );

    // Re-claim after the retry is available and leave this second lease in
    // PostgreSQL while the first server is stopped. This makes lease expiry,
    // monotonic fencing and recovery observable at the real restart boundary.
    wait_until_platform_time(retry_available_at).await;
    let second_claim_now = platform_now();
    let second_claim = database
        .claim_work(
            target.timeline_id,
            pending_work_id,
            second_claim_now,
            platform_after(second_claim_now, RECLAIM_LEASE_MS),
        )
        .await
        .map_err(|error| format!("failed to arrange reclaimed Work lease: {error}"))?;
    assert!(second_claim.fence() > first_claim.fence());
    let stale_retry = database
        .retry_work(
            &first_claim,
            second_claim_now,
            platform_after(second_claim_now, 1),
            Some("stale worker must not retry".to_owned()),
        )
        .await;
    assert!(matches!(stale_retry, Err(WorkError::StaleClaim { .. })));
    let leased_work = database
        .read_work(target.timeline_id, pending_work_id)
        .await
        .map_err(|error| format!("failed to read restart lease state: {error}"))?
        .ok_or_else(|| "reclaimed Work disappeared before restart".to_owned())?;
    assert_eq!(leased_work.status, WorkStatus::Pending);
    assert_eq!(leased_work.attempt_count, 2);
    assert_eq!(leased_work.claim_generation, second_claim.fence());
    assert_eq!(
        leased_work.lease.map(WorkLease::fence),
        Some(second_claim.fence())
    );
    let stale_worker_state = database
        .read_work(target.timeline_id, pending_work_id)
        .await
        .map_err(|error| format!("failed to re-read fenced Work state: {error}"))?
        .ok_or_else(|| "fenced Work disappeared after stale retry rejection".to_owned())?;
    assert_eq!(stale_worker_state.attempt_count, 2);
    assert_eq!(stale_worker_state.claim_generation, second_claim.fence());
    assert_eq!(
        stale_worker_state.lease.map(WorkLease::fence),
        Some(second_claim.fence())
    );

    let first_pid = first.child.id();
    let first_exit = first.stop()?;
    assert!(
        first_exit.success(),
        "first loom-server did not shut down cleanly: {first_exit}"
    );
    drop(first_client);

    wait_until_platform_time(second_claim.claimed_until()).await;
    let lease_expired_before_restart_recovery = platform_now() >= second_claim.claimed_until();

    // This is a fresh OS process with a fresh SchedulerSupervisor and no copied discovery cursor.
    let mut second = ServerProcess::start(
        port,
        database.database_url(),
        data_dir.path(),
        revision_id,
        build_ref,
    )?;
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
    let persisted_recovery = database
        .read_work(target.timeline_id, pending_work_id)
        .await
        .map_err(|error| format!("failed to read recovered Work state: {error}"))?
        .ok_or_else(|| "recovered Work disappeared from storage".to_owned())?;
    assert_eq!(persisted_recovery.status, WorkStatus::Completed);
    assert_eq!(persisted_recovery.attempt_count, 3);
    assert_eq!(
        persisted_recovery.claim_generation,
        second_claim.fence() + 1
    );
    assert!(persisted_recovery.lease.is_none());
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
        "T20 restart evidence: backend=controlled-postgresql-18 server_boundary_restart=true first_pid={first_pid} first_stop={first_exit} second_pid={second_pid} second_stop={second_exit} target={target:?} recovered_work={pending_work_id} first_claim_fence={} retry_attempt=1 second_claim_fence={} lease_expired_before_recovery={lease_expired_before_restart_recovery} recovery_attempt={} history=2->{} counter=1->2 cursor_reused=false scheduler_target_configured=false stale_fence_rejected=true",
        first_claim.fence(),
        second_claim.fence(),
        persisted_recovery.attempt_count,
        after_events.len(),
    );

    Ok(())
}
