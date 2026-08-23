//! `PostgreSQL` 18 storage foundation for Loom Runtime persistence ports.
//!
//! This module owns concrete `SQLx`/`PostgreSQL` concerns. `PgStorage` deliberately
//! exposes no `PgPool` accessor: Runtime and higher Loom layers consume
//! Runtime-owned persistence traits rather than reaching through the adapter to
//! issue SQL directly. M2-T1 establishes connection, migration and health
//! behavior plus the M2-T2 `WorldStore` read path. M2-T3 adds the atomic
//! `CommitStore` path, and M2-T4 adds Durable Work claim/retry fencing in
//! private child modules.

mod commit;
mod fork;
mod session;
mod work;

use std::{fmt::Display, str::FromStr, time::Instant};

use loom_core::{
    AssociationRole, Entity, EntityId, EventId, EventRef, EventSeq, EventTypeId, FacetOwner,
    FacetTypeId, Relationship, RelationshipId, RelationshipParticipant, RelationshipTypeId,
    SchemaRevision, StateRevision, TimelineAncestry, TimelineId, TimelineVersion, WorkId,
    WorldEffect, WorldId, WorldInstant,
};
use loom_runtime::{
    AdvanceWorldTime, BaseWorldSnapshot, BindingError, ChronologyBudgetConsumption,
    ChronologyBudgetState, CommittedEvent, LifecycleError, LogicalCommit, LogicalJournalStore,
    LogicalWorkTransition, PersistenceFuture, PinnedFacet, PinnedRead, PinnedReadMetrics,
    PinnedReadSession, PinnedWorldReadStore, PlatformTime, ProposedEvent, ReadError,
    RuntimeRevisionDescriptor, RuntimeRevisionError, RuntimeRevisionId, RuntimeRevisionSelection,
    RuntimeRevisionStore, TimelineFork, TimelineForkStore, TimelineSnapshot, ValidatedResolution,
    WorkLease, WorkRecord, WorkStatus, WorkTarget, WorldCreation, WorldLifecycleStore,
    WorldRuntimeBinding, WorldRuntimeBindingStore, WorldStore, WorldTimeError, WorldTimeStore,
    WorldTimeTransition,
};
use serde_json::Value;
use sqlx::{PgPool, Postgres, Row, Transaction, postgres::PgPoolOptions};

static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!();

const HEALTH_SQL: &str = include_str!("../sql/health/check.sql");
const REPEATABLE_READ_READ_ONLY_SQL: &str =
    include_str!("../sql/transaction/repeatable_read_read_only.sql");
const READ_TIMELINE_SQL: &str = include_str!("../sql/world/read_timeline.sql");
const READ_ENTITY_SQL: &str = include_str!("../sql/world/read_entity.sql");
const READ_RELATIONSHIP_SQL: &str = include_str!("../sql/world/read_relationship.sql");
const READ_ENTITY_FACET_SQL: &str = include_str!("../sql/world/read_entity_facet.sql");
const READ_RELATIONSHIP_FACET_SQL: &str = include_str!("../sql/world/read_relationship_facet.sql");
const READ_ENTITIES_SQL: &str = include_str!("../sql/world/read_entities.sql");
const READ_RELATIONSHIPS_SQL: &str = include_str!("../sql/world/read_relationships.sql");
const READ_RELATIONSHIP_PARTICIPANTS_SQL: &str =
    include_str!("../sql/world/read_relationship_participants.sql");
const READ_ENTITY_FACETS_SQL: &str = include_str!("../sql/world/read_entity_facets.sql");
const READ_RELATIONSHIP_FACETS_SQL: &str =
    include_str!("../sql/world/read_relationship_facets.sql");
const READ_VISIBLE_EVENTS_SQL: &str = include_str!("../sql/ancestry/read_visible_events.sql");
const READ_VISIBLE_EVENT_SQL: &str = include_str!("../sql/ancestry/read_visible_event.sql");
const READ_EVENT_PARTICIPANTS_SQL: &str = include_str!("../sql/event/read_participants.sql");
const READ_EVENT_RELATIONSHIP_REFS_SQL: &str =
    include_str!("../sql/event/read_relationship_refs.sql");
const READ_EVENT_CAUSAL_LINKS_SQL: &str = include_str!("../sql/event/read_causal_links.sql");
const READ_WORK_SQL: &str = include_str!("../sql/work/read_all_for_timeline.sql");
const READ_LOGICAL_JOURNAL_SQL: &str = include_str!("../sql/logical_journal/read_all.sql");
const INSERT_WORLD_SQL: &str = include_str!("../sql/world/insert_world.sql");
const WORLD_EXISTS_SQL: &str = include_str!("../sql/world/exists.sql");
const LOCK_WORLD_EXISTS_SQL: &str = include_str!("../sql/world/lock_exists.sql");
const INSERT_BINDING_SQL: &str = include_str!("../sql/binding/insert.sql");
const INSERT_BINDING_IF_ABSENT_SQL: &str = include_str!("../sql/binding/insert_if_absent.sql");
const READ_BINDING_SQL: &str = include_str!("../sql/binding/read.sql");
const INSERT_TIMELINE_SQL: &str = include_str!("../sql/timeline/insert.sql");
const REGISTER_RUNTIME_REVISION_SQL: &str = include_str!("../sql/runtime_revision/register.sql");
const READ_RUNTIME_REVISION_SQL: &str = include_str!("../sql/runtime_revision/read.sql");
const LIST_RUNTIME_REVISIONS_SQL: &str = include_str!("../sql/runtime_revision/list.sql");
const READ_ACTIVE_RUNTIME_REVISION_SQL: &str =
    include_str!("../sql/runtime_revision/read_active.sql");
const LOCK_ACTIVE_RUNTIME_REVISION_SQL: &str =
    include_str!("../sql/runtime_revision/lock_active.sql");
const ACTIVATE_RUNTIME_REVISION_SQL: &str = include_str!("../sql/runtime_revision/activate.sql");
const LOCK_WORLD_TIME_SQL: &str = include_str!("../sql/timeline/lock_world_time.sql");
const UPDATE_WORLD_TIME_SQL: &str = include_str!("../sql/timeline/update_world_time.sql");
const SELECT_DUE_PENDING_SQL: &str = include_str!("../sql/work/select_due_pending.sql");

/// Concrete `PostgreSQL` persistence adapter owned by `loom-storage`.
///
/// The contained `SQLx` pool is intentionally private. Application composition
/// code may construct this adapter and inject it into Runtime-owned persistence
/// ports, but Core/Protocol/API/Capability/Runtime code must never receive the
/// underlying pool or `SQLx` transaction types.
#[derive(Clone, Debug)]
pub struct PgStorage {
    pool: PgPool,
}

impl PgStorage {
    /// Connects to an existing `PostgreSQL` database without changing its schema.
    ///
    /// Migrations are explicit through [`Self::migrate`] so deployment/startup
    /// policy can decide when schema changes are allowed. This method owns only
    /// concrete adapter setup; it does not grant Runtime commit authority.
    ///
    /// # Errors
    ///
    /// Returns [`sqlx::Error`] when `SQLx` cannot establish the `PostgreSQL` pool.
    pub async fn connect(database_url: &str) -> Result<Self, sqlx::Error> {
        let pool = PgPoolOptions::new().connect(database_url).await?;
        Ok(Self { pool })
    }

    /// Applies the embedded, repository-versioned `SQLx` migrations.
    ///
    /// SQL migrations under `crates/loom-storage/migrations` are the readable
    /// database representation of the already-reviewed Loom persistence
    /// contract. Re-running this method is safe: `SQLx` records applied migration
    /// checksums and does not replay an unchanged migration.
    ///
    /// # Errors
    ///
    /// Returns [`sqlx::migrate::MigrateError`] if migration metadata is invalid,
    /// a migration checksum changed, or `PostgreSQL` rejects a migration.
    pub async fn migrate(&self) -> Result<(), sqlx::migrate::MigrateError> {
        MIGRATOR.run(&self.pool).await
    }

    /// Checks whether the configured `PostgreSQL` authority database is reachable.
    ///
    /// This is an operational adapter health check only. A successful result
    /// does not mean migrations are current and does not imply any World commit
    /// has been authorized.
    ///
    /// # Errors
    ///
    /// Returns [`sqlx::Error`] when the pool cannot execute a trivial query.
    pub async fn health(&self) -> Result<(), sqlx::Error> {
        let _: i32 = sqlx::query_scalar(HEALTH_SQL).fetch_one(&self.pool).await?;
        Ok(())
    }

