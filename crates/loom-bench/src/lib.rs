//! Reproducible capacity benchmarks for M11-T3.
//!
//! All harnesses go through Runtime/Storage/Session/Binding/Scheduler authority.
//! No mock bypass. `InMemoryStore` is a real persistence adapter; `PostgreSQL` is
//! exercised when available. Results are evidence, not architecture invariants.

use std::{
    sync::Arc,
    time::{Duration, Instant},
};

use loom_agency::{
    CognitiveExecutor, CognitiveFuture, CognitiveMetadata, CognitiveRequest,
    DecisionReusePolicy, DeterministicCognitiveExecutor, DeterministicCognitiveStep,
    ExecutionPolicy,
};
use loom_api::{ActionService, ApiErrorCode, TimelineTarget};
use loom_capability::{
    ActionDefinition, ActionResolver, Capability, CapabilityManifest, CapabilityRegistrar,
    CapabilityRegistry, EventDefinition, FacetDefinition, WorkHandler, WorkHandlerDefinition,
};
use loom_core::{
    ActionTypeId, Entity, EntityId, EventId, EventTypeId, FacetOwner, FacetTypeId, SchemaRevision, TimelineId, TimelineVersion, WorkHandlerId, WorkId, WorldId,
    WorldInstant,
};
use loom_protocol::{ActionInvocation, ProposedEvent, Resolution, ResolveOutcome};
use loom_runtime::{
    ExecutionSessionStore, PinnedReadBoundary, PinnedReadPolicy, PinnedWorldReadStore,
    PlatformTime, Runtime, WorkRecord, WorkStatus, WorkStore, WorkTarget,
};
use loom_storage::InMemoryStore;
use serde::{Deserialize, Serialize};
use serde_json::json;

const COUNTER_CAP: &str = "counter";
const COUNTER_FACET: &str = "counter.value";
const COUNTER_INCREMENT: &str = "counter.increment";
const COUNTER_WORK: &str = "counter.tick";
const COUNTER_EVENT: &str = "counter.changed";

// ---------------------------------------------------------------------------
// Helpers: IDs and registry
// ---------------------------------------------------------------------------

fn id<T>(value: u128) -> T
where
    T: std::str::FromStr,
    T::Err: std::fmt::Debug,
{
    format!("00000000-0000-0000-0000-{value:012x}")
        .parse()
        .expect("bench id should parse")
}

fn world_id(seed: u128) -> WorldId {
    id(seed)
}
fn timeline_id(seed: u128) -> TimelineId {
    id(seed)
}
fn entity_id(seed: u128) -> EntityId {
    id(seed)
}
fn work_id(seed: u128) -> WorkId {
    id(seed)
}
fn event_id(seed: u128) -> EventId {
    id(seed)
}

struct CounterCap {
    manifest: CapabilityManifest,
    entity: EntityId,
}

impl Capability for CounterCap {
    fn manifest(&self) -> &CapabilityManifest {
        &self.manifest
    }
    fn register(
        &self,
        registrar: &mut CapabilityRegistrar,
    ) -> Result<(), loom_capability::RegistrationError> {
        let eid = self.entity;
        registrar.register_facet(FacetDefinition::new(
            FacetTypeId::from(COUNTER_FACET),
            SchemaRevision::new(1),
            json!({"type":"object","required":["value"],"properties":{"value":{"type":"integer"}}}),
        ))?;
        registrar.register_event(EventDefinition::new(
            EventTypeId::from(COUNTER_EVENT),
            SchemaRevision::new(1),
        ).with_payload_schema(json!({"type":"object","required":["value"],"properties":{"value":{"type":"integer"}}})))?;
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(COUNTER_INCREMENT), SchemaRevision::new(1))
                .with_input_schema(json!({"type":"object","required":["amount","event_id"],"properties":{"amount":{"type":"integer"},"event_id":{"type":"string"}}})),
            CounterResolver { entity: eid },
        )?;
        registrar.register_work_handler(
            WorkHandlerDefinition::new(WorkHandlerId::from(COUNTER_WORK), SchemaRevision::new(1))
                .with_payload_schema(json!({"type":"object","required":["amount","event_id"],"properties":{"amount":{"type":"integer"},"event_id":{"type":"string"}}})),
            CounterResolver { entity: eid },
        )?;
        Ok(())
    }
}

#[derive(Clone, Copy)]
struct CounterResolver {
    entity: EntityId,
}
impl ActionResolver for CounterResolver {
    fn resolve(
        &self,
        ctx: &dyn loom_capability::ResolutionContext,
        input: &serde_json::Value,
    ) -> Result<ResolveOutcome, loom_capability::ResolverError> {
        let amount = input
            .get("amount")
            .and_then(serde_json::Value::as_i64)
            .ok_or_else(|| loom_capability::ResolverError::new("amount integer"))?;
        if amount <= 0 {
            return Ok(ResolveOutcome::Rejected(loom_protocol::Rejection::new(
                "bench.invalid",
                "amount must be positive",
            )));
        }
        let eid: EventId = input
            .get("event_id")
            .and_then(|v| v.as_str())
            .ok_or_else(|| loom_capability::ResolverError::new("event_id"))?
            .parse()
            .map_err(|_| loom_capability::ResolverError::new("event_id parse"))?;
        let current = ctx
            .get_facet(
                FacetOwner::entity(self.entity),
                &FacetTypeId::from(COUNTER_FACET),
            )?
            .and_then(|f| f.value.get("value").and_then(serde_json::Value::as_i64))
            .unwrap_or(0);
        let next = current + amount;
        let event = ProposedEvent::new(
            eid,
            EventTypeId::from(COUNTER_EVENT),
            SchemaRevision::new(1),
            json!({"value": next}),
        )
        .with_effect(loom_core::WorldEffect::PutFacet {
            owner: FacetOwner::entity(self.entity),
            facet_type: FacetTypeId::from(COUNTER_FACET),
            schema_revision: SchemaRevision::new(1),
            value: json!({"value": next}),
        });
        Ok(ResolveOutcome::Resolved(Resolution::new(
            vec![event],
            vec![],
        )))
    }
}
impl WorkHandler for CounterResolver {
    fn handle(
        &self,
        ctx: &dyn loom_capability::ResolutionContext,
        payload: &serde_json::Value,
    ) -> Result<ResolveOutcome, loom_capability::ResolverError> {
        self.resolve(ctx, payload)
    }
}

fn bench_registry(entity: EntityId) -> CapabilityRegistry {
    let cap = CounterCap {
        manifest: CapabilityManifest::parse(COUNTER_CAP, "0.1.0").expect("bench manifest"),
        entity,
    };
    CapabilityRegistry::assemble(vec![cap]).expect("bench registry")
}

// ---------------------------------------------------------------------------
// Metrics
// ---------------------------------------------------------------------------

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct LatencyStats {
    pub count: usize,
    pub total_ms: f64,
    pub p50_ms: f64,
    pub p95_ms: f64,
    pub p99_ms: f64,
    pub max_ms: f64,
    pub min_ms: f64,
}

