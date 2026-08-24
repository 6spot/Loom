//! `PostgreSQL` implementation of the Runtime-owned atomic `CommitStore` port.

use std::collections::HashSet;

use loom_core::{
    EventId, EventRef, EventSeq, ExecutionSessionId, FacetOwner, StateRevision, TimelineId,
    TimelineVersion, WorkId, WorldEffect,
};
use loom_runtime::{
    ChronologyBudgetConsumption, CommitAuthorityContext, CommitError, CommitProvenance,
    CommitResult, CommitStore, CommittedEvent, ExecutionSession, ExecutionSessionStatus,
    IngressClaim, IngressError, IngressOperationalRecord, IngressStatus, LogicalCommit,
    LogicalWorkTransition, PersistenceFuture, PlatformTime, ProposedEvent, RuntimeControlStore,
    SchedulerCommitStore, ValidatedResolution, WorkClaim, WorkError, WorkMutation, WorkStatus,
    WorkTerminalState, WorkTerminalization,
};
use sqlx::{Postgres, Row, Transaction};

use super::PgStorage;

type PgTransaction<'a> = Transaction<'a, Postgres>;

const UPDATE_TIMELINE_VERSION_SQL: &str = include_str!("../../sql/timeline/update_version.sql");
const LOCK_TIMELINE_VERSION_SQL: &str = include_str!("../../sql/timeline/lock_version.sql");
const INSERT_EVENT_SQL: &str = include_str!("../../sql/event/insert_event.sql");
const INSERT_EVENT_PARTICIPANT_SQL: &str = include_str!("../../sql/event/insert_participant.sql");
const INSERT_EVENT_RELATIONSHIP_REF_SQL: &str =
    include_str!("../../sql/event/insert_relationship_ref.sql");
const INSERT_EVENT_CAUSAL_LINK_SQL: &str = include_str!("../../sql/event/insert_causal_link.sql");
const EVENT_EXISTS_SQL: &str = include_str!("../../sql/event/exists.sql");
const READ_VISIBLE_EVENT_IDS_SQL: &str =
    include_str!("../../sql/ancestry/read_visible_event_ids.sql");
const INSERT_ENTITY_SQL: &str = include_str!("../../sql/world/insert_entity.sql");
const UPSERT_ENTITY_FACET_SQL: &str = include_str!("../../sql/world/upsert_entity_facet.sql");
const UPSERT_RELATIONSHIP_FACET_SQL: &str =
    include_str!("../../sql/world/upsert_relationship_facet.sql");
const DELETE_ENTITY_FACET_SQL: &str = include_str!("../../sql/world/delete_entity_facet.sql");
const DELETE_RELATIONSHIP_FACET_SQL: &str =
    include_str!("../../sql/world/delete_relationship_facet.sql");
const INSERT_RELATIONSHIP_SQL: &str = include_str!("../../sql/world/insert_relationship.sql");
const INSERT_RELATIONSHIP_PARTICIPANT_SQL: &str =
    include_str!("../../sql/world/insert_relationship_participant.sql");
const READ_RELATIONSHIP_ACTIVE_SQL: &str =
    include_str!("../../sql/world/read_relationship_active.sql");
const END_RELATIONSHIP_SQL: &str = include_str!("../../sql/world/end_relationship.sql");
const ENTITY_EXISTS_SQL: &str = include_str!("../../sql/world/entity_exists.sql");
const RELATIONSHIP_EXISTS_SQL: &str = include_str!("../../sql/world/relationship_exists.sql");
const ACTIVE_RELATIONSHIP_EXISTS_SQL: &str =
    include_str!("../../sql/world/active_relationship_exists.sql");
const INSERT_SCHEDULED_WORK_SQL: &str = include_str!("../../sql/work/insert_scheduled.sql");
const NEXT_LOGICAL_SCHEDULE_ORDER_SQL: &str =
    include_str!("../../sql/work/next_logical_schedule_order.sql");
const CANCEL_WORK_SQL: &str = include_str!("../../sql/work/cancel.sql");
const SELECT_WORK_CLAIM_FOR_UPDATE_SQL: &str =
    include_str!("../../sql/work/select_claim_for_update.sql");
const COMPLETE_WORK_SQL: &str = include_str!("../../sql/work/complete.sql");
const TERMINALIZE_WORK_SQL: &str = include_str!("../../sql/work/terminalize.sql");
const SELECT_WORK_STATUS_FOR_UPDATE_SQL: &str =
    include_str!("../../sql/work/select_status_for_update.sql");
