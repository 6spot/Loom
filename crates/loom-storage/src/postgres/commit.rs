//! `PostgreSQL` implementation of the Runtime-owned atomic `CommitStore` port.

use std::collections::HashSet;

use loom_core::{
    EventId, EventSeq, FacetOwner, StateRevision, TimelineId, TimelineVersion, WorldEffect,
};
use loom_runtime::{
    CommitError, CommitResult, CommitStore, CommittedEvent, PersistenceFuture, PlatformTime,
    ProposedEvent, ValidatedResolution, WorkClaim, WorkError, WorkMutation, WorkStatus,
};
use sqlx::{Postgres, Row, Transaction};

use super::PgStorage;

type PgTransaction<'a> = Transaction<'a, Postgres>;

#[derive(Clone, Copy)]
struct LockedTimeline {
    version: TimelineVersion,
}

impl CommitStore for PgStorage {
    fn commit<'a>(
        &'a self,
        resolution: &'a ValidatedResolution,
        current_work: Option<&'a WorkClaim>,
        now: PlatformTime,
    ) -> PersistenceFuture<'a, Result<CommitResult, CommitError>> {
        Box::pin(async move { commit_resolution(self, resolution, current_work, now).await })
    }
}

async fn commit_resolution(
    storage: &PgStorage,
    resolution: &ValidatedResolution,
    current_work: Option<&WorkClaim>,
    now: PlatformTime,
) -> Result<CommitResult, CommitError> {
    let timeline_id = resolution.timeline_id();
    let mut transaction = storage.pool.begin().await.map_err(storage_error)?;
    let locked = lock_timeline(&mut transaction, timeline_id).await?;
    if locked.version != resolution.base_version() {
        return Err(CommitError::TimelineConflict {
            expected: resolution.base_version(),
            actual: locked.version,
        });
    }
    if let Some(claim) = current_work {
        validate_current_work(&mut transaction, timeline_id, claim, now).await?;
    }

    let changes_runtime_state =
        !resolution.events().is_empty() || !resolution.work().is_empty() || current_work.is_some();
    let mut committed_events = Vec::with_capacity(resolution.events().len());
    let mut next_sequence = locked.version.head_event_seq.value();
    let mut seen_events = HashSet::new();

    for event in resolution.events() {
        next_sequence = next_sequence
            .checked_add(1)
            .ok_or(CommitError::RevisionOverflow)?;
        let committed = apply_event(
            &mut transaction,
            timeline_id,
            EventSeq::new(next_sequence),
            event,
            &seen_events,
            resolution.pinned_world_time(),
        )
        .await?;
        seen_events.insert(event.id);
        committed_events.push(committed);
    }

    for mutation in resolution.work() {
        apply_work_mutation(&mut transaction, timeline_id, mutation, now).await?;
    }
    let completed_work = if let Some(claim) = current_work {
        complete_current_work(&mut transaction, timeline_id, claim).await?;
        Some(claim.work_id())
    } else {
        None
    };

    let next_state_revision = if changes_runtime_state {
        locked
            .version
            .state_revision
            .value()
            .checked_add(1)
            .ok_or(CommitError::RevisionOverflow)?
    } else {
        locked.version.state_revision.value()
    };
    let next_head = if committed_events.is_empty() {
        locked.version.head_event_seq
    } else {
        EventSeq::new(next_sequence)
    };
    let version = TimelineVersion::new(next_head, StateRevision::new(next_state_revision));

    if changes_runtime_state {
        sqlx::query(
            "UPDATE loom_timeline SET head_event_seq = $2::numeric, state_revision = $3::numeric \
             WHERE timeline_id = $1::uuid",
        )
        .bind(timeline_id.to_string())
        .bind(next_head.value().to_string())
        .bind(next_state_revision.to_string())
        .execute(&mut *transaction)
        .await
        .map_err(storage_error)?;
    }

    transaction.commit().await.map_err(storage_error)?;
    Ok(CommitResult {
        timeline_id,
        version,
        events: committed_events,
        completed_work,
    })
}

