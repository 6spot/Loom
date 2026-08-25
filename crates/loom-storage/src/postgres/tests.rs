use super::PgStorage;

use std::{path::Path, process::Command, str::FromStr, sync::OnceLock};

use loom_agency::DecisionReusePolicy;
use loom_api::{
    AdminScheduleAgencyWakeRequest, AdminService, IngressAuthorizationContext, IngressEnvelope,
    IngressId, IngressProvenance, IngressService, IngressStatus, IngressTimeMetadata,
    TimelineTarget,
};
use loom_capability::{
    ActionDefinition, ActionResolver, Capability, CapabilityManifest, CapabilityRegistrar,
    CapabilityRegistry, EventDefinition, FacetDefinition, RegistrationError, ResolutionContext,
    ResolverError,
};
use loom_core::{
    ActionTypeId, EntityId, EventId, EventTypeId, FacetOwner, FacetTypeId, SchemaRevision,
    TimelineId, WorkId, WorldEffect, WorldId,
};
use loom_protocol::{ActionInvocation, ProposedEvent, Resolution, ResolveOutcome, WorkSchedule};
use loom_runtime::{
    CognitiveDisposition, CognitiveOutcome, DeterministicCognitiveExecutor,
    DeterministicCognitiveStep, ExecutionOrigin, ExecutionSessionStatus, ExecutionSessionStore,
    IngressStore, LogicalJournalStore, ManualPlatformClock, Runtime, WorldStore,
};
use serde_json::{Value, json};

const WORLD_ID: &str = "00000000-0000-0000-0000-000000000101";
const TIMELINE_ID: &str = "00000000-0000-0000-0000-000000000102";
const ENTITY_ID: &str = "00000000-0000-0000-0000-000000000103";
const AGENCY_COGNITION: &str = "deterministic.fake";
const DEFAULT_POSTGRES_CONTROL_URL: &str = "postgresql://loom:loom@127.0.0.1:15432/loom_control";

static REPOSITORY_POSTGRES_READY: OnceLock<()> = OnceLock::new();

fn postgres_url() -> String {
    match std::env::var("LOOM_TEST_POSTGRES_URL") {
        Ok(url) if !url.trim().is_empty() => url,
        _ => {
            REPOSITORY_POSTGRES_READY.get_or_init(start_repository_postgres);
            DEFAULT_POSTGRES_CONTROL_URL.to_owned()
        }
    }
}

fn start_repository_postgres() {
    let script = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tools/postgres-test.sh");
    let status = Command::new("bash")
        .arg(&script)
        .arg("up")
        .status()
        .unwrap_or_else(|error| {
            panic!(
                "failed to start repository-managed PostgreSQL test service with `{}`: {error}",
                script.display()
            )
        });
    assert!(
        status.success(),
        "repository-managed PostgreSQL test service startup `{}` exited with {status}",
        script.display()
    );
}

fn database_error_code(error: &sqlx::Error) -> Option<String> {
    error
        .as_database_error()
        .and_then(sqlx::error::DatabaseError::code)
        .map(std::borrow::Cow::into_owned)
}