const WORK_EXISTS_SQL: &str = include_str!("../../sql/work/exists.sql");
const INSERT_LOGICAL_JOURNAL_SQL: &str = include_str!("../../sql/logical_journal/insert.sql");
const SELECT_LOGICAL_HEAD_SQL: &str = include_str!("../../sql/work/select_logical_head.sql");
const SELECT_INGRESS_FOR_UPDATE_SQL: &str = include_str!("../../sql/ingress/select_for_update.sql");
const INSERT_SESSION_EVENT_SQL: &str = "INSERT INTO loom_execution_session_event (timeline_id, event_id, event_seq, session_id) VALUES ($1::uuid, $2::uuid, $3::numeric, $4::uuid)";

#[derive(Clone, Copy)]
struct LockedTimeline {
    version: TimelineVersion,
    world_time: loom_core::WorldInstant,
    chronology_budget_world_time: loom_core::WorldInstant,
    chronology_budget_consumed: u64,
    logical_schedule_order: u64,
}

impl CommitStore for PgStorage {
    fn commit<'a>(
        &'a self,
        resolution: &'a ValidatedResolution,
        current_work: Option<&'a WorkClaim>,
        now: PlatformTime,
    ) -> PersistenceFuture<'a, Result<CommitResult, CommitError>> {
        Box::pin(async move {
            commit_resolution(self, resolution, current_work, None, None, None, now, None).await
        })
    }

    fn commit_with_authority<'a>(
        &'a self,
        resolution: &'a ValidatedResolution,
        context: CommitAuthorityContext,
        now: PlatformTime,
    ) -> PersistenceFuture<'a, Result<CommitResult, CommitError>> {
        Box::pin(async move {
            commit_resolution(
                self,
                resolution,
                context.current_work.as_ref(),
                context.ingress_claim.as_ref(),
                context.provenance.as_ref(),
                context.session_id,
                now,
                None,
            )
            .await
        })
    }
}

impl SchedulerCommitStore for PgStorage {
    fn commit_scheduler_work<'a>(
        &'a self,
        resolution: &'a ValidatedResolution,
        current_work: &'a WorkClaim,
        now: PlatformTime,
        max_completions: u64,
    ) -> PersistenceFuture<'a, Result<CommitResult, CommitError>> {
        Box::pin(async move {
            commit_resolution(
                self,
                resolution,
                Some(current_work),
                None,
                None,
                None,
                now,
                Some(max_completions),
            )
            .await
        })
    }

    fn commit_scheduler_work_with_session<'a>(
        &'a self,
        resolution: &'a ValidatedResolution,
        current_work: &'a WorkClaim,
        now: PlatformTime,
        max_completions: u64,
        session_id: ExecutionSessionId,
    ) -> PersistenceFuture<'a, Result<CommitResult, CommitError>> {
        Box::pin(async move {
            #[cfg(test)]
            if let Some(conflict_work_id) = self.take_scheduler_conflict_work_once() {
                let terminalization = WorkTerminalization::new(
                    resolution.timeline_id(),
                    resolution.base_version(),
                    conflict_work_id,
                    WorkTerminalState::Cancelled,
                    now,
                );
                terminalize_current_work(self, &terminalization).await?;
            }
            commit_resolution(
                self,
                resolution,
                Some(current_work),
                None,
                None,
                Some(session_id),
                now,
                Some(max_completions),
            )
            .await
        })
    }
}

impl RuntimeControlStore for PgStorage {
    fn terminalize_work<'a>(
        &'a self,
        terminalization: &'a WorkTerminalization,
    ) -> PersistenceFuture<'a, Result<TimelineVersion, CommitError>> {
        Box::pin(async move { terminalize_work(self, terminalization).await })
    }

    fn terminalize_current_work<'a>(
        &'a self,
        terminalization: &'a WorkTerminalization,
    ) -> PersistenceFuture<'a, Result<TimelineVersion, CommitError>> {
        Box::pin(async move { terminalize_current_work(self, terminalization).await })
    }
}

async fn terminalize_work(
    storage: &PgStorage,
    terminalization: &WorkTerminalization,
) -> Result<TimelineVersion, CommitError> {
    terminalize_work_internal(storage, terminalization, true).await
}

async fn terminalize_current_work(
    storage: &PgStorage,
    terminalization: &WorkTerminalization,
) -> Result<TimelineVersion, CommitError> {
    terminalize_work_internal(storage, terminalization, false).await
}

