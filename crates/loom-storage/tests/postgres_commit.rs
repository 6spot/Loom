mod support;

use std::str::FromStr;

use loom_capability::{
    Capability, CapabilityManifest, CapabilityRegistrar, CapabilityRegistry, EventDefinition,
    FacetDefinition, RegistrationError, RelationshipDefinition, ResolutionContext, ResolverError,
    WorkHandler, WorkHandlerDefinition,
};
use loom_core::{
    EntityId, EventId, EventSeq, EventTypeId, FacetOwner, FacetTypeId, RelationshipId,
    RelationshipParticipant, RelationshipTypeId, SchemaRevision, TimelineId, WorkHandlerId, WorkId,
    WorldEffect, WorldId, WorldInstant,
};
use loom_protocol::{
    CausalLink, EventParticipant, EventRelationshipRef, NewWork, ProposedEvent, Resolution,
    ResolveOutcome, WorkMutation, WorkSchedule,
};
use loom_runtime::{
    AdvanceWorldTime, CommitError, CommitStore, EffectEngine, PlatformTime, RuntimeError,
    ValidationError, WorkClaim, WorkError, WorkStatus, WorldStore, WorldTimeError, WorldTimeStore,
};
use loom_storage::PgStorage;
use serde_json::{Value, json};
use sqlx::PgPool;
use support::TestDatabase;

const OWNER: &str = "postgres.commit.test";
const EVENT_TYPE: &str = "postgres.commit.changed";
const FACET_TYPE: &str = "postgres.commit.facet";
const RELATIONSHIP_TYPE: &str = "postgres.commit.relationship";
const WORK_HANDLER: &str = "postgres.commit.handler";

fn id<T>(value: u128) -> T
where
    T: FromStr,
    T::Err: std::fmt::Debug,
{
    format!("00000000-0000-0000-0000-{value:012x}")
        .parse()
        .expect("test identity should parse")
}

struct CommitTestCapability {
    manifest: CapabilityManifest,
}

struct EmptyWorkHandler;

impl WorkHandler for EmptyWorkHandler {
    fn handle(
        &self,
        _context: &dyn ResolutionContext,
        _payload: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        Ok(ResolveOutcome::Resolved(Resolution::default()))
    }
}

impl Capability for CommitTestCapability {
    fn manifest(&self) -> &CapabilityManifest {
        &self.manifest
    }

    fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
        registrar.register_facet(FacetDefinition::new(
            FacetTypeId::from(FACET_TYPE),
            SchemaRevision::new(1),
            json!({"type": "object"}),
        ))?;
        registrar.register_relationship(RelationshipDefinition::new(
            RelationshipTypeId::from(RELATIONSHIP_TYPE),
            SchemaRevision::new(1),
        ))?;
        registrar.register_event(EventDefinition::new(
            EventTypeId::from(EVENT_TYPE),
            SchemaRevision::new(1),
        ))?;
        registrar.register_work_handler(
            WorkHandlerDefinition::new(WorkHandlerId::from(WORK_HANDLER), SchemaRevision::new(1)),
            EmptyWorkHandler,
        )
    }
}

fn registry() -> CapabilityRegistry {
    CapabilityRegistry::assemble([CommitTestCapability {
        manifest: CapabilityManifest::parse(OWNER, "0.1.0")
            .expect("test Capability manifest should parse"),
    }])
    .expect("test Capability registry should assemble")
}