    /// Gracefully closes the `SQLx` pool owned by this adapter.
    pub async fn close(&self) {
        self.pool.close().await;
    }
}

impl PgStorage {
    async fn read_snapshot(&self, timeline_id: TimelineId) -> Result<TimelineSnapshot, ReadError> {
        let mut transaction = self.pool.begin().await.map_err(sql_read_error)?;
        sqlx::query(REPEATABLE_READ_READ_ONLY_SQL)
            .execute(&mut *transaction)
            .await
            .map_err(sql_read_error)?;

        let timeline_row = sqlx::query(READ_TIMELINE_SQL)
            .bind(timeline_id.to_string())
            .fetch_optional(&mut *transaction)
            .await
            .map_err(sql_read_error)?;
        let Some(timeline_row) = timeline_row else {
            let _ = transaction.rollback().await;
            return Err(ReadError::TimelineNotFound { timeline_id });
        };

        let world_id =
            parse_identity::<WorldId>(&row_string(&timeline_row, "world_id")?, "WorldId")?;
        let head_event_seq = EventSeq::new(parse_u64(
            &row_string(&timeline_row, "head_event_seq")?,
            "head_event_seq",
        )?);
        let state_revision = StateRevision::new(parse_u64(
            &row_string(&timeline_row, "state_revision")?,
            "state_revision",
        )?);
        let world_time = WorldInstant::new(row_i64(&timeline_row, "world_time")?);
        let chronology_world_time =
            WorldInstant::new(row_i64(&timeline_row, "chronology_budget_world_time")?);
        let chronology_consumed = parse_u64(
            &row_string(&timeline_row, "chronology_budget_consumed")?,
            "chronology_budget_consumed",
        )?;
        let parent_timeline =
            optional_identity::<TimelineId>(&timeline_row, "parent_timeline_id", "TimelineId")?;
        let parent_head = optional_u64(
            &timeline_row,
            "fork_parent_head_event_seq",
            "fork_parent_head_event_seq",
        )?;
        let parent_state = optional_u64(
            &timeline_row,
            "fork_parent_state_revision",
            "fork_parent_state_revision",
        )?;
        let parent_event_timeline = optional_identity::<TimelineId>(
            &timeline_row,
            "fork_parent_event_timeline_id",
            "TimelineId",
        )?;
        let parent_event =
            optional_identity::<EventId>(&timeline_row, "fork_parent_event_id", "EventId")?;
        let ancestry = match (
            parent_timeline,
            parent_head,
            parent_state,
            parent_event_timeline,
            parent_event,
        ) {
            (None, None, None, None, None) => TimelineAncestry::root(),
            (
                Some(parent_timeline),
                Some(parent_head),
                Some(parent_state),
                Some(parent_event_timeline),
                Some(parent_event),
            ) => TimelineAncestry::fork(
                parent_timeline,
                TimelineVersion::new(EventSeq::new(parent_head), StateRevision::new(parent_state)),
                Some(EventRef::new(parent_event_timeline, parent_event)),
            ),
            (Some(parent_timeline), Some(parent_head), Some(parent_state), None, None) => {
                TimelineAncestry::fork(
                    parent_timeline,
                    TimelineVersion::new(
                        EventSeq::new(parent_head),
                        StateRevision::new(parent_state),
                    ),
                    None,
                )
            }
            _ => return Err(corrupt("persisted Timeline ancestry columns disagree")),
        };
        let mut base = BaseWorldSnapshot::new(
            world_id,
            timeline_id,
            TimelineVersion::new(head_event_seq, state_revision),
            world_time,
        );

        let entity_rows = sqlx::query(READ_ENTITIES_SQL)
            .bind(timeline_id.to_string())
            .fetch_all(&mut *transaction)
            .await
            .map_err(sql_read_error)?;
        for row in entity_rows {
            let entity_id =
                parse_identity::<EntityId>(&row_string(&row, "entity_id")?, "EntityId")?;
            base.insert_entity(Entity {
                id: entity_id,
                world_id,
            });
        }

        let relationship_rows = sqlx::query(READ_RELATIONSHIPS_SQL)
            .bind(timeline_id.to_string())
            .fetch_all(&mut *transaction)
            .await
            .map_err(sql_read_error)?;
        for row in relationship_rows {
            let relationship_id = parse_identity::<RelationshipId>(
                &row_string(&row, "relationship_id")?,
                "RelationshipId",
            )?;
            let relationship_type =
                RelationshipTypeId::from(row_string(&row, "relationship_type")?);
            let active: bool = row.try_get("active").map_err(sql_read_error)?;
            let participant_rows = sqlx::query(READ_RELATIONSHIP_PARTICIPANTS_SQL)
                .bind(timeline_id.to_string())
                .bind(relationship_id.to_string())
                .fetch_all(&mut *transaction)
                .await
                .map_err(sql_read_error)?;
            let mut participants = Vec::with_capacity(participant_rows.len());
            for participant in participant_rows {
                participants.push(RelationshipParticipant::new(
                    parse_identity::<EntityId>(
                        &row_string(&participant, "entity_id")?,
                        "EntityId",
                    )?,
                    AssociationRole::from(row_string(&participant, "role")?),
                ));
            }
            base.insert_relationship(
                Relationship::new(relationship_id, world_id, relationship_type, participants),
                active,
            );
        }

        let entity_facet_rows = sqlx::query(READ_ENTITY_FACETS_SQL)
            .bind(timeline_id.to_string())
            .fetch_all(&mut *transaction)
            .await
            .map_err(sql_read_error)?;
        for row in entity_facet_rows {
            base.insert_facet(
                FacetOwner::entity(parse_identity::<EntityId>(
                    &row_string(&row, "owner_id")?,
                    "EntityId",
                )?),
                FacetTypeId::from(row_string(&row, "facet_type")?),
                schema_revision(&row)?,
                row_json(&row, "value")?,
            );
        }

        let relationship_facet_rows = sqlx::query(READ_RELATIONSHIP_FACETS_SQL)
            .bind(timeline_id.to_string())
            .fetch_all(&mut *transaction)
            .await
            .map_err(sql_read_error)?;
        for row in relationship_facet_rows {
            base.insert_facet(
                FacetOwner::relationship(parse_identity::<RelationshipId>(
                    &row_string(&row, "owner_id")?,
                    "RelationshipId",
                )?),
                FacetTypeId::from(row_string(&row, "facet_type")?),
                schema_revision(&row)?,
                row_json(&row, "value")?,
            );
        }

        let event_rows = sqlx::query(READ_VISIBLE_EVENTS_SQL)
            .bind(timeline_id.to_string())
            .fetch_all(&mut *transaction)
            .await
            .map_err(sql_read_error)?;
        let mut events = Vec::with_capacity(event_rows.len());
        for row in event_rows {
            let event_timeline_id =
                parse_identity::<TimelineId>(&row_string(&row, "timeline_id")?, "TimelineId")?;
            let event_id = parse_identity::<EventId>(&row_string(&row, "event_id")?, "EventId")?;
            let effects_value = row_json(&row, "effects")?;
            let effects: Vec<WorldEffect> = serde_json::from_value(effects_value)
                .map_err(|error| corrupt(format!("invalid persisted Event effects: {error}")))?;
            let event_seq = EventSeq::new(parse_u64(&row_string(&row, "event_seq")?, "event_seq")?);
            let mut proposal = ProposedEvent::new(
                event_id,
                EventTypeId::from(row_string(&row, "event_type")?),
                schema_revision(&row)?,
                row_json(&row, "payload")?,
            );
            proposal.effects = effects;
            let mut event = CommittedEvent::from_proposed(
                event_timeline_id,
                event_seq,
                &proposal,
                WorldInstant::new(row_i64(&row, "occurred_at")?),
            );

            let participant_rows = sqlx::query(READ_EVENT_PARTICIPANTS_SQL)
                .bind(event_timeline_id.to_string())
                .bind(event_id.to_string())
                .fetch_all(&mut *transaction)
                .await
                .map_err(sql_read_error)?;
            for participant in participant_rows {
                event.push_participant(
                    parse_identity::<EntityId>(
                        &row_string(&participant, "entity_id")?,
                        "EntityId",
                    )?,
                    AssociationRole::from(row_string(&participant, "role")?),
                );
            }

            let relationship_rows = sqlx::query(READ_EVENT_RELATIONSHIP_REFS_SQL)
                .bind(event_timeline_id.to_string())
                .bind(event_id.to_string())
                .fetch_all(&mut *transaction)
                .await
                .map_err(sql_read_error)?;
            for relationship in relationship_rows {
                event.push_relationship_ref(
                    parse_identity::<RelationshipId>(
                        &row_string(&relationship, "relationship_id")?,
                        "RelationshipId",
                    )?,
                    AssociationRole::from(row_string(&relationship, "role")?),
                );
            }

            let causal_rows = sqlx::query(READ_EVENT_CAUSAL_LINKS_SQL)
                .bind(event_timeline_id.to_string())
                .bind(event_id.to_string())
                .fetch_all(&mut *transaction)
                .await
                .map_err(sql_read_error)?;
            for causal in causal_rows {
                event.push_causal_link(parse_identity::<EventId>(
                    &row_string(&causal, "cause_event_id")?,
                    "EventId",
                )?);
            }
            base.insert_event(event_id);
            events.push(event);
        }

        let work_rows = sqlx::query(READ_WORK_SQL)
            .bind(timeline_id.to_string())
            .fetch_all(&mut *transaction)
            .await
            .map_err(sql_read_error)?;
        let mut works = Vec::with_capacity(work_rows.len());
        for row in work_rows {
            let work_id = parse_identity::<WorkId>(&row_string(&row, "work_id")?, "WorkId")?;
            let lease_until: Option<i64> =
                row.try_get("lease_claimed_until").map_err(sql_read_error)?;
            let lease_fence: Option<String> = row.try_get("lease_fence").map_err(sql_read_error)?;
            let lease = match (lease_until, lease_fence) {
                (None, None) => None,
                (Some(until), Some(fence)) => Some(WorkLease::new(
                    PlatformTime::new(until),
                    parse_u64(&fence, "lease_fence")?,
                )),
                _ => return Err(corrupt("persisted Work lease columns disagree")),
            };
            let attempt_count = u32::try_from(row_i64(&row, "attempt_count")?)
                .map_err(|_| corrupt("attempt_count exceeds u32"))?;
            works.push(WorkRecord {
                id: work_id,
                timeline_id,
                target: work_target(&row)?,
                schema_revision: schema_revision(&row)?,
                payload: row_json(&row, "payload")?,
                effective_due_world_time: WorldInstant::new(row_i64(
                    &row,
                    "effective_due_world_time",
                )?),
                logical_schedule_order: parse_u64(
                    &row_string(&row, "logical_schedule_order")?,
                    "logical_schedule_order",
                )?,
                causal_event_id: optional_identity::<EventId>(&row, "causal_event_id", "EventId")?,
                origin_work_id: optional_identity::<WorkId>(&row, "origin_work_id", "WorkId")?,
                status: parse_work_status(&row_string(&row, "status")?)?,
                attempt_count,
                claim_generation: parse_u64(
                    &row_string(&row, "claim_generation")?,
                    "claim_generation",
                )?,
                available_at: PlatformTime::new(row_i64(&row, "available_at")?),
                last_error: row.try_get("last_error").map_err(sql_read_error)?,
                lease,
            });
        }

        let journal_rows = sqlx::query(READ_LOGICAL_JOURNAL_SQL)
            .bind(timeline_id.to_string())
            .fetch_all(&mut *transaction)
            .await
            .map_err(sql_read_error)?;
        let journal = journal_rows
            .iter()
            .map(logical_commit_from_row)
            .collect::<Result<Vec<_>, _>>()?;

        transaction.commit().await.map_err(sql_read_error)?;
        Ok(TimelineSnapshot::with_journal_ancestry_and_budget(
            base,
            events,
            works,
            journal,
            ancestry,
            ChronologyBudgetState::new(chronology_world_time, chronology_consumed),
        ))
    }