async fn terminalize_work_internal(
    storage: &PgStorage,
    terminalization: &WorkTerminalization,
    check_expected_version: bool,
) -> Result<TimelineVersion, CommitError> {
    let timeline_id = terminalization.timeline_id();
    let mut transaction = storage.pool.begin().await.map_err(storage_error)?;
    let locked = lock_timeline(&mut transaction, timeline_id).await?;
    if check_expected_version && locked.version != terminalization.expected_version() {
        return Err(CommitError::TimelineConflict {
            expected: terminalization.expected_version(),
            actual: locked.version,
        });
    }

    if let Some(claim) = terminalization.claim() {
        if claim.work_id() != terminalization.work_id() {
            return Err(WorkError::WorkMismatch {
                expected: terminalization.work_id(),
                actual: claim.work_id(),
            }
            .into());
        }
        validate_current_work(&mut transaction, timeline_id, &claim, terminalization.now()).await?;
    } else {
        let status =
            lock_work_status(&mut transaction, timeline_id, terminalization.work_id()).await?;
        if status != WorkStatus::Pending {
            return Err(WorkError::NotPending {
                work_id: terminalization.work_id(),
                status,
            }
            .into());
        }
    }

    sqlx::query(TERMINALIZE_WORK_SQL)
        .bind(timeline_id.to_string())
        .bind(terminalization.work_id().to_string())
        .bind(match terminalization.terminal_state() {
            WorkTerminalState::Dead => "dead",
            WorkTerminalState::Cancelled => "cancelled",
        })
        .bind(terminalization.last_error())
        .execute(&mut *transaction)
        .await
        .map_err(storage_error)?;

    let before_version = locked.version;
    let next_state_revision = before_version
        .state_revision
        .value()
        .checked_add(1)
        .ok_or(CommitError::RevisionOverflow)?;
    let version = TimelineVersion::new(
        before_version.head_event_seq,
        StateRevision::new(next_state_revision),
    );
    sqlx::query(UPDATE_TIMELINE_VERSION_SQL)
        .bind(timeline_id.to_string())
        .bind(version.head_event_seq.value().to_string())
        .bind(version.state_revision.value().to_string())
        .bind(locked.chronology_budget_world_time.value())
        .bind(locked.chronology_budget_consumed.to_string())
        .bind(locked.logical_schedule_order.to_string())
        .execute(&mut *transaction)
        .await
        .map_err(storage_error)?;

    let work_transition = match terminalization.terminal_state() {
        WorkTerminalState::Dead => LogicalWorkTransition::Dead {
            work_id: terminalization.work_id(),
        },
        WorkTerminalState::Cancelled => LogicalWorkTransition::Cancel {
            work_id: terminalization.work_id(),
        },
    };
    insert_logical_commit(
        &mut transaction,
        &LogicalCommit {
            timeline_id,
            before_version,
            after_version: version,
            world_time: None,
            event_ids: Vec::new(),
            work_transitions: vec![work_transition],
            chronology_budget: None,
            provenance: None,
        },
    )
    .await?;
    transaction.commit().await.map_err(storage_error)?;
    Ok(version)
}

