mod support;

use std::str::FromStr;

use loom_capability::CapabilityRegistry;
use loom_core::{
    SchemaRevision, TimelineAncestry, TimelineId, WorkHandlerId, WorkId, WorldInstant,
};
use loom_protocol::WorkTarget;
use loom_runtime::{
    BaseWorldSnapshot, ChronologyBudgetState, CommittedEvent, LogicalCommit, PlatformTime, Runtime,
    SchedulerDiscoveryCursor, SchedulerDiscoveryError, SchedulerDiscoveryPage,
    SchedulerDiscoveryRequest, SchedulerDiscoveryTarget, TimelineSnapshot, WorkLease, WorkRecord,
    WorkStatus, WorldStore,
};
use loom_storage::InMemoryStore;
use serde_json::json;
use sqlx::PgPool;

use support::TestDatabase;

const PARITY_HANDLER: &str = "scheduler.discovery.parity";

type Target = SchedulerDiscoveryTarget;

#[derive(Clone, Copy, Debug)]
struct DiscoveryFixture {
    no_pending: Target,
    one_pending: Target,
    duplicate_pending: Target,
    terminal_only: Target,
    future_pending: Target,
    first_multi_target: Target,
    second_multi_target: Target,
}

impl DiscoveryFixture {
    fn all_targets(self) -> [Target; 7] {
        [
            self.no_pending,
            self.one_pending,
            self.duplicate_pending,
            self.terminal_only,
            self.future_pending,
            self.first_multi_target,
            self.second_multi_target,
        ]
    }

    fn expected_pending_targets(self) -> [Target; 5] {
        [
            self.one_pending,
            self.duplicate_pending,
            self.future_pending,
            self.first_multi_target,
            self.second_multi_target,
        ]
    }
}