    async fn read_logical_journal(
        &self,
        timeline_id: TimelineId,
    ) -> Result<Vec<LogicalCommit>, ReadError> {
        let mut transaction = self.pool.begin().await.map_err(sql_read_error)?;
        let timeline_exists = sqlx::query(READ_TIMELINE_SQL)
            .bind(timeline_id.to_string())
            .fetch_optional(&mut *transaction)
            .await
            .map_err(sql_read_error)?
            .is_some();
        if !timeline_exists {
            let _ = transaction.rollback().await;
            return Err(ReadError::TimelineNotFound { timeline_id });
        }
        let rows = sqlx::query(READ_LOGICAL_JOURNAL_SQL)
            .bind(timeline_id.to_string())
            .fetch_all(&mut *transaction)
            .await
            .map_err(sql_read_error)?;
        let journal = rows
            .iter()
            .map(logical_commit_from_row)
            .collect::<Result<Vec<_>, _>>()?;
        transaction.commit().await.map_err(sql_read_error)?;
        Ok(journal)
    }
}

impl PgStorage {
    async fn begin_fenced_read<'a>(
        &'a self,
        session: &PinnedReadSession,
    ) -> Result<Transaction<'a, Postgres>, ReadError> {
        let mut transaction = self.pool.begin().await.map_err(sql_read_error)?;
        sqlx::query(REPEATABLE_READ_READ_ONLY_SQL)
            .execute(&mut *transaction)
            .await
            .map_err(sql_read_error)?;
        let row = sqlx::query(READ_TIMELINE_SQL)
            .bind(session.timeline_id().to_string())
            .fetch_optional(&mut *transaction)
            .await
            .map_err(sql_read_error)?
            .ok_or(ReadError::TimelineNotFound {
                timeline_id: session.timeline_id(),
            })?;
        let (world_id, actual, _) = timeline_read_position(&row)?;
        if world_id != session.world_id() {
            let _ = transaction.rollback().await;
            return Err(ReadError::PinnedWorldMismatch {
                timeline_id: session.timeline_id(),
                expected: session.world_id(),
                actual: world_id,
            });
        }
        if actual != session.version() {
            let _ = transaction.rollback().await;
            return Err(ReadError::PinnedVersionMismatch {
                timeline_id: session.timeline_id(),
                expected: session.version(),
                actual,
            });
        }
        Ok(transaction)
    }

    async fn open_pinned_read(
        &self,
        assembly: &loom_runtime::ExecutionAssembly,
    ) -> Result<PinnedReadSession, ReadError> {
        let mut transaction = self.pool.begin().await.map_err(sql_read_error)?;
        sqlx::query(REPEATABLE_READ_READ_ONLY_SQL)
            .execute(&mut *transaction)
            .await
            .map_err(sql_read_error)?;
        let row = sqlx::query(READ_TIMELINE_SQL)
            .bind(assembly.timeline_id().to_string())
            .fetch_optional(&mut *transaction)
            .await
            .map_err(sql_read_error)?
            .ok_or(ReadError::TimelineNotFound {
                timeline_id: assembly.timeline_id(),
            })?;
        let (world_id, actual, world_time) = timeline_read_position(&row)?;
        if world_id != assembly.world_id() {
            let _ = transaction.rollback().await;
            return Err(ReadError::PinnedWorldMismatch {
                timeline_id: assembly.timeline_id(),
                expected: assembly.world_id(),
                actual: world_id,
            });
        }
        if actual != assembly.expected_version() {
            let _ = transaction.rollback().await;
            return Err(ReadError::PinnedVersionMismatch {
                timeline_id: assembly.timeline_id(),
                expected: assembly.expected_version(),
                actual,
            });
        }
        transaction.commit().await.map_err(sql_read_error)?;
        Ok(PinnedReadSession::new(
            assembly.session_id(),
            world_id,
            assembly.timeline_id(),
            actual,
            world_time,
        ))
    }

    async fn read_pinned_entity(
        &self,
        session: &PinnedReadSession,
        entity_id: EntityId,
    ) -> Result<PinnedRead<Option<loom_core::Entity>>, ReadError> {
        let started = Instant::now();
        let mut transaction = self.begin_fenced_read(session).await?;
        let row = sqlx::query(READ_ENTITY_SQL)
            .bind(session.timeline_id().to_string())
            .bind(entity_id.to_string())
            .bind(session.version().head_event_seq.value().to_string())
            .bind(session.version().state_revision.value().to_string())
            .fetch_optional(&mut *transaction)
            .await
            .map_err(sql_read_error)?;
        let present = row.is_some();
        let value = row.map(|_| loom_core::Entity {
            id: entity_id,
            world_id: session.world_id(),
        });
        let bytes = u64::from(value.is_some()) * entity_id.to_string().len() as u64;
        transaction.commit().await.map_err(sql_read_error)?;
        Ok(PinnedRead::new(
            value,
            PinnedReadMetrics::new(u64::from(present), bytes, elapsed_micros(started)),
        ))
    }

    async fn read_pinned_relationship(
        &self,
        session: &PinnedReadSession,
        relationship_id: RelationshipId,
    ) -> Result<PinnedRead<Option<Relationship>>, ReadError> {
        let started = Instant::now();
        let mut transaction = self.begin_fenced_read(session).await?;
        let row = sqlx::query(READ_RELATIONSHIP_SQL)
            .bind(session.timeline_id().to_string())
            .bind(relationship_id.to_string())
            .bind(session.version().head_event_seq.value().to_string())
            .bind(session.version().state_revision.value().to_string())
            .fetch_optional(&mut *transaction)
            .await
            .map_err(sql_read_error)?;
        let value = if let Some(row) = row {
            let relationship_type =
                RelationshipTypeId::from(row_string(&row, "relationship_type")?);
            let active: bool = row.try_get("active").map_err(sql_read_error)?;
            let participant_rows = sqlx::query(READ_RELATIONSHIP_PARTICIPANTS_SQL)
                .bind(session.timeline_id().to_string())
                .bind(relationship_id.to_string())
                .fetch_all(&mut *transaction)
                .await
                .map_err(sql_read_error)?;
            let mut participants = Vec::with_capacity(participant_rows.len());
            let mut bytes = relationship_type.as_str().len() as u64 + 1;
            for participant in participant_rows {
                let entity_id = parse_identity::<EntityId>(
                    &row_string(&participant, "entity_id")?,
                    "EntityId",
                )?;
                let role = row_string(&participant, "role")?;
                bytes =
                    bytes.saturating_add(entity_id.to_string().len() as u64 + role.len() as u64);
                participants.push(RelationshipParticipant::new(entity_id, role));
            }
            let relationship = Relationship::new(
                relationship_id,
                session.world_id(),
                relationship_type,
                participants,
            );
            (Some(relationship), active, bytes)
        } else {
            (None, false, 0)
        };
        transaction.commit().await.map_err(sql_read_error)?;
        let (value, active, bytes) = value;
        let rows_read = u64::from(value.is_some());
        Ok(PinnedRead::new(
            value.filter(|_| active),
            PinnedReadMetrics::new(rows_read, bytes, elapsed_micros(started)),
        ))
    }

    async fn read_pinned_facet(
        &self,
        session: &PinnedReadSession,
        owner: FacetOwner,
        facet_type: &FacetTypeId,
    ) -> Result<PinnedRead<Option<PinnedFacet>>, ReadError> {
        let started = Instant::now();
        let mut transaction = self.begin_fenced_read(session).await?;
        let owner_id = match owner {
            FacetOwner::Entity(entity_id) => entity_id.to_string(),
            FacetOwner::Relationship(relationship_id) => relationship_id.to_string(),
        };
        let query = match owner {
            FacetOwner::Entity(_) => READ_ENTITY_FACET_SQL,
            FacetOwner::Relationship(_) => READ_RELATIONSHIP_FACET_SQL,
        };
        let row = sqlx::query(query)
            .bind(session.timeline_id().to_string())
            .bind(owner_id)
            .bind(facet_type.to_string())
            .bind(session.version().head_event_seq.value().to_string())
            .bind(session.version().state_revision.value().to_string())
            .fetch_optional(&mut *transaction)
            .await
            .map_err(sql_read_error)?;
        let value = row
            .map(|row| {
                Ok(PinnedFacet::new(
                    schema_revision(&row)?,
                    row_json(&row, "value")?,
                ))
            })
            .transpose()?;
        let bytes = value
            .as_ref()
            .map_or(0, |facet| facet.value.to_string().len() as u64);
        let present = value.is_some();
        transaction.commit().await.map_err(sql_read_error)?;
        Ok(PinnedRead::new(
            value,
            PinnedReadMetrics::new(u64::from(present), bytes, elapsed_micros(started)),
        ))
    }

    async fn read_pinned_event(
        &self,
        session: &PinnedReadSession,
        event_id: EventId,
    ) -> Result<PinnedRead<Option<CommittedEvent>>, ReadError> {
        let started = Instant::now();
        let mut transaction = self.begin_fenced_read(session).await?;
        let row = sqlx::query(READ_VISIBLE_EVENT_SQL)
            .bind(session.timeline_id().to_string())
            .bind(event_id.to_string())
            .bind(session.version().head_event_seq.value().to_string())
            .bind(session.version().state_revision.value().to_string())
            .fetch_optional(&mut *transaction)
            .await
            .map_err(sql_read_error)?;
        let Some(row) = row else {
            transaction.commit().await.map_err(sql_read_error)?;
            return Ok(PinnedRead::new(
                None,
                PinnedReadMetrics::new(0, 0, elapsed_micros(started)),
            ));
        };
        let event_timeline_id =
            parse_identity::<TimelineId>(&row_string(&row, "timeline_id")?, "TimelineId")?;
        let event_seq = EventSeq::new(parse_u64(&row_string(&row, "event_seq")?, "event_seq")?);
        let effects: Vec<WorldEffect> = serde_json::from_value(row_json(&row, "effects")?)
            .map_err(|error| corrupt(format!("invalid persisted Event effects: {error}")))?;
        let mut proposal = ProposedEvent::new(
            event_id,
            EventTypeId::from(row_string(&row, "event_type")?),
            schema_revision(&row)?,
            row_json(&row, "payload")?,
        );
        proposal.effects = effects;
        let mut event = CommittedEvent::from_proposed(
            event_timeline_id,
            event_seq,
            &proposal,
            WorldInstant::new(row_i64(&row, "occurred_at")?),
        );
        let participant_rows = sqlx::query(READ_EVENT_PARTICIPANTS_SQL)
            .bind(event_timeline_id.to_string())
            .bind(event_id.to_string())
            .fetch_all(&mut *transaction)
            .await
            .map_err(sql_read_error)?;
        for participant in participant_rows {
            event.push_participant(
                parse_identity::<EntityId>(&row_string(&participant, "entity_id")?, "EntityId")?,
                AssociationRole::from(row_string(&participant, "role")?),
            );
        }
        let relationship_rows = sqlx::query(READ_EVENT_RELATIONSHIP_REFS_SQL)
            .bind(event_timeline_id.to_string())
            .bind(event_id.to_string())
            .fetch_all(&mut *transaction)
            .await
            .map_err(sql_read_error)?;
        for relationship in relationship_rows {
            event.push_relationship_ref(
                parse_identity::<RelationshipId>(
                    &row_string(&relationship, "relationship_id")?,
                    "RelationshipId",
                )?,
                AssociationRole::from(row_string(&relationship, "role")?),
            );
        }
        let causal_rows = sqlx::query(READ_EVENT_CAUSAL_LINKS_SQL)
            .bind(event_timeline_id.to_string())
            .bind(event_id.to_string())
            .fetch_all(&mut *transaction)
            .await
            .map_err(sql_read_error)?;
        for causal in causal_rows {
            event.push_causal_link(parse_identity::<EventId>(
                &row_string(&causal, "cause_event_id")?,
                "EventId",
            )?);
        }
        let bytes = event.payload.to_string().len() as u64 + event.effects.len() as u64;
        transaction.commit().await.map_err(sql_read_error)?;
        Ok(PinnedRead::new(
            Some(event),
            PinnedReadMetrics::new(1, bytes, elapsed_micros(started)),
        ))
    }
}