#[tokio::test]
async fn postgres_18_schema_contract() {
    let database_url = postgres_url();

    let storage = PgStorage::connect(&database_url)
        .await
        .expect("PostgreSQL test database should accept connections");

    let server_version: i32 =
        sqlx::query_scalar("SELECT current_setting('server_version_num')::integer")
            .fetch_one(&storage.pool)
            .await
            .expect("PostgreSQL should report its server version");
    assert!(
        (180_000..190_000).contains(&server_version),
        "schema gate must run against PostgreSQL 18, got server_version_num={server_version}"
    );

    storage
        .migrate()
        .await
        .expect("migrations should apply to an empty PostgreSQL 18 database");
    storage
        .migrate()
        .await
        .expect("re-running unchanged migrations should be deterministic");
    storage.health().await.expect("health query should succeed");

    let loom_table_count: i64 = sqlx::query_scalar(
        "SELECT count(*)::bigint \
         FROM information_schema.tables \
         WHERE table_schema = 'public' AND table_name LIKE 'loom_%'",
    )
    .fetch_one(&storage.pool)
    .await
    .expect("schema tables should be inspectable");
    assert_eq!(loom_table_count, 22);

    sqlx::query("INSERT INTO loom_world (world_id) VALUES ($1::uuid)")
        .bind(WORLD_ID)
        .execute(&storage.pool)
        .await
        .expect("test World should insert");
    sqlx::query("INSERT INTO loom_timeline (timeline_id, world_id) VALUES ($1::uuid, $2::uuid)")
        .bind(TIMELINE_ID)
        .bind(WORLD_ID)
        .execute(&storage.pool)
        .await
        .expect("test Timeline should insert");
    sqlx::query("INSERT INTO loom_entity (timeline_id, entity_id) VALUES ($1::uuid, $2::uuid)")
        .bind(TIMELINE_ID)
        .bind(ENTITY_ID)
        .execute(&storage.pool)
        .await
        .expect("test Entity should insert");

    let duplicate_entity =
        sqlx::query("INSERT INTO loom_entity (timeline_id, entity_id) VALUES ($1::uuid, $2::uuid)")
            .bind(TIMELINE_ID)
            .bind(ENTITY_ID)
            .execute(&storage.pool)
            .await
            .expect_err("duplicate Timeline-local Entity identity must be rejected");
    assert_eq!(
        database_error_code(&duplicate_entity).as_deref(),
        Some("23505")
    );

    let missing_facet_owner = sqlx::query(
        "INSERT INTO loom_entity_facet \
         (timeline_id, entity_id, facet_type, schema_revision, value) \
         VALUES ($1::uuid, $2::uuid, 'test.missing', 1, '{}'::jsonb)",
    )
    .bind(TIMELINE_ID)
    .bind("00000000-0000-0000-0000-000000000199")
    .execute(&storage.pool)
    .await
    .expect_err("Facet owner foreign key must be enforced");
    assert_eq!(
        database_error_code(&missing_facet_owner).as_deref(),
        Some("23503")
    );

    let invalid_u64_range = sqlx::query(
        "INSERT INTO loom_timeline \
         (timeline_id, world_id, head_event_seq) \
         VALUES ('00000000-0000-0000-0000-000000000198'::uuid, $1::uuid, -1)",
    )
    .bind(WORLD_ID)
    .execute(&storage.pool)
    .await
    .expect_err("negative EventSeq representation must be rejected");
    assert_eq!(
        database_error_code(&invalid_u64_range).as_deref(),
        Some("23514")
    );

    storage.close().await;
}