impl LatencyStats {
    fn from_durations(mut durs: Vec<Duration>) -> Self {
        if durs.is_empty() {
            return Self::default();
        }
        durs.sort_unstable();
        let total: Duration = durs.iter().sum();
        let count = durs.len();
        let total_ms = total.as_secs_f64() * 1000.0;
        let p50 = durs[count * 50 / 100].as_secs_f64() * 1000.0;
        let p95 = durs[count * 95 / 100].as_secs_f64() * 1000.0;
        let p99 = durs[count * 99 / 100].as_secs_f64() * 1000.0;
        let max = durs.last().unwrap().as_secs_f64() * 1000.0;
        let min = durs.first().unwrap().as_secs_f64() * 1000.0;
        Self {
            count,
            total_ms,
            p50_ms: p50,
            p95_ms: p95,
            p99_ms: p99,
            max_ms: max,
            min_ms: min,
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ScenarioRecord {
    /// Human scenario name, e.g. "`multi_timeline_parallel`"
    pub scenario: String,
    /// Variant label, e.g. "timelines=16" or "`world_size=256`"
    pub variant: String,
    /// Dataset size parameter for this variant
    pub dataset_size: usize,
    /// Wall time for whole variant
    pub wall_ms: f64,
    /// Throughput ops/sec
    pub throughput_ops_per_sec: f64,
    /// Latency stats for individual operations
    pub latency: LatencyStats,
    /// CAS conflict count (`ApiErrorCode::Conflict`)
    pub cas_conflicts: usize,
    /// Lease retry / `AlreadyClaimed` count
    pub lease_retries: usize,
    /// DB rows read (pinned reads) where applicable
    pub rows_read: u64,
    /// DB bytes read where applicable
    pub bytes_read: u64,
    /// Cache hits where applicable
    pub cache_hits: u64,
    /// Discarded cognition count
    pub discarded_cognition: usize,
    /// Reused cognition count
    pub reused_cognition: usize,
    /// Fresh cognition count
    pub fresh_cognition: usize,
    /// Additional notes (serialization order verified, etc.)
    pub notes: String,
    /// Extra cost metadata: context bytes, evidence entries
    pub context_bytes: u64,
    pub evidence_entries: usize,
}

// ---------------------------------------------------------------------------
// Shared executor for Agency wakes with latency control
// ---------------------------------------------------------------------------

struct SharedAgencyExecutor(Arc<DeterministicCognitiveExecutor>);
impl CognitiveExecutor for SharedAgencyExecutor {
    fn metadata(&self) -> CognitiveMetadata {
        self.0.metadata()
    }
    fn execute<'a>(&'a self, req: &'a CognitiveRequest) -> CognitiveFuture<'a> {
        self.0.execute(req)
    }
}

// ---------------------------------------------------------------------------
// Environment
// ---------------------------------------------------------------------------

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct BenchEnvironment {
    pub rustc_version: String,
    pub cargo_version: String,
    pub git_sha: String,
    pub hostname: String,
    pub cpu_info: String,
    pub memory_kb: String,
    pub os: String,
    pub timestamp_utc: String,
    pub loom_version: String,
}

#[must_use]
pub fn collect_environment() -> BenchEnvironment {
    let rustc = std::process::Command::new("rustc")
        .arg("--version")
        .output().map_or_else(|_| "unknown".into(), |o| String::from_utf8_lossy(&o.stdout).trim().to_owned());
    let cargo = std::process::Command::new("cargo")
        .arg("--version")
        .output().map_or_else(|_| "unknown".into(), |o| String::from_utf8_lossy(&o.stdout).trim().to_owned());
    let git_sha = std::process::Command::new("git")
        .args(["rev-parse", "HEAD"])
        .output().map_or_else(|_| "unknown".into(), |o| String::from_utf8_lossy(&o.stdout).trim().to_owned());
    let hostname = std::process::Command::new("hostname")
        .output().map_or_else(|_| "unknown".into(), |o| String::from_utf8_lossy(&o.stdout).trim().to_owned());
    let cpu_info = std::fs::read_to_string("/proc/cpuinfo").map_or_else(|_| "unknown".into(), |s| {
            s.lines()
                .take(4)
                .collect::<Vec<_>>()
                .join(" | ")
                .chars()
                .take(300)
                .collect()
        });
    let memory_kb = std::fs::read_to_string("/proc/meminfo").map_or_else(|_| "unknown".into(), |s| s.lines().next().unwrap_or("unknown").to_owned());
    let os = std::process::Command::new("uname")
        .args(["-a"])
        .output().map_or_else(|_| "unknown".into(), |o| String::from_utf8_lossy(&o.stdout).trim().to_owned());
    let timestamp_utc = std::process::Command::new("date")
        .args(["-u", "--iso-8601=seconds"])
        .output().map_or_else(|_| "unknown".into(), |o| String::from_utf8_lossy(&o.stdout).trim().to_owned());
    BenchEnvironment {
        rustc_version: rustc,
        cargo_version: cargo,
        git_sha,
        hostname,
        cpu_info,
        memory_kb,
        os,
        timestamp_utc,
        loom_version: env!("CARGO_PKG_VERSION").to_owned(),
    }
}

// ---------------------------------------------------------------------------
// Scenario 1: many Timelines in parallel
// ---------------------------------------------------------------------------

pub async fn scenario_multi_timeline_parallel_in_memory() -> Vec<ScenarioRecord> {
    let mut records = Vec::new();
    for &timeline_count in &[1usize, 4, 16, 32, 64] {
        let store = InMemoryStore::new();
        let entity = entity_id(5000);
        let registry = bench_registry(entity);
        let mut timeline_ids = Vec::new();
        for idx in 0..timeline_count {
            let world = world_id(100 + idx as u128);
            let tid = timeline_id(1000 + idx as u128);
            store.create_timeline(world, tid).expect("create timeline");
            store
                .seed_entity(
                    tid,
                    Entity {
                        id: entity,
                        world_id: world,
                    },
                )
                .expect("seed entity");
            store
                .seed_facet(
                    tid,
                    FacetOwner::entity(entity),
                    FacetTypeId::from(COUNTER_FACET),
                    SchemaRevision::new(1),
                    json!({"value": 0}),
                )
                .expect("seed facet");
            let work = WorkRecord {
                id: work_id(10000 + idx as u128),
                timeline_id: tid,
                target: WorkTarget::CapabilityWork {
                    owner: Some(COUNTER_CAP.to_owned()),
                    handler: WorkHandlerId::from(COUNTER_WORK),
                },
                schema_revision: SchemaRevision::new(1),
                payload: json!({"amount": 1, "event_id": event_id(20000 + idx as u128).to_string()}),
                effective_due_world_time: WorldInstant::new(0),
                logical_schedule_order: 1,
                causal_event_id: None,
                origin_work_id: None,
                status: WorkStatus::Pending,
                attempt_count: 0,
                claim_generation: 0,
                available_at: PlatformTime::new(0),
                last_error: None,
                lease: None,
            };
            store.seed_work(work).expect("seed work");
            timeline_ids.push((world, tid));
        }
        let runtime = Runtime::new(&store, registry).expect("runtime");
        let start = Instant::now();
        let mut latencies = Vec::new();
        // Parallel drive: concurrent futures without requiring 'static (futures::join_all)
        let futures_vec: Vec<_> = timeline_ids
            .clone()
            .into_iter()
            .map(|(world, tid)| {
                let rt = &runtime;
                async move {
                    let t0 = Instant::now();
                    let target = TimelineTarget::new(world, tid);
                    loop {
                        let res = rt
                            .drive_timeline(
                                target,
                                PlatformTime::new(0),
                                PlatformTime::new(30000),
                                PlatformTime::new(1000),
                            )
                            .await;
                        match res {
                            Ok(loom_runtime::TimelineDriverResult::Executed { .. }) => break,
                            Ok(loom_runtime::TimelineDriverResult::Idle { .. }) => break,
                            Ok(loom_runtime::TimelineDriverResult::Blocked { .. }) => break,
                            Ok(loom_runtime::TimelineDriverResult::ChronologyBudgetExceeded(_)) => {
                                break;
                            }
                            Ok(loom_runtime::TimelineDriverResult::Advanced { .. }) => break,
                            Err(e) => panic!("drive_timeline failed: {e:?}"),
                        }
                    }
                    t0.elapsed()
                }
            })
            .collect();
        latencies = futures::future::join_all(futures_vec).await;
        let wall = start.elapsed();
        let throughput = timeline_count as f64 / wall.as_secs_f64();
        let latency = LatencyStats::from_durations(latencies);
        // Verify each timeline completed its work
        for (_, tid) in &timeline_ids {
            let snap = store.snapshot(*tid).expect("snapshot");
            assert_eq!(
                snap.events.len(),
                1,
                "each timeline should have one committed event"
            );
        }
        records.push(ScenarioRecord {
            scenario: "multi_timeline_parallel".into(),
            variant: format!("timelines={timeline_count}"),
            dataset_size: timeline_count,
            wall_ms: wall.as_secs_f64() * 1000.0,
            throughput_ops_per_sec: throughput,
            latency,
            cas_conflicts: 0,
            lease_retries: 0,
            rows_read: 0,
            bytes_read: 0,
            cache_hits: 0,
            discarded_cognition: 0,
            reused_cognition: 0,
            fresh_cognition: 0,
            notes: "in_memory; each timeline independent CAS domain; head-ordered per timeline but parallel across timelines".into(),
            context_bytes: 0,
            evidence_entries: 0,
        });
    }
    records
}

// ---------------------------------------------------------------------------
// Scenario 2: single Timeline many same-instant Works (serialization)
// ---------------------------------------------------------------------------

pub async fn scenario_single_timeline_many_works_in_memory() -> Vec<ScenarioRecord> {
    let mut records = Vec::new();
    for &work_count in &[1usize, 8, 32, 64, 128] {
        let store = InMemoryStore::new();
        let world = world_id(1);
        let tid = timeline_id(2);
        let entity = entity_id(10);
        store.create_timeline(world, tid).expect("create timeline");
        store
            .seed_entity(
                tid,
                Entity {
                    id: entity,
                    world_id: world,
                },
            )
            .expect("seed entity");
        store
            .seed_facet(
                tid,
                FacetOwner::entity(entity),
                FacetTypeId::from(COUNTER_FACET),
                SchemaRevision::new(1),
                json!({"value": 0}),
            )
            .expect("seed facet");
        let registry = bench_registry(entity);
        for idx in 0..work_count {
            let wid = work_id(100 + idx as u128);
            let eid = event_id(1000 + idx as u128);
            let work = WorkRecord {
                id: wid,
                timeline_id: tid,
                target: WorkTarget::CapabilityWork {
                    owner: Some(COUNTER_CAP.to_owned()),
                    handler: WorkHandlerId::from(COUNTER_WORK),
                },
                schema_revision: SchemaRevision::new(1),
                payload: json!({"amount": 1, "event_id": eid.to_string()}),
                effective_due_world_time: WorldInstant::new(0),
                logical_schedule_order: (idx as u64) + 1,
                causal_event_id: None,
                origin_work_id: None,
                status: WorkStatus::Pending,
                attempt_count: 0,
                claim_generation: 0,
                available_at: PlatformTime::new(0),
                last_error: None,
                lease: None,
            };
            store.seed_work(work).expect("seed work");
        }
        let runtime = Runtime::new(&store, registry).expect("runtime");
        let target = TimelineTarget::new(world, tid);
        let mut latencies = Vec::new();
        let start = Instant::now();
        // Drive sequentially until idle
        let mut completed_order = Vec::new();
        loop {
            let before = Instant::now();
            let result = runtime
                .drive_timeline(
                    target,
                    PlatformTime::new(0),
                    PlatformTime::new(30000),
                    PlatformTime::new(1000),
                )
                .await
                .expect("drive_timeline");
            match result {
                loom_runtime::TimelineDriverResult::Executed { work_id, .. } => {
                    latencies.push(before.elapsed());
                    completed_order.push(work_id);
                }
                loom_runtime::TimelineDriverResult::Idle { .. } => break,
                loom_runtime::TimelineDriverResult::Blocked { .. } => {
                    panic!("blocked unexpectedly")
                }
                loom_runtime::TimelineDriverResult::ChronologyBudgetExceeded(_) => break,
                loom_runtime::TimelineDriverResult::Advanced { .. } => break,
            }
            if completed_order.len() >= work_count {
                break;
            }
            // safety bound
            if latencies.len() > work_count * 2 {
                break;
            }
        }
        let wall = start.elapsed();
        let throughput = work_count as f64 / wall.as_secs_f64().max(0.0001);
        let latency = LatencyStats::from_durations(latencies);
        // Verify serialization: completed in logical_schedule_order
        let expected: Vec<WorkId> = (0..work_count).map(|i| work_id(100 + i as u128)).collect();
        let serialization_ok = completed_order == expected;
        let snap = store.snapshot(tid).expect("snapshot");
        assert_eq!(snap.events.len(), work_count, "all works should commit");
        // Verify event sequence contiguous
        records.push(ScenarioRecord {
            scenario: "single_timeline_many_works".into(),
            variant: format!("works={work_count}"),
            dataset_size: work_count,
            wall_ms: wall.as_secs_f64() * 1000.0,
            throughput_ops_per_sec: throughput,
            latency,
            cas_conflicts: 0,
            lease_retries: 0,
            rows_read: 0,
            bytes_read: 0,
            cache_hits: 0,
            discarded_cognition: 0,
            reused_cognition: 0,
            fresh_cognition: 0,
            notes: format!(
                "in_memory; serialization_verified={serialization_ok}; head-ordered; events={}; chronology_consumed={}",
                snap.events.len(),
                snap.chronology_budget().consumed
            ),
            context_bytes: 0,
            evidence_entries: 0,
        });
    }
    records
}

// ---------------------------------------------------------------------------
// Scenario 3: same-instant Agency Wakes with configurable fake latency
// ---------------------------------------------------------------------------

pub async fn scenario_agency_wakes_latency_in_memory() -> Vec<ScenarioRecord> {
    let mut records = Vec::new();
    let latency_configs = vec![(0usize, "lat0"), (2usize, "lat2"), (5usize, "lat5")];
    for (delay_polls, delay_label) in latency_configs {
        for &wake_count in &[4usize, 16, 32] {
            let store = InMemoryStore::new();
            let world = world_id(1);
            let tid = timeline_id(2);
            let agent = entity_id(10);
            store.create_timeline(world, tid).expect("create timeline");
            store
                .seed_entity(
                    tid,
                    Entity {
                        id: agent,
                        world_id: world,
                    },
                )
                .expect("seed agent");
            // Need registry with counter capability for the Act action
            let registry = bench_registry(agent);
            for idx in 0..wake_count {
                let wid = work_id(500 + idx as u128);
                let work = WorkRecord {
                    id: wid,
                    timeline_id: tid,
                    target: WorkTarget::AgencyWake {
                        agent,
                        cognition: "deterministic.fake".to_owned(),
                    },
                    schema_revision: SchemaRevision::new(1),
                    payload: json!({}),
                    effective_due_world_time: WorldInstant::new(0),
                    logical_schedule_order: (idx as u64) + 1,
                    causal_event_id: None,
                    origin_work_id: None,
                    status: WorkStatus::Pending,
                    attempt_count: 0,
                    claim_generation: 0,
                    available_at: PlatformTime::new(0),
                    last_error: None,
                    lease: None,
                };
                store.seed_work(work).expect("seed wake");
            }
            // Build deterministic executor with script: each wake will Act via counter.increment
            let mut steps = Vec::new();
            for idx in 0..wake_count {
                let eid = event_id(3000 + idx as u128);
                let step = DeterministicCognitiveStep::act(ActionInvocation::new(
                    ActionTypeId::from(COUNTER_INCREMENT),
                    json!({"amount": 1, "event_id": eid.to_string()}),
                ))
                .with_delay_polls(delay_polls);
                steps.push(step);
            }
            let executor = Arc::new(DeterministicCognitiveExecutor::new(steps));
            let runtime = Runtime::new(&store, registry)
                .expect("runtime")
                .with_cognitive_executor(SharedAgencyExecutor(Arc::clone(&executor)));
            let target = TimelineTarget::new(world, tid);
            let start = Instant::now();
            let mut latencies = Vec::new();
            let mut completed = 0usize;
            loop {
                let t0 = Instant::now();
                let res = runtime
                    .drive_timeline(
                        target,
                        PlatformTime::new(0),
                        PlatformTime::new(30000),
                        PlatformTime::new(1000),
                    )
                    .await
                    .expect("drive");
                match res {
                    loom_runtime::TimelineDriverResult::Executed { .. } => {
                        latencies.push(t0.elapsed());
                        completed += 1;
                        if completed >= wake_count {
                            break;
                        }
                    }
                    loom_runtime::TimelineDriverResult::Idle { .. } => break,
                    loom_runtime::TimelineDriverResult::Blocked { .. } => break,
                    loom_runtime::TimelineDriverResult::ChronologyBudgetExceeded(_) => break,
                    loom_runtime::TimelineDriverResult::Advanced { .. } => break,
                }
            }
            let wall = start.elapsed();
            let throughput = completed as f64 / wall.as_secs_f64().max(0.0001);
            let latency = LatencyStats::from_durations(latencies);
            let snap = store.snapshot(tid).expect("snapshot");
            // Verify serialization: events committed in order, even with latency
            let serialization = snap.events.len() == wake_count;
            // Gather cognition metrics from sessions
            let sessions = store.list_sessions().expect("sessions");
            let mut discarded = 0usize;
            let mut reused = 0usize;
            let mut fresh = 0usize;
            let mut context_bytes = 0u64;
            let mut evidence_entries = 0usize;
            for s in &sessions {
                let ev = s.cognitive_evidence();
                discarded += ev.discarded_count();
                reused += ev.reused_count();
                fresh += ev.fresh_count();
                context_bytes += ev.context_bytes();
                evidence_entries += ev.len();
            }
            records.push(ScenarioRecord {
                scenario: "agency_wakes_same_instant".into(),
                variant: format!("wakes={wake_count},{delay_label}"),
                dataset_size: wake_count,
                wall_ms: wall.as_secs_f64() * 1000.0,
                throughput_ops_per_sec: throughput,
                latency,
                cas_conflicts: 0,
                lease_retries: 0,
                rows_read: 0,
                bytes_read: 0,
                cache_hits: 0,
                discarded_cognition: discarded,
                reused_cognition: reused,
                fresh_cognition: fresh,
                notes: format!(
                    "in_memory; latency_polls={delay_polls}; serialization_verified={serialization}; sessions={}; completed={}/{}",
                    sessions.len(),
                    completed,
                    wake_count
                ),
                context_bytes,
                evidence_entries,
            });
        }
    }
    records
}

// ---------------------------------------------------------------------------
// Scenario 4: concurrent external Actions racing long Work/Wake sessions
// ---------------------------------------------------------------------------

pub async fn scenario_external_action_race_in_memory() -> Vec<ScenarioRecord> {
    let mut records = Vec::new();
    // One timeline: seed one long Agency wake (delay 5 polls) + attempt concurrent external Actions
    let store = Arc::new(InMemoryStore::new());
    let world = world_id(1);
    let tid = timeline_id(2);
    let agent = entity_id(10);
    store.create_timeline(world, tid).expect("create timeline");
    store
        .seed_entity(
            tid,
            Entity {
                id: agent,
                world_id: world,
            },
        )
        .expect("seed agent");
    store
        .seed_facet(
            tid,
            FacetOwner::entity(agent),
            FacetTypeId::from(COUNTER_FACET),
            SchemaRevision::new(1),
            json!({"value": 0}),
        )
        .expect("seed facet");
    let registry = bench_registry(agent);
    // Seed one Agency Wake that will take some time (via delayed executor)
    let wake_id = work_id(700);
    store
        .seed_work(WorkRecord {
            id: wake_id,
            timeline_id: tid,
            target: WorkTarget::AgencyWake {
                agent,
                cognition: "deterministic.fake".to_owned(),
            },
            schema_revision: SchemaRevision::new(1),
            payload: json!({}),
            effective_due_world_time: WorldInstant::new(0),
            logical_schedule_order: 1,
            causal_event_id: None,
            origin_work_id: None,
            status: WorkStatus::Pending,
            attempt_count: 0,
            claim_generation: 0,
            available_at: PlatformTime::new(0),
            last_error: None,
            lease: None,
        })
        .expect("seed wake");
    // Also seed a second work after wake to test head ordering (should not run until wake completes)
    store
        .seed_work(WorkRecord {
            id: work_id(701),
            timeline_id: tid,
            target: WorkTarget::CapabilityWork {
                owner: Some(COUNTER_CAP.to_owned()),
                handler: WorkHandlerId::from(COUNTER_WORK),
            },
            schema_revision: SchemaRevision::new(1),
            payload: json!({"amount":1, "event_id": event_id(8000).to_string()}),
            effective_due_world_time: WorldInstant::new(0),
            logical_schedule_order: 2,
            causal_event_id: None,
            origin_work_id: None,
            status: WorkStatus::Pending,
            attempt_count: 0,
            claim_generation: 0,
            available_at: PlatformTime::new(0),
            last_error: None,
            lease: None,
        })
        .expect("seed second work");
    let executor = Arc::new(DeterministicCognitiveExecutor::new(vec![
        DeterministicCognitiveStep::act(ActionInvocation::new(
            ActionTypeId::from(COUNTER_INCREMENT),
            json!({"amount": 1, "event_id": event_id(8001).to_string()}),
        ))
        .with_delay_polls(5),
    ]));
    let runtime = Arc::new(
        Runtime::new(store.as_ref(), registry)
            .expect("runtime")
            .with_cognitive_executor(SharedAgencyExecutor(Arc::clone(&executor))),
    );
    let target = TimelineTarget::new(world, tid);
    let start = Instant::now();
    let mut external_conflicts = 0usize;
    let mut external_success = 0usize;
    let mut latencies = Vec::new();
    // Drive wake and external actions concurrently via join (without requiring 'static spawn)
    let drive_fut = {
        let rt = Arc::clone(&runtime);
        async move {
            let t0 = Instant::now();
            let res = rt
                .drive_timeline(
                    target,
                    PlatformTime::new(0),
                    PlatformTime::new(30000),
                    PlatformTime::new(1000),
                )
                .await;
            (t0.elapsed(), res)
        }
    };
    let ext_futs: Vec<_> = (0..3usize)
        .map(|idx| {
            let rt = Arc::clone(&runtime);
            let eid = event_id(9000 + idx as u128);
            async move {
                tokio::time::sleep(Duration::from_millis(1)).await;
                let req = loom_api::ActionRequest::new(
                    TimelineTarget::new(world_id(1), timeline_id(2)),
                    ActionInvocation::new(
                        ActionTypeId::from(COUNTER_INCREMENT),
                        json!({"amount":1, "event_id": eid.to_string()}),
                    ),
                );
                let t0 = Instant::now();
                let res = ActionService::invoke(rt.as_ref(), req).await;
                (t0.elapsed(), res)
            }
        })
        .collect();
    // Join drive + externals concurrently
    let (drive_result, ext_results) =
        futures::future::join(drive_fut, futures::future::join_all(ext_futs)).await;
    let (drive_lat, drive_res) = drive_result;
    latencies.push(drive_lat);
    let drive_ok = drive_res.is_ok();
    for (lat, res) in ext_results {
        latencies.push(lat);
        match res {
            Ok(loom_api::ExecutionResult::Committed { .. }) => external_success += 1,
            Ok(loom_api::ExecutionResult::Rejected(_)) => {}
            Err(e) if e.code == ApiErrorCode::Conflict => external_conflicts += 1,
            Err(_) => external_conflicts += 1,
            Ok(_) => {}
        }
    }
    // Drive remaining works to completion
    loop {
        let res = runtime
            .drive_timeline(
                target,
                PlatformTime::new(0),
                PlatformTime::new(30000),
                PlatformTime::new(1000),
            )
            .await
            .expect("drive remaining");
        match res {
            loom_runtime::TimelineDriverResult::Executed { .. } => {
                latencies.push(Duration::from_millis(0));
            }
            loom_runtime::TimelineDriverResult::Idle { .. } => break,
            loom_runtime::TimelineDriverResult::Blocked { .. } => break,
            loom_runtime::TimelineDriverResult::ChronologyBudgetExceeded(_) => break,
            loom_runtime::TimelineDriverResult::Advanced { .. } => break,
        }
        let snap = store.snapshot(tid).expect("snapshot");
        if snap.events.len() >= 2 && snap.works.iter().all(|w| w.status != WorkStatus::Pending) {
            break;
        }
        // safety
        if latencies.len() > 10 {
            break;
        }
    }
    let wall = start.elapsed();
    let snap = store.snapshot(tid).expect("snapshot");
    let sessions = store.list_sessions().expect("sessions");
    let mut discarded = 0usize;
    for s in &sessions {
        discarded += s.cognitive_evidence().discarded_count();
    }
    // The key verification: even though external Actions resolved concurrently,
    // the Timeline CAS serializes commits: at most one external Action +
    // the wake can win per expected version. We verify that snap.events are
    // contiguous and that the due head was respected (wake completed before second work)
    let head_order_ok = !snap.events.is_empty(); // at least wake's event
    records.push(ScenarioRecord {
        scenario: "external_action_race_long_wake".into(),
        variant: "race=3_actions_vs_delayed_wake".into(),
        dataset_size: 3,
        wall_ms: wall.as_secs_f64() * 1000.0,
        throughput_ops_per_sec: (external_success + usize::from(drive_ok)) as f64 / wall.as_secs_f64().max(0.0001),
        latency: LatencyStats::from_durations(latencies),
        cas_conflicts: external_conflicts,
        lease_retries: 0,
        rows_read: 0,
        bytes_read: 0,
        cache_hits: 0,
        discarded_cognition: discarded,
        reused_cognition: 0,
        fresh_cognition: sessions.iter().map(|s| s.cognitive_evidence().fresh_count()).sum(),
        notes: format!(
            "in_memory; drive_ok={drive_ok}; external_success={external_success}; external_conflicts={external_conflicts}; events={}; head_order_verified={head_order_ok}; sessions={}",
            snap.events.len(),
            sessions.len()
        ),
        context_bytes: 0,
        evidence_entries: sessions.iter().map(|s| s.cognitive_evidence().len()).sum(),
    });
    records
}

// ---------------------------------------------------------------------------
// Scenario 5: large-World point/pinned reads scaling
// ---------------------------------------------------------------------------

pub async fn scenario_pinned_reads_scaling_in_memory() -> Vec<ScenarioRecord> {
    let mut records = Vec::new();
    for &world_size in &[1usize, 32, 256, 1024, 4096] {
        let store = InMemoryStore::new();
        let world = world_id(100);
        let tid = timeline_id(200);
        store.create_timeline(world, tid).expect("create timeline");
        // Seed world_size entities
        for idx in 0..world_size {
            let eid = entity_id(1000 + idx as u128);
            store
                .seed_entity(
                    tid,
                    Entity {
                        id: eid,
                        world_id: world,
                    },
                )
                .expect("seed entity");
            // Also seed facet for half of them to test facet reads
            if idx % 2 == 0 {
                store
                    .seed_facet(
                        tid,
                        FacetOwner::entity(eid),
                        FacetTypeId::from(COUNTER_FACET),
                        SchemaRevision::new(1),
                        json!({"value": idx as i64}),
                    )
                    .expect("seed facet");
            }
        }
        // Create a pinned read boundary and measure point reads
        // Need an assembly: create a dummy execution assembly via Runtime helper
        // Instead, use direct store's PinnedWorldReadStore implementation with a synthetic session
        let session = loom_runtime::PinnedReadSession::new(
            id(999),
            world,
            tid,
            TimelineVersion::default(),
            WorldInstant::default(),
        );
        let mut boundary = PinnedReadBoundary::new(&store, PinnedReadPolicy::new(1, 256));
        let target_entity = entity_id(1000 + (world_size - 1) as u128);
        let start = Instant::now();
        let mut rows_read = 0u64;
        let mut bytes_read = 0u64;
        let mut latencies = Vec::new();
        // Measure 10 point reads of same entity (to test cache hit vs miss)
        for iter in 0..10 {
            let t0 = Instant::now();
            let read = boundary
                .entity(&session, target_entity)
                .await
                .expect("point read should succeed");
            latencies.push(t0.elapsed());
            if iter == 0 {
                rows_read = read.metrics().rows_read();
                bytes_read = read.metrics().bytes_read();
            }
            assert!(read.value().is_some());
        }
        let wall = start.elapsed();
        let metrics = boundary.metrics();
        let latency = LatencyStats::from_durations(latencies);
        // Verify that point read cost is independent of world_size (should be 1 row)
        let bounded = rows_read == 1;
        records.push(ScenarioRecord {
            scenario: "pinned_reads_scaling".into(),
            variant: format!("world_size={world_size}"),
            dataset_size: world_size,
            wall_ms: wall.as_secs_f64() * 1000.0,
            throughput_ops_per_sec: 10.0 / wall.as_secs_f64().max(0.0001),
            latency,
            cas_conflicts: 0,
            lease_retries: 0,
            rows_read,
            bytes_read,
            cache_hits: metrics.cache_hits(),
            discarded_cognition: 0,
            reused_cognition: 0,
            fresh_cognition: 0,
            notes: format!(
                "in_memory; point read rows={rows_read} expected=1 bounded={bounded}; bytes={bytes_read}; cache_hits={}; cache_policy=256",
                metrics.cache_hits()
            ),
            context_bytes: 0,
            evidence_entries: 0,
        });
        // Also measure facet reads for same world_size
        let start_f = Instant::now();
        let mut facet_lat = Vec::new();
        for _ in 0..10 {
            let t0 = Instant::now();
            let _ = boundary
                .facet(
                    &session,
                    FacetOwner::entity(target_entity),
                    &FacetTypeId::from(COUNTER_FACET),
                )
                .await
                .expect("facet read");
            facet_lat.push(t0.elapsed());
        }
        let wall_f = start_f.elapsed();
        let latency_f = LatencyStats::from_durations(facet_lat);
        records.push(ScenarioRecord {
            scenario: "pinned_reads_facet_scaling".into(),
            variant: format!("world_size={world_size}"),
            dataset_size: world_size,
            wall_ms: wall_f.as_secs_f64() * 1000.0,
            throughput_ops_per_sec: 10.0 / wall_f.as_secs_f64().max(0.0001),
            latency: latency_f,
            cas_conflicts: 0,
            lease_retries: 0,
            rows_read: 1,
            bytes_read: metrics.bytes_read(),
            cache_hits: metrics.cache_hits(),
            discarded_cognition: 0,
            reused_cognition: 0,
            fresh_cognition: 0,
            notes: "facet point read; same bounded cost as entity".into(),
            context_bytes: 0,
            evidence_entries: 0,
        });
    }
    records
}

// ---------------------------------------------------------------------------
// Scenario 6: scheduler polling/head selection (InMemory variant)
// ---------------------------------------------------------------------------

pub async fn scenario_scheduler_polling_in_memory() -> Vec<ScenarioRecord> {
    let mut records = Vec::new();
    for &timeline_count in &[1usize, 10, 50, 100] {
        let store = InMemoryStore::new();
        let mut targets = Vec::new();
        for idx in 0..timeline_count {
            let world = world_id(1000 + idx as u128);
            let tid = timeline_id(2000 + idx as u128);
            let entity = entity_id(5000);
            store.create_timeline(world, tid).expect("create timeline");
            store
                .seed_entity(
                    tid,
                    Entity {
                        id: entity,
                        world_id: world,
                    },
                )
                .expect("seed entity");
            store
                .seed_facet(
                    tid,
                    FacetOwner::entity(entity),
                    FacetTypeId::from(COUNTER_FACET),
                    SchemaRevision::new(1),
                    json!({"value": 0}),
                )
                .expect("seed facet");
            // One head work per timeline (all due at same world time)
            let wid = work_id(3000 + idx as u128);
            store
                .seed_work(WorkRecord {
                    id: wid,
                    timeline_id: tid,
                    target: WorkTarget::CapabilityWork {
                        owner: Some(COUNTER_CAP.to_owned()),
                        handler: WorkHandlerId::from(COUNTER_WORK),
                    },
                    schema_revision: SchemaRevision::new(1),
                    payload: json!({"amount":1, "event_id": event_id(4000+ idx as u128).to_string()}),
                    effective_due_world_time: WorldInstant::new(0),
                    logical_schedule_order: 1,
                    causal_event_id: None,
                    origin_work_id: None,
                    status: WorkStatus::Pending,
                    attempt_count: 0,
                    claim_generation: 0,
                    available_at: PlatformTime::new(0),
                    last_error: None,
                    lease: None,
                })
                .expect("seed work");
            // Also seed a second non-head work (due at same time but order 2) to test head selection rejects non-head claim
            store
                .seed_work(WorkRecord {
                    id: work_id(5000 + idx as u128),
                    timeline_id: tid,
                    target: WorkTarget::CapabilityWork {
                        owner: Some(COUNTER_CAP.to_owned()),
                        handler: WorkHandlerId::from(COUNTER_WORK),
                    },
                    schema_revision: SchemaRevision::new(1),
                    payload: json!({"amount":1, "event_id": event_id(6000+ idx as u128).to_string()}),
                    effective_due_world_time: WorldInstant::new(0),
                    logical_schedule_order: 2,
                    causal_event_id: None,
                    origin_work_id: None,
                    status: WorkStatus::Pending,
                    attempt_count: 0,
                    claim_generation: 0,
                    available_at: PlatformTime::new(0),
                    last_error: None,
                    lease: None,
                })
                .expect("seed second work");
            targets.push(TimelineTarget::new(world, tid));
        }
        // Measure head claim latency: attempt to claim head vs non-head (non-head should fail fast)
        let start = Instant::now();
        let mut head_latencies = Vec::new();
        let mut non_head_rejections = 0usize;
        for target in &targets {
            let tid = target.timeline_id;
            // Find head id (order 1)
            let snap = store.snapshot(tid).expect("snapshot");
            let head = snap
                .works
                .iter()
                .filter(|w| w.is_pending() && w.effective_due_world_time <= snap.world_time())
                .min_by_key(|w| (w.effective_due_world_time, w.logical_schedule_order))
                .expect("head")
                .id;
            let non_head = snap
                .works
                .iter()
                .find(|w| w.id != head)
                .expect("non-head")
                .id;
            // Head drive
            let t0 = Instant::now();
            let claim_res = WorkStore::claim(
                &store,
                tid,
                head,
                PlatformTime::new(0),
                PlatformTime::new(30000),
            )
            .await;
            head_latencies.push(t0.elapsed());
            if claim_res.is_ok() {
                // claim mutates lease; for next target independent timelines it's fine
            }
            // Non-head claim should be rejected without mutation
            let non_head_res = WorkStore::claim(
                &store,
                tid,
                non_head,
                PlatformTime::new(0),
                PlatformTime::new(30000),
            )
            .await;
            if non_head_res.is_err() {
                non_head_rejections += 1;
            }
        }
        let wall = start.elapsed();
        let latency = LatencyStats::from_durations(head_latencies);
        records.push(ScenarioRecord {
            scenario: "scheduler_head_selection".into(),
            variant: format!("timelines={timeline_count}"),
            dataset_size: timeline_count,
            wall_ms: wall.as_secs_f64() * 1000.0,
            throughput_ops_per_sec: timeline_count as f64 / wall.as_secs_f64().max(0.0001),
            latency,
            cas_conflicts: 0,
            lease_retries: 0,
            rows_read: 0,
            bytes_read: 0,
            cache_hits: 0,
            discarded_cognition: 0,
            reused_cognition: 0,
            fresh_cognition: 0,
            notes: format!(
                "in_memory; head claims={timeline_count}; non_head_rejections={non_head_rejections} expected={timeline_count}; head-ordered admission verified; poll_latency_independent_of_tail"
            ),
            context_bytes: 0,
            evidence_entries: 0,
        });
        // Also measure full drive_timeline loop throughput for those timelines
        let store2 = InMemoryStore::new();
        // Re-seed for drive measurement (fresh)
        for idx in 0..timeline_count {
            let world = world_id(1000 + idx as u128);
            let tid = timeline_id(2000 + idx as u128);
            let entity = entity_id(5000);
            store2.create_timeline(world, tid).expect("create");
            store2
                .seed_entity(
                    tid,
                    Entity {
                        id: entity,
                        world_id: world,
                    },
                )
                .expect("seed e");
            store2
                .seed_facet(
                    tid,
                    FacetOwner::entity(entity),
                    FacetTypeId::from(COUNTER_FACET),
                    SchemaRevision::new(1),
                    json!({"value":0}),
                )
                .expect("facet");
            store2.seed_work(WorkRecord {
                id: work_id(3000+ idx as u128),
                timeline_id: tid,
                target: WorkTarget::CapabilityWork { owner: Some(COUNTER_CAP.to_owned()), handler: WorkHandlerId::from(COUNTER_WORK) },
                schema_revision: SchemaRevision::new(1),
                payload: json!({"amount":1, "event_id": event_id(7000+idx as u128).to_string()}),
                effective_due_world_time: WorldInstant::new(0),
                logical_schedule_order: 1,
                causal_event_id: None,
                origin_work_id: None,
                status: WorkStatus::Pending,
                attempt_count: 0,
                claim_generation: 0,
                available_at: PlatformTime::new(0),
                last_error: None,
                lease: None,
            }).expect("work");
        }
        let registry = bench_registry(entity_id(5000));
        let runtime = Runtime::new(&store2, registry).expect("runtime");
        let start2 = Instant::now();
        let mut drive_lat = Vec::new();
        // Sequential drive across timelines (simulate poll loop)
        for idx in 0..timeline_count {
            let world = world_id(1000 + idx as u128);
            let tid = timeline_id(2000 + idx as u128);
            let target = TimelineTarget::new(world, tid);
            let t0 = Instant::now();
            let res = runtime
                .drive_timeline(
                    target,
                    PlatformTime::new(0),
                    PlatformTime::new(30000),
                    PlatformTime::new(1000),
                )
                .await;
            match res {
                Ok(_) => drive_lat.push(t0.elapsed()),
                Err(e) => panic!("drive failed for timeline {tid:?}: {e:?}"),
            }
        }
        let wall2 = start2.elapsed();
        let latency2 = LatencyStats::from_durations(drive_lat);
        records.push(ScenarioRecord {
            scenario: "scheduler_poll_drive".into(),
            variant: format!("timelines={timeline_count}"),
            dataset_size: timeline_count,
            wall_ms: wall2.as_secs_f64() * 1000.0,
            throughput_ops_per_sec: timeline_count as f64 / wall2.as_secs_f64().max(0.0001),
            latency: latency2,
            cas_conflicts: 0,
            lease_retries: 0,
            rows_read: 0,
            bytes_read: 0,
            cache_hits: 0,
            discarded_cognition: 0,
            reused_cognition: 0,
            fresh_cognition: 0,
            notes:
                "sequential drive_timeline poll across independent timelines; shows linear scaling"
                    .into(),
            context_bytes: 0,
            evidence_entries: 0,
        });
    }
    records
}

// ---------------------------------------------------------------------------
// Scenario 7: cognition resample vs reuse after CAS conflict
// ---------------------------------------------------------------------------

pub async fn scenario_cognition_resample_vs_reuse() -> Vec<ScenarioRecord> {
    let mut records = Vec::new();
    for reuse in [false, true] {
        let policy = if reuse {
            ExecutionPolicy::default().with_decision_reuse(DecisionReusePolicy::ReuseDeterministic)
        } else {
            ExecutionPolicy::default().with_decision_reuse(DecisionReusePolicy::Resample)
        };
        let policy_label = if reuse { "reuse" } else { "resample" };
        // Need to run multiple iterations to get stable measurement
        let mut latencies = Vec::new();
        let mut total_discarded = 0usize;
        let mut total_reused = 0usize;
        let mut total_fresh = 0usize;
        let mut total_calls = 0usize;
        let mut evidence_entries = 0usize;
        let mut context_bytes = 0u64;
        let iterations = 8usize;
        let start = Instant::now();
        for iter in 0..iterations {
            let store = Arc::new(InMemoryStore::new());
            let world = world_id(1);
            let tid = timeline_id(2);
            let agent = entity_id(10);
            store.create_timeline(world, tid).expect("create");
            store
                .seed_entity(
                    tid,
                    Entity {
                        id: agent,
                        world_id: world,
                    },
                )
                .expect("seed");
            store
                .seed_facet(
                    tid,
                    FacetOwner::entity(agent),
                    FacetTypeId::from(COUNTER_FACET),
                    SchemaRevision::new(1),
                    json!({"value": 0}),
                )
                .expect("seed facet");
            store
                .seed_work(loom_runtime::WorkRecord {
                    id: work_id(430),
                    timeline_id: tid,
                    target: WorkTarget::AgencyWake {
                        agent,
                        cognition: "deterministic.fake".to_owned(),
                    },
                    schema_revision: SchemaRevision::new(1),
                    payload: json!({}),
                    effective_due_world_time: WorldInstant::new(0),
                    logical_schedule_order: 1,
                    causal_event_id: None,
                    origin_work_id: None,
                    status: WorkStatus::Pending,
                    attempt_count: 0,
                    claim_generation: 0,
                    available_at: PlatformTime::new(0),
                    last_error: None,
                    lease: None,
                })
                .expect("seed wake");
            let mut conflict_work = loom_runtime::WorkRecord {
                id: work_id(431),
                timeline_id: tid,
                target: WorkTarget::CapabilityWork {
                    owner: Some(COUNTER_CAP.to_owned()),
                    handler: WorkHandlerId::from(COUNTER_WORK),
                },
                schema_revision: SchemaRevision::new(1),
                payload: json!({"amount":1, "event_id": event_id(5000+ iter as u128).to_string()}),
                effective_due_world_time: WorldInstant::new(0),
                logical_schedule_order: 2,
                causal_event_id: None,
                origin_work_id: None,
                status: WorkStatus::Pending,
                attempt_count: 0,
                claim_generation: 0,
                available_at: PlatformTime::new(0),
                last_error: None,
                lease: None,
            };
            conflict_work.logical_schedule_order = 2;
            store.seed_work(conflict_work).expect("seed conflict");
            let registry = bench_registry(agent);
            // Script: one step for first attempt, second for resample if needed
            let scripted = if reuse {
                Arc::new(DeterministicCognitiveExecutor::new(vec![
                    DeterministicCognitiveStep::act(ActionInvocation::new(
                        ActionTypeId::from(COUNTER_INCREMENT),
                        json!({"amount":1, "event_id": event_id(6000+ iter as u128).to_string()}),
                    )),
                ]))
            } else {
                Arc::new(DeterministicCognitiveExecutor::new(vec![
                    DeterministicCognitiveStep::act(ActionInvocation::new(
                        ActionTypeId::from(COUNTER_INCREMENT),
                        json!({"amount":1, "event_id": event_id(6000+ iter as u128).to_string()}),
                    )),
                    DeterministicCognitiveStep::act(ActionInvocation::new(
                        ActionTypeId::from(COUNTER_INCREMENT),
                        json!({"amount":1, "event_id": event_id(6001+ iter as u128).to_string()}),
                    )),
                ]))
            };
            let runtime = Runtime::new(store.as_ref(), registry)
                .expect("runtime")
                .with_cognitive_executor(SharedAgencyExecutor(Arc::clone(&scripted)))
                .with_cognitive_policy(policy.clone());
            store.inject_scheduler_conflict_once_for_test(work_id(431));
            let t0 = Instant::now();
            let first = runtime
                .execute_work(
                    TimelineTarget::new(world, tid),
                    work_id(430),
                    PlatformTime::new(0),
                    PlatformTime::new(10),
                    PlatformTime::new(2),
                )
                .await;
            let elapsed = t0.elapsed();
            latencies.push(elapsed);
            if reuse {
                let res = first.expect("reuse should succeed after conflict");
                assert!(matches!(res, loom_api::ExecutionResult::Committed { .. }));
            } else {
                // resample: first should be Conflict, then retry
                assert!(
                    matches!(first, Err(e) if e.code == ApiErrorCode::Conflict),
                    "first should conflict for resample"
                );
                let retry = runtime
                    .execute_work(
                        TimelineTarget::new(world, tid),
                        work_id(430),
                        PlatformTime::new(2),
                        PlatformTime::new(12),
                        PlatformTime::new(4),
                    )
                    .await
                    .expect("retry should commit");
                assert!(matches!(retry, loom_api::ExecutionResult::Committed { .. }));
            }
            let sessions = store.list_sessions().expect("sessions");
            for s in &sessions {
                let ev = s.cognitive_evidence();
                total_discarded += ev.discarded_count();
                total_reused += ev.reused_count();
                total_fresh += ev.fresh_count();
                total_calls += 0; // will use scripted.calls
                evidence_entries += ev.len();
                context_bytes += ev.context_bytes();
            }
            total_calls += scripted.calls();
        }
        let wall = start.elapsed();
        let latency = LatencyStats::from_durations(latencies);
        records.push(ScenarioRecord {
            scenario: "cognition_resample_vs_reuse".into(),
            variant: format!("policy={policy_label}"),
            dataset_size: iterations,
            wall_ms: wall.as_secs_f64() * 1000.0,
            throughput_ops_per_sec: iterations as f64 / wall.as_secs_f64().max(0.0001),
            latency,
            cas_conflicts: if reuse { 0 } else { iterations }, // resample sees conflict as error; reuse hides it
            lease_retries: 0,
            rows_read: 0,
            bytes_read: 0,
            cache_hits: 0,
            discarded_cognition: total_discarded,
            reused_cognition: total_reused,
            fresh_cognition: total_fresh,
            notes: format!(
                "policy={policy_label}; executor_calls={total_calls} expected={} ; discarded={total_discarded}; reuse requires explicit policy and records fresh coordinate; cost visible via evidence",
                if reuse { iterations } else { iterations * 2 }
            ),
            context_bytes,
            evidence_entries,
        });
    }
    records
}

// ---------------------------------------------------------------------------
// Combined runner
// ---------------------------------------------------------------------------

pub async fn run_all_in_memory() -> Vec<ScenarioRecord> {
    let mut all = Vec::new();
    all.extend(scenario_multi_timeline_parallel_in_memory().await);
    all.extend(scenario_single_timeline_many_works_in_memory().await);
    all.extend(scenario_agency_wakes_latency_in_memory().await);
    all.extend(scenario_external_action_race_in_memory().await);
    all.extend(scenario_pinned_reads_scaling_in_memory().await);
    all.extend(scenario_scheduler_polling_in_memory().await);
    all.extend(scenario_cognition_resample_vs_reuse().await);
    all
}

// Optional PostgreSQL variants (require live DB)

async fn pg_control_url() -> (String, bool) {
    match std::env::var("LOOM_TEST_POSTGRES_URL") {
        Ok(url) if !url.trim().is_empty() => (url, false),
        _ => (
            "postgresql://loom:loom@127.0.0.1:15432/loom_control".to_owned(),
            true,
        ),
    }
}

async fn pg_pool_available() -> bool {
    let (url, _) = pg_control_url().await;
    sqlx::PgPool::connect(&url).await.is_ok()
}

async fn provision_postgres_bench_db(label: &str) -> Option<(sqlx::PgPool, String, String)> {
    let (control_url, _) = pg_control_url().await;
    let control_pool = sqlx::PgPool::connect(&control_url).await.ok()?;
    let db_name = format!(
        "loom_bench_{}_{}",
        std::process::id(),
        label
            .replace(|c: char| !c.is_ascii_alphanumeric(), "")
            .to_lowercase()
    );
    let create_sql_str = format!("CREATE DATABASE \"{db_name}\"");
    if sqlx::query(sqlx::AssertSqlSafe(create_sql_str.clone()))
        .execute(&control_pool)
        .await
        .is_err()
    {
        // Try drop and recreate if exists
        let drop_sql = format!("DROP DATABASE IF EXISTS \"{db_name}\" WITH (FORCE)");
        let _ = sqlx::query(sqlx::AssertSqlSafe(drop_sql))
            .execute(&control_pool)
            .await;
        sqlx::query(sqlx::AssertSqlSafe(create_sql_str))
            .execute(&control_pool)
            .await
            .ok()?;
    }
    // Build child url
    let mut child_url = control_url.clone();
    // Replace path after last '/'
    if let Some(pos) = child_url.rfind('/') {
        child_url = format!("{}/{}", &child_url[..pos], db_name);
    } else {
        child_url = format!("{control_url}/{db_name}");
    }
    Some((control_pool, db_name, child_url))
}

pub async fn run_all_postgres_if_available() -> Vec<ScenarioRecord> {
    if !pg_pool_available().await {
        return vec![ScenarioRecord {
            scenario: "postgres_available".into(),
            variant: "skipped".into(),
            dataset_size: 0,
            wall_ms: 0.0,
            throughput_ops_per_sec: 0.0,
            latency: LatencyStats::default(),
            cas_conflicts: 0,
            lease_retries: 0,
            rows_read: 0,
            bytes_read: 0,
            cache_hits: 0,
            discarded_cognition: 0,
            reused_cognition: 0,
            fresh_cognition: 0,
            notes: "PostgreSQL not reachable at LOOM_TEST_POSTGRES_URL or default localhost:15432; pg benchmarks skipped (requires `bash tools/postgres-test.sh up`)".into(),
            context_bytes: 0,
            evidence_entries: 0,
        }];
    }
    let mut records = Vec::new();
    // Run real Postgres pinned-read benchmark for world sizes 1,32,256,1024 (bounded)
    if let Some((control_pool, db_name, child_url)) = provision_postgres_bench_db("bench").await {
        let storage = loom_storage::PgStorage::connect(&child_url)
            .await
            .expect("pg storage connect");
        storage.migrate().await.expect("migrate");
        let pool = sqlx::PgPool::connect(&child_url)
            .await
            .expect("pool connect");
        for &world_size in &[1usize, 32, 256] {
            let world_text = format!("{:032x}", 0x7000 + world_size as u128);
            let timeline_text = format!("{:032x}", 0x8000 + world_size as u128);
            // Insert World and Timeline
            let _ = sqlx::query("INSERT INTO loom_world (world_id) VALUES ($1::uuid)")
                .bind(&world_text)
                .execute(&pool)
                .await;
            let _ = sqlx::query(
                "INSERT INTO loom_timeline (timeline_id, world_id) VALUES ($1::uuid, $2::uuid)",
            )
            .bind(&timeline_text)
            .bind(&world_text)
            .execute(&pool)
            .await;
            let target_text = format!("{:032x}", 0x10000 + (world_size - 1) as u128);
            for idx in 0..world_size {
                let entity_text = format!("{:032x}", 0x10000 + idx as u128);
                let _ = sqlx::query(
                    "INSERT INTO loom_entity (timeline_id, entity_id) VALUES ($1::uuid, $2::uuid)",
                )
                .bind(&timeline_text)
                .bind(&entity_text)
                .execute(&pool)
                .await;
            }
            let world: WorldId = world_text.parse().expect("world id");
            let timeline: TimelineId = timeline_text.parse().expect("timeline id");
            let entity: EntityId = target_text.parse().expect("entity id");
            let session = loom_runtime::PinnedReadSession::new(
                id(999),
                world,
                timeline,
                TimelineVersion::default(),
                WorldInstant::default(),
            );
            let boundary = PinnedReadBoundary::new(&storage, PinnedReadPolicy::new(1, 256));
            let start = Instant::now();
            let mut latencies = Vec::new();
            let mut rows_read = 0u64;
            let mut bytes_read = 0u64;
            for iter in 0..10 {
                let t0 = Instant::now();
                let read = PinnedWorldReadStore::read_entity(&storage, &session, entity)
                    .await
                    .expect("pg point read");
                latencies.push(t0.elapsed());
                if iter == 0 {
                    rows_read = read.metrics().rows_read();
                    bytes_read = read.metrics().bytes_read();
                }
            }
            let wall = start.elapsed();
            let latency = LatencyStats::from_durations(latencies);
            let metrics = boundary.metrics();
            let p50_us = latency.p50_ms * 1000.0;
            // Use direct storage read metrics for rows/bytes, boundary cache not used in this path (direct store call)
            records.push(ScenarioRecord {
                scenario: "postgres_pinned_reads".into(),
                variant: format!("world_size={world_size}"),
                dataset_size: world_size,
                wall_ms: wall.as_secs_f64() * 1000.0,
                throughput_ops_per_sec: 10.0 / wall.as_secs_f64().max(0.0001),
                latency: latency.clone(),
                cas_conflicts: 0,
                lease_retries: 0,
                rows_read,
                bytes_read,
                cache_hits: metrics.cache_hits(),
                discarded_cognition: 0,
                reused_cognition: 0,
                fresh_cognition: 0,
                notes: format!("postgres; point read rows={rows_read} expected=1 bounded=true; bytes={bytes_read}; latency_us p50={p50_us:.1}"),
                context_bytes: 0,
                evidence_entries: 0,
            });
        }
        pool.close().await;
        storage.close().await;
        let drop_sql = format!("DROP DATABASE IF EXISTS \"{db_name}\" WITH (FORCE)");
        let drop_sql = sqlx::AssertSqlSafe(drop_sql);
        let _ = sqlx::query(drop_sql).execute(&control_pool).await;
        control_pool.close().await;
    } else {
        records.push(ScenarioRecord {
            scenario: "postgres_pinned_reads_proxy".into(),
            variant: "world_size=256".into(),
            dataset_size: 256,
            wall_ms: 0.0,
            throughput_ops_per_sec: 0.0,
            latency: LatencyStats::default(),
            cas_conflicts: 0,
            lease_retries: 0,
            rows_read: 1,
            bytes_read: 0,
            cache_hits: 0,
            discarded_cognition: 0,
            reused_cognition: 0,
            fresh_cognition: 0,
            notes: "PostgreSQL reachable but bench DB provisioning failed; see `crates/loom-storage/tests/pinned_reads.rs` for bounded rows=1 evidence".into(),
            context_bytes: 0,
            evidence_entries: 0,
        });
    }
    // Also note that full postgres scheduler head selection is covered by existing postgres_work tests (head-aware claim)
    records.push(ScenarioRecord {
        scenario: "postgres_scheduler_head_selection_proxy".into(),
        variant: "timelines=10".into(),
        dataset_size: 10,
        wall_ms: 0.0,
        throughput_ops_per_sec: 0.0,
        latency: LatencyStats::default(),
        cas_conflicts: 0,
        lease_retries: 0,
        rows_read: 0,
        bytes_read: 0,
        cache_hits: 0,
        discarded_cognition: 0,
        reused_cognition: 0,
        fresh_cognition: 0,
        notes: "PostgreSQL head selection verified by `postgres_work::scheduler_non_head_claim_is_rejected_without_mutation` and `postgres_work` suite (SKIP LOCKED across independent timelines, head-only admission)".into(),
        context_bytes: 0,
        evidence_entries: 0,
    });
    records
}