impl PinnedWorldReadStore for PgStorage {
    fn open_pinned_read<'a>(
        &'a self,
        assembly: &'a loom_runtime::ExecutionAssembly,
    ) -> PersistenceFuture<'a, Result<PinnedReadSession, ReadError>> {
        Box::pin(async move { self.open_pinned_read(assembly).await })
    }

    fn read_entity<'a>(
        &'a self,
        session: &'a PinnedReadSession,
        entity_id: EntityId,
    ) -> PersistenceFuture<'a, Result<PinnedRead<Option<Entity>>, ReadError>> {
        Box::pin(async move { self.read_pinned_entity(session, entity_id).await })
    }

    fn read_relationship<'a>(
        &'a self,
        session: &'a PinnedReadSession,
        relationship_id: RelationshipId,
    ) -> PersistenceFuture<'a, Result<PinnedRead<Option<Relationship>>, ReadError>> {
        Box::pin(async move {
            self.read_pinned_relationship(session, relationship_id)
                .await
        })
    }

    fn read_facet<'a>(
        &'a self,
        session: &'a PinnedReadSession,
        owner: FacetOwner,
        facet_type: &'a FacetTypeId,
    ) -> PersistenceFuture<'a, Result<PinnedRead<Option<PinnedFacet>>, ReadError>> {
        Box::pin(async move { self.read_pinned_facet(session, owner, facet_type).await })
    }

    fn read_event<'a>(
        &'a self,
        session: &'a PinnedReadSession,
        event_id: EventId,
    ) -> PersistenceFuture<'a, Result<PinnedRead<Option<CommittedEvent>>, ReadError>> {
        Box::pin(async move { self.read_pinned_event(session, event_id).await })
    }
}