#[expect(
    clippy::too_many_arguments,
    reason = "the PostgreSQL commit boundary carries all authority inputs"
)]
async fn commit_resolution(
    storage: &PgStorage,
    resolution: &ValidatedResolution,
    current_work: Option<&WorkClaim>,
    ingress_claim: Option<&IngressClaim>,
    provenance: Option<&CommitProvenance>,
    session_id: Option<ExecutionSessionId>,
    now: PlatformTime,
    chronology_budget_limit: Option<u64>,
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
    if let Some(claim) = ingress_claim {
        validate_current_ingress(&mut transaction, claim, now).await?;
    }
    if let Some(claim) = current_work {
        validate_current_work(&mut transaction, timeline_id, claim, now).await?;
        validate_logical_head(&mut transaction, timeline_id, claim.work_id()).await?;
        if let Some(limit) = chronology_budget_limit
            && locked.chronology_budget_consumed >= limit
        {
            return Err(CommitError::ChronologyBudgetExceeded(
                loom_runtime::ChronologyBudgetExceeded {
                    timeline_id,
                    world_time: locked.world_time,
                    limit,
                    consumed: locked.chronology_budget_consumed,
                },
            ));
        }
    }
    validate_session_link(
        &mut transaction,
        timeline_id,
        resolution.base_version(),
        session_id,
    )
    .await?;
    let before_version = locked.version;
    let before_budget = locked.chronology_budget_consumed;
    let visible_event_ids = read_visible_event_ids(&mut transaction, timeline_id).await?;

    let changes_runtime_state =
        !resolution.events().is_empty() || !resolution.work().is_empty() || current_work.is_some();
    let mut committed_events = Vec::with_capacity(resolution.events().len());
    let mut event_ids = Vec::with_capacity(resolution.events().len());
    let mut next_sequence = locked.version.head_event_seq.value();
    let mut seen_events = HashSet::new();
    let mut logical_schedule_order =
        next_logical_schedule_order(&mut transaction, timeline_id).await?;

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
            &visible_event_ids,
            resolution.pinned_world_time(),
        )
        .await?;
        seen_events.insert(event.id);
        event_ids.push(event.id);
        committed_events.push(committed);
    }

    let mut work_transitions =
        Vec::with_capacity(resolution.work().len() + usize::from(current_work.is_some()));
    for mutation in resolution.work() {
        work_transitions.push(
            apply_work_mutation(
                &mut transaction,
                timeline_id,
                mutation,
                resolution.pinned_world_time(),
                now,
                &mut logical_schedule_order,
            )
            .await?,
        );
    }
    let completed_work = if let Some(claim) = current_work {
        work_transitions.push(complete_current_work(&mut transaction, timeline_id, claim).await?);
        Some(claim.work_id())
    } else {
        None
    };

    let chronology_budget = if current_work.is_some() {
        let after = before_budget.checked_add(1).ok_or(CommitError::Work(
            WorkError::ChronologyBudgetOverflow { timeline_id },
        ))?;
        Some(ChronologyBudgetConsumption {
            world_time: locked.world_time,
            before: before_budget,
            after,
        })
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

    let next_budget = chronology_budget
        .as_ref()
        .map_or(before_budget, |consumption| consumption.after);

    let provenance = provenance.map(|provenance| {
        let mut committed = provenance.clone();
        committed
            .logical_work_transitions
            .clone_from(&work_transitions);
        committed
    });

    if changes_runtime_state {
        sqlx::query(UPDATE_TIMELINE_VERSION_SQL)
            .bind(timeline_id.to_string())
            .bind(next_head.value().to_string())
            .bind(next_state_revision.to_string())
            .bind(locked.chronology_budget_world_time.value())
            .bind(next_budget.to_string())
            .bind(logical_schedule_order.to_string())
            .execute(&mut *transaction)
            .await
            .map_err(storage_error)?;
    }

    if changes_runtime_state {
        insert_logical_commit(
            &mut transaction,
            &LogicalCommit {
                timeline_id,
                before_version,
                after_version: version,
                world_time: None,
                event_ids,
                work_transitions,
                chronology_budget,
                provenance: provenance.clone(),
            },
        )
        .await?;
    }

    link_committed_events(&mut transaction, timeline_id, session_id, &committed_events).await?;

    transaction
        .commit()
        .await
        .map_err(|error| CommitError::CommitOutcomeUnknown {
            message: format!("PostgreSQL authority commit outcome is unknown: {error}"),
        })?;
    #[cfg(test)]
    if storage.take_test_unknown_commit_once() {
        return Err(CommitError::CommitOutcomeUnknown {
            message: "test PostgreSQL authority commit outcome is unknown".to_owned(),
        });
    }
    Ok(CommitResult {
        timeline_id,
        version,
        events: committed_events,
        completed_work,
        provenance,
    })
}

async fn validate_session_link(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    expected_version: TimelineVersion,
    session_id: Option<ExecutionSessionId>,
) -> Result<(), CommitError> {
    let Some(session_id) = session_id else {
        return Ok(());
    };
    let row = sqlx::query(
        "SELECT timeline_id::text AS timeline_id, status, record FROM loom_execution_session WHERE session_id = $1::uuid FOR UPDATE",
    )
    .bind(session_id.to_string())
    .fetch_optional(&mut **transaction)
    .await
    .map_err(storage_error)?
    .ok_or_else(|| CommitError::SessionLink {
        message: format!("Execution Session {session_id} was not found"),
    })?;
    let stored_timeline: String = row.try_get("timeline_id").map_err(storage_error)?;
    let stored_status: String = row.try_get("status").map_err(storage_error)?;
    let parsed_timeline =
        stored_timeline
            .parse::<TimelineId>()
            .map_err(|error| CommitError::SessionLink {
                message: format!("invalid Session Timeline identity: {error}"),
            })?;
    if parsed_timeline != timeline_id {
        return Err(CommitError::SessionLink {
            message: format!("Execution Session {session_id} targets another Timeline"),
        });
    }
    if stored_status != "Started" {
        return Err(CommitError::SessionLink {
            message: format!("Execution Session {session_id} is not Started"),
        });
    }
    let record: serde_json::Value = row.try_get("record").map_err(storage_error)?;
    let session: ExecutionSession =
        serde_json::from_value(record).map_err(|error| CommitError::SessionLink {
            message: format!("invalid persisted Execution Session: {error}"),
        })?;
    if session.status() != ExecutionSessionStatus::Started
        || session.assembly().expected_version() != expected_version
    {
        return Err(CommitError::SessionLink {
            message: format!("Execution Session {session_id} is not pinned to this commit"),
        });
    }
    if !session.event_refs().is_empty() {
        return Err(CommitError::SessionLink {
            message: format!("Execution Session {session_id} already owns committed Events"),
        });
    }
    Ok(())
}

