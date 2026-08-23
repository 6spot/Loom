mod support;

use std::{
    str::FromStr,
    sync::{Arc, Barrier},
};

use loom_api::{ApiErrorCode, TimelineTarget};
use loom_capability::{
    Capability, CapabilityManifest, CapabilityRegistrar, CapabilityRegistry, RegistrationError,
    ResolutionContext, ResolverError, WorkHandler, WorkHandlerDefinition,
};
use loom_core::{ExecutionSessionId, SchemaRevision, TimelineId, WorkHandlerId, WorkId, WorldId};
use loom_protocol::{NewWork, Resolution, ResolveOutcome, WorkMutation, WorkSchedule};
use loom_runtime::{
    ChronologyBudgetExceeded, CommitError, CommitStore, EffectEngine, IdentityAllocator,
    LogicalJournalStore, LogicalWorkTransition, PlatformTime, Runtime, RuntimeControlStore,
    TimelineDriverResult, WorkError, WorkStatus, WorkStore, WorkTerminalState, WorkTerminalization,
    WorldStore,
};
use loom_storage::PgStorage;
use serde_json::Value;
use sqlx::PgPool;
use support::TestDatabase;

const OWNER: &str = "postgres.work.test";
const HANDLER: &str = "postgres.work.handler";

fn id<T>(value: u128) -> T
where
    T: FromStr,
    T::Err: std::fmt::Debug,
{
    format!("00000000-0000-0000-0000-{value:012x}")
        .parse()
        .expect("test identity should parse")
}

struct WorkCapability {
    manifest: CapabilityManifest,
}

#[derive(Clone, Copy)]
struct TestIdentityAllocator {
    session_id: ExecutionSessionId,
}

impl IdentityAllocator for TestIdentityAllocator {
    fn allocate_world_id(&self) -> WorldId {
        id(0x2aff)
    }

    fn allocate_timeline_id(&self) -> TimelineId {
        id(0x2afe)
    }

    fn allocate_execution_session_id(&self) -> ExecutionSessionId {
        self.session_id
    }
}

struct EmptyHandler;

impl WorkHandler for EmptyHandler {
    fn handle(
        &self,
        _context: &dyn ResolutionContext,
        _payload: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        Ok(ResolveOutcome::Resolved(Resolution::default()))
    }
}

impl Capability for WorkCapability {
    fn manifest(&self) -> &CapabilityManifest {
        &self.manifest
    }

    fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
        registrar.register_work_handler(
            WorkHandlerDefinition::new(WorkHandlerId::from(HANDLER), SchemaRevision::new(1)),
            EmptyHandler,
        )
    }
}

fn registry() -> CapabilityRegistry {
    CapabilityRegistry::assemble([WorkCapability {
        manifest: CapabilityManifest::parse(OWNER, "0.1.0")
            .expect("test Capability manifest should parse"),
    }])
    .expect("test Capability registry should assemble")
}

async fn authority(seed: u128) -> Option<(TestDatabase, PgStorage, PgPool, WorldId, TimelineId)> {
    let database = TestDatabase::provision("work").await?;
    let storage = database.storage().await;
    let pool = database.pool().await;
    let world_id: WorldId = id(seed);
    let timeline_id: TimelineId = id(seed + 1);
    sqlx::query("INSERT INTO loom_world (world_id) VALUES ($1::uuid) ON CONFLICT DO NOTHING")
        .bind(world_id.to_string())
        .execute(&pool)
        .await
        .expect("test World should insert");
    sqlx::query(
        "INSERT INTO loom_timeline (timeline_id, world_id) VALUES ($1::uuid, $2::uuid) \
         ON CONFLICT DO NOTHING",
    )
    .bind(timeline_id.to_string())
    .bind(world_id.to_string())
    .execute(&pool)
    .await
    .expect("test Timeline should insert");
    Some((database, storage, pool, world_id, timeline_id))
}

async fn seed_work(
    pool: &PgPool,
    timeline_id: TimelineId,
    work_id: WorkId,
    available_at: i64,
    due_world_time: Option<i64>,
) {
    sqlx::query(
        "INSERT INTO loom_work \
         (timeline_id, work_id, target_kind, target_handler, schema_revision, payload, \
          effective_due_world_time, logical_schedule_order, status, attempt_count, \
          claim_generation, available_at) \
         VALUES ($1::uuid, $2::uuid, 'capability_work', $3, 1, '{}'::jsonb, $4, \
                 (SELECT COALESCE(MAX(logical_schedule_order), 0) + 1 \
                    FROM loom_work WHERE timeline_id = $1::uuid), \
                 'pending', 0, 0, $5)",
    )
    .bind(timeline_id.to_string())
    .bind(work_id.to_string())
    .bind(HANDLER)
    .bind(due_world_time.unwrap_or(0))
    .bind(available_at)
    .execute(pool)
    .await
    .expect("test Work should insert");
}

