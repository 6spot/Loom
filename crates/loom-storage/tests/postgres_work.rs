mod support;

use std::str::FromStr;

use loom_api::{ApiErrorCode, TimelineTarget};
use loom_capability::{
    Capability, CapabilityManifest, CapabilityRegistrar, CapabilityRegistry, RegistrationError,
    ResolutionContext, ResolverError, WorkHandler, WorkHandlerDefinition,
};
use loom_core::{SchemaRevision, TimelineId, WorkHandlerId, WorkId, WorldId};
use loom_protocol::{Resolution, ResolveOutcome, WorkMutation};
use loom_runtime::{
    CommitError, CommitStore, EffectEngine, PlatformTime, Runtime, WorkError, WorkStatus,
    WorkStore, WorldStore,
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
         (timeline_id, work_id, handler, schema_revision, payload, due_world_time, status, \
          attempt_count, claim_generation, available_at) \
         VALUES ($1::uuid, $2::uuid, $3, 1, '{}'::jsonb, $4, 'pending', 0, 0, $5)",
    )
    .bind(timeline_id.to_string())
    .bind(work_id.to_string())
    .bind(HANDLER)
    .bind(due_world_time)
    .bind(available_at)
    .execute(pool)
    .await
    .expect("test Work should insert");
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