#[tokio::test]
async fn postgres_18_read_snapshot_parity() {
    let database_url = postgres_url();
    let storage = PgStorage::connect(&database_url)
        .await
        .expect("PostgreSQL test database should accept connections");
    storage
        .migrate()
        .await
        .expect("migrations should be current");

    let world_id = "00000000-0000-0000-0000-000000000201";
    let timeline_id = "00000000-0000-0000-0000-000000000202";
    let entity_a = "00000000-0000-0000-0000-000000000203";
    let entity_b = "00000000-0000-0000-0000-000000000204";
    let relationship_id = "00000000-0000-0000-0000-000000000205";
    let event_first = "00000000-0000-0000-0000-000000000299";
    let event_second = "00000000-0000-0000-0000-000000000210";
    let work_id = "00000000-0000-0000-0000-000000000211";

    sqlx::query("INSERT INTO loom_world (world_id) VALUES ($1::uuid) ON CONFLICT DO NOTHING")
        .bind(world_id)
        .execute(&storage.pool)
        .await
        .expect("read fixture World should insert");
    sqlx::query(
        "INSERT INTO loom_timeline \
         (timeline_id, world_id, head_event_seq, state_revision, world_time) \
         VALUES ($1::uuid, $2::uuid, 2, 3, 42) ON CONFLICT DO NOTHING",
    )
    .bind(timeline_id)
    .bind(world_id)
    .execute(&storage.pool)
    .await
    .expect("read fixture Timeline should insert");
    for entity_id in [entity_a, entity_b] {
        sqlx::query(
            "INSERT INTO loom_entity (timeline_id, entity_id) VALUES ($1::uuid, $2::uuid) \
             ON CONFLICT DO NOTHING",
        )
        .bind(timeline_id)
        .bind(entity_id)
        .execute(&storage.pool)
        .await
        .expect("read fixture Entity should insert");
    }
    sqlx::query(
        "INSERT INTO loom_relationship \
         (timeline_id, relationship_id, relationship_type, active) \
         VALUES ($1::uuid, $2::uuid, 'test.membership', FALSE) ON CONFLICT DO NOTHING",
    )
    .bind(timeline_id)
    .bind(relationship_id)
    .execute(&storage.pool)
    .await
    .expect("read fixture Relationship should insert");
    sqlx::query(
        "INSERT INTO loom_relationship_participant \
         (timeline_id, relationship_id, participant_order, entity_id, role) \
         VALUES ($1::uuid, $2::uuid, 0, $3::uuid, 'member') ON CONFLICT DO NOTHING",
    )
    .bind(timeline_id)
    .bind(relationship_id)
    .bind(entity_a)
    .execute(&storage.pool)
    .await
    .expect("Relationship participant should insert");
    sqlx::query(
        "INSERT INTO loom_entity_facet \
         (timeline_id, entity_id, facet_type, schema_revision, value) \
         VALUES ($1::uuid, $2::uuid, 'test.counter', 1, '{\"value\":7}'::jsonb) \
         ON CONFLICT DO NOTHING",
    )
    .bind(timeline_id)
    .bind(entity_a)
    .execute(&storage.pool)
    .await
    .expect("Entity Facet should insert");
    sqlx::query(
        "INSERT INTO loom_relationship_facet \
         (timeline_id, relationship_id, facet_type, schema_revision, value) \
         VALUES ($1::uuid, $2::uuid, 'test.relationship_state', 2, '{\"ended\":true}'::jsonb) \
         ON CONFLICT DO NOTHING",
    )
    .bind(timeline_id)
    .bind(relationship_id)
    .execute(&storage.pool)
    .await
    .expect("Relationship Facet should insert");

    // Insert EventSeq 2 first and give EventSeq 1 the lexicographically larger UUID.
    // A correct adapter must still return [1, 2].
    for (event_id, sequence, event_type, occurred_at) in [
        (event_second, 2_i64, "test.second", 42_i64),
        (event_first, 1_i64, "test.first", 40_i64),
    ] {
        sqlx::query(
            "INSERT INTO loom_event \
             (timeline_id, event_id, event_seq, event_type, schema_revision, occurred_at, payload, effects) \
             VALUES ($1::uuid, $2::uuid, $3, $4, 1, $5, '{}'::jsonb, '[]'::jsonb) \
             ON CONFLICT DO NOTHING",
        )
        .bind(timeline_id)
        .bind(event_id)
        .bind(sequence)
        .bind(event_type)
        .bind(occurred_at)
        .execute(&storage.pool)
        .await
        .expect("Event fixture should insert");
    }
    sqlx::query(
        "INSERT INTO loom_event_participant \
         (timeline_id, event_id, participant_order, entity_id, role) \
         VALUES ($1::uuid, $2::uuid, 0, $3::uuid, 'actor') ON CONFLICT DO NOTHING",
    )
    .bind(timeline_id)
    .bind(event_first)
    .bind(entity_a)
    .execute(&storage.pool)
    .await
    .expect("Event participant should insert");
    sqlx::query(
        "INSERT INTO loom_event_relationship_ref \
         (timeline_id, event_id, reference_order, relationship_id, role) \
         VALUES ($1::uuid, $2::uuid, 0, $3::uuid, 'subject') ON CONFLICT DO NOTHING",
    )
    .bind(timeline_id)
    .bind(event_first)
    .bind(relationship_id)
    .execute(&storage.pool)
    .await
    .expect("Event Relationship reference should insert");
    sqlx::query(
        "INSERT INTO loom_event_causal_link \
         (timeline_id, event_id, causal_order, cause_event_id) \
         VALUES ($1::uuid, $2::uuid, 0, $3::uuid) ON CONFLICT DO NOTHING",
    )
    .bind(timeline_id)
    .bind(event_second)
    .bind(event_first)
    .execute(&storage.pool)
    .await
    .expect("Event causal link should insert");
    sqlx::query(
        "INSERT INTO loom_work \
         (timeline_id, work_id, target_kind, target_handler, schema_revision, payload, \
          effective_due_world_time, logical_schedule_order, status, attempt_count, \
          claim_generation, available_at) \
         VALUES ($1::uuid, $2::uuid, 'capability_work', 'test.handler', 1, '{}'::jsonb, 50, 1, \
          'pending', 2, 4, 9) \
         ON CONFLICT DO NOTHING",
    )
    .bind(timeline_id)
    .bind(work_id)
    .execute(&storage.pool)
    .await
    .expect("Work fixture should insert");

    let timeline: loom_core::TimelineId = timeline_id.parse().expect("TimelineId should parse");
    let snapshot = loom_runtime::WorldStore::snapshot(&storage, timeline)
        .await
        .expect("PostgreSQL snapshot should reconstruct the fixture");
    assert_eq!(snapshot.version().head_event_seq.value(), 2);
    assert_eq!(snapshot.version().state_revision.value(), 3);
    assert_eq!(snapshot.world_time().value(), 42);
    assert_eq!(snapshot.events.len(), 2);
    assert_eq!(snapshot.events[0].event_seq.value(), 1);
    assert_eq!(snapshot.events[1].event_seq.value(), 2);
    assert_eq!(snapshot.events[0].id.to_string(), event_first);
    assert_eq!(snapshot.events[0].participants.len(), 1);
    assert_eq!(snapshot.events[0].relationship_refs.len(), 1);
    assert_eq!(
        snapshot.events[1].causal_links[0].event_id(),
        snapshot.events[0].id
    );
    assert_eq!(snapshot.works.len(), 1);
    assert_eq!(snapshot.works[0].attempt_count, 2);
    assert_eq!(snapshot.works[0].claim_generation, 4);
    assert_eq!(snapshot.works[0].available_at.value(), 9);

    let view = snapshot.world_view();
    let entity: loom_core::EntityId = entity_a.parse().expect("EntityId should parse");
    assert!(view.entity(entity).is_some());
    let relationship: loom_core::RelationshipId = relationship_id
        .parse()
        .expect("RelationshipId should parse");
    assert!(
        view.relationship(relationship).is_none(),
        "ended Relationship must not be active"
    );
    assert_eq!(
        view.facet(
            loom_core::FacetOwner::entity(entity),
            &loom_core::FacetTypeId::from("test.counter"),
        )
        .expect("Entity Facet should be reconstructed")
        .value(),
        &serde_json::json!({"value": 7}),
    );

    let missing: loom_core::TimelineId = "00000000-0000-0000-0000-000000000298"
        .parse()
        .expect("missing TimelineId should parse");
    assert!(matches!(
        loom_runtime::WorldStore::snapshot(&storage, missing).await,
        Err(loom_runtime::ReadError::TimelineNotFound { .. })
    ));
    storage.close().await;
}