#[tokio::test]
async fn postgres_18_runtime_terminalization_survives_restart() {
    let Some((database, storage, pool, _world_id, timeline_id)) = authority(0x2600).await else {
        return;
    };
    let work_id: WorkId = id(0x2610);
    seed_work(&pool, timeline_id, work_id, 0, None).await;
    let before = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("initial Timeline should be readable");
    let terminalized = RuntimeControlStore::terminalize_work(
        &storage,
        &WorkTerminalization::new(
            timeline_id,
            before.version(),
            work_id,
            WorkTerminalState::Cancelled,
            PlatformTime::new(1),
        ),
    )
    .await
    .expect("Runtime Control cancellation should commit");
    assert_eq!(terminalized.state_revision.value(), 1);
    let journal_before_restart = LogicalJournalStore::read_logical_journal(&storage, timeline_id)
        .await
        .expect("terminalization journal should be readable");
    assert!(matches!(
        journal_before_restart.as_slice(),
        [commit] if matches!(
            commit.work_transitions.as_slice(),
            [LogicalWorkTransition::Cancel { work_id: cancelled_id }] if *cancelled_id == work_id
        )
    ));

    pool.close().await;
    storage.close().await;
    let restarted = database.storage().await;
    let after = WorldStore::snapshot(&restarted, timeline_id)
        .await
        .expect("terminalized Timeline should survive restart");
    assert_eq!(after.version().state_revision.value(), 1);
    assert!(after.events.is_empty());
    assert_eq!(
        LogicalJournalStore::read_logical_journal(&restarted, timeline_id)
            .await
            .expect("terminalization journal should survive restart"),
        journal_before_restart
    );
    let work = after
        .works
        .iter()
        .find(|work| work.id == work_id)
        .expect("cancelled Work should survive restart");
    assert_eq!(work.status, WorkStatus::Cancelled);
    assert!(work.lease.is_none());
    let claim = WorkStore::claim(
        &restarted,
        timeline_id,
        work_id,
        PlatformTime::new(2),
        PlatformTime::new(3),
    )
    .await
    .expect_err("terminal Work must remain non-claimable after restart");
    assert!(matches!(claim, WorkError::NotPending { .. }));

    restarted.close().await;
    database.cleanup().await;
}

#[tokio::test]
async fn postgres_18_runtime_terminalization_rejects_cross_work_claim_without_mutation() {
    let Some((database, storage, pool, _world_id, timeline_id)) = authority(0x2700).await else {
        return;
    };
    let claimed_work: WorkId = id(0x2710);
    let target_work: WorkId = id(0x2711);
    seed_work(&pool, timeline_id, claimed_work, 0, None).await;
    seed_work(&pool, timeline_id, target_work, 0, None).await;
    let claim = WorkStore::claim(
        &storage,
        timeline_id,
        claimed_work,
        PlatformTime::new(0),
        PlatformTime::new(10),
    )
    .await
    .expect("the claimed Work should have a live fence");
    let before = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("the pre-terminalization Timeline should be readable");

    let error = RuntimeControlStore::terminalize_work(
        &storage,
        &WorkTerminalization::new(
            timeline_id,
            before.version(),
            target_work,
            WorkTerminalState::Dead,
            PlatformTime::new(1),
        )
        .with_claim(claim),
    )
    .await
    .expect_err("a claim for another Work must be rejected");
    assert!(matches!(
        error,
        CommitError::Work(WorkError::WorkMismatch { expected, actual })
            if expected == target_work && actual == claimed_work
    ));

    let after = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("the post-rejection Timeline should be readable");
    assert_eq!(after.version(), before.version());
    assert_eq!(after.events, before.events);
    assert_eq!(after.journal, before.journal);
    assert_eq!(after.works, before.works);

    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}