async fn lock_timeline(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
) -> Result<LockedTimeline, CommitError> {
    let row = sqlx::query(
        "SELECT head_event_seq::text AS head_event_seq, state_revision::text AS state_revision \
         FROM loom_timeline WHERE timeline_id = $1::uuid FOR UPDATE",
    )
    .bind(timeline_id.to_string())
    .fetch_optional(&mut **transaction)
    .await
    .map_err(storage_error)?
    .ok_or(CommitError::TimelineNotFound { timeline_id })?;
    Ok(LockedTimeline {
        version: TimelineVersion::new(
            EventSeq::new(parse_u64(&row, "head_event_seq")?),
            StateRevision::new(parse_u64(&row, "state_revision")?),
        ),
    })
}

async fn apply_event(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    event_seq: EventSeq,
    event: &ProposedEvent,
    seen_events: &HashSet<EventId>,
    occurred_at: loom_core::WorldInstant,
) -> Result<CommittedEvent, CommitError> {
    if event.id.is_nil() {
        return Err(invalid_event(event.id, "Event identity is nil"));
    }
    if seen_events.contains(&event.id) || event_exists(transaction, timeline_id, event.id).await? {
        return Err(CommitError::DuplicateEvent { event_id: event.id });
    }

    for effect in &event.effects {
        apply_effect(transaction, timeline_id, event.id, effect).await?;
    }
    validate_event_references(transaction, timeline_id, event).await?;

    let effects = serde_json::to_value(&event.effects).map_err(|error| {
        invalid_event(
            event.id,
            format!("cannot serialize frozen Effects: {error}"),
        )
    })?;
    sqlx::query(
        "INSERT INTO loom_event \
         (timeline_id, event_id, event_seq, event_type, schema_revision, occurred_at, payload, effects) \
         VALUES ($1::uuid, $2::uuid, $3::numeric, $4, $5, $6, $7, $8)",
    )
    .bind(timeline_id.to_string())
    .bind(event.id.to_string())
    .bind(event_seq.value().to_string())
    .bind(event.event_type.as_str())
    .bind(i64::from(event.schema_revision.value()))
    .bind(occurred_at.value())
    .bind(event.payload.clone())
    .bind(effects)
    .execute(&mut **transaction)
    .await
    .map_err(|error| event_sql_error(event.id, error))?;

    for (order, participant) in event.participants.iter().enumerate() {
        sqlx::query(
            "INSERT INTO loom_event_participant \
             (timeline_id, event_id, participant_order, entity_id, role) \
             VALUES ($1::uuid, $2::uuid, $3, $4::uuid, $5)",
        )
        .bind(timeline_id.to_string())
        .bind(event.id.to_string())
        .bind(order_i32(order, event.id)?)
        .bind(participant.entity_id.to_string())
        .bind(participant.role.as_str())
        .execute(&mut **transaction)
        .await
        .map_err(|error| event_sql_error(event.id, error))?;
    }
    for (order, reference) in event.relationship_refs.iter().enumerate() {
        sqlx::query(
            "INSERT INTO loom_event_relationship_ref \
             (timeline_id, event_id, reference_order, relationship_id, role) \
             VALUES ($1::uuid, $2::uuid, $3, $4::uuid, $5)",
        )
        .bind(timeline_id.to_string())
        .bind(event.id.to_string())
        .bind(order_i32(order, event.id)?)
        .bind(reference.relationship_id.to_string())
        .bind(reference.role.as_str())
        .execute(&mut **transaction)
        .await
        .map_err(|error| event_sql_error(event.id, error))?;
    }
    for (order, causal) in event.causal_links.iter().enumerate() {
        sqlx::query(
            "INSERT INTO loom_event_causal_link \
             (timeline_id, event_id, causal_order, cause_event_id) \
             VALUES ($1::uuid, $2::uuid, $3, $4::uuid)",
        )
        .bind(timeline_id.to_string())
        .bind(event.id.to_string())
        .bind(order_i32(order, event.id)?)
        .bind(causal.event_id().to_string())
        .execute(&mut **transaction)
        .await
        .map_err(|error| event_sql_error(event.id, error))?;
    }

    Ok(CommittedEvent::from_proposed(
        timeline_id,
        event_seq,
        event,
        occurred_at,
    ))
}