const INGRESS_OWNER: &str = "postgres.vertical.counter";
const INGRESS_FACET: &str = "postgres.unit.ingress.value";
const INGRESS_ACTION: &str = "postgres.unit.ingress.increment";
const INGRESS_EVENT: &str = "postgres.unit.ingress.incremented";

struct IngressCapability {
    manifest: CapabilityManifest,
    entity_id: EntityId,
}

impl Capability for IngressCapability {
    fn manifest(&self) -> &CapabilityManifest {
        &self.manifest
    }

    fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
        registrar.register_facet(FacetDefinition::new(
            FacetTypeId::from(INGRESS_FACET),
            SchemaRevision::new(1),
            json!({
                "type": "object",
                "required": ["value"],
                "properties": {"value": {"type": "integer"}}
            }),
        ))?;
        registrar.register_event(
            EventDefinition::new(EventTypeId::from(INGRESS_EVENT), SchemaRevision::new(1))
                .with_payload_schema(json!({
                    "type": "object",
                    "required": ["previous", "amount", "value"],
                    "properties": {
                        "previous": {"type": "integer"},
                        "amount": {"type": "integer"},
                        "value": {"type": "integer"}
                    }
                })),
        )?;
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(INGRESS_ACTION), SchemaRevision::new(1))
                .with_input_schema(json!({
                    "type": "object",
                    "required": ["amount", "event_id"],
                    "properties": {
                        "amount": {"type": "integer"},
                        "event_id": {"type": "string"}
                    }
                })),
            IngressIncrementer {
                entity_id: self.entity_id,
            },
        )?;
        Ok(())
    }
}