async fn link_committed_events(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    session_id: Option<ExecutionSessionId>,
    committed_events: &[CommittedEvent],
) -> Result<(), CommitError> {
    let Some(session_id) = session_id else {
        return Ok(());
    };
    if committed_events.is_empty() {
        return Ok(());
    }
    let event_refs: Vec<EventRef> = committed_events
        .iter()
        .map(CommittedEvent::event_ref)
        .collect();
    for committed in committed_events {
        sqlx::query(INSERT_SESSION_EVENT_SQL)
            .bind(timeline_id.to_string())
            .bind(committed.id.to_string())
            .bind(committed.event_seq.value().to_string())
            .bind(session_id.to_string())
            .execute(&mut **transaction)
            .await
            .map_err(|error| {
                if super::is_unique_violation(&error) {
                    CommitError::SessionLink {
                        message: format!("Event {} already has a producing Session", committed.id),
                    }
                } else {
                    storage_error(error)
                }
            })?;
    }
    let refs = serde_json::to_value(event_refs).map_err(|error| CommitError::SessionLink {
        message: format!("Event provenance serialization failed: {error}"),
    })?;
    let updated = sqlx::query(
        "UPDATE loom_execution_session SET record = jsonb_set(record, '{event_refs}', $2::jsonb, true) WHERE session_id = $1::uuid AND status = 'Started'",
    )
    .bind(session_id.to_string())
    .bind(refs)
    .execute(&mut **transaction)
    .await
    .map_err(storage_error)?;
    if updated.rows_affected() != 1 {
        return Err(CommitError::SessionLink {
            message: format!("Execution Session {session_id} link update was lost"),
        });
    }
    Ok(())
}

/// Applies Runtime-validated Template bootstrap resolutions inside the caller's
/// already-open World birth transaction. The caller owns the final commit or
/// rollback, so World, Binding, Timeline, Events, Effects and Work share one
/// `PostgreSQL` authority transaction.
pub(super) async fn commit_birth_in_transaction(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    initial_world_time: loom_core::WorldInstant,
    bootstrap: &[ValidatedResolution],
    now: PlatformTime,
    session_id: Option<ExecutionSessionId>,
) -> Result<TimelineVersion, CommitError> {
    let locked = lock_timeline(transaction, timeline_id).await?;
    if locked.version != TimelineVersion::default() {
        return Err(CommitError::TimelineConflict {
            expected: TimelineVersion::default(),
            actual: locked.version,
        });
    }
    validate_session_link(
        transaction,
        timeline_id,
        TimelineVersion::default(),
        session_id,
    )
    .await?;

    let mut next_sequence = locked.version.head_event_seq.value();
    let mut seen_events = HashSet::new();
    let mut changes_runtime_state = false;
    let mut event_ids = Vec::new();
    let mut committed_events = Vec::new();
    let mut work_transitions = Vec::new();
    let mut logical_schedule_order = next_logical_schedule_order(transaction, timeline_id).await?;

    for resolution in bootstrap {
        if resolution.timeline_id() != timeline_id {
            return Err(CommitError::TimelineMismatch {
                expected: timeline_id,
                actual: resolution.timeline_id(),
            });
        }
        if resolution.base_version() != TimelineVersion::default() {
            return Err(CommitError::TimelineConflict {
                expected: TimelineVersion::default(),
                actual: resolution.base_version(),
            });
        }
        if resolution.pinned_world_time() != initial_world_time {
            return Err(CommitError::StorageUnavailable {
                message: "validated Template bootstrap uses a different World Time".to_owned(),
            });
        }

        for event in resolution.events() {
            next_sequence = next_sequence
                .checked_add(1)
                .ok_or(CommitError::RevisionOverflow)?;
            let committed = apply_event(
                transaction,
                timeline_id,
                EventSeq::new(next_sequence),
                event,
                &seen_events,
                &seen_events,
                initial_world_time,
            )
            .await?;
            seen_events.insert(event.id);
            event_ids.push(event.id);
            committed_events.push(committed);
            changes_runtime_state = true;
        }
        for mutation in resolution.work() {
            work_transitions.push(
                apply_work_mutation(
                    transaction,
                    timeline_id,
                    mutation,
                    initial_world_time,
                    now,
                    &mut logical_schedule_order,
                )
                .await?,
            );
            changes_runtime_state = true;
        }
    }

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
    let next_head = if changes_runtime_state && !seen_events.is_empty() {
        EventSeq::new(next_sequence)
    } else {
        locked.version.head_event_seq
    };
    let version = TimelineVersion::new(next_head, StateRevision::new(next_state_revision));

    if changes_runtime_state {
        sqlx::query(UPDATE_TIMELINE_VERSION_SQL)
            .bind(timeline_id.to_string())
            .bind(next_head.value().to_string())
            .bind(next_state_revision.to_string())
            .bind(locked.chronology_budget_world_time.value())
            .bind(locked.chronology_budget_consumed.to_string())
            .bind(logical_schedule_order.to_string())
            .execute(&mut **transaction)
            .await
            .map_err(storage_error)?;
        insert_logical_commit(
            transaction,
            &LogicalCommit {
                timeline_id,
                before_version: locked.version,
                after_version: version,
                world_time: None,
                event_ids,
                work_transitions,
                chronology_budget: None,
                provenance: None,
            },
        )
        .await?;
    }

    link_committed_events(transaction, timeline_id, session_id, &committed_events).await?;

    Ok(version)
}