async fn validate_event_references(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    event: &ProposedEvent,
) -> Result<(), CommitError> {
    for participant in &event.participants {
        if !entity_exists(transaction, timeline_id, participant.entity_id).await? {
            return Err(invalid_event(
                event.id,
                format!("missing participant Entity {}", participant.entity_id),
            ));
        }
    }
    for reference in &event.relationship_refs {
        let active =
            active_relationship_exists(transaction, timeline_id, reference.relationship_id).await?;
        let ended_by_this_event = event.effects.iter().any(|effect| {
            matches!(
                effect,
                WorldEffect::EndRelationship { relationship_id }
                    if *relationship_id == reference.relationship_id
            )
        });
        if !active && !ended_by_this_event {
            return Err(invalid_event(
                event.id,
                format!("missing active Relationship {}", reference.relationship_id),
            ));
        }
    }
    for causal in &event.causal_links {
        if !event_exists(transaction, timeline_id, causal.event_id()).await? {
            return Err(invalid_event(
                event.id,
                format!(
                    "causal Event {} is not committed ancestry or prior batch",
                    causal.event_id()
                ),
            ));
        }
    }
    Ok(())
}

async fn apply_effect(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    event_id: EventId,
    effect: &WorldEffect,
) -> Result<(), CommitError> {
    match effect {
        WorldEffect::CreateEntity { entity_id } => {
            if entity_id.is_nil() || entity_exists(transaction, timeline_id, *entity_id).await? {
                return Err(invalid_effect(
                    event_id,
                    "Entity identity is nil or already exists",
                ));
            }
            sqlx::query(
                "INSERT INTO loom_entity (timeline_id, entity_id) VALUES ($1::uuid, $2::uuid)",
            )
            .bind(timeline_id.to_string())
            .bind(entity_id.to_string())
            .execute(&mut **transaction)
            .await
            .map_err(|error| effect_sql_error(event_id, error))?;
        }
        WorldEffect::PutFacet {
            owner,
            facet_type,
            schema_revision,
            value,
        } => {
            if !owner_exists(transaction, timeline_id, *owner).await? {
                return Err(invalid_effect(event_id, "Facet owner does not exist"));
            }
            match owner {
                FacetOwner::Entity(entity_id) => {
                    sqlx::query(
                        "INSERT INTO loom_entity_facet \
                         (timeline_id, entity_id, facet_type, schema_revision, value) \
                         VALUES ($1::uuid, $2::uuid, $3, $4, $5) \
                         ON CONFLICT (timeline_id, entity_id, facet_type) DO UPDATE \
                         SET schema_revision = EXCLUDED.schema_revision, value = EXCLUDED.value",
                    )
                    .bind(timeline_id.to_string())
                    .bind(entity_id.to_string())
                    .bind(facet_type.as_str())
                    .bind(i64::from(schema_revision.value()))
                    .bind(value.clone())
                    .execute(&mut **transaction)
                    .await
                    .map_err(|error| effect_sql_error(event_id, error))?;
                }
                FacetOwner::Relationship(relationship_id) => {
                    sqlx::query(
                        "INSERT INTO loom_relationship_facet \
                         (timeline_id, relationship_id, facet_type, schema_revision, value) \
                         VALUES ($1::uuid, $2::uuid, $3, $4, $5) \
                         ON CONFLICT (timeline_id, relationship_id, facet_type) DO UPDATE \
                         SET schema_revision = EXCLUDED.schema_revision, value = EXCLUDED.value",
                    )
                    .bind(timeline_id.to_string())
                    .bind(relationship_id.to_string())
                    .bind(facet_type.as_str())
                    .bind(i64::from(schema_revision.value()))
                    .bind(value.clone())
                    .execute(&mut **transaction)
                    .await
                    .map_err(|error| effect_sql_error(event_id, error))?;
                }
            }
        }
        WorldEffect::RemoveFacet { owner, facet_type } => {
            if !owner_exists(transaction, timeline_id, *owner).await? {
                return Err(invalid_effect(event_id, "Facet owner does not exist"));
            }
            match owner {
                FacetOwner::Entity(entity_id) => {
                    sqlx::query(
                        "DELETE FROM loom_entity_facet \
                         WHERE timeline_id = $1::uuid AND entity_id = $2::uuid AND facet_type = $3",
                    )
                    .bind(timeline_id.to_string())
                    .bind(entity_id.to_string())
                    .bind(facet_type.as_str())
                    .execute(&mut **transaction)
                    .await
                    .map_err(storage_error)?;
                }
                FacetOwner::Relationship(relationship_id) => {
                    sqlx::query(
                        "DELETE FROM loom_relationship_facet WHERE timeline_id = $1::uuid \
                         AND relationship_id = $2::uuid AND facet_type = $3",
                    )
                    .bind(timeline_id.to_string())
                    .bind(relationship_id.to_string())
                    .bind(facet_type.as_str())
                    .execute(&mut **transaction)
                    .await
                    .map_err(storage_error)?;
                }
            }
        }
        WorldEffect::CreateRelationship {
            relationship_id,
            relationship_type,
            participants,
        } => {
            if relationship_id.is_nil()
                || participants.is_empty()
                || relationship_exists(transaction, timeline_id, *relationship_id).await?
            {
                return Err(invalid_effect(
                    event_id,
                    "Relationship identity is invalid, duplicated, or has no participants",
                ));
            }
            let mut participant_ids = HashSet::new();
            for participant in participants {
                if participant.entity_id.is_nil()
                    || !entity_exists(transaction, timeline_id, participant.entity_id).await?
                {
                    return Err(invalid_effect(
                        event_id,
                        "Relationship participant Entity does not exist",
                    ));
                }
                if !participant_ids.insert(participant.entity_id) {
                    return Err(invalid_effect(
                        event_id,
                        "Relationship contains a duplicate participant Entity",
                    ));
                }
            }
            sqlx::query(
                "INSERT INTO loom_relationship \
                 (timeline_id, relationship_id, relationship_type, active) \
                 VALUES ($1::uuid, $2::uuid, $3, TRUE)",
            )
            .bind(timeline_id.to_string())
            .bind(relationship_id.to_string())
            .bind(relationship_type.as_str())
            .execute(&mut **transaction)
            .await
            .map_err(|error| effect_sql_error(event_id, error))?;
            for (order, participant) in participants.iter().enumerate() {
                sqlx::query(
                    "INSERT INTO loom_relationship_participant \
                     (timeline_id, relationship_id, participant_order, entity_id, role) \
                     VALUES ($1::uuid, $2::uuid, $3, $4::uuid, $5)",
                )
                .bind(timeline_id.to_string())
                .bind(relationship_id.to_string())
                .bind(order_i32(order, event_id)?)
                .bind(participant.entity_id.to_string())
                .bind(participant.role.as_str())
                .execute(&mut **transaction)
                .await
                .map_err(|error| effect_sql_error(event_id, error))?;
            }
        }
        WorldEffect::EndRelationship { relationship_id } => {
            let active: Option<bool> = sqlx::query_scalar(
                "SELECT active FROM loom_relationship \
                 WHERE timeline_id = $1::uuid AND relationship_id = $2::uuid",
            )
            .bind(timeline_id.to_string())
            .bind(relationship_id.to_string())
            .fetch_optional(&mut **transaction)
            .await
            .map_err(storage_error)?;
            match active {
                None => return Err(invalid_effect(event_id, "Relationship does not exist")),
                Some(false) => {
                    return Err(invalid_effect(event_id, "Relationship is already ended"));
                }
                Some(true) => {}
            }
            sqlx::query(
                "UPDATE loom_relationship SET active = FALSE \
                 WHERE timeline_id = $1::uuid AND relationship_id = $2::uuid",
            )
            .bind(timeline_id.to_string())
            .bind(relationship_id.to_string())
            .execute(&mut **transaction)
            .await
            .map_err(storage_error)?;
        }
    }
    Ok(())
}