#[derive(Clone, Copy)]
struct IngressIncrementer {
    entity_id: EntityId,
}

impl ActionResolver for IngressIncrementer {
    fn resolve(
        &self,
        context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        let amount = input
            .get("amount")
            .and_then(Value::as_i64)
            .ok_or_else(|| ResolverError::new("amount must be an integer"))?;
        let event_id = input
            .get("event_id")
            .and_then(Value::as_str)
            .ok_or_else(|| ResolverError::new("event_id must be a UUID string"))?
            .parse::<EventId>()
            .map_err(|_| ResolverError::new("event_id must be a UUID string"))?;
        let current = context
            .get_facet(
                FacetOwner::entity(self.entity_id),
                &FacetTypeId::from(INGRESS_FACET),
            )?
            .ok_or_else(|| ResolverError::new("Ingress Facet is missing"))?
            .value
            .get("value")
            .and_then(Value::as_i64)
            .ok_or_else(|| ResolverError::new("Ingress Facet value is not an integer"))?;
        let next = current
            .checked_add(amount)
            .ok_or_else(|| ResolverError::new("Ingress value overflowed"))?;
        Ok(ResolveOutcome::Resolved(Resolution::new(
            vec![
                ProposedEvent::new(
                    event_id,
                    EventTypeId::from(INGRESS_EVENT),
                    SchemaRevision::new(1),
                    json!({"previous": current, "amount": amount, "value": next}),
                )
                .with_effect(WorldEffect::PutFacet {
                    owner: FacetOwner::entity(self.entity_id),
                    facet_type: FacetTypeId::from(INGRESS_FACET),
                    schema_revision: SchemaRevision::new(1),
                    value: json!({"value": next}),
                }),
            ],
            Vec::new(),
        )))
    }
}

fn ingress_registry(entity_id: EntityId) -> CapabilityRegistry {
    CapabilityRegistry::assemble([IngressCapability {
        manifest: CapabilityManifest::parse(INGRESS_OWNER, "0.1.0")
            .expect("Ingress test Capability manifest should parse"),
        entity_id,
    }])
    .expect("Ingress test Capability registry should assemble")
}

fn unique_id<T>(tag: u64) -> T
where
    T: FromStr,
    T::Err: std::fmt::Debug,
{
    let nanos = u64::try_from(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("system clock should be after Unix epoch")
            .as_nanos(),
    )
    .expect("test clock should fit in u64 nanoseconds");
    let value = ((nanos ^ (u64::from(std::process::id()) << 16)) & 0x0000_ffff_ffff_ffff)
        .wrapping_add(tag)
        & 0x0000_ffff_ffff_ffff;
    format!("00000000-0000-0000-0000-{value:012x}")
        .parse()
        .expect("test identity should parse")
}

async fn postgres_agency_fixture() -> (PgStorage, WorldId, TimelineId, EntityId) {
    let database_url = postgres_url();
    let storage = PgStorage::connect(&database_url)
        .await
        .expect("PostgreSQL test database should accept connections");
    storage
        .migrate()
        .await
        .expect("migrations should be current");
    let world_id = unique_id::<WorldId>(0x301);
    let timeline_id = unique_id::<TimelineId>(0x302);
    let entity_id = unique_id::<EntityId>(0x303);
    sqlx::query("INSERT INTO loom_world (world_id) VALUES ($1::uuid)")
        .bind(world_id.to_string())
        .execute(&storage.pool)
        .await
        .expect("Agency fixture World should insert");
    sqlx::query("INSERT INTO loom_timeline (timeline_id, world_id) VALUES ($1::uuid, $2::uuid)")
        .bind(timeline_id.to_string())
        .bind(world_id.to_string())
        .execute(&storage.pool)
        .await
        .expect("Agency fixture Timeline should insert");
    sqlx::query("INSERT INTO loom_entity (timeline_id, entity_id) VALUES ($1::uuid, $2::uuid)")
        .bind(timeline_id.to_string())
        .bind(entity_id.to_string())
        .execute(&storage.pool)
        .await
        .expect("Agency fixture Entity should insert");
    (storage, world_id, timeline_id, entity_id)
}

