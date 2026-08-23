//! `PostgreSQL` atomic current-head Timeline fork.

use std::collections::HashSet;

use loom_core::{
    EventId, EventRef, EventSeq, FacetOwner, StateRevision, TimelineId, TimelineVersion, WorkId,
};
use loom_runtime::{
    ForkError, ForkWork, PersistenceFuture, TimelineFork, TimelineForkStore, TimelineSnapshot,
    WorkTarget,
};
use sqlx::Row;

use super::PgStorage;

const LOCK_SOURCE_SQL: &str = include_str!("../../sql/ancestry/lock_source.sql");
const INSERT_TIMELINE_SQL: &str = include_str!("../../sql/ancestry/insert_timeline.sql");
const COPY_ENTITIES_SQL: &str = include_str!("../../sql/ancestry/copy_entities.sql");
const COPY_RELATIONSHIPS_SQL: &str = include_str!("../../sql/ancestry/copy_relationships.sql");
const COPY_PARTICIPANTS_SQL: &str =
    include_str!("../../sql/ancestry/copy_relationship_participants.sql");
const COPY_ENTITY_FACETS_SQL: &str = include_str!("../../sql/ancestry/copy_entity_facets.sql");
const COPY_RELATIONSHIP_FACETS_SQL: &str =
    include_str!("../../sql/ancestry/copy_relationship_facets.sql");
const INSERT_ENTITY_SQL: &str = include_str!("../../sql/world/insert_entity.sql");
const INSERT_RELATIONSHIP_PARTICIPANT_SQL: &str =
    include_str!("../../sql/world/insert_relationship_participant.sql");
const UPSERT_ENTITY_FACET_SQL: &str = include_str!("../../sql/world/upsert_entity_facet.sql");
const UPSERT_RELATIONSHIP_FACET_SQL: &str =
    include_str!("../../sql/world/upsert_relationship_facet.sql");
const INSERT_RELATIONSHIP_STATE_SQL: &str = "INSERT INTO loom_relationship\n     (timeline_id, relationship_id, relationship_type, active)\nVALUES ($1::uuid, $2::uuid, $3, $4)";
const INSERT_WORK_SQL: &str = include_str!("../../sql/ancestry/insert_work.sql");
const READ_TIMELINE_SQL: &str = include_str!("../../sql/world/read_timeline.sql");
const READ_PARENT_EVENT_SQL: &str = include_str!("../../sql/ancestry/read_parent_event.sql");
const LOCK_SOURCE_WORK_SQL: &str = include_str!("../../sql/ancestry/lock_source_work.sql");

impl TimelineForkStore for PgStorage {
    fn fork_timeline<'a>(
        &'a self,
        fork: &'a TimelineFork,
    ) -> PersistenceFuture<'a, Result<TimelineSnapshot, ForkError>> {
        Box::pin(async move { fork_timeline(self, fork).await })
    }
}