#[tokio::test]
async fn postgres_18_runtime_failure_terminalization_recovers_stale_cas_without_reclaim() {
    let Some((database, storage, pool, _world_id, timeline_id)) = authority(0x2800).await else {
        return;
    };
    let work_id: WorkId = id(0x2810);
    let concurrent_work: WorkId = id(0x2811);
    seed_work(&pool, timeline_id, work_id, 0, None).await;
    let initial = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("the initial Timeline should be readable");
    let claim = WorkStore::claim(
        &storage,
        timeline_id,
        work_id,
        PlatformTime::new(0),
        PlatformTime::new(10),
    )
    .await
    .expect("the failure Work should have a live fence");

    let concurrent = validated(
        &storage,
        timeline_id,
        &registry(),
        Resolution::new(
            Vec::new(),
            vec![WorkMutation::Schedule(NewWork::new(
                concurrent_work,
                timeline_id,
                WorkHandlerId::from(HANDLER),
                SchemaRevision::new(1),
                serde_json::json!({}),
                WorkSchedule::Immediate,
            ))],
        ),
    )
    .await;
    CommitStore::commit(&storage, &concurrent, None, PlatformTime::new(1))
        .await
        .expect("the concurrent logical commit should advance the Timeline");

    let terminalization = WorkTerminalization::new(
        timeline_id,
        initial.version(),
        work_id,
        WorkTerminalState::Dead,
        PlatformTime::new(2),
    )
    .with_claim(claim)
    .with_last_error("handler failed");
    let stale = RuntimeControlStore::terminalize_work(&storage, &terminalization)
        .await
        .expect_err("the execution snapshot must be stale after the concurrent commit");
    assert!(matches!(stale, CommitError::TimelineConflict { .. }));

    let before_recovery = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("the current Timeline should be readable");
    let recovered = RuntimeControlStore::terminalize_current_work(&storage, &terminalization)
        .await
        .expect("bounded stale-CAS recovery should read the current version atomically");
    let after = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("the terminalized Timeline should be readable");
    assert_eq!(recovered, after.version());
    assert_eq!(after.version().state_revision.value(), 2);
    assert_eq!(after.journal.len(), 2);
    assert_eq!(after.events.len(), 0);
    assert_eq!(after.journal[1].before_version, before_recovery.version());
    assert!(matches!(
        after.journal[1].work_transitions.as_slice(),
        [LogicalWorkTransition::Dead { work_id: dead_id }] if *dead_id == work_id
    ));
    let terminal = after
        .works
        .iter()
        .find(|work| work.id == work_id)
        .expect("terminalized Work should remain readable");
    assert_eq!(terminal.status, WorkStatus::Dead);
    assert_eq!(terminal.attempt_count, 1);
    assert!(terminal.lease.is_none());

    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}

async fn validated(
    storage: &PgStorage,
    timeline_id: TimelineId,
    registry: &CapabilityRegistry,
    resolution: Resolution,
) -> loom_runtime::ValidatedResolution {
    let snapshot = WorldStore::snapshot(storage, timeline_id)
        .await
        .expect("test Timeline should be readable");
    EffectEngine::new(registry)
        .validate(&snapshot.world_view(), OWNER, resolution)
        .expect("test Resolution should validate")
}

#[tokio::test]
async fn postgres_18_work_concurrent_claims_choose_one_fence_winner() {
    let Some((database, storage, pool, _world_id, timeline_id)) = authority(0x2100).await else {
        return;
    };
    let work_id: WorkId = id(0x2110);
    seed_work(&pool, timeline_id, work_id, 0, None).await;

    let (first, second) = tokio::join!(
        WorkStore::claim(
            &storage,
            timeline_id,
            work_id,
            PlatformTime::new(10),
            PlatformTime::new(20)
        ),
        WorkStore::claim(
            &storage,
            timeline_id,
            work_id,
            PlatformTime::new(10),
            PlatformTime::new(20)
        ),
    );
    let results = [first, second];
    assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
    assert_eq!(
        results
            .iter()
            .filter(|result| matches!(result, Err(WorkError::AlreadyClaimed { .. })))
            .count(),
        1
    );

    let work = WorkStore::work(&storage, timeline_id, work_id)
        .await
        .expect("Work read should succeed")
        .expect("Work should remain present");
    assert_eq!(work.status, WorkStatus::Pending);
    assert_eq!(work.attempt_count, 1);
    assert_eq!(work.claim_generation, 1);
    assert_eq!(work.lease.expect("winner lease should persist").fence(), 1);
    let snapshot = WorldStore::snapshot(&storage, timeline_id).await.unwrap();
    assert_eq!(snapshot.version().state_revision.value(), 0);
    assert_eq!(snapshot.world_time().value(), 0);
    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}