#[tokio::test]
#[expect(
    clippy::too_many_lines,
    reason = "the PostgreSQL Agency Wake CAS scenario keeps schedule, recovery and provenance together"
)]
async fn postgres_agency_wake_resample_cas_conflict_is_single_winner_and_durable() {
    let (storage, world_id, timeline_id, entity_id) = postgres_agency_fixture().await;
    let target = TimelineTarget::new(world_id, timeline_id);
    let wake_work_id = unique_id::<WorkId>(0x304);
    let conflict_work_id = unique_id::<WorkId>(0x305);
    let scripted = DeterministicCognitiveExecutor::new([
        DeterministicCognitiveStep::no_action(),
        DeterministicCognitiveStep::no_action(),
    ]);
    let runtime = Runtime::new(storage.clone(), CapabilityRegistry::new())
        .expect("Agency Runtime should assemble")
        .with_cognitive_executor(scripted);
    let initial = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("initial Agency Timeline should be readable");
    let first_schedule = AdminService::schedule_agency_wake(
        &runtime,
        AdminScheduleAgencyWakeRequest {
            target,
            expected_version: initial.version(),
            work_id: wake_work_id,
            agent: entity_id,
            cognition: AGENCY_COGNITION.to_owned(),
            payload: json!({"policy": "default"}),
            schedule: WorkSchedule::Immediate,
        },
    )
    .await
    .expect("Agency Wake schedule should persist");
    let second_schedule = AdminService::schedule_agency_wake(
        &runtime,
        AdminScheduleAgencyWakeRequest {
            target,
            expected_version: first_schedule.version,
            work_id: conflict_work_id,
            agent: entity_id,
            cognition: AGENCY_COGNITION.to_owned(),
            payload: json!({"policy": "conflict"}),
            schedule: WorkSchedule::Immediate,
        },
    )
    .await
    .expect("conflict Work schedule should persist");
    storage.inject_scheduler_conflict_once_for_test(conflict_work_id);

    let first_result = runtime
        .execute_work(
            target,
            wake_work_id,
            loom_runtime::PlatformTime::new(0),
            loom_runtime::PlatformTime::new(10),
            loom_runtime::PlatformTime::new(2),
        )
        .await;
    assert!(matches!(
        first_result,
        Err(loom_api::ApiError {
            code: loom_api::ApiErrorCode::Conflict,
            ..
        })
    ));
    let after_conflict = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("conflicted Agency Timeline should be readable");
    assert_eq!(after_conflict.events.len(), 0);
    assert_eq!(
        after_conflict
            .works
            .iter()
            .find(|work| work.id == wake_work_id)
            .expect("Wake should remain pending after stale CAS")
            .attempt_count,
        1
    );
    assert_eq!(
        after_conflict
            .works
            .iter()
            .find(|work| work.id == conflict_work_id)
            .expect("conflict Work should remain readable")
            .status,
        loom_runtime::WorkStatus::Cancelled
    );
    assert_ne!(after_conflict.version(), second_schedule.version);

    let result = runtime
        .execute_work(
            target,
            wake_work_id,
            loom_runtime::PlatformTime::new(2),
            loom_runtime::PlatformTime::new(12),
            loom_runtime::PlatformTime::new(4),
        )
        .await
        .expect("resampled Agency Wake should commit");
    assert!(matches!(
        result,
        loom_api::ExecutionResult::Committed { ref event_ids, .. }
            if event_ids.is_empty()
    ));
    let final_snapshot = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("final Agency Timeline should be readable");
    assert_eq!(final_snapshot.events.len(), 0);
    assert_eq!(
        final_snapshot
            .works
            .iter()
            .find(|work| work.id == wake_work_id)
            .expect("Wake should be completed once")
            .status,
        loom_runtime::WorkStatus::Completed
    );

    let sessions = ExecutionSessionStore::list_sessions(&storage)
        .await
        .expect("Agency Sessions should survive the CAS retry")
        .into_iter()
        .filter(|session| session.assembly().timeline_id() == timeline_id)
        .collect::<Vec<_>>();
    assert_eq!(
        sessions.len(),
        2,
        "CAS recovery should retain two Agency Sessions"
    );
    let failed = sessions
        .iter()
        .find(|session| session.status() == ExecutionSessionStatus::Failed)
        .expect("stale Agency Session should be failed");
    let committed = sessions
        .iter()
        .find(|session| session.status() == ExecutionSessionStatus::Committed)
        .expect("resampled Agency Session should commit");
    assert_eq!(failed.cognitive_evidence().discarded_count(), 1);
    assert_eq!(failed.cognitive_evidence().fresh_count(), 0);
    assert_eq!(committed.cognitive_evidence().fresh_count(), 1);
    assert_eq!(committed.cognitive_evidence().reused_count(), 0);
    assert_eq!(committed.cognitive_evidence().discarded_count(), 0);
    assert_eq!(
        committed.cognitive_evidence().observations()[0].outcome,
        CognitiveOutcome::NoAction
    );
    assert_eq!(
        committed.cognitive_evidence().observations()[0].disposition,
        CognitiveDisposition::Fresh
    );
    assert_eq!(
        failed.cognitive_evidence().observations()[0]
            .policy
            .decision_reuse,
        DecisionReusePolicy::Resample
    );
    assert_eq!(
        committed.cognitive_evidence().observations()[0]
            .policy
            .decision_reuse,
        DecisionReusePolicy::Resample
    );
    assert_ne!(
        failed.cognitive_evidence().observations()[0].version,
        committed.cognitive_evidence().observations()[0].version
    );
    storage.close().await;
}