#[derive(Clone, Copy, Debug)]
struct WorkSpec {
    timeline_id: TimelineId,
    work_id: WorkId,
    logical_schedule_order: u64,
    status: WorkStatus,
    due_world_time: i64,
    available_at: i64,
    lease: Option<WorkLease>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct DiscoveryMatrix {
    first: SchedulerDiscoveryPage,
    resumed: SchedulerDiscoveryPage,
    final_page: SchedulerDiscoveryPage,
    all: SchedulerDiscoveryPage,
    repeated: SchedulerDiscoveryPage,
}

#[derive(Clone, Debug, PartialEq)]
struct SnapshotState {
    base: BaseWorldSnapshot,
    events: Vec<CommittedEvent>,
    works: Vec<WorkRecord>,
    journal: Vec<LogicalCommit>,
    ancestry: TimelineAncestry,
    chronology_budget: ChronologyBudgetState,
}

fn id<T>(value: u128) -> T
where
    T: FromStr,
    T::Err: std::fmt::Debug,
{
    format!("00000000-0000-0000-0000-{value:012x}")
        .parse()
        .expect("test identity should parse")
}

fn target(world: u128, timeline: u128) -> Target {
    Target::new(id(world), id(timeline))
}

fn fixture() -> DiscoveryFixture {
    DiscoveryFixture {
        no_pending: target(0x1000, 0x1001),
        one_pending: target(0x2000, 0x2001),
        duplicate_pending: target(0x3000, 0x3001),
        terminal_only: target(0x4000, 0x4001),
        future_pending: target(0x5000, 0x5001),
        first_multi_target: target(0x6000, 0x6001),
        second_multi_target: target(0x6000, 0x6002),
    }
}

fn work_specs(fixture: DiscoveryFixture) -> Vec<WorkSpec> {
    vec![
        WorkSpec {
            timeline_id: fixture.one_pending.timeline_id,
            work_id: id(0x2101),
            logical_schedule_order: 1,
            status: WorkStatus::Pending,
            due_world_time: 0,
            available_at: 0,
            lease: None,
        },
        WorkSpec {
            timeline_id: fixture.duplicate_pending.timeline_id,
            work_id: id(0x3101),
            logical_schedule_order: 1,
            status: WorkStatus::Pending,
            due_world_time: 0,
            available_at: 0,
            lease: None,
        },
        WorkSpec {
            timeline_id: fixture.duplicate_pending.timeline_id,
            work_id: id(0x3102),
            logical_schedule_order: 2,
            status: WorkStatus::Pending,
            due_world_time: 0,
            available_at: 0,
            lease: None,
        },
        WorkSpec {
            timeline_id: fixture.terminal_only.timeline_id,
            work_id: id(0x4101),
            logical_schedule_order: 1,
            status: WorkStatus::Completed,
            due_world_time: 0,
            available_at: 0,
            lease: None,
        },
        WorkSpec {
            timeline_id: fixture.terminal_only.timeline_id,
            work_id: id(0x4102),
            logical_schedule_order: 2,
            status: WorkStatus::Cancelled,
            due_world_time: 0,
            available_at: 0,
            lease: None,
        },
        WorkSpec {
            timeline_id: fixture.terminal_only.timeline_id,
            work_id: id(0x4103),
            logical_schedule_order: 3,
            status: WorkStatus::Dead,
            due_world_time: 0,
            available_at: 0,
            lease: None,
        },
        WorkSpec {
            timeline_id: fixture.future_pending.timeline_id,
            work_id: id(0x5101),
            logical_schedule_order: 1,
            status: WorkStatus::Pending,
            due_world_time: 100,
            available_at: 1_000,
            lease: Some(WorkLease::new(PlatformTime::new(2_000), 7)),
        },
        WorkSpec {
            timeline_id: fixture.first_multi_target.timeline_id,
            work_id: id(0x6101),
            logical_schedule_order: 1,
            status: WorkStatus::Pending,
            due_world_time: 0,
            available_at: 0,
            lease: None,
        },
        WorkSpec {
            timeline_id: fixture.second_multi_target.timeline_id,
            work_id: id(0x6102),
            logical_schedule_order: 1,
            status: WorkStatus::Pending,
            due_world_time: 0,
            available_at: 0,
            lease: None,
        },
    ]
}

fn in_memory_work(spec: WorkSpec) -> WorkRecord {
    WorkRecord {
        id: spec.work_id,
        timeline_id: spec.timeline_id,
        target: WorkTarget::CapabilityWork {
            owner: None,
            handler: WorkHandlerId::from(PARITY_HANDLER),
        },
        schema_revision: SchemaRevision::new(1),
        payload: json!({"work_id": spec.work_id.to_string()}),
        effective_due_world_time: WorldInstant::new(spec.due_world_time),
        logical_schedule_order: spec.logical_schedule_order,
        causal_event_id: None,
        origin_work_id: None,
        status: spec.status,
        attempt_count: 0,
        claim_generation: 0,
        available_at: PlatformTime::new(spec.available_at),
        last_error: None,
        lease: spec.lease,
    }
}

fn seed_in_memory(store: &InMemoryStore, fixture: DiscoveryFixture) {
    for target in fixture.all_targets() {
        store
            .create_timeline(target.world_id, target.timeline_id)
            .expect("fixture Timeline should be created");
    }
    for spec in work_specs(fixture) {
        store
            .seed_work(in_memory_work(spec))
            .expect("fixture Work should be seeded");
    }
}

async fn insert_target(pool: &PgPool, target: Target) {
    sqlx::query("INSERT INTO loom_world (world_id) VALUES ($1::uuid) ON CONFLICT DO NOTHING")
        .bind(target.world_id.to_string())
        .execute(pool)
        .await
        .expect("fixture World should be inserted");
    sqlx::query("INSERT INTO loom_timeline (timeline_id, world_id) VALUES ($1::uuid, $2::uuid)")
        .bind(target.timeline_id.to_string())
        .bind(target.world_id.to_string())
        .execute(pool)
        .await
        .expect("fixture Timeline should be inserted");
}

fn sql_status(status: WorkStatus) -> &'static str {
    match status {
        WorkStatus::Pending => "pending",
        WorkStatus::Completed => "completed",
        WorkStatus::Cancelled => "cancelled",
        WorkStatus::Dead => "dead",
    }
}

async fn insert_work(pool: &PgPool, spec: WorkSpec) {
    sqlx::query(
        "INSERT INTO loom_work \
         (timeline_id, work_id, target_kind, target_handler, schema_revision, payload, \
          effective_due_world_time, logical_schedule_order, status, attempt_count, \
          claim_generation, available_at) \
         VALUES ($1::uuid, $2::uuid, 'capability_work', $3, 1, $4::jsonb, $5, $6, $7, 0, 0, $8)",
    )
    .bind(spec.timeline_id.to_string())
    .bind(spec.work_id.to_string())
    .bind(PARITY_HANDLER)
    .bind(json!({"work_id": spec.work_id.to_string()}))
    .bind(spec.due_world_time)
    .bind(i64::try_from(spec.logical_schedule_order).expect("fixture order fits in i64"))
    .bind(sql_status(spec.status))
    .bind(spec.available_at)
    .execute(pool)
    .await
    .expect("fixture Work should be inserted");

    if let Some(lease) = spec.lease {
        sqlx::query(
            "UPDATE loom_work SET lease_claimed_until = $3, lease_fence = $4::numeric \
             WHERE timeline_id = $1::uuid AND work_id = $2::uuid",
        )
        .bind(spec.timeline_id.to_string())
        .bind(spec.work_id.to_string())
        .bind(lease.claimed_until().value())
        .bind(lease.fence().to_string())
        .execute(pool)
        .await
        .expect("fixture Work lease should be inserted");
    }
}