#[tokio::test]
async fn postgres_18_work_expiry_reclaim_and_retry_fence_preserve_world_truth() {
    let Some((database, storage, pool, _world_id, timeline_id)) = authority(0x2200).await else {
        return;
    };
    let work_id: WorkId = id(0x2210);
    seed_work(&pool, timeline_id, work_id, 0, None).await;
    let first = WorkStore::claim(
        &storage,
        timeline_id,
        work_id,
        PlatformTime::new(10),
        PlatformTime::new(20),
    )
    .await
    .expect("first claim should succeed");
    let second = WorkStore::claim(
        &storage,
        timeline_id,
        work_id,
        PlatformTime::new(20),
        PlatformTime::new(30),
    )
    .await
    .expect("expired lease should be reclaimable");
    assert_eq!(first.fence(), 1);
    assert_eq!(second.fence(), 2);

    let stale = WorkStore::retry(
        &storage,
        &first,
        PlatformTime::new(21),
        PlatformTime::new(40),
        Some("stale".to_owned()),
    )
    .await
    .expect_err("old fence must not retry a re-claimed Work");
    assert!(matches!(stale, WorkError::StaleClaim { .. }));
    let retried = WorkStore::retry(
        &storage,
        &second,
        PlatformTime::new(21),
        PlatformTime::new(50),
        Some("technical".to_owned()),
    )
    .await
    .expect("live fence should record technical retry");
    assert_eq!(retried.id, work_id);
    assert_eq!(retried.status, WorkStatus::Pending);
    assert_eq!(retried.attempt_count, 2);
    assert_eq!(retried.claim_generation, 2);
    assert_eq!(retried.available_at, PlatformTime::new(50));
    assert!(retried.lease.is_none());

    let snapshot = WorldStore::snapshot(&storage, timeline_id).await.unwrap();
    assert!(snapshot.events.is_empty());
    assert_eq!(snapshot.version().state_revision.value(), 0);
    assert_eq!(snapshot.world_time().value(), 0);
    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}

#[tokio::test]
async fn postgres_18_scheduler_non_head_claim_is_rejected_without_mutation() {
    let Some((database, storage, pool, _world_id, timeline_id)) = authority(0x2150).await else {
        return;
    };
    let head_work: WorkId = id(0x2160);
    let non_head_work: WorkId = id(0x2161);
    seed_work(&pool, timeline_id, head_work, 0, None).await;
    seed_work(&pool, timeline_id, non_head_work, 0, None).await;
    let before = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("initial Timeline should be readable");

    let error = WorkStore::claim(
        &storage,
        timeline_id,
        non_head_work,
        PlatformTime::new(0),
        PlatformTime::new(10),
    )
    .await
    .expect_err("Scheduler claim must reject a non-head Work");
    assert!(matches!(
        error,
        WorkError::NotLogicalHead { work_id, head_work_id }
            if work_id == non_head_work && head_work_id == head_work
    ));

    let after = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("post-rejection Timeline should be readable");
    assert_eq!(after.version(), before.version());
    assert_eq!(after.events, before.events);
    assert_eq!(after.journal, before.journal);
    assert_eq!(after.works, before.works);

    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}

#[tokio::test]
async fn postgres_18_work_future_availability_and_world_due_are_not_claimed_early() {
    let Some((database, storage, pool, world_id, timeline_id)) = authority(0x2300).await else {
        return;
    };
    let unavailable: WorkId = id(0x2310);
    seed_work(&pool, timeline_id, unavailable, 100, None).await;
    let error = WorkStore::claim(
        &storage,
        timeline_id,
        unavailable,
        PlatformTime::new(99),
        PlatformTime::new(110),
    )
    .await
    .expect_err("platform-unavailable Work must not claim early");
    assert!(matches!(error, WorkError::NotAvailable { .. }));

    let future_world: WorkId = id(0x2311);
    seed_work(&pool, timeline_id, future_world, 0, Some(100)).await;
    let runtime = Runtime::new(storage.clone(), registry()).expect("Runtime should assemble");
    let error = runtime
        .execute_work(
            TimelineTarget::new(world_id, timeline_id),
            future_world,
            PlatformTime::new(10),
            PlatformTime::new(20),
            PlatformTime::new(30),
        )
        .await
        .expect_err("World-future Work must be rejected before claim");
    assert_eq!(error.code, ApiErrorCode::Unavailable);
    let work = WorkStore::work(&storage, timeline_id, future_world)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(work.attempt_count, 0);
    assert!(work.lease.is_none());
    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}