async fn ingress_authority_fixture() -> (String, PgStorage, WorldId, TimelineId, EntityId, EventId)
{
    let database_url = postgres_url();
    let storage = PgStorage::connect(&database_url)
        .await
        .expect("PostgreSQL test database should accept connections");
    storage
        .migrate()
        .await
        .expect("migrations should be current");

    let world_id = unique_id::<WorldId>(0x101);
    let timeline_id = unique_id::<TimelineId>(0x102);
    let entity_id = unique_id::<EntityId>(0x103);
    let event_id = unique_id::<EventId>(0x104);
    sqlx::query("INSERT INTO loom_world (world_id) VALUES ($1::uuid)")
        .bind(world_id.to_string())
        .execute(&storage.pool)
        .await
        .expect("Ingress fixture World should insert");
    sqlx::query("INSERT INTO loom_timeline (timeline_id, world_id) VALUES ($1::uuid, $2::uuid)")
        .bind(timeline_id.to_string())
        .bind(world_id.to_string())
        .execute(&storage.pool)
        .await
        .expect("Ingress fixture Timeline should insert");
    sqlx::query("INSERT INTO loom_entity (timeline_id, entity_id) VALUES ($1::uuid, $2::uuid)")
        .bind(timeline_id.to_string())
        .bind(entity_id.to_string())
        .execute(&storage.pool)
        .await
        .expect("Ingress fixture Entity should insert");
    sqlx::query(
        "INSERT INTO loom_entity_facet \
         (timeline_id, entity_id, facet_type, schema_revision, value) \
         VALUES ($1::uuid, $2::uuid, $3, 1, '{\"value\":0}'::jsonb)",
    )
    .bind(timeline_id.to_string())
    .bind(entity_id.to_string())
    .bind(INGRESS_FACET)
    .execute(&storage.pool)
    .await
    .expect("Ingress fixture Facet should insert");

    (
        database_url,
        storage,
        world_id,
        timeline_id,
        entity_id,
        event_id,
    )
}