async fn apply_work_mutation(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    mutation: &WorkMutation,
    now: PlatformTime,
) -> Result<(), CommitError> {
    match mutation {
        WorkMutation::Schedule(work) => {
            if work.timeline_id != timeline_id {
                return Err(WorkError::TimelineMismatch {
                    expected: timeline_id,
                    actual: work.timeline_id,
                }
                .into());
            }
            if work_exists(transaction, timeline_id, work.id).await? {
                return Err(WorkError::DuplicateWork { work_id: work.id }.into());
            }
            if let Some(event_id) = work.causal_event_id
                && !event_exists(transaction, timeline_id, event_id).await?
            {
                return Err(WorkError::MissingCausalEvent {
                    work_id: work.id,
                    event_id,
                }
                .into());
            }
            if let Some(origin_work_id) = work.origin_work_id
                && !work_exists(transaction, timeline_id, origin_work_id).await?
            {
                return Err(WorkError::WorkNotFound {
                    timeline_id,
                    work_id: origin_work_id,
                }
                .into());
            }
            let record = loom_runtime::WorkRecord::from_new_work(work, now);
            sqlx::query(
                "INSERT INTO loom_work \
                 (timeline_id, work_id, handler, schema_revision, payload, due_world_time, causal_event_id, \
                  origin_work_id, status, attempt_count, claim_generation, available_at, last_error, \
                  lease_claimed_until, lease_fence) \
                 VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7::uuid, $8::uuid, 'pending', 0, 0, $9, \
                         NULL, NULL, NULL)",
            )
            .bind(timeline_id.to_string())
            .bind(work.id.to_string())
            .bind(work.handler.as_str())
            .bind(i64::from(work.schema_revision.value()))
            .bind(work.payload.clone())
            .bind(record.due_world_time.map(loom_core::WorldInstant::value))
            .bind(work.causal_event_id.map(|id| id.to_string()))
            .bind(work.origin_work_id.map(|id| id.to_string()))
            .bind(now.value())
            .execute(&mut **transaction)
            .await
            .map_err(storage_error)?;
            Ok(())
        }
        WorkMutation::Cancel(work_id) => cancel_work(transaction, timeline_id, *work_id).await,
    }
}