#[tokio::test]
async fn postgres_18_work_zero_event_runtime_completion_is_durable() {
    let Some((database, storage, pool, world_id, timeline_id)) = authority(0x2400).await else {
        return;
    };
    let work_id: WorkId = id(0x2410);
    seed_work(&pool, timeline_id, work_id, 0, None).await;
    let runtime = Runtime::new(storage.clone(), registry()).expect("Runtime should assemble");
    let result = runtime
        .execute_work(
            TimelineTarget::new(world_id, timeline_id),
            work_id,
            PlatformTime::new(10),
            PlatformTime::new(20),
            PlatformTime::new(30),
        )
        .await
        .expect("empty handler result should atomically complete Work");
    assert!(result.is_committed());
    let snapshot = WorldStore::snapshot(&storage, timeline_id).await.unwrap();
    let work = snapshot
        .works
        .iter()
        .find(|work| work.id == work_id)
        .expect("completed Work should remain readable");
    assert_eq!(work.status, WorkStatus::Completed);
    assert_eq!(work.attempt_count, 1);
    assert!(work.lease.is_none());
    assert!(snapshot.events.is_empty());
    assert_eq!(snapshot.version().head_event_seq.value(), 0);
    assert_eq!(snapshot.version().state_revision.value(), 1);
    assert_eq!(snapshot.world_time().value(), 0);
    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}