async fn seed_postgres(pool: &PgPool, fixture: DiscoveryFixture) {
    for target in fixture.all_targets() {
        insert_target(pool, target).await;
    }
    for spec in work_specs(fixture) {
        insert_work(pool, spec).await;
    }
}

async fn collect_matrix<S>(runtime: &Runtime<S>) -> DiscoveryMatrix
where
    S: loom_runtime::SchedulerDiscoveryStore,
{
    let first = runtime
        .discover_scheduler_targets(
            SchedulerDiscoveryRequest::new(2).expect("matrix page bound should be valid"),
        )
        .await
        .expect("first Runtime discovery page should succeed");
    let cursor = first
        .continuation()
        .expect("first bounded page should have a continuation");
    let resumed = runtime
        .discover_scheduler_targets(
            SchedulerDiscoveryRequest::new(2)
                .expect("matrix continuation bound should be valid")
                .with_cursor(cursor),
        )
        .await
        .expect("continued Runtime discovery page should succeed");
    let final_cursor = resumed
        .continuation()
        .expect("second bounded page should have a continuation");
    let final_page = runtime
        .discover_scheduler_targets(
            SchedulerDiscoveryRequest::new(2)
                .expect("final continuation bound should be valid")
                .with_cursor(final_cursor),
        )
        .await
        .expect("final Runtime discovery page should succeed");
    let all = runtime
        .discover_scheduler_targets(
            SchedulerDiscoveryRequest::new(256).expect("full matrix bound should be valid"),
        )
        .await
        .expect("full Runtime discovery page should succeed");
    let repeated = runtime
        .discover_scheduler_targets(
            SchedulerDiscoveryRequest::new(256).expect("repeated matrix bound should be valid"),
        )
        .await
        .expect("repeated Runtime discovery page should succeed");
    DiscoveryMatrix {
        first,
        resumed,
        final_page,
        all,
        repeated,
    }
}

async fn snapshot_states<S>(store: &S, fixture: DiscoveryFixture) -> Vec<(Target, SnapshotState)>
where
    S: WorldStore,
{
    let mut states = Vec::with_capacity(fixture.all_targets().len());
    for target in fixture.all_targets() {
        let snapshot = WorldStore::snapshot(store, target.timeline_id)
            .await
            .expect("fixture Timeline snapshot should be readable");
        states.push((target, snapshot_state(&snapshot)));
    }
    states
}

fn snapshot_state(snapshot: &TimelineSnapshot) -> SnapshotState {
    SnapshotState {
        base: snapshot.base.clone(),
        events: snapshot.events.clone(),
        works: snapshot.works.clone(),
        journal: snapshot.logical_journal().to_vec(),
        ancestry: snapshot.ancestry(),
        chronology_budget: snapshot.chronology_budget(),
    }
}

fn assert_matrix(matrix: &DiscoveryMatrix, fixture: DiscoveryFixture) {
    let expected = fixture.expected_pending_targets();
    assert_eq!(matrix.first.targets, expected[..2].to_vec());
    assert_eq!(
        matrix.first.continuation(),
        Some(SchedulerDiscoveryCursor::after(expected[1]))
    );
    assert_eq!(
        matrix.first.targets.len(),
        2,
        "the page bound must be enforced"
    );
    assert_eq!(matrix.resumed.targets, expected[2..4].to_vec());
    assert_eq!(
        matrix.resumed.continuation(),
        Some(SchedulerDiscoveryCursor::after(expected[3]))
    );
    assert_eq!(matrix.final_page.targets, expected[4..].to_vec());
    assert_eq!(matrix.final_page.continuation(), None);
    assert_eq!(matrix.all.targets, expected.to_vec());
    assert_eq!(matrix.all.continuation(), None);
    assert_eq!(matrix.repeated, matrix.all);

    assert_eq!(
        matrix
            .all
            .targets
            .iter()
            .filter(|target| **target == fixture.duplicate_pending)
            .count(),
        1,
        "several Pending Work items on one Timeline must return one target"
    );
    assert!(
        !matrix.all.targets.contains(&fixture.no_pending),
        "a Timeline without Pending Work must not be discovered"
    );
    assert!(
        !matrix.all.targets.contains(&fixture.terminal_only),
        "terminal-only Work must not make a Timeline discoverable"
    );
    assert!(
        matrix.all.targets.contains(&fixture.future_pending),
        "future-World-Time Pending Work must remain discoverable"
    );
    assert!(
        matrix.all.targets.contains(&fixture.first_multi_target)
            && matrix.all.targets.contains(&fixture.second_multi_target),
        "multiple World/Timeline identities must be preserved"
    );
}