async fn cancel_work(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    work_id: loom_core::WorkId,
) -> Result<(), CommitError> {
    let status = lock_work_status(transaction, timeline_id, work_id).await?;
    if status != WorkStatus::Pending {
        return Err(WorkError::NotPending { work_id, status }.into());
    }
    sqlx::query(
        "UPDATE loom_work SET status = 'cancelled', lease_claimed_until = NULL, lease_fence = NULL \
         WHERE timeline_id = $1::uuid AND work_id = $2::uuid",
    )
    .bind(timeline_id.to_string())
    .bind(work_id.to_string())
    .execute(&mut **transaction)
    .await
    .map_err(storage_error)?;
    Ok(())
}

async fn validate_current_work(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    claim: &WorkClaim,
    now: PlatformTime,
) -> Result<(), CommitError> {
    if claim.timeline_id() != timeline_id {
        return Err(WorkError::TimelineMismatch {
            expected: timeline_id,
            actual: claim.timeline_id(),
        }
        .into());
    }
    let row = sqlx::query(
        "SELECT status, lease_claimed_until, lease_fence::text AS lease_fence \
         FROM loom_work WHERE timeline_id = $1::uuid AND work_id = $2::uuid FOR UPDATE",
    )
    .bind(timeline_id.to_string())
    .bind(claim.work_id().to_string())
    .fetch_optional(&mut **transaction)
    .await
    .map_err(storage_error)?
    .ok_or(WorkError::WorkNotFound {
        timeline_id,
        work_id: claim.work_id(),
    })?;
    let status = parse_status(row.try_get("status").map_err(storage_error)?)?;
    if status != WorkStatus::Pending {
        return Err(WorkError::NotPending {
            work_id: claim.work_id(),
            status,
        }
        .into());
    }
    let claimed_until: Option<i64> = row.try_get("lease_claimed_until").map_err(storage_error)?;
    let fence: Option<String> = row.try_get("lease_fence").map_err(storage_error)?;
    let (Some(claimed_until), Some(fence)) = (claimed_until, fence) else {
        return Err(WorkError::MissingLease {
            work_id: claim.work_id(),
        }
        .into());
    };
    let actual_fence = fence
        .parse::<u64>()
        .map_err(|error| CommitError::StorageUnavailable {
            message: format!("invalid persisted Work fence: {error}"),
        })?;
    if actual_fence != claim.fence() || PlatformTime::new(claimed_until) != claim.claimed_until() {
        return Err(WorkError::StaleClaim {
            work_id: claim.work_id(),
            expected_fence: claim.fence(),
            actual_fence: Some(actual_fence),
        }
        .into());
    }
    if now >= PlatformTime::new(claimed_until) {
        return Err(WorkError::LeaseExpired {
            work_id: claim.work_id(),
            claimed_until: PlatformTime::new(claimed_until),
            now,
        }
        .into());
    }
    Ok(())
}