async fn lock_timeline(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
) -> Result<LockedTimeline, CommitError> {
    let row = sqlx::query(LOCK_TIMELINE_VERSION_SQL)
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
        world_time: loom_core::WorldInstant::new(row.try_get("world_time").map_err(storage_error)?),
        chronology_budget_world_time: loom_core::WorldInstant::new(
            row.try_get("chronology_budget_world_time")
                .map_err(storage_error)?,
        ),
        chronology_budget_consumed: parse_u64(&row, "chronology_budget_consumed")?,
        logical_schedule_order: parse_u64(&row, "logical_schedule_order")?,
    })
}

async fn validate_current_ingress(
    transaction: &mut PgTransaction<'_>,
    claim: &IngressClaim,
    now: PlatformTime,
) -> Result<(), CommitError> {
    let row = sqlx::query(SELECT_INGRESS_FOR_UPDATE_SQL)
        .bind(claim.ingress_id().as_str())
        .fetch_optional(&mut **transaction)
        .await
        .map_err(storage_error)?
        .ok_or_else(|| CommitError::IngressClaim {
            message: format!("Ingress {} was not found", claim.ingress_id()),
        })?;
    let record: serde_json::Value = row.try_get("record").map_err(storage_error)?;
    let record: IngressOperationalRecord =
        serde_json::from_value(record).map_err(|error| CommitError::IngressClaim {
            message: format!("invalid persisted Ingress claim record: {error}"),
        })?;
    if !matches!(record.status, IngressStatus::Processing) {
        return Err(CommitError::IngressClaim {
            message: IngressError::NotClaimable {
                ingress_id: claim.ingress_id().clone(),
                status: record.status,
            }
            .to_string(),
        });
    }
    let Some(lease) = record.lease else {
        return Err(CommitError::IngressClaim {
            message: format!("Ingress {} has no active lease", claim.ingress_id()),
        });
    };
    if lease.fence() != claim.fence() || lease.claimed_until() != claim.claimed_until() {
        return Err(CommitError::IngressClaim {
            message: format!("Ingress {} claim fence is stale", claim.ingress_id()),
        });
    }
    if now >= lease.claimed_until() {
        return Err(CommitError::IngressClaim {
            message: format!("Ingress {} lease has expired", claim.ingress_id()),
        });
    }
    Ok(())
}

async fn next_logical_schedule_order(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
) -> Result<u64, CommitError> {
    let row = sqlx::query(NEXT_LOGICAL_SCHEDULE_ORDER_SQL)
        .bind(timeline_id.to_string())
        .fetch_one(&mut **transaction)
        .await
        .map_err(storage_error)?;
    parse_u64(&row, "logical_schedule_order")
}

async fn read_visible_event_ids(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
) -> Result<HashSet<EventId>, CommitError> {
    let rows = sqlx::query_scalar::<_, String>(READ_VISIBLE_EVENT_IDS_SQL)
        .bind(timeline_id.to_string())
        .fetch_all(&mut **transaction)
        .await
        .map_err(storage_error)?;
    rows.into_iter()
        .map(|value| {
            value
                .parse::<EventId>()
                .map_err(|error| CommitError::StorageUnavailable {
                    message: format!("invalid visible Event identity: {error}"),
                })
        })
        .collect()
}