async fn authority(seed: u128) -> Option<(TestDatabase, PgStorage, PgPool, WorldId, TimelineId)> {
    let database = TestDatabase::provision("commit").await?;
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
async fn postgres_18_world_time_port_advances_and_rejects_stale_cas() {
    let Some((database, storage, pool, _world_id, timeline_id)) = authority(0x1050).await else {
        return;
    };
    let initial = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("initial Timeline should be readable");
    assert_eq!(initial.version().head_event_seq, EventSeq::new(0));
    assert_eq!(initial.version().state_revision.value(), 0);
    assert_eq!(initial.world_time(), WorldInstant::new(0));

    let transition = AdvanceWorldTime::new(
        timeline_id,
        initial.version(),
        initial.world_time(),
        WorldInstant::new(42),
    )
    .expect("forward World-Time transition should validate");
    let advanced = WorldTimeStore::advance_world_time(&storage, transition)
        .await
        .expect("PostgreSQL World-Time transition should succeed");
    assert_eq!(advanced.head_event_seq, EventSeq::new(0));
    assert_eq!(advanced.state_revision.value(), 1);

    let after_advance = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("advanced Timeline should be readable");
    assert_eq!(after_advance.version(), advanced);
    assert_eq!(after_advance.world_time(), WorldInstant::new(42));

    let stale = AdvanceWorldTime::new(
        timeline_id,
        initial.version(),
        initial.world_time(),
        WorldInstant::new(99),
    )
    .expect("stale transition remains structurally monotonic");
    let stale_error = WorldTimeStore::advance_world_time(&storage, stale)
        .await
        .expect_err("stale World-Time CAS should lose");
    assert!(matches!(
        stale_error,
        WorldTimeError::TimelineConflict { .. }
    ));

    let after_stale = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("Timeline should remain readable after stale CAS");
    assert_eq!(after_stale.version(), advanced);
    assert_eq!(after_stale.world_time(), WorldInstant::new(42));
    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}

async fn seed_entity(pool: &PgPool, timeline_id: TimelineId, entity_id: EntityId) {
    sqlx::query("INSERT INTO loom_entity (timeline_id, entity_id) VALUES ($1::uuid, $2::uuid)")
        .bind(timeline_id.to_string())
        .bind(entity_id.to_string())
        .execute(pool)
        .await
        .expect("test Entity should insert");
}

async fn seed_pending_work(pool: &PgPool, timeline_id: TimelineId, work_id: WorkId) {
    sqlx::query(
        "INSERT INTO loom_work \
         (timeline_id, work_id, target_kind, target_handler, schema_revision, payload, \
          effective_due_world_time, logical_schedule_order, status, attempt_count, \
          claim_generation, available_at) \
         VALUES ($1::uuid, $2::uuid, 'capability_work', $3, 1, '{}'::jsonb, 0, 1, \
                 'pending', 0, 0, 0)",
    )
    .bind(timeline_id.to_string())
    .bind(work_id.to_string())
    .bind(WORK_HANDLER)
    .execute(pool)
    .await
    .expect("test Work should insert");
}

fn event(event_id: EventId, source_time: i64) -> ProposedEvent {
    ProposedEvent::new(
        event_id,
        EventTypeId::from(EVENT_TYPE),
        SchemaRevision::new(1),
        json!({"event": event_id.to_string(), "source_time": source_time}),
    )
}

#[tokio::test]
async fn postgres_18_commit_multi_event_sequences_and_same_event_references() {
    let Some((database, storage, pool, _world_id, timeline_id)) = authority(0x1000).await else {
        return;
    };
    let left: EntityId = id(0x1010);
    let right: EntityId = id(0x1011);
    seed_entity(&pool, timeline_id, left).await;
    seed_entity(&pool, timeline_id, right).await;
    let created: EntityId = id(0x1020);
    let relationship: RelationshipId = id(0x1021);

    let mut first = event(id(0x1030), 5)
        .with_effect(WorldEffect::CreateEntity { entity_id: created })
        .with_effect(WorldEffect::PutFacet {
            owner: FacetOwner::entity(created),
            facet_type: FacetTypeId::from(FACET_TYPE),
            schema_revision: SchemaRevision::new(1),
            value: json!({"created": true}),
        });
    first
        .participants
        .push(EventParticipant::new(created, "subject"));
    let mut second = event(id(0x1031), 7).with_effect(WorldEffect::CreateRelationship {
        relationship_id: relationship,
        relationship_type: RelationshipTypeId::from(RELATIONSHIP_TYPE),
        participants: vec![
            RelationshipParticipant::new(left, "left"),
            RelationshipParticipant::new(right, "right"),
        ],
    });
    second
        .relationship_refs
        .push(EventRelationshipRef::new(relationship, "subject"));
    let mut third = event(id(0x1032), 6);
    third.causal_links.push(CausalLink::new(second.id));

    let token = validated(
        &storage,
        timeline_id,
        &registry(),
        Resolution::new(vec![first, second, third], Vec::new()),
    )
    .await;
    let result = CommitStore::commit(&storage, &token, None, PlatformTime::new(11))
        .await
        .expect("multi-Event PostgreSQL commit should succeed");

    assert_eq!(
        result
            .events
            .iter()
            .map(|item| item.event_seq.value())
            .collect::<Vec<_>>(),
        vec![1, 2, 3]
    );
    assert_eq!(result.version.head_event_seq, EventSeq::new(3));
    assert_eq!(result.version.state_revision.value(), 1);
    let snapshot = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("committed Timeline should be readable");
    assert_eq!(snapshot.world_time(), WorldInstant::new(0));
    assert_eq!(snapshot.events.len(), 3);
    assert!(snapshot.world_view().entity(created).is_some());
    assert!(snapshot.world_view().relationship(relationship).is_some());
    assert_eq!(snapshot.events[0].participants[0].entity_id, created);
    assert_eq!(
        snapshot.events[1].relationship_refs[0].relationship_id,
        relationship
    );
    assert_eq!(
        snapshot.events[2].causal_links[0].event_id(),
        snapshot.events[1].id
    );
    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}

#[tokio::test]
async fn postgres_18_commit_relationship_reference_survives_same_event_end() {
    let Some((database, storage, pool, _world_id, timeline_id)) = authority(0x1100).await else {
        return;
    };
    let left: EntityId = id(0x1110);
    let right: EntityId = id(0x1111);
    let relationship: RelationshipId = id(0x1120);
    seed_entity(&pool, timeline_id, left).await;
    seed_entity(&pool, timeline_id, right).await;
    sqlx::query(
        "INSERT INTO loom_relationship (timeline_id, relationship_id, relationship_type, active) \
         VALUES ($1::uuid, $2::uuid, $3, TRUE)",
    )
    .bind(timeline_id.to_string())
    .bind(relationship.to_string())
    .bind(RELATIONSHIP_TYPE)
    .execute(&pool)
    .await
    .expect("test Relationship should insert");
    for (order, entity_id, role) in [(0_i32, left, "left"), (1, right, "right")] {
        sqlx::query(
            "INSERT INTO loom_relationship_participant \
             (timeline_id, relationship_id, participant_order, entity_id, role) \
             VALUES ($1::uuid, $2::uuid, $3, $4::uuid, $5)",
        )
        .bind(timeline_id.to_string())
        .bind(relationship.to_string())
        .bind(order)
        .bind(entity_id.to_string())
        .bind(role)
        .execute(&pool)
        .await
        .expect("test Relationship participant should insert");
    }
    let mut proposed = event(id(0x1130), 3).with_effect(WorldEffect::EndRelationship {
        relationship_id: relationship,
    });
    proposed
        .relationship_refs
        .push(EventRelationshipRef::new(relationship, "subject"));
    let token = validated(
        &storage,
        timeline_id,
        &registry(),
        Resolution::new(vec![proposed], Vec::new()),
    )
    .await;

    CommitStore::commit(&storage, &token, None, PlatformTime::new(4))
        .await
        .expect("an Event may reference the active Relationship it ends");
    let snapshot = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("Timeline should remain readable");
    assert_eq!(
        snapshot.events[0].relationship_refs[0].relationship_id,
        relationship
    );
    assert!(snapshot.world_view().relationship(relationship).is_none());
    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}

#[tokio::test]
async fn postgres_18_commit_concurrent_cas_has_exactly_one_winner() {
    let Some((database, storage, pool, _world_id, timeline_id)) = authority(0x1200).await else {
        return;
    };
    let registry = registry();
    let snapshot = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("base Timeline should be readable");
    let view = snapshot.world_view();
    let first_entity: EntityId = id(0x1210);
    let second_entity: EntityId = id(0x1211);
    let first = EffectEngine::new(&registry)
        .validate(
            &view,
            OWNER,
            Resolution::new(
                vec![event(id(0x1220), 1).with_effect(WorldEffect::CreateEntity {
                    entity_id: first_entity,
                })],
                Vec::new(),
            ),
        )
        .expect("first Resolution should validate");
    let second = EffectEngine::new(&registry)
        .validate(
            &view,
            OWNER,
            Resolution::new(
                vec![event(id(0x1221), 2).with_effect(WorldEffect::CreateEntity {
                    entity_id: second_entity,
                })],
                Vec::new(),
            ),
        )
        .expect("second Resolution should validate");

    let (first_result, second_result) = tokio::join!(
        CommitStore::commit(&storage, &first, None, PlatformTime::new(5)),
        CommitStore::commit(&storage, &second, None, PlatformTime::new(5)),
    );
    let results = [first_result, second_result];
    assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
    assert_eq!(
        results
            .iter()
            .filter(|result| matches!(result, Err(CommitError::TimelineConflict { .. })))
            .count(),
        1
    );
    let after = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("winner state should be readable");
    assert_eq!(after.version().head_event_seq.value(), 1);
    assert_eq!(after.version().state_revision.value(), 1);
    assert_eq!(after.events.len(), 1);
    assert_ne!(
        after.world_view().entity(first_entity).is_some(),
        after.world_view().entity(second_entity).is_some()
    );
    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}

#[tokio::test]
async fn postgres_18_commit_work_failure_rolls_back_event_and_state() {
    let Some((database, storage, pool, _world_id, timeline_id)) = authority(0x1300).await else {
        return;
    };
    let duplicate_work: WorkId = id(0x1310);
    seed_pending_work(&pool, timeline_id, duplicate_work).await;
    let created: EntityId = id(0x1311);
    let resolution = Resolution::new(
        vec![event(id(0x1320), 9).with_effect(WorldEffect::CreateEntity { entity_id: created })],
        vec![WorkMutation::Schedule(NewWork::new(
            duplicate_work,
            timeline_id,
            WorkHandlerId::from(WORK_HANDLER),
            SchemaRevision::new(1),
            json!({}),
            WorkSchedule::Immediate,
        ))],
    );
    let token = validated(&storage, timeline_id, &registry(), resolution).await;

    let error = CommitStore::commit(&storage, &token, None, PlatformTime::new(12))
        .await
        .expect_err("duplicate Work should roll the transaction back");
    assert!(matches!(
        error,
        CommitError::Work(WorkError::DuplicateWork { .. })
    ));
    let after = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("rolled-back Timeline should be readable");
    assert_eq!(after.version().head_event_seq.value(), 0);
    assert_eq!(after.version().state_revision.value(), 0);
    assert_eq!(after.world_time(), WorldInstant::new(0));
    assert!(after.events.is_empty());
    assert!(after.world_view().entity(created).is_none());
    assert_eq!(after.works.len(), 1);
    assert_eq!(after.works[0].status, WorkStatus::Pending);
    assert!(after.journal.is_empty());
    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}

#[tokio::test]
async fn postgres_18_commit_no_change_and_work_only_semantics() {
    let Some((database, storage, pool, _world_id, timeline_id)) = authority(0x1400).await else {
        return;
    };
    let empty_registry = CapabilityRegistry::new();
    let empty = validated(
        &storage,
        timeline_id,
        &empty_registry,
        Resolution::default(),
    )
    .await;
    let no_change = CommitStore::commit(&storage, &empty, None, PlatformTime::new(17))
        .await
        .expect("true NoChange should commit as a no-op");
    assert_eq!(no_change.version.head_event_seq.value(), 0);
    assert_eq!(no_change.version.state_revision.value(), 0);

    let work_id: WorkId = id(0x1410);
    let work_only = validated(
        &storage,
        timeline_id,
        &registry(),
        Resolution::new(
            Vec::new(),
            vec![WorkMutation::Schedule(NewWork::new(
                work_id,
                timeline_id,
                WorkHandlerId::from(WORK_HANDLER),
                SchemaRevision::new(1),
                json!({"future": true}),
                WorkSchedule::At(WorldInstant::new(100)),
            ))],
        ),
    )
    .await;
    let result = CommitStore::commit(&storage, &work_only, None, PlatformTime::new(19))
        .await
        .expect("zero-Event Work mutation should commit Runtime state");
    assert!(result.events.is_empty());
    assert_eq!(result.version.head_event_seq.value(), 0);
    assert_eq!(result.version.state_revision.value(), 1);
    let after = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("Work-only commit should be readable");
    assert_eq!(after.world_time(), WorldInstant::new(0));
    let work = after
        .works
        .iter()
        .find(|item| item.id == work_id)
        .expect("scheduled Work should exist");
    assert_eq!(work.status, WorkStatus::Pending);
    assert_eq!(work.available_at, PlatformTime::new(19));
    assert_eq!(work.effective_due_world_time, WorldInstant::new(100));
    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}

#[tokio::test]
async fn postgres_18_commit_current_work_completion_is_atomic_runtime_state() {
    let Some((database, storage, pool, _world_id, timeline_id)) = authority(0x1500).await else {
        return;
    };
    let work_id: WorkId = id(0x1510);
    sqlx::query(
        "INSERT INTO loom_work \
         (timeline_id, work_id, target_kind, target_handler, schema_revision, payload, \
          effective_due_world_time, logical_schedule_order, status, attempt_count, \
          claim_generation, available_at, lease_claimed_until, lease_fence) \
         VALUES ($1::uuid, $2::uuid, 'capability_work', $3, 1, '{}'::jsonb, 0, 1, \
                 'pending', 1, 4, 0, 50, 4)",
    )
    .bind(timeline_id.to_string())
    .bind(work_id.to_string())
    .bind(WORK_HANDLER)
    .execute(&pool)
    .await
    .expect("leased Work should insert");
    let empty_registry = CapabilityRegistry::new();
    let token = validated(
        &storage,
        timeline_id,
        &empty_registry,
        Resolution::default(),
    )
    .await;
    let claim = WorkClaim::new(timeline_id, work_id, PlatformTime::new(50), 4);

    let result = CommitStore::commit(&storage, &token, Some(&claim), PlatformTime::new(20))
        .await
        .expect("current Work completion should commit atomically");
    assert_eq!(result.completed_work, Some(work_id));
    assert!(result.events.is_empty());
    assert_eq!(result.version.head_event_seq.value(), 0);
    assert_eq!(result.version.state_revision.value(), 1);
    let after = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("completed Work state should be readable");
    let work = after
        .works
        .iter()
        .find(|item| item.id == work_id)
        .expect("completed Work should remain readable");
    assert_eq!(work.status, WorkStatus::Completed);
    assert!(work.lease.is_none());
    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}

#[tokio::test]
async fn postgres_18_commit_runtime_and_storage_reject_forward_or_missing_structure() {
    let Some((database, storage, pool, _world_id, timeline_id)) = authority(0x1600).await else {
        return;
    };
    let registry = registry();
    let future_entity: EntityId = id(0x1610);
    let mut first = event(id(0x1620), 1);
    first
        .participants
        .push(EventParticipant::new(future_entity, "subject"));
    let second = event(id(0x1621), 2).with_effect(WorldEffect::CreateEntity {
        entity_id: future_entity,
    });
    let snapshot = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("base Timeline should be readable");
    let rejected = EffectEngine::new(&registry).validate(
        &snapshot.world_view(),
        OWNER,
        Resolution::new(vec![first, second], Vec::new()),
    );
    assert!(matches!(
        rejected,
        Err(RuntimeError::Validation(
            ValidationError::MissingEntity { .. }
        ))
    ));

    let existing: EntityId = id(0x1611);
    seed_entity(&pool, timeline_id, existing).await;
    let mut raced_event = event(id(0x1622), 3).with_effect(WorldEffect::CreateEntity {
        entity_id: id(0x1612),
    });
    raced_event
        .participants
        .push(EventParticipant::new(existing, "subject"));
    let raced_resolution = Resolution::new(vec![raced_event], Vec::new());
    let token = validated(&storage, timeline_id, &registry, raced_resolution.clone()).await;
    sqlx::query("DELETE FROM loom_entity WHERE timeline_id = $1::uuid AND entity_id = $2::uuid")
        .bind(timeline_id.to_string())
        .bind(existing.to_string())
        .execute(&pool)
        .await
        .expect("test race should remove the participant without advancing TimelineVersion");

    let storage_error = CommitStore::commit(&storage, &token, None, PlatformTime::new(4))
        .await
        .expect_err("storage hard boundary should reject the missing participant");
    assert!(matches!(storage_error, CommitError::InvalidEvent { .. }));
    let current = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("post-race Timeline should be readable");
    assert!(matches!(
        EffectEngine::new(&registry).validate(&current.world_view(), OWNER, raced_resolution),
        Err(RuntimeError::Validation(
            ValidationError::MissingEntity { .. }
        ))
    ));
    assert!(current.events.is_empty());
    assert!(current.world_view().entity(id(0x1612)).is_none());
    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}