async fn complete_current_work(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    claim: &WorkClaim,
) -> Result<(), CommitError> {
    sqlx::query(
        "UPDATE loom_work SET status = 'completed', lease_claimed_until = NULL, lease_fence = NULL, \
         last_error = NULL WHERE timeline_id = $1::uuid AND work_id = $2::uuid",
    )
    .bind(timeline_id.to_string())
    .bind(claim.work_id().to_string())
    .execute(&mut **transaction)
    .await
    .map_err(storage_error)?;
    Ok(())
}

async fn lock_work_status(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    work_id: loom_core::WorkId,
) -> Result<WorkStatus, CommitError> {
    let value: String = sqlx::query_scalar(
        "SELECT status FROM loom_work WHERE timeline_id = $1::uuid AND work_id = $2::uuid FOR UPDATE",
    )
    .bind(timeline_id.to_string())
    .bind(work_id.to_string())
    .fetch_optional(&mut **transaction)
    .await
    .map_err(storage_error)?
    .ok_or(WorkError::WorkNotFound {
        timeline_id,
        work_id,
    })?;
    parse_status(&value)
}

async fn owner_exists(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    owner: FacetOwner,
) -> Result<bool, CommitError> {
    match owner {
        FacetOwner::Entity(entity_id) => entity_exists(transaction, timeline_id, entity_id).await,
        FacetOwner::Relationship(relationship_id) => {
            active_relationship_exists(transaction, timeline_id, relationship_id).await
        }
    }
}

async fn entity_exists(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    entity_id: loom_core::EntityId,
) -> Result<bool, CommitError> {
    exists(
        transaction,
        "SELECT EXISTS (SELECT 1 FROM loom_entity WHERE timeline_id = $1::uuid AND entity_id = $2::uuid)",
        timeline_id,
        entity_id.to_string(),
    )
    .await
}