impl WorldLifecycleStore for PgStorage {
    fn create_world(
        &self,
        world_id: WorldId,
        timeline_id: TimelineId,
        initial_world_time: WorldInstant,
    ) -> PersistenceFuture<'_, Result<WorldCreation, LifecycleError>> {
        Box::pin(async move {
            self.create_world_internal(world_id, timeline_id, initial_world_time, None)
                .await
        })
    }

    fn create_world_with_binding(
        &self,
        world_id: WorldId,
        timeline_id: TimelineId,
        initial_world_time: WorldInstant,
        binding: WorldRuntimeBinding,
    ) -> PersistenceFuture<'_, Result<WorldCreation, LifecycleError>> {
        Box::pin(async move {
            self.create_world_internal(world_id, timeline_id, initial_world_time, Some(binding))
                .await
        })
    }

    fn create_world_with_bootstrap<'a>(
        &'a self,
        world_id: WorldId,
        timeline_id: TimelineId,
        initial_world_time: WorldInstant,
        binding: WorldRuntimeBinding,
        bootstrap: &'a [ValidatedResolution],
        now: PlatformTime,
    ) -> PersistenceFuture<'a, Result<WorldCreation, LifecycleError>> {
        Box::pin(async move {
            self.create_world_with_bootstrap_internal(
                world_id,
                timeline_id,
                initial_world_time,
                binding,
                bootstrap,
                now,
            )
            .await
        })
    }
}

impl PgStorage {
    async fn create_world_internal(
        &self,
        world_id: WorldId,
        timeline_id: TimelineId,
        initial_world_time: WorldInstant,
        binding: Option<WorldRuntimeBinding>,
    ) -> Result<WorldCreation, LifecycleError> {
        let mut transaction = self.pool.begin().await.map_err(sql_lifecycle_error)?;

        if let Err(error) = sqlx::query(INSERT_WORLD_SQL)
            .bind(world_id.to_string())
            .execute(&mut *transaction)
            .await
        {
            let _ = transaction.rollback().await;
            if is_unique_violation(&error) {
                return Err(LifecycleError::WorldAlreadyExists { world_id });
            }
            return Err(sql_lifecycle_error(error));
        }

        if let Some(binding) = binding {
            let value = serde_json::to_value(binding).map_err(|error| {
                LifecycleError::StorageUnavailable {
                    message: format!("World Runtime Binding serialization failed: {error}"),
                }
            })?;
            if let Err(error) = sqlx::query(INSERT_BINDING_SQL)
                .bind(world_id.to_string())
                .bind(value)
                .execute(&mut *transaction)
                .await
            {
                let _ = transaction.rollback().await;
                return Err(sql_lifecycle_error(error));
            }
        }

        if let Err(error) = sqlx::query(INSERT_TIMELINE_SQL)
            .bind(timeline_id.to_string())
            .bind(world_id.to_string())
            .bind(initial_world_time.value())
            .execute(&mut *transaction)
            .await
        {
            let _ = transaction.rollback().await;
            if is_unique_violation(&error) {
                return Err(LifecycleError::TimelineAlreadyExists { timeline_id });
            }
            return Err(sql_lifecycle_error(error));
        }

        transaction.commit().await.map_err(sql_lifecycle_error)?;
        Ok(WorldCreation::new(
            world_id,
            timeline_id,
            initial_world_time,
        ))
    }

    async fn create_world_with_bootstrap_internal(
        &self,
        world_id: WorldId,
        timeline_id: TimelineId,
        initial_world_time: WorldInstant,
        binding: WorldRuntimeBinding,
        bootstrap: &[ValidatedResolution],
        now: PlatformTime,
    ) -> Result<WorldCreation, LifecycleError> {
        let binding_value =
            serde_json::to_value(binding).map_err(|error| LifecycleError::StorageUnavailable {
                message: format!("World Runtime Binding serialization failed: {error}"),
            })?;
        let mut transaction = self.pool.begin().await.map_err(sql_lifecycle_error)?;

        if let Err(error) = sqlx::query(INSERT_WORLD_SQL)
            .bind(world_id.to_string())
            .execute(&mut *transaction)
            .await
        {
            let _ = transaction.rollback().await;
            if is_unique_violation(&error) {
                return Err(LifecycleError::WorldAlreadyExists { world_id });
            }
            return Err(sql_lifecycle_error(error));
        }

        if let Err(error) = sqlx::query(INSERT_BINDING_SQL)
            .bind(world_id.to_string())
            .bind(binding_value)
            .execute(&mut *transaction)
            .await
        {
            let _ = transaction.rollback().await;
            return Err(sql_lifecycle_error(error));
        }

        if let Err(error) = sqlx::query(INSERT_TIMELINE_SQL)
            .bind(timeline_id.to_string())
            .bind(world_id.to_string())
            .bind(initial_world_time.value())
            .execute(&mut *transaction)
            .await
        {
            let _ = transaction.rollback().await;
            if is_unique_violation(&error) {
                return Err(LifecycleError::TimelineAlreadyExists { timeline_id });
            }
            return Err(sql_lifecycle_error(error));
        }

        let version = match commit::commit_birth_in_transaction(
            &mut transaction,
            timeline_id,
            initial_world_time,
            bootstrap,
            now,
        )
        .await
        {
            Ok(version) => version,
            Err(error) => {
                let _ = transaction.rollback().await;
                return Err(lifecycle_birth_error(error));
            }
        };

        transaction.commit().await.map_err(sql_lifecycle_error)?;
        Ok(WorldCreation::with_version(
            world_id,
            timeline_id,
            version,
            initial_world_time,
        ))
    }
}

impl WorldStore for PgStorage {
    fn snapshot(
        &self,
        timeline_id: TimelineId,
    ) -> PersistenceFuture<'_, Result<TimelineSnapshot, ReadError>> {
        Box::pin(async move { self.read_snapshot(timeline_id).await })
    }

    fn fork_timeline<'a>(
        &'a self,
        fork: &'a TimelineFork,
    ) -> PersistenceFuture<'a, Result<TimelineSnapshot, loom_runtime::ForkError>> {
        TimelineForkStore::fork_timeline(self, fork)
    }
}

impl LogicalJournalStore for PgStorage {
    fn read_logical_journal(
        &self,
        timeline_id: TimelineId,
    ) -> PersistenceFuture<'_, Result<Vec<LogicalCommit>, ReadError>> {
        Box::pin(async move { self.read_logical_journal(timeline_id).await })
    }
}

impl WorldRuntimeBindingStore for PgStorage {
    fn read_binding(
        &self,
        world_id: WorldId,
    ) -> PersistenceFuture<'_, Result<WorldRuntimeBinding, BindingError>> {
        Box::pin(async move { self.read_binding(world_id).await })
    }

    fn persist_binding(
        &self,
        world_id: WorldId,
        binding: WorldRuntimeBinding,
    ) -> PersistenceFuture<'_, Result<(), BindingError>> {
        Box::pin(async move { self.persist_binding(world_id, binding).await })
    }

    fn ensure_binding(
        &self,
        world_id: WorldId,
        legacy_binding: WorldRuntimeBinding,
    ) -> PersistenceFuture<'_, Result<WorldRuntimeBinding, BindingError>> {
        Box::pin(async move { self.ensure_binding(world_id, legacy_binding).await })
    }
}

impl PgStorage {
    async fn read_binding(&self, world_id: WorldId) -> Result<WorldRuntimeBinding, BindingError> {
        let row = sqlx::query(READ_BINDING_SQL)
            .bind(world_id.to_string())
            .fetch_optional(&self.pool)
            .await
            .map_err(sql_binding_error)?;
        if let Some(row) = row {
            let value: Value = row.try_get("binding").map_err(sql_binding_error)?;
            return serde_json::from_value(value).map_err(|error| {
                BindingError::StorageUnavailable {
                    message: format!("invalid persisted World Runtime Binding: {error}"),
                }
            });
        }

        let world_exists: Option<i32> = sqlx::query_scalar(WORLD_EXISTS_SQL)
            .bind(world_id.to_string())
            .fetch_optional(&self.pool)
            .await
            .map_err(sql_binding_error)?;
        if world_exists.is_none() {
            return Err(BindingError::WorldNotFound { world_id });
        }
        Err(BindingError::BindingNotFound { world_id })
    }