async fn fork_timeline(
    storage: &PgStorage,
    fork: &TimelineFork,
) -> Result<TimelineSnapshot, ForkError> {
    let mut transaction = storage.pool.begin().await.map_err(storage_error)?;
    let source = sqlx::query(LOCK_SOURCE_SQL)
        .bind(fork.source_timeline_id.to_string())
        .fetch_optional(&mut *transaction)
        .await
        .map_err(storage_error)?
        .ok_or(ForkError::SourceTimelineNotFound {
            timeline_id: fork.source_timeline_id,
        })?;
    let actual = TimelineVersion::new(
        EventSeq::new(parse_u64(&source, "head_event_seq")?),
        StateRevision::new(parse_u64(&source, "state_revision")?),
    );
    if actual != fork.expected_version {
        return Err(ForkError::SourceVersionConflict {
            expected: fork.expected_version,
            actual,
        });
    }
    if fork.fork_version.head_event_seq > actual.head_event_seq
        || fork.fork_version.state_revision > actual.state_revision
    {
        return Err(ForkError::InvalidForkVersion {
            requested: fork.fork_version,
            head: actual,
        });
    }
    if fork.child_timeline_id.is_nil() {
        return Err(ForkError::StorageUnavailable {
            message: "fork child Timeline identity is nil".to_owned(),
        });
    }
    let world_id = parse_identity::<loom_core::WorldId>(&source, "world_id")?;
    let existing_child = sqlx::query(READ_TIMELINE_SQL)
        .bind(fork.child_timeline_id.to_string())
        .fetch_optional(&mut *transaction)
        .await
        .map_err(storage_error)?;
    if let Some(existing) = existing_child {
        let existing_world = parse_identity::<loom_core::WorldId>(&existing, "world_id")?;
        let existing_version = TimelineVersion::new(
            EventSeq::new(parse_u64(&existing, "head_event_seq")?),
            StateRevision::new(parse_u64(&existing, "state_revision")?),
        );
        let parent_timeline =
            optional_identity::<TimelineId>(&existing, "parent_timeline_id", "TimelineId")?;
        let parent_head = optional_u64(
            &existing,
            "fork_parent_head_event_seq",
            "fork_parent_head_event_seq",
        )?;
        let parent_state = optional_u64(
            &existing,
            "fork_parent_state_revision",
            "fork_parent_state_revision",
        )?;
        let matches = existing_world == world_id
            && existing_version == fork.fork_version
            && parent_timeline == Some(fork.source_timeline_id)
            && parent_head == Some(fork.fork_version.head_event_seq.value())
            && parent_state == Some(fork.fork_version.state_revision.value());
        if matches {
            transaction.commit().await.map_err(storage_error)?;
            return storage
                .read_snapshot(fork.child_timeline_id)
                .await
                .map_err(|error| ForkError::StorageUnavailable {
                    message: error.to_string(),
                });
        }
        return Err(ForkError::TimelineAlreadyExists {
            timeline_id: fork.child_timeline_id,
        });
    }

    let (world_time, chronology_world_time, chronology_consumed, logical_schedule_order) =
        if let Some(materialization) = &fork.materialization {
            let base = &materialization.base;
            if base.world_id() != world_id
                || base.timeline_id() != fork.source_timeline_id
                || base.version() != fork.fork_version
                || materialization.chronology_budget.world_time != base.world_time()
            {
                return Err(ForkError::StorageUnavailable {
                    message: "fork materialization does not match its source position".to_owned(),
                });
            }
            (
                base.world_time().value(),
                materialization.chronology_budget.world_time.value(),
                materialization.chronology_budget.consumed,
                materialization.logical_schedule_order,
            )
        } else {
            (
                row_i64(&source, "world_time")?,
                row_i64(&source, "chronology_budget_world_time")?,
                parse_u64(&source, "chronology_budget_consumed")?,
                parse_u64(&source, "logical_schedule_order")?,
            )
        };
    // `EventSeq(0)` has no EventRef. The parent head Event is found by the
    // source version's sequence, without copying its row into the child.
    let parent_event =
        resolve_parent_event_ref(&mut transaction, fork.source_timeline_id, fork.fork_version)
            .await?;

    sqlx::query(INSERT_TIMELINE_SQL)
        .bind(fork.child_timeline_id.to_string())
        .bind(world_id.to_string())
        .bind(fork.fork_version.head_event_seq.value().to_string())
        .bind(fork.fork_version.state_revision.value().to_string())
        .bind(world_time)
        .bind(chronology_world_time)
        .bind(chronology_consumed.to_string())
        .bind(fork.source_timeline_id.to_string())
        .bind(fork.fork_version.head_event_seq.value().to_string())
        .bind(fork.fork_version.state_revision.value().to_string())
        .bind(parent_event.map(|event| event.timeline_id.to_string()))
        .bind(parent_event.map(|event| event.event_id.to_string()))
        .bind(logical_schedule_order.to_string())
        .execute(&mut *transaction)
        .await
        .map_err(storage_error)?;

    if let Some(materialization) = &fork.materialization {
        insert_materialization(&mut transaction, fork.child_timeline_id, materialization).await?;
    } else {
        for sql in [
            COPY_ENTITIES_SQL,
            COPY_RELATIONSHIPS_SQL,
            COPY_PARTICIPANTS_SQL,
            COPY_ENTITY_FACETS_SQL,
            COPY_RELATIONSHIP_FACETS_SQL,
        ] {
            sqlx::query(sql)
                .bind(fork.child_timeline_id.to_string())
                .bind(fork.source_timeline_id.to_string())
                .execute(&mut *transaction)
                .await
                .map_err(storage_error)?;
        }
    }

    let mut child_ids = std::collections::HashSet::new();
    for ForkWork {
        source_work_id,
        work,
    } in &fork.pending_work
    {
        let source_work = if fork.materialization.is_none() {
            Some(
                sqlx::query(LOCK_SOURCE_WORK_SQL)
                    .bind(fork.source_timeline_id.to_string())
                    .bind(source_work_id.to_string())
                    .fetch_optional(&mut *transaction)
                    .await
                    .map_err(storage_error)?
                    .ok_or_else(|| ForkError::InvalidWork {
                        work_id: *source_work_id,
                        message: "source Work is not present at the fork head".to_owned(),
                    })?,
            )
        } else {
            None
        };
        if let Some(source_work) = source_work {
            let status: String = source_work.try_get("status").map_err(storage_error)?;
            if status != "pending" {
                return Err(ForkError::InvalidWork {
                    work_id: *source_work_id,
                    message: "only Pending Work may be forked".to_owned(),
                });
            }
        }
        validate_work(source_work_id, work, fork.child_timeline_id, &mut child_ids)?;
        let (kind, owner, handler, agent, cognition) = match &work.target {
            WorkTarget::CapabilityWork { owner, handler } => (
                "capability_work",
                owner.clone(),
                Some(handler.as_str().to_owned()),
                None,
                None,
            ),
            WorkTarget::AgencyWake { agent, cognition } => (
                "agency_wake",
                None,
                None,
                Some(agent.to_string()),
                Some(cognition.clone()),
            ),
        };
        sqlx::query(INSERT_WORK_SQL)
            .bind(fork.child_timeline_id.to_string())
            .bind(work.id.to_string())
            .bind(kind)
            .bind(owner)
            .bind(handler)
            .bind(agent)
            .bind(cognition)
            .bind(i64::from(work.schema_revision.value()))
            .bind(work.payload.clone())
            .bind(work.effective_due_world_time.value())
            .bind(work.logical_schedule_order.to_string())
            .bind(work.causal_event_id.map(|event| event.to_string()))
            .bind(work.origin_work_id.map(|work| work.to_string()))
            .execute(&mut *transaction)
            .await
            .map_err(storage_error)?;
    }

    transaction.commit().await.map_err(storage_error)?;
    storage
        .read_snapshot(fork.child_timeline_id)
        .await
        .map_err(|error| ForkError::StorageUnavailable {
            message: error.to_string(),
        })
}