pub(super) async fn insert_logical_commit(
    transaction: &mut PgTransaction<'_>,
    commit: &LogicalCommit,
) -> Result<(), CommitError> {
    let event_ids = serde_json::to_value(&commit.event_ids).map_err(|error| {
        CommitError::StorageUnavailable {
            message: format!("logical journal Event serialization failed: {error}"),
        }
    })?;
    let work_transitions = serde_json::to_value(&commit.work_transitions).map_err(|error| {
        CommitError::StorageUnavailable {
            message: format!("logical journal Work serialization failed: {error}"),
        }
    })?;
    let provenance = commit
        .provenance
        .as_ref()
        .map(serde_json::to_value)
        .transpose()
        .map_err(|error| CommitError::StorageUnavailable {
            message: format!("logical journal provenance serialization failed: {error}"),
        })?;
    let (world_time_before, world_time_after) =
        commit.world_time.map_or((None, None), |transition| {
            (Some(transition.from.value()), Some(transition.to.value()))
        });
    let (budget_world_time, budget_before, budget_after) =
        commit
            .chronology_budget
            .map_or((None, None, None), |budget| {
                (
                    Some(budget.world_time.value()),
                    Some(budget.before.to_string()),
                    Some(budget.after.to_string()),
                )
            });

    sqlx::query(INSERT_LOGICAL_JOURNAL_SQL)
        .bind(commit.timeline_id.to_string())
        .bind(commit.after_version.state_revision.value().to_string())
        .bind(commit.before_version.head_event_seq.value().to_string())
        .bind(commit.before_version.state_revision.value().to_string())
        .bind(commit.after_version.head_event_seq.value().to_string())
        .bind(world_time_before)
        .bind(world_time_after)
        .bind(event_ids)
        .bind(work_transitions)
        .bind(provenance)
        .bind(budget_world_time)
        .bind(budget_before)
        .bind(budget_after)
        .execute(&mut **transaction)
        .await
        .map_err(storage_error)?;
    Ok(())
}

async fn apply_event(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    event_seq: EventSeq,
    event: &ProposedEvent,
    seen_events: &HashSet<EventId>,
    visible_event_ids: &HashSet<EventId>,
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
    validate_event_references(
        transaction,
        timeline_id,
        event,
        seen_events,
        visible_event_ids,
    )
    .await?;

    let effects = serde_json::to_value(&event.effects).map_err(|error| {
        invalid_event(
            event.id,
            format!("cannot serialize frozen Effects: {error}"),
        )
    })?;
    sqlx::query(INSERT_EVENT_SQL)
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
        sqlx::query(INSERT_EVENT_PARTICIPANT_SQL)
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
        sqlx::query(INSERT_EVENT_RELATIONSHIP_REF_SQL)
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
        sqlx::query(INSERT_EVENT_CAUSAL_LINK_SQL)
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
    seen_events: &HashSet<EventId>,
    visible_event_ids: &HashSet<EventId>,
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
        if !visible_event_ids.contains(&causal.event_id())
            && !seen_events.contains(&causal.event_id())
        {
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
            sqlx::query(INSERT_ENTITY_SQL)
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
                    sqlx::query(UPSERT_ENTITY_FACET_SQL)
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
                    sqlx::query(UPSERT_RELATIONSHIP_FACET_SQL)
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
                    sqlx::query(DELETE_ENTITY_FACET_SQL)
                        .bind(timeline_id.to_string())
                        .bind(entity_id.to_string())
                        .bind(facet_type.as_str())
                        .execute(&mut **transaction)
                        .await
                        .map_err(storage_error)?;
                }
                FacetOwner::Relationship(relationship_id) => {
                    sqlx::query(DELETE_RELATIONSHIP_FACET_SQL)
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
            sqlx::query(INSERT_RELATIONSHIP_SQL)
                .bind(timeline_id.to_string())
                .bind(relationship_id.to_string())
                .bind(relationship_type.as_str())
                .execute(&mut **transaction)
                .await
                .map_err(|error| effect_sql_error(event_id, error))?;
            for (order, participant) in participants.iter().enumerate() {
                sqlx::query(INSERT_RELATIONSHIP_PARTICIPANT_SQL)
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
            let active: Option<bool> = sqlx::query_scalar(READ_RELATIONSHIP_ACTIVE_SQL)
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
            sqlx::query(END_RELATIONSHIP_SQL)
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
    world_time: loom_core::WorldInstant,
    now: PlatformTime,
    logical_schedule_order: &mut u64,
) -> Result<LogicalWorkTransition, CommitError> {
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
            let next_order = logical_schedule_order
                .checked_add(1)
                .ok_or(WorkError::LogicalScheduleOrderOverflow { timeline_id })?;
            let effective_due_world_time = match work.schedule {
                loom_runtime::WorkSchedule::Immediate => world_time,
                loom_runtime::WorkSchedule::At(instant) => instant,
            };
            let record = loom_runtime::WorkRecord::from_scheduled_work(
                work,
                effective_due_world_time,
                next_order,
                now,
            );
            let (target_kind, target_owner, target_handler, target_agent_id, target_cognition) =
                match &record.target {
                    loom_runtime::WorkTarget::CapabilityWork { owner, handler } => (
                        "capability_work",
                        owner.clone(),
                        Some(handler.as_str().to_owned()),
                        None,
                        None,
                    ),
                    loom_runtime::WorkTarget::AgencyWake { agent, cognition } => (
                        "agency_wake",
                        None,
                        None,
                        Some(agent.to_string()),
                        Some(cognition.clone()),
                    ),
                };
            sqlx::query(INSERT_SCHEDULED_WORK_SQL)
                .bind(timeline_id.to_string())
                .bind(work.id.to_string())
                .bind(target_kind)
                .bind(target_owner)
                .bind(target_handler)
                .bind(target_agent_id)
                .bind(target_cognition)
                .bind(i64::from(record.schema_revision.value()))
                .bind(record.payload.clone())
                .bind(record.effective_due_world_time.value())
                .bind(next_order.to_string())
                .bind(work.causal_event_id.map(|id| id.to_string()))
                .bind(work.origin_work_id.map(|id| id.to_string()))
                .bind(now.value())
                .execute(&mut **transaction)
                .await
                .map_err(storage_error)?;
            *logical_schedule_order = next_order;
            Ok(LogicalWorkTransition::Schedule {
                work_id: work.id,
                target: work.target.clone(),
                schema_revision: work.schema_revision,
                payload: work.payload.clone(),
                effective_due_world_time,
                logical_schedule_order: next_order,
                causal_event_id: work.causal_event_id,
                origin_work_id: work.origin_work_id,
            })
        }
        WorkMutation::Cancel(work_id) => cancel_work(transaction, timeline_id, *work_id).await,
    }
}