    async fn persist_binding(
        &self,
        world_id: WorldId,
        binding: WorldRuntimeBinding,
    ) -> Result<(), BindingError> {
        let value =
            serde_json::to_value(binding).map_err(|error| BindingError::StorageUnavailable {
                message: format!("World Runtime Binding serialization failed: {error}"),
            })?;
        let mut transaction = self.pool.begin().await.map_err(sql_binding_error)?;
        let world_exists: Option<i32> = sqlx::query_scalar(LOCK_WORLD_EXISTS_SQL)
            .bind(world_id.to_string())
            .fetch_optional(&mut *transaction)
            .await
            .map_err(sql_binding_error)?;
        if world_exists.is_none() {
            let _ = transaction.rollback().await;
            return Err(BindingError::WorldNotFound { world_id });
        }
        let result = sqlx::query(INSERT_BINDING_SQL)
            .bind(world_id.to_string())
            .bind(value)
            .execute(&mut *transaction)
            .await;
        if let Err(error) = result {
            let _ = transaction.rollback().await;
            if is_unique_violation(&error) {
                return Err(BindingError::BindingAlreadyExists { world_id });
            }
            return Err(sql_binding_error(error));
        }
        transaction.commit().await.map_err(sql_binding_error)
    }

    async fn ensure_binding(
        &self,
        world_id: WorldId,
        legacy_binding: WorldRuntimeBinding,
    ) -> Result<WorldRuntimeBinding, BindingError> {
        let value = serde_json::to_value(legacy_binding).map_err(|error| {
            BindingError::StorageUnavailable {
                message: format!("World Runtime Binding serialization failed: {error}"),
            }
        })?;
        let mut transaction = self.pool.begin().await.map_err(sql_binding_error)?;
        let world_exists: Option<i32> = sqlx::query_scalar(LOCK_WORLD_EXISTS_SQL)
            .bind(world_id.to_string())
            .fetch_optional(&mut *transaction)
            .await
            .map_err(sql_binding_error)?;
        if world_exists.is_none() {
            let _ = transaction.rollback().await;
            return Err(BindingError::WorldNotFound { world_id });
        }
        sqlx::query(INSERT_BINDING_IF_ABSENT_SQL)
            .bind(world_id.to_string())
            .bind(value)
            .execute(&mut *transaction)
            .await
            .map_err(sql_binding_error)?;
        let row = sqlx::query(READ_BINDING_SQL)
            .bind(world_id.to_string())
            .fetch_one(&mut *transaction)
            .await
            .map_err(sql_binding_error)?;
        let value: Value = row.try_get("binding").map_err(sql_binding_error)?;
        let binding =
            serde_json::from_value(value).map_err(|error| BindingError::StorageUnavailable {
                message: format!("invalid persisted World Runtime Binding: {error}"),
            })?;
        transaction.commit().await.map_err(sql_binding_error)?;
        Ok(binding)
    }
}

impl RuntimeRevisionStore for PgStorage {
    fn register_revision(
        &self,
        revision: RuntimeRevisionDescriptor,
    ) -> PersistenceFuture<'_, Result<(), RuntimeRevisionError>> {
        Box::pin(async move { self.register_revision(revision).await })
    }

    fn confirm_revision(
        &self,
        revision: RuntimeRevisionDescriptor,
    ) -> PersistenceFuture<'_, Result<RuntimeRevisionDescriptor, RuntimeRevisionError>> {
        Box::pin(async move { self.confirm_revision(revision).await })
    }

    fn read_revision(
        &self,
        revision_id: RuntimeRevisionId,
    ) -> PersistenceFuture<'_, Result<RuntimeRevisionDescriptor, RuntimeRevisionError>> {
        Box::pin(async move { self.read_revision(revision_id).await })
    }

    fn list_revisions(
        &self,
    ) -> PersistenceFuture<'_, Result<Vec<RuntimeRevisionDescriptor>, RuntimeRevisionError>> {
        Box::pin(async move { self.list_revisions().await })
    }

    fn read_active_revision(
        &self,
    ) -> PersistenceFuture<'_, Result<Option<RuntimeRevisionSelection>, RuntimeRevisionError>> {
        Box::pin(async move { self.read_active_revision().await })
    }

    fn activate_revision(
        &self,
        revision_id: RuntimeRevisionId,
        expected_generation: Option<u64>,
        activated_at: PlatformTime,
    ) -> PersistenceFuture<'_, Result<RuntimeRevisionSelection, RuntimeRevisionError>> {
        Box::pin(async move {
            self.activate_revision(revision_id, expected_generation, activated_at)
                .await
        })
    }
}

impl PgStorage {
    async fn register_revision(
        &self,
        revision: RuntimeRevisionDescriptor,
    ) -> Result<(), RuntimeRevisionError> {
        let revision_id = revision.id().clone();
        let descriptor = serde_json::to_value(revision).map_err(|error| {
            RuntimeRevisionError::StorageUnavailable {
                message: format!("Runtime Revision serialization failed: {error}"),
            }
        })?;
        let result = sqlx::query(REGISTER_RUNTIME_REVISION_SQL)
            .bind(revision_id.as_str())
            .bind(descriptor)
            .execute(&self.pool)
            .await;
        if let Err(error) = result {
            if is_unique_violation(&error) {
                return Err(RuntimeRevisionError::RevisionAlreadyExists { revision_id });
            }
            return Err(sql_revision_error(error));
        }
        Ok(())
    }

    async fn confirm_revision(
        &self,
        revision: RuntimeRevisionDescriptor,
    ) -> Result<RuntimeRevisionDescriptor, RuntimeRevisionError> {
        let revision_id = revision.id().clone();
        match self.read_revision(revision_id.clone()).await {
            Ok(existing) => {
                if existing != revision {
                    return Err(RuntimeRevisionError::RevisionDescriptorMismatch { revision_id });
                }
                Ok(existing)
            }
            Err(RuntimeRevisionError::RevisionNotFound { .. }) => {
                match self.register_revision(revision.clone()).await {
                    Ok(()) => Ok(revision),
                    Err(RuntimeRevisionError::RevisionAlreadyExists { .. }) => {
                        let existing = self.read_revision(revision_id.clone()).await?;
                        if existing != revision {
                            return Err(RuntimeRevisionError::RevisionDescriptorMismatch {
                                revision_id,
                            });
                        }
                        Ok(existing)
                    }
                    Err(error) => Err(error),
                }
            }
            Err(error) => Err(error),
        }
    }

    async fn read_revision(
        &self,
        revision_id: RuntimeRevisionId,
    ) -> Result<RuntimeRevisionDescriptor, RuntimeRevisionError> {
        let row = sqlx::query(READ_RUNTIME_REVISION_SQL)
            .bind(revision_id.as_str())
            .fetch_optional(&self.pool)
            .await
            .map_err(sql_revision_error)?;
        let Some(row) = row else {
            return Err(RuntimeRevisionError::RevisionNotFound { revision_id });
        };
        let descriptor: Value = row.try_get("descriptor").map_err(sql_revision_error)?;
        serde_json::from_value(descriptor).map_err(|error| {
            RuntimeRevisionError::StorageUnavailable {
                message: format!("invalid persisted Runtime Revision: {error}"),
            }
        })
    }

    async fn list_revisions(&self) -> Result<Vec<RuntimeRevisionDescriptor>, RuntimeRevisionError> {
        let rows = sqlx::query(LIST_RUNTIME_REVISIONS_SQL)
            .fetch_all(&self.pool)
            .await
            .map_err(sql_revision_error)?;
        rows.into_iter()
            .map(|row| {
                let descriptor: Value = row.try_get("descriptor").map_err(sql_revision_error)?;
                serde_json::from_value(descriptor).map_err(|error| {
                    RuntimeRevisionError::StorageUnavailable {
                        message: format!("invalid persisted Runtime Revision: {error}"),
                    }
                })
            })
            .collect()
    }