async fn assert_invalid_bound<S>(runtime: &Runtime<S>)
where
    S: loom_runtime::SchedulerDiscoveryStore,
{
    for page_size in [0, loom_runtime::MAX_SCHEDULER_DISCOVERY_PAGE_SIZE + 1] {
        let invalid = SchedulerDiscoveryRequest {
            page_size,
            cursor: None,
        };
        let error = runtime.discover_scheduler_targets(invalid).await;
        assert_eq!(
            error,
            Err(SchedulerDiscoveryError::InvalidPageSize {
                max: loom_runtime::MAX_SCHEDULER_DISCOVERY_PAGE_SIZE,
                actual: page_size,
            })
        );
    }
}

#[tokio::test]
async fn scheduler_discovery_runtime_matrix_matches_inmemory_and_postgres_18() {
    let fixture = fixture();

    let in_memory = InMemoryStore::new();
    seed_in_memory(&in_memory, fixture);
    let in_memory_before = snapshot_states(&in_memory, fixture).await;
    let in_memory_runtime =
        Runtime::new(&in_memory, CapabilityRegistry::new()).expect("InMemory Runtime assembly");
    let in_memory_matrix = collect_matrix(&in_memory_runtime).await;
    assert_invalid_bound(&in_memory_runtime).await;
    let in_memory_after = snapshot_states(&in_memory, fixture).await;
    assert_eq!(
        in_memory_before, in_memory_after,
        "InMemory discovery must not mutate Work or Timeline state"
    );
    assert_matrix(&in_memory_matrix, fixture);

    let database = TestDatabase::provision("scheduler-discovery-parity").await;
    let storage = database.storage().await;
    let pool = database.pool().await;
    seed_postgres(&pool, fixture).await;
    let postgres_before = snapshot_states(&storage, fixture).await;
    let postgres_runtime =
        Runtime::new(&storage, CapabilityRegistry::new()).expect("PostgreSQL Runtime assembly");
    let postgres_matrix = collect_matrix(&postgres_runtime).await;
    assert_invalid_bound(&postgres_runtime).await;
    let postgres_after = snapshot_states(&storage, fixture).await;
    assert_eq!(
        postgres_before, postgres_after,
        "PostgreSQL discovery must not mutate Work or Timeline state"
    );
    assert_matrix(&postgres_matrix, fixture);

    assert_eq!(
        in_memory_matrix, postgres_matrix,
        "Runtime discovery pages and continuations must be backend-equivalent"
    );

    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}

#[tokio::test]
async fn scheduler_discovery_runtime_empty_pending_set_is_empty_on_both_backends() {
    let empty_target = target(0x7000, 0x7001);
    let in_memory = InMemoryStore::new();
    in_memory
        .create_timeline(empty_target.world_id, empty_target.timeline_id)
        .expect("empty InMemory Timeline should be created");
    let in_memory_runtime =
        Runtime::new(&in_memory, CapabilityRegistry::new()).expect("empty InMemory Runtime");
    let in_memory_page = in_memory_runtime
        .discover_scheduler_targets(
            SchedulerDiscoveryRequest::new(1).expect("empty page bound should be valid"),
        )
        .await
        .expect("empty InMemory discovery should succeed");
    assert!(in_memory_page.targets.is_empty());
    assert_eq!(in_memory_page.continuation(), None);

    let database = TestDatabase::provision("scheduler-discovery-empty-parity").await;
    let storage = database.storage().await;
    let pool = database.pool().await;
    insert_target(&pool, empty_target).await;
    let postgres_runtime =
        Runtime::new(&storage, CapabilityRegistry::new()).expect("empty PostgreSQL Runtime");
    let postgres_page = postgres_runtime
        .discover_scheduler_targets(
            SchedulerDiscoveryRequest::new(1).expect("empty page bound should be valid"),
        )
        .await
        .expect("empty PostgreSQL discovery should succeed");
    assert!(postgres_page.targets.is_empty());
    assert_eq!(postgres_page.continuation(), None);

    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}