async fn cancel_work(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    work_id: loom_core::WorkId,
) -> Result<LogicalWorkTransition, CommitError> {
    let status = lock_work_status(transaction, timeline_id, work_id).await?;
    if status != WorkStatus::Pending {
        return Err(WorkError::NotPending { work_id, status }.into());
    }
    sqlx::query(CANCEL_WORK_SQL)
        .bind(timeline_id.to_string())
        .bind(work_id.to_string())
        .execute(&mut **transaction)
        .await
        .map_err(storage_error)?;
    Ok(LogicalWorkTransition::Cancel { work_id })
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
    let row = sqlx::query(SELECT_WORK_CLAIM_FOR_UPDATE_SQL)
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

async fn validate_logical_head(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    work_id: WorkId,
) -> Result<(), CommitError> {
    let Some(row) = sqlx::query(SELECT_LOGICAL_HEAD_SQL)
        .bind(timeline_id.to_string())
        .fetch_optional(&mut **transaction)
        .await
        .map_err(storage_error)?
    else {
        return Err(WorkError::WorkNotFound {
            timeline_id,
            work_id,
        }
        .into());
    };
    let head_work_id = row
        .try_get::<String, _>("work_id")
        .map_err(storage_error)?
        .parse::<WorkId>()
        .map_err(|error| CommitError::StorageUnavailable {
            message: format!("invalid persisted logical head Work identity: {error}"),
        })?;
    if head_work_id != work_id {
        return Err(WorkError::NotLogicalHead {
            work_id,
            head_work_id,
        }
        .into());
    }
    Ok(())
}

async fn complete_current_work(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    claim: &WorkClaim,
) -> Result<LogicalWorkTransition, CommitError> {
    sqlx::query(COMPLETE_WORK_SQL)
        .bind(timeline_id.to_string())
        .bind(claim.work_id().to_string())
        .execute(&mut **transaction)
        .await
        .map_err(storage_error)?;
    Ok(LogicalWorkTransition::Complete {
        work_id: claim.work_id(),
    })
}

async fn lock_work_status(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    work_id: loom_core::WorkId,
) -> Result<WorkStatus, CommitError> {
    let value: String = sqlx::query_scalar(SELECT_WORK_STATUS_FOR_UPDATE_SQL)
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
        ENTITY_EXISTS_SQL,
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
        RELATIONSHIP_EXISTS_SQL,
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
        ACTIVE_RELATIONSHIP_EXISTS_SQL,
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
        EVENT_EXISTS_SQL,
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
        WORK_EXISTS_SQL,
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