    async fn read_active_revision(
        &self,
    ) -> Result<Option<RuntimeRevisionSelection>, RuntimeRevisionError> {
        let row = sqlx::query(READ_ACTIVE_RUNTIME_REVISION_SQL)
            .fetch_optional(&self.pool)
            .await
            .map_err(sql_revision_error)?;
        let Some(row) = row else {
            return Err(RuntimeRevisionError::StorageUnavailable {
                message: "Runtime active-revision anchor is missing".to_owned(),
            });
        };
        let revision_id: Option<String> = row.try_get("revision_id").map_err(sql_revision_error)?;
        let Some(revision_id) = revision_id else {
            return Ok(None);
        };
        let generation = parse_runtime_u64(
            &row.try_get::<String, _>("activation_generation")
                .map_err(sql_revision_error)?,
            "activation_generation",
        )?;
        let activated_at: i64 = row.try_get("activated_at").map_err(sql_revision_error)?;
        let descriptor: Value = row.try_get("descriptor").map_err(sql_revision_error)?;
        let revision = serde_json::from_value(descriptor).map_err(|error| {
            RuntimeRevisionError::StorageUnavailable {
                message: format!(
                    "invalid persisted active Runtime Revision {revision_id}: {error}"
                ),
            }
        })?;
        Ok(Some(RuntimeRevisionSelection::new(
            revision,
            generation,
            PlatformTime::new(activated_at),
        )))
    }

    async fn activate_revision(
        &self,
        revision_id: RuntimeRevisionId,
        expected_generation: Option<u64>,
        activated_at: PlatformTime,
    ) -> Result<RuntimeRevisionSelection, RuntimeRevisionError> {
        let mut transaction = self.pool.begin().await.map_err(sql_revision_error)?;
        let active_row = sqlx::query(LOCK_ACTIVE_RUNTIME_REVISION_SQL)
            .fetch_optional(&mut *transaction)
            .await
            .map_err(sql_revision_error)?
            .ok_or_else(|| RuntimeRevisionError::StorageUnavailable {
                message: "Runtime active-revision anchor is missing".to_owned(),
            })?;
        let current_revision_id: Option<String> = active_row
            .try_get("revision_id")
            .map_err(sql_revision_error)?;
        let stored_generation = parse_runtime_u64(
            &active_row
                .try_get::<String, _>("activation_generation")
                .map_err(sql_revision_error)?,
            "activation_generation",
        )?;
        let actual_generation = current_revision_id.as_ref().map(|_| stored_generation);
        if actual_generation != expected_generation {
            let _ = transaction.rollback().await;
            return Err(RuntimeRevisionError::ActiveRevisionConflict {
                expected_generation,
                actual_generation,
            });
        }

        let descriptor_row = sqlx::query(READ_RUNTIME_REVISION_SQL)
            .bind(revision_id.as_str())
            .fetch_optional(&mut *transaction)
            .await
            .map_err(sql_revision_error)?
            .ok_or_else(|| RuntimeRevisionError::RevisionNotFound {
                revision_id: revision_id.clone(),
            })?;
        let descriptor: Value = descriptor_row
            .try_get("descriptor")
            .map_err(sql_revision_error)?;
        let revision: RuntimeRevisionDescriptor =
            serde_json::from_value(descriptor).map_err(|error| {
                RuntimeRevisionError::StorageUnavailable {
                    message: format!("invalid persisted Runtime Revision: {error}"),
                }
            })?;
        let generation = stored_generation
            .checked_add(1)
            .ok_or(RuntimeRevisionError::ActivationGenerationOverflow)?;
        sqlx::query(ACTIVATE_RUNTIME_REVISION_SQL)
            .bind(revision_id.as_str())
            .bind(generation.to_string())
            .bind(activated_at.value())
            .execute(&mut *transaction)
            .await
            .map_err(sql_revision_error)?;
        transaction.commit().await.map_err(sql_revision_error)?;
        Ok(RuntimeRevisionSelection::new(
            revision,
            generation,
            activated_at,
        ))
    }
}

impl WorldTimeStore for PgStorage {
    fn advance_world_time(
        &self,
        transition: AdvanceWorldTime,
    ) -> PersistenceFuture<'_, Result<TimelineVersion, WorldTimeError>> {
        Box::pin(async move {
            let mut transaction =
                self.pool
                    .begin()
                    .await
                    .map_err(|error| WorldTimeError::StorageUnavailable {
                        message: format!("PostgreSQL World-Time persistence failed: {error}"),
                    })?;
            let row = sqlx::query(LOCK_WORLD_TIME_SQL)
                .bind(transition.timeline_id().to_string())
                .fetch_optional(&mut *transaction)
                .await
                .map_err(|error| WorldTimeError::StorageUnavailable {
                    message: format!("PostgreSQL World-Time read failed: {error}"),
                })?
                .ok_or(WorldTimeError::TimelineNotFound {
                    timeline_id: transition.timeline_id(),
                })?;
            let actual = TimelineVersion::new(
                EventSeq::new(
                    row.try_get::<String, _>("head_event_seq")
                        .map_err(|error| WorldTimeError::StorageUnavailable {
                            message: format!("invalid persisted Event sequence: {error}"),
                        })?
                        .parse()
                        .map_err(|error| WorldTimeError::StorageUnavailable {
                            message: format!("invalid persisted Event sequence: {error}"),
                        })?,
                ),
                StateRevision::new(
                    row.try_get::<String, _>("state_revision")
                        .map_err(|error| WorldTimeError::StorageUnavailable {
                            message: format!("invalid persisted state revision: {error}"),
                        })?
                        .parse()
                        .map_err(|error| WorldTimeError::StorageUnavailable {
                            message: format!("invalid persisted state revision: {error}"),
                        })?,
                ),
            );
            if actual != transition.expected_version() {
                return Err(WorldTimeError::TimelineConflict {
                    expected: transition.expected_version(),
                    actual,
                });
            }
            let current = WorldInstant::new(row.try_get("world_time").map_err(|error| {
                WorldTimeError::StorageUnavailable {
                    message: format!("invalid persisted World Time: {error}"),
                }
            })?);
            if current != transition.current() {
                return Err(WorldTimeError::CurrentTimeMismatch {
                    expected: transition.current(),
                    actual: current,
                });
            }
            if let Some(row) = sqlx::query(SELECT_DUE_PENDING_SQL)
                .bind(transition.timeline_id().to_string())
                .bind(current.value())
                .fetch_optional(&mut *transaction)
                .await
                .map_err(|error| WorldTimeError::StorageUnavailable {
                    message: format!("PostgreSQL due-Work recheck failed: {error}"),
                })?
            {
                let work_id = row
                    .try_get::<String, _>("work_id")
                    .map_err(|error| WorldTimeError::StorageUnavailable {
                        message: format!("invalid persisted due Work identity: {error}"),
                    })?
                    .parse::<WorkId>()
                    .map_err(|error| WorldTimeError::StorageUnavailable {
                        message: format!("invalid persisted due Work identity: {error}"),
                    })?;
                return Err(WorldTimeError::DueWorkPending { work_id });
            }
            let next_revision = actual
                .state_revision
                .value()
                .checked_add(1)
                .ok_or(WorldTimeError::RevisionOverflow)?;
            let next =
                TimelineVersion::new(actual.head_event_seq, StateRevision::new(next_revision));
            sqlx::query(UPDATE_WORLD_TIME_SQL)
                .bind(transition.timeline_id().to_string())
                .bind(next_revision.to_string())
                .bind(transition.next().value())
                .execute(&mut *transaction)
                .await
                .map_err(|error| WorldTimeError::StorageUnavailable {
                    message: format!("PostgreSQL World-Time write failed: {error}"),
                })?;
            commit::insert_logical_commit(
                &mut transaction,
                &LogicalCommit {
                    timeline_id: transition.timeline_id(),
                    before_version: actual,
                    after_version: next,
                    world_time: Some(WorldTimeTransition {
                        from: transition.current(),
                        to: transition.next(),
                    }),
                    event_ids: Vec::new(),
                    work_transitions: Vec::new(),
                    chronology_budget: None,
                },
            )
            .await
            .map_err(|error| WorldTimeError::StorageUnavailable {
                message: format!("PostgreSQL World-Time journal write failed: {error}"),
            })?;
            transaction
                .commit()
                .await
                .map_err(|error| WorldTimeError::StorageUnavailable {
                    message: format!("PostgreSQL World-Time commit failed: {error}"),
                })?;
            Ok(next)
        })
    }
}

fn sql_lifecycle_error(error: sqlx::Error) -> LifecycleError {
    LifecycleError::StorageUnavailable {
        message: format!("PostgreSQL lifecycle persistence failed: {error}"),
    }
}

fn lifecycle_birth_error(error: loom_runtime::CommitError) -> LifecycleError {
    LifecycleError::StorageUnavailable {
        message: format!("PostgreSQL atomic Template bootstrap failed: {error}"),
    }
}