async fn insert_materialization(
    transaction: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    child_timeline_id: TimelineId,
    materialization: &loom_runtime::ForkMaterialization,
) -> Result<(), ForkError> {
    let base = &materialization.base;
    for entity in base.entities() {
        sqlx::query(INSERT_ENTITY_SQL)
            .bind(child_timeline_id.to_string())
            .bind(entity.id.to_string())
            .execute(&mut **transaction)
            .await
            .map_err(storage_error)?;
    }
    for (relationship, active) in base.relationships() {
        sqlx::query(INSERT_RELATIONSHIP_STATE_SQL)
            .bind(child_timeline_id.to_string())
            .bind(relationship.id.to_string())
            .bind(relationship.relationship_type.as_str())
            .bind(active)
            .execute(&mut **transaction)
            .await
            .map_err(storage_error)?;
        for (order, participant) in relationship.participants().iter().enumerate() {
            let order = i32::try_from(order).map_err(|_| ForkError::StorageUnavailable {
                message: "fork Relationship participant order exceeds storage range".to_owned(),
            })?;
            sqlx::query(INSERT_RELATIONSHIP_PARTICIPANT_SQL)
                .bind(child_timeline_id.to_string())
                .bind(relationship.id.to_string())
                .bind(order)
                .bind(participant.entity_id.to_string())
                .bind(participant.role.as_str())
                .execute(&mut **transaction)
                .await
                .map_err(storage_error)?;
        }
    }
    for (owner, facet_type, schema_revision, value) in base.facets() {
        match owner {
            FacetOwner::Entity(entity_id) => {
                sqlx::query(UPSERT_ENTITY_FACET_SQL)
                    .bind(child_timeline_id.to_string())
                    .bind(entity_id.to_string())
                    .bind(facet_type.as_str())
                    .bind(i64::from(schema_revision.value()))
                    .bind(value.clone())
                    .execute(&mut **transaction)
                    .await
                    .map_err(storage_error)?;
            }
            FacetOwner::Relationship(relationship_id) => {
                sqlx::query(UPSERT_RELATIONSHIP_FACET_SQL)
                    .bind(child_timeline_id.to_string())
                    .bind(relationship_id.to_string())
                    .bind(facet_type.as_str())
                    .bind(i64::from(schema_revision.value()))
                    .bind(value.clone())
                    .execute(&mut **transaction)
                    .await
                    .map_err(storage_error)?;
            }
        }
    }
    Ok(())
}