async fn relationship_exists(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    relationship_id: loom_core::RelationshipId,
) -> Result<bool, CommitError> {
    exists(
        transaction,
        "SELECT EXISTS (SELECT 1 FROM loom_relationship WHERE timeline_id = $1::uuid AND relationship_id = $2::uuid)",
        timeline_id,
        relationship_id.to_string(),
    )
    .await
}

async fn active_relationship_exists(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    relationship_id: loom_core::RelationshipId,
) -> Result<bool, CommitError> {
    exists(
        transaction,
        "SELECT EXISTS (SELECT 1 FROM loom_relationship WHERE timeline_id = $1::uuid AND relationship_id = $2::uuid AND active)",
        timeline_id,
        relationship_id.to_string(),
    )
    .await
}

async fn event_exists(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    event_id: EventId,
) -> Result<bool, CommitError> {
    exists(
        transaction,
        "SELECT EXISTS (SELECT 1 FROM loom_event WHERE timeline_id = $1::uuid AND event_id = $2::uuid)",
        timeline_id,
        event_id.to_string(),
    )
    .await
}

async fn work_exists(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    work_id: loom_core::WorkId,
) -> Result<bool, CommitError> {
    exists(
        transaction,
        "SELECT EXISTS (SELECT 1 FROM loom_work WHERE timeline_id = $1::uuid AND work_id = $2::uuid)",
        timeline_id,
        work_id.to_string(),
    )
    .await
}

async fn exists(
    transaction: &mut PgTransaction<'_>,
    query: &'static str,
    timeline_id: TimelineId,
    id: String,
) -> Result<bool, CommitError> {
    sqlx::query_scalar(query)
        .bind(timeline_id.to_string())
        .bind(id)
        .fetch_one(&mut **transaction)
        .await
        .map_err(storage_error)
}

fn parse_u64(row: &sqlx::postgres::PgRow, column: &str) -> Result<u64, CommitError> {
    let value: String = row.try_get(column).map_err(storage_error)?;
    value
        .parse()
        .map_err(|error| CommitError::StorageUnavailable {
            message: format!("invalid persisted {column}: {error}"),
        })
}

fn parse_status(value: &str) -> Result<WorkStatus, CommitError> {
    match value {
        "pending" => Ok(WorkStatus::Pending),
        "completed" => Ok(WorkStatus::Completed),
        "cancelled" => Ok(WorkStatus::Cancelled),
        "dead" => Ok(WorkStatus::Dead),
        other => Err(CommitError::StorageUnavailable {
            message: format!("invalid persisted Work status {other}"),
        }),
    }
}

fn order_i32(order: usize, event_id: EventId) -> Result<i32, CommitError> {
    i32::try_from(order).map_err(|_| invalid_event(event_id, "association count exceeds i32"))
}

fn invalid_event(event_id: EventId, message: impl Into<String>) -> CommitError {
    CommitError::InvalidEvent {
        event_id,
        message: message.into(),
    }
}

fn invalid_effect(event_id: EventId, message: impl Into<String>) -> CommitError {
    CommitError::InvalidEffect {
        event_id,
        message: message.into(),
    }
}

fn storage_error(error: sqlx::Error) -> CommitError {
    CommitError::StorageUnavailable {
        message: format!("PostgreSQL atomic commit failed: {error}"),
    }
}

fn event_sql_error(event_id: EventId, error: sqlx::Error) -> CommitError {
    if database_code(&error).as_deref() == Some("23505") {
        CommitError::DuplicateEvent { event_id }
    } else {
        storage_error(error)
    }
}

fn effect_sql_error(event_id: EventId, error: sqlx::Error) -> CommitError {
    match database_code(&error).as_deref() {
        Some("23503" | "23505" | "23514") => invalid_effect(event_id, error.to_string()),
        _ => storage_error(error),
    }
}

fn database_code(error: &sqlx::Error) -> Option<std::borrow::Cow<'_, str>> {
    error.as_database_error()?.code()
}