#[tokio::test]
#[expect(
    clippy::too_many_lines,
    reason = "the PostgreSQL Ingress crash-window recovery stays in one unit harness scenario"
)]
async fn postgres_runtime_ingress_completion_and_provenance_survive_restart() {
    let (database_url, storage, world_id, timeline_id, entity_id, event_id) =
        ingress_authority_fixture().await;
    let target = loom_api::TimelineTarget::new(world_id, timeline_id);
    let clock = ManualPlatformClock::new(loom_runtime::PlatformTime::new(10));
    let runtime = Runtime::new(storage.clone(), ingress_registry(entity_id))
        .expect("Runtime should assemble")
        .with_platform_clock(clock);
    let ingress_id = IngressId::from(format!("postgres-runtime-ingress-{event_id}"));
    runtime
        .submit_ingress(IngressEnvelope::new(
            ingress_id.clone(),
            format!("postgres-runtime-ingress-key-{event_id}"),
            IngressProvenance::new("postgres-unit-test"),
            target,
            IngressAuthorizationContext::new(json!({"role": "test"})),
            IngressTimeMetadata::none(),
            ActionInvocation::new(
                ActionTypeId::from(INGRESS_ACTION),
                json!({
                    "amount": 2,
                    "event_id": event_id.to_string()
                }),
            ),
        ))
        .await
        .expect("Ingress should be accepted");
    storage.fail_next_commit_outcome_unknown_for_test();
    storage.fail_next_ingress_finalization_for_test();
    runtime
        .process_ingress(
            ingress_id.clone(),
            loom_runtime::PlatformTime::new(10),
            loom_runtime::PlatformTime::new(20),
            loom_runtime::PlatformTime::new(10),
        )
        .await
        .expect_err("the test harness should interrupt finalization after an unknown commit");
    let first_record = IngressStore::ingress(&storage, ingress_id.clone())
        .await
        .expect("Ingress should remain readable after injected interruption");
    assert!(matches!(first_record.status, IngressStatus::Processing));
    drop(runtime);
    storage.close().await;

    let restarted_storage = PgStorage::connect(&database_url)
        .await
        .expect("restarted PostgreSQL storage should connect");
    let restarted_clock = ManualPlatformClock::new(loom_runtime::PlatformTime::new(20));
    let restarted_runtime = Runtime::new(restarted_storage.clone(), ingress_registry(entity_id))
        .expect("restarted Runtime should assemble")
        .with_platform_clock(restarted_clock);
    let completion = restarted_runtime
        .process_ingress(
            ingress_id.clone(),
            loom_runtime::PlatformTime::new(20),
            loom_runtime::PlatformTime::new(30),
            loom_runtime::PlatformTime::new(20),
        )
        .await
        .expect("restarted Ingress should reconcile and finalize");
    assert!(completion.is_committed());
    let snapshot = WorldStore::snapshot(&restarted_storage, timeline_id)
        .await
        .expect("committed Timeline should be readable");
    assert_eq!(snapshot.events.len(), 1);
    assert_eq!(snapshot.works.len(), 0);
    let status = restarted_runtime
        .ingress_status(ingress_id.clone())
        .await
        .expect("restarted Runtime should read Ingress completion");
    assert!(matches!(status.status, IngressStatus::Completed(_)));
    let sessions = ExecutionSessionStore::list_sessions(&restarted_storage)
        .await
        .expect("restarted Runtime should read Session provenance");
    let session = sessions
        .iter()
        .find(|session| session.ingress_id() == Some(&ingress_id))
        .expect("Ingress Session should survive restart");
    assert_eq!(session.origin(), ExecutionOrigin::Ingress);
    assert_eq!(session.status(), ExecutionSessionStatus::Committed);
    assert_eq!(session.ingress_completion(), Some(&completion));
    let provenance = session
        .commit_provenance()
        .expect("committed Session should retain provenance");
    assert_eq!(provenance.ingress_id, ingress_id);
    let journal = LogicalJournalStore::read_logical_journal(&restarted_storage, timeline_id)
        .await
        .expect("authority journal should survive restart");
    assert_eq!(journal.len(), 1);
    assert_eq!(journal[0].provenance.as_ref(), Some(provenance));
    assert_eq!(
        WorldStore::snapshot(&restarted_storage, timeline_id)
            .await
            .expect("restarted Timeline should be readable")
            .events
            .len(),
        1
    );
    restarted_storage.close().await;
}