async fn resolve_parent_event_ref(
    transaction: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    source_timeline_id: TimelineId,
    source_version: TimelineVersion,
) -> Result<Option<EventRef>, ForkError> {
    let mut timeline_id = source_timeline_id;
    let mut visible_head = source_version.head_event_seq;
    let mut visited = HashSet::new();

    loop {
        if !visited.insert(timeline_id) {
            return Err(ForkError::StorageUnavailable {
                message: "Timeline ancestry contains a cycle".to_owned(),
            });
        }
        let event = sqlx::query_scalar::<_, String>(READ_PARENT_EVENT_SQL)
            .bind(timeline_id.to_string())
            .bind(visible_head.value().to_string())
            .fetch_optional(&mut **transaction)
            .await
            .map_err(storage_error)?;
        if let Some(event) = event {
            let event_id =
                event
                    .parse::<EventId>()
                    .map_err(|error| ForkError::StorageUnavailable {
                        message: format!("invalid persisted fork parent EventId: {error}"),
                    })?;
            return Ok(Some(EventRef::new(timeline_id, event_id)));
        }

        let Some(ancestry) = sqlx::query(READ_TIMELINE_SQL)
            .bind(timeline_id.to_string())
            .fetch_optional(&mut **transaction)
            .await
            .map_err(storage_error)?
        else {
            return Ok(None);
        };
        let parent_timeline: Option<TimelineId> =
            optional_identity(&ancestry, "parent_timeline_id", "TimelineId")?;
        let parent_head = optional_u64(
            &ancestry,
            "fork_parent_head_event_seq",
            "fork_parent_head_event_seq",
        )?;
        let parent_state = optional_u64(
            &ancestry,
            "fork_parent_state_revision",
            "fork_parent_state_revision",
        )?;
        let parent_event_timeline: Option<TimelineId> =
            optional_identity(&ancestry, "fork_parent_event_timeline_id", "TimelineId")?;
        let parent_event: Option<EventId> =
            optional_identity(&ancestry, "fork_parent_event_id", "EventId")?;
        let (Some(parent_timeline), Some(parent_head), Some(_parent_state)) =
            (parent_timeline, parent_head, parent_state)
        else {
            if parent_timeline.is_none()
                && parent_head.is_none()
                && parent_state.is_none()
                && parent_event_timeline.is_none()
                && parent_event.is_none()
            {
                return Ok(None);
            }
            return Err(ForkError::StorageUnavailable {
                message: "persisted Timeline ancestry columns disagree".to_owned(),
            });
        };
        if parent_event_timeline.is_some() != parent_event.is_some() {
            return Err(ForkError::StorageUnavailable {
                message: "persisted Timeline ancestry EventRef columns disagree".to_owned(),
            });
        }
        timeline_id = parent_timeline;
        visible_head = EventSeq::new(visible_head.value().min(parent_head));
    }
}

fn validate_work(
    source_work_id: &WorkId,
    work: &loom_runtime::WorkRecord,
    child_timeline_id: TimelineId,
    child_ids: &mut std::collections::HashSet<WorkId>,
) -> Result<(), ForkError> {
    if work.timeline_id != child_timeline_id
        || !work.is_pending()
        || work.id.is_nil()
        || !child_ids.insert(work.id)
    {
        return Err(ForkError::InvalidWork {
            work_id: *source_work_id,
            message: "child Work identity or Timeline is invalid".to_owned(),
        });
    }
    Ok(())
}

fn storage_error(error: sqlx::Error) -> ForkError {
    ForkError::StorageUnavailable {
        message: format!("PostgreSQL Timeline fork failed: {error}"),
    }
}

fn parse_identity<T>(row: &sqlx::postgres::PgRow, column: &str) -> Result<T, ForkError>
where
    T: std::str::FromStr,
    T::Err: std::fmt::Display,
{
    row.try_get::<String, _>(column)
        .map_err(storage_error)?
        .parse()
        .map_err(|error| ForkError::StorageUnavailable {
            message: format!("invalid persisted {column}: {error}"),
        })
}

fn parse_u64(row: &sqlx::postgres::PgRow, column: &str) -> Result<u64, ForkError> {
    row.try_get::<String, _>(column)
        .map_err(storage_error)?
        .parse()
        .map_err(|error| ForkError::StorageUnavailable {
            message: format!("invalid persisted {column}: {error}"),
        })
}

fn row_i64(row: &sqlx::postgres::PgRow, column: &str) -> Result<i64, ForkError> {
    row.try_get(column).map_err(storage_error)
}

fn optional_identity<T>(
    row: &sqlx::postgres::PgRow,
    column: &str,
    label: &str,
) -> Result<Option<T>, ForkError>
where
    T: std::str::FromStr,
    T::Err: std::fmt::Display,
{
    row.try_get::<Option<String>, _>(column)
        .map_err(storage_error)?
        .map(|value| {
            value
                .parse()
                .map_err(|error| ForkError::StorageUnavailable {
                    message: format!("invalid persisted {label}: {error}"),
                })
        })
        .transpose()
}

fn optional_u64(
    row: &sqlx::postgres::PgRow,
    column: &str,
    label: &str,
) -> Result<Option<u64>, ForkError> {
    row.try_get::<Option<String>, _>(column)
        .map_err(storage_error)?
        .map(|value| {
            value
                .parse()
                .map_err(|error| ForkError::StorageUnavailable {
                    message: format!("invalid persisted {label}: {error}"),
                })
        })
        .transpose()
}