fn sql_binding_error(error: sqlx::Error) -> BindingError {
    BindingError::StorageUnavailable {
        message: format!("PostgreSQL World Runtime Binding persistence failed: {error}"),
    }
}

fn sql_revision_error(error: sqlx::Error) -> RuntimeRevisionError {
    RuntimeRevisionError::StorageUnavailable {
        message: format!("PostgreSQL Runtime Revision persistence failed: {error}"),
    }
}

fn is_unique_violation(error: &sqlx::Error) -> bool {
    error
        .as_database_error()
        .and_then(sqlx::error::DatabaseError::code)
        .is_some_and(|code| code == "23505")
}

fn corrupt(message: impl Into<String>) -> ReadError {
    ReadError::StorageUnavailable {
        message: message.into(),
    }
}

fn sql_read_error(error: sqlx::Error) -> ReadError {
    corrupt(format!("PostgreSQL authority read failed: {error}"))
}

fn parse_identity<T>(value: &str, label: &str) -> Result<T, ReadError>
where
    T: FromStr,
    T::Err: Display,
{
    value
        .parse()
        .map_err(|error| corrupt(format!("invalid persisted {label}: {error}")))
}

fn parse_u64(value: &str, label: &str) -> Result<u64, ReadError> {
    value
        .parse()
        .map_err(|error| corrupt(format!("invalid persisted {label}: {error}")))
}

fn parse_runtime_u64(value: &str, label: &str) -> Result<u64, RuntimeRevisionError> {
    value
        .parse()
        .map_err(|error| RuntimeRevisionError::StorageUnavailable {
            message: format!("invalid persisted Runtime Revision {label}: {error}"),
        })
}

fn row_string(row: &sqlx::postgres::PgRow, column: &str) -> Result<String, ReadError> {
    row.try_get(column).map_err(sql_read_error)
}

fn row_i64(row: &sqlx::postgres::PgRow, column: &str) -> Result<i64, ReadError> {
    row.try_get(column).map_err(sql_read_error)
}

fn row_json(row: &sqlx::postgres::PgRow, column: &str) -> Result<Value, ReadError> {
    row.try_get(column).map_err(sql_read_error)
}

fn timeline_read_position(
    row: &sqlx::postgres::PgRow,
) -> Result<(WorldId, TimelineVersion, WorldInstant), ReadError> {
    let world_id = parse_identity::<WorldId>(&row_string(row, "world_id")?, "WorldId")?;
    let version = TimelineVersion::new(
        EventSeq::new(parse_u64(
            &row_string(row, "head_event_seq")?,
            "head_event_seq",
        )?),
        StateRevision::new(parse_u64(
            &row_string(row, "state_revision")?,
            "state_revision",
        )?),
    );
    Ok((
        world_id,
        version,
        WorldInstant::new(row_i64(row, "world_time")?),
    ))
}

fn elapsed_micros(started: Instant) -> u64 {
    started.elapsed().as_micros().try_into().unwrap_or(u64::MAX)
}

fn logical_commit_from_row(row: &sqlx::postgres::PgRow) -> Result<LogicalCommit, ReadError> {
    let timeline_id = parse_identity::<TimelineId>(&row_string(row, "timeline_id")?, "TimelineId")?;
    let before_version = TimelineVersion::new(
        EventSeq::new(parse_u64(
            &row_string(row, "before_head_event_seq")?,
            "before_head_event_seq",
        )?),
        StateRevision::new(parse_u64(
            &row_string(row, "before_state_revision")?,
            "before_state_revision",
        )?),
    );
    let after_version = TimelineVersion::new(
        EventSeq::new(parse_u64(
            &row_string(row, "after_head_event_seq")?,
            "after_head_event_seq",
        )?),
        StateRevision::new(parse_u64(
            &row_string(row, "after_state_revision")?,
            "after_state_revision",
        )?),
    );

    let world_time_before: Option<i64> =
        row.try_get("world_time_before").map_err(sql_read_error)?;
    let world_time_after: Option<i64> = row.try_get("world_time_after").map_err(sql_read_error)?;
    let world_time = match (world_time_before, world_time_after) {
        (None, None) => None,
        (Some(from), Some(to)) => Some(WorldTimeTransition {
            from: WorldInstant::new(from),
            to: WorldInstant::new(to),
        }),
        _ => return Err(corrupt("logical journal World-Time columns disagree")),
    };

    let event_ids = serde_json::from_value::<Vec<EventId>>(row_json(row, "event_ids")?)
        .map_err(|error| corrupt(format!("invalid logical journal Event IDs: {error}")))?;
    let work_transitions =
        serde_json::from_value::<Vec<LogicalWorkTransition>>(row_json(row, "work_transitions")?)
            .map_err(|error| {
                corrupt(format!("invalid logical journal Work transitions: {error}"))
            })?;

    let budget_world_time: Option<i64> = row
        .try_get("chronology_budget_world_time")
        .map_err(sql_read_error)?;
    let budget_before: Option<String> = row
        .try_get("chronology_budget_before")
        .map_err(sql_read_error)?;
    let budget_after: Option<String> = row
        .try_get("chronology_budget_after")
        .map_err(sql_read_error)?;
    let chronology_budget = match (budget_world_time, budget_before, budget_after) {
        (None, None, None) => None,
        (Some(world_time), Some(before), Some(after)) => Some(ChronologyBudgetConsumption {
            world_time: WorldInstant::new(world_time),
            before: parse_u64(&before, "chronology_budget_before")?,
            after: parse_u64(&after, "chronology_budget_after")?,
        }),
        _ => {
            return Err(corrupt(
                "logical journal chronology budget columns disagree",
            ));
        }
    };

    Ok(LogicalCommit {
        timeline_id,
        before_version,
        after_version,
        world_time,
        event_ids,
        work_transitions,
        chronology_budget,
    })
}

fn work_target(row: &sqlx::postgres::PgRow) -> Result<WorkTarget, ReadError> {
    match row_string(row, "target_kind")?.as_str() {
        "capability_work" => Ok(WorkTarget::CapabilityWork {
            owner: row
                .try_get::<Option<String>, _>("target_owner")
                .map_err(sql_read_error)?,
            handler: row_string(row, "target_handler")?.into(),
        }),
        "agency_wake" => {
            let agent = row
                .try_get::<Option<String>, _>("target_agent_id")
                .map_err(sql_read_error)?
                .ok_or_else(|| corrupt("Agency Wake target has no Agent Entity"))?
                .parse::<EntityId>()
                .map_err(|error| corrupt(format!("invalid Agency Wake Agent Entity: {error}")))?;
            let cognition = row
                .try_get::<Option<String>, _>("target_cognition")
                .map_err(sql_read_error)?
                .ok_or_else(|| corrupt("Agency Wake target has no cognition requirement"))?;
            if cognition.is_empty() {
                return Err(corrupt(
                    "Agency Wake target has an empty cognition requirement",
                ));
            }
            Ok(WorkTarget::AgencyWake { agent, cognition })
        }
        other => Err(corrupt(format!(
            "invalid persisted Work target kind {other}"
        ))),
    }
}

fn schema_revision(row: &sqlx::postgres::PgRow) -> Result<SchemaRevision, ReadError> {
    let value = u32::try_from(row_i64(row, "schema_revision")?)
        .map_err(|_| corrupt("schema_revision exceeds u32"))?;
    Ok(SchemaRevision::new(value))
}

fn optional_identity<T>(
    row: &sqlx::postgres::PgRow,
    column: &str,
    label: &str,
) -> Result<Option<T>, ReadError>
where
    T: FromStr,
    T::Err: Display,
{
    row.try_get::<Option<String>, _>(column)
        .map_err(sql_read_error)?
        .map(|value| parse_identity(&value, label))
        .transpose()
}

fn optional_u64(
    row: &sqlx::postgres::PgRow,
    column: &str,
    label: &str,
) -> Result<Option<u64>, ReadError> {
    row.try_get::<Option<String>, _>(column)
        .map_err(sql_read_error)?
        .map(|value| parse_u64(&value, label))
        .transpose()
}

fn parse_work_status(value: &str) -> Result<WorkStatus, ReadError> {
    match value {
        "pending" => Ok(WorkStatus::Pending),
        "completed" => Ok(WorkStatus::Completed),
        "cancelled" => Ok(WorkStatus::Cancelled),
        "dead" => Ok(WorkStatus::Dead),
        other => Err(corrupt(format!("invalid persisted Work status {other}"))),
    }
}

#[cfg(test)]
mod tests;