#[tokio::test]
async fn postgres_18_scheduler_budget_is_durable_across_restart() {
    let Some((database, storage, pool, world_id, timeline_id)) = authority(0x2450).await else {
        return;
    };
    let first_work: WorkId = id(0x2460);
    let second_work: WorkId = id(0x2461);
    seed_work(&pool, timeline_id, first_work, 0, None).await;
    seed_work(&pool, timeline_id, second_work, 0, None).await;

    let runtime = Runtime::new(storage.clone(), registry())
        .expect("Runtime should assemble")
        .with_chronology_budget_limit(1);
    let target = TimelineTarget::new(world_id, timeline_id);
    let executed = runtime
        .drive_timeline(
            target,
            PlatformTime::new(10),
            PlatformTime::new(20),
            PlatformTime::new(30),
        )
        .await
        .expect("the first due logical head should execute");
    assert!(matches!(
        executed,
        TimelineDriverResult::Executed { work_id, result }
            if work_id == first_work && result.is_committed()
    ));

    let exhausted = runtime
        .drive_timeline(
            target,
            PlatformTime::new(10),
            PlatformTime::new(20),
            PlatformTime::new(30),
        )
        .await
        .expect("budget exhaustion should be a typed driver result");
    assert!(matches!(
        exhausted,
        TimelineDriverResult::ChronologyBudgetExceeded(ChronologyBudgetExceeded {
            timeline_id: exhausted_timeline,
            world_time,
            limit: 1,
            consumed: 1,
        }) if exhausted_timeline == timeline_id && world_time.value() == 0
    ));

    let before_restart = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("budget snapshot should be readable before restart");
    assert_eq!(before_restart.chronology_budget().consumed, 1);
    assert_eq!(before_restart.journal.len(), 1);

    pool.close().await;
    storage.close().await;
    let restarted = database.storage().await;
    let after_restart = WorldStore::snapshot(&restarted, timeline_id)
        .await
        .expect("budget snapshot should survive restart");
    assert_eq!(after_restart.chronology_budget().consumed, 1);
    let restarted_runtime = Runtime::new(restarted.clone(), registry())
        .expect("restarted Runtime should assemble")
        .with_chronology_budget_limit(1);
    let restarted_result = restarted_runtime
        .drive_timeline(
            target,
            PlatformTime::new(10),
            PlatformTime::new(20),
            PlatformTime::new(30),
        )
        .await
        .expect("restarted budget exhaustion should remain observable");
    assert!(matches!(
        restarted_result,
        TimelineDriverResult::ChronologyBudgetExceeded(ChronologyBudgetExceeded {
            limit: 1,
            consumed: 1,
            ..
        })
    ));

    restarted.close().await;
    database.cleanup().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn postgres_18_independent_timeline_workers_resolve_concurrently() {
    let Some((database, storage, pool, world_a, timeline_a)) = authority(0x2a00).await else {
        return;
    };
    let world_b: WorldId = id(0x2a02);
    let timeline_b: TimelineId = id(0x2a03);
    let work_a: WorkId = id(0x2a10);
    let work_b: WorkId = id(0x2a11);
    sqlx::query("INSERT INTO loom_world (world_id) VALUES ($1::uuid)")
        .bind(world_b.to_string())
        .execute(&pool)
        .await
        .expect("second test World should insert");
    sqlx::query("INSERT INTO loom_timeline (timeline_id, world_id) VALUES ($1::uuid, $2::uuid)")
        .bind(timeline_b.to_string())
        .bind(world_b.to_string())
        .execute(&pool)
        .await
        .expect("second test Timeline should insert");
    seed_work(&pool, timeline_a, work_a, 0, None).await;
    seed_work(&pool, timeline_b, work_b, 0, None).await;

    let first_storage = database.storage().await;
    let second_storage = database.storage().await;
    let result = std::thread::scope(|scope| {
        let start = Arc::new(Barrier::new(2));
        let first_start = start.clone();
        let second_start = start.clone();
        let first = scope.spawn(move || {
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .expect("first worker executor should build");
            first_start.wait();
            runtime.block_on(async move {
                Runtime::new(first_storage, registry())
                    .expect("first worker Runtime should assemble")
                    .with_identity_allocator(TestIdentityAllocator {
                        session_id: id(0x2a20),
                    })
                    .drive_timeline(
                        TimelineTarget::new(world_a, timeline_a),
                        PlatformTime::new(10),
                        PlatformTime::new(20),
                        PlatformTime::new(30),
                    )
                    .await
            })
        });
        let second = scope.spawn(move || {
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .expect("second worker executor should build");
            second_start.wait();
            runtime.block_on(async move {
                Runtime::new(second_storage, registry())
                    .expect("second worker Runtime should assemble")
                    .with_identity_allocator(TestIdentityAllocator {
                        session_id: id(0x2a21),
                    })
                    .drive_timeline(
                        TimelineTarget::new(world_b, timeline_b),
                        PlatformTime::new(10),
                        PlatformTime::new(20),
                        PlatformTime::new(30),
                    )
                    .await
            })
        });
        (
            first.join().expect("first worker should finish"),
            second.join().expect("second worker should finish"),
        )
    });

    let first = result.0.expect("first independent Timeline should drive");
    let second = result.1.expect("second independent Timeline should drive");
    assert!(matches!(
        first,
        TimelineDriverResult::Executed { work_id, result }
            if work_id == work_a && result.is_committed()
    ));
    assert!(matches!(
        second,
        TimelineDriverResult::Executed { work_id, result }
            if work_id == work_b && result.is_committed()
    ));

    let first_work = WorkStore::work(&storage, timeline_a, work_a)
        .await
        .expect("first Work should remain readable")
        .expect("first Work should remain present")
        .status;
    let second_work = WorkStore::work(&storage, timeline_b, work_b)
        .await
        .expect("second Work should remain readable")
        .expect("second Work should remain present")
        .status;
    assert_eq!(first_work, WorkStatus::Completed);
    assert_eq!(second_work, WorkStatus::Completed);

    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}

#[tokio::test]
async fn postgres_18_work_completion_cancel_race_has_one_typed_winner() {
    let Some((database, storage, pool, _world_id, timeline_id)) = authority(0x2500).await else {
        return;
    };
    let work_id: WorkId = id(0x2510);
    seed_work(&pool, timeline_id, work_id, 0, None).await;
    let claim = WorkStore::claim(
        &storage,
        timeline_id,
        work_id,
        PlatformTime::new(10),
        PlatformTime::new(30),
    )
    .await
    .expect("race fixture should claim Work");
    let registry = CapabilityRegistry::new();
    let completion = validated(&storage, timeline_id, &registry, Resolution::default()).await;
    let cancellation = validated(
        &storage,
        timeline_id,
        &registry,
        Resolution::new(Vec::new(), vec![WorkMutation::Cancel(work_id)]),
    )
    .await;

    let (complete, cancel) = tokio::join!(
        CommitStore::commit(&storage, &completion, Some(&claim), PlatformTime::new(20)),
        CommitStore::commit(&storage, &cancellation, None, PlatformTime::new(20)),
    );
    let results = [complete, cancel];
    assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
    assert_eq!(
        results
            .iter()
            .filter(|result| matches!(result, Err(CommitError::TimelineConflict { .. })))
            .count(),
        1
    );
    let work = WorkStore::work(&storage, timeline_id, work_id)
        .await
        .unwrap()
        .unwrap();
    assert!(matches!(
        work.status,
        WorkStatus::Completed | WorkStatus::Cancelled
    ));
    assert!(work.lease.is_none());
    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}
