//! Deterministic reconstruction of Timeline Logical State.
//!
//! The Event replay engine reconstructs materialized World State from frozen
//! Event Effects. This module replays the separate Runtime-owned Logical
//! Journal for the Timeline time/future position and composes both results for
//! historical reads. Operational Work metadata is intentionally not an input
//! to this reconstruction.

use std::{
    collections::{BTreeMap, HashSet},
    fmt,
};

use loom_core::{EventId, EventSeq, TimelineId, TimelineVersion, WorkId, WorldInstant};
use loom_protocol::WorkTarget;
use serde_json::Value;

use crate::{
    BaseWorldSnapshot, BaseWorldView, ChronologyBudgetState, CommittedEvent, LogicalCommit,
    LogicalWorkTransition, ReplayEngine, ReplayError, WorkStatus,
};

/// The semantic portion of one historical Durable Work record.
///
/// Lease, fence, attempt, availability and technical error fields are absent
/// by construction. Those values belong to Platform Operational State and
/// cannot influence historical Timeline reconstruction.
#[derive(Clone, Debug, PartialEq)]
pub struct LogicalWorkState {
    /// Stable Work identity.
    pub work_id: WorkId,
    /// Explicit logical execution target.
    pub target: WorkTarget,
    /// Schema revision for the serialized Work payload.
    pub schema_revision: loom_core::SchemaRevision,
    /// Serialized logical Work input.
    pub payload: Value,
    /// World-semantic due coordinate.
    pub effective_due_world_time: WorldInstant,
    /// Timeline-local persistent chronology order.
    pub logical_schedule_order: u64,
    /// Optional Event that caused the Work.
    pub causal_event_id: Option<EventId>,
    /// Optional preceding Work from which this Work was derived.
    pub origin_work_id: Option<WorkId>,
    /// Durable semantic lifecycle at the requested version.
    pub status: WorkStatus,
}

impl LogicalWorkState {
    #[expect(
        clippy::too_many_arguments,
        reason = "the journal Schedule record is the complete semantic Work reconstruction payload"
    )]
    fn from_schedule(
        work_id: WorkId,
        target: WorkTarget,
        schema_revision: loom_core::SchemaRevision,
        payload: Value,
        effective_due_world_time: WorldInstant,
        logical_schedule_order: u64,
        causal_event_id: Option<EventId>,
        origin_work_id: Option<WorkId>,
    ) -> Self {
        Self {
            work_id,
            target,
            schema_revision,
            payload,
            effective_due_world_time,
            logical_schedule_order,
            causal_event_id,
            origin_work_id,
            status: WorkStatus::Pending,
        }
    }
}

/// Reconstructed logical state at one exact committed `TimelineVersion`.
#[derive(Clone, Debug, PartialEq)]
pub struct TimelineLogicalState {
    /// Timeline containing this historical logical position.
    pub timeline_id: TimelineId,
    /// Exact committed version represented by this state.
    pub version: TimelineVersion,
    /// World Time reconstructed only from logical time transitions.
    pub world_time: WorldInstant,
    /// All Work obligations that exist at this position, ordered by their
    /// persistent logical schedule key.
    pub works: Vec<LogicalWorkState>,
    /// Same-instant chronology consumption at the reconstructed World Time.
    pub chronology_budget: ChronologyBudgetState,
}

impl TimelineLogicalState {
    /// Returns one Work at this historical position.
    #[must_use]
    pub fn work(&self, work_id: WorkId) -> Option<&LogicalWorkState> {
        self.works.iter().find(|work| work.work_id == work_id)
    }

    /// Returns only Pending Work in deterministic Scheduler order.
    pub fn pending_works(&self) -> impl Iterator<Item = &LogicalWorkState> {
        self.works
            .iter()
            .filter(|work| work.status == WorkStatus::Pending)
    }
}

/// Materialized World State and Timeline Logical State at one exact version.
#[derive(Clone, Debug)]
pub struct HistoricalTimelineState {
    /// Materialized semantic World State reconstructed from frozen Events.
    materialization: BaseWorldSnapshot,
    /// Runtime-owned logical time/future state reconstructed from the journal.
    logical: TimelineLogicalState,
}

impl HistoricalTimelineState {
    /// Returns the materialized World reconstruction.
    #[must_use]
    pub const fn materialization(&self) -> &BaseWorldSnapshot {
        &self.materialization
    }

    /// Returns the Runtime read view over the materialized reconstruction.
    #[must_use]
    pub fn world_view(&self) -> BaseWorldView {
        BaseWorldView::new(self.materialization.clone())
    }

    /// Returns the reconstructed logical Timeline state.
    #[must_use]
    pub const fn logical_state(&self) -> &TimelineLogicalState {
        &self.logical
    }

    /// Returns the exact version represented by both reconstruction domains.
    #[must_use]
    pub const fn version(&self) -> TimelineVersion {
        self.logical.version
    }

    /// Returns the reconstructed World Time.
    #[must_use]
    pub const fn world_time(&self) -> WorldInstant {
        self.logical.world_time
    }

    /// Returns the Timeline identity.
    #[must_use]
    pub const fn timeline_id(&self) -> TimelineId {
        self.logical.timeline_id
    }

    /// Returns the World identity.
    #[must_use]
    pub const fn world_id(&self) -> loom_core::WorldId {
        self.materialization.world_id()
    }
}

/// A deterministic failure while replaying Timeline Logical State.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LogicalReplayError {
    /// The initial materialization and logical journal refer to different
    /// Timelines.
    TimelineMismatch {
        /// Timeline expected by the initial materialization.
        expected: TimelineId,
        /// Timeline found in the inconsistent record.
        actual: TimelineId,
    },
    /// The first journal record does not continue the supplied initial
    /// logical position, or a later record does not continue its predecessor.
    JournalVersionMismatch {
        /// Version required before the next journal record.
        expected: TimelineVersion,
        /// Version supplied by that record.
        actual: TimelineVersion,
    },
    /// A journal record does not advance the logical revision exactly once.
    InvalidRevisionAdvance {
        /// Version before the invalid record.
        before: TimelineVersion,
        /// Version after the invalid record.
        after: TimelineVersion,
    },
    /// A requested version is not the initial position or a journal commit
    /// boundary.
    TargetVersionNotCommitted { target: TimelineVersion },
    /// A journal Event identity/sequence range does not match the Event
    /// ledger supplied for the same historical prefix.
    EventJournalMismatch {
        /// Logical commit containing the inconsistent range.
        version: TimelineVersion,
        /// Event IDs recorded by the logical commit.
        expected: Vec<EventId>,
        /// Event IDs found at the corresponding Event sequence positions.
        actual: Vec<EventId>,
    },
    /// An Event sequence in the historical prefix is not the next expected
    /// sequence for its journal range.
    EventSequenceMismatch {
        /// Logical commit containing the inconsistent Event range.
        version: TimelineVersion,
        /// Sequence required by the logical version boundary.
        expected: EventSeq,
        /// Sequence found in the Event record.
        actual: EventSeq,
    },
    /// A Work/Event reference in the logical journal cannot be resolved from
    /// the historical prefix.
    InvalidWorkTransition {
        /// Logical commit containing the invalid transition.
        version: TimelineVersion,
        /// Work identity involved, when one exists.
        work_id: Option<WorkId>,
        /// Stable structural reason.
        reason: LogicalWorkReplayError,
    },
    /// A logical commit has an invalid World-Time transition or chronology
    /// budget record.
    InvalidLogicalCommit {
        /// Logical commit containing the invalid transition.
        version: TimelineVersion,
        /// Stable structural reason.
        reason: LogicalCommitReplayError,
    },
    /// Frozen Event replay failed while composing the historical materialized
    /// state.
    MaterializedReplay(ReplayError),
}

/// Structural Work-history failures returned by [`LogicalReplayError`].
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LogicalWorkReplayError {
    /// A Schedule reused an existing Work identity.
    DuplicateWork,
    /// A terminal transition targeted no Work.
    WorkNotFound,
    /// A terminal transition targeted a Work that was already terminal.
    NotPending { status: WorkStatus },
    /// A scheduled Work reused or regressed the persistent order.
    InvalidScheduleOrder { previous: u64, actual: u64 },
    /// A Schedule referenced a missing causal Event.
    MissingCausalEvent { event_id: EventId },
    /// A Schedule referenced a missing origin Work.
    MissingOriginWork { work_id: WorkId },
}

/// Structural logical-commit failures returned by [`LogicalReplayError`].
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LogicalCommitReplayError {
    /// The journal recorded a World-Time transition from a different time.
    WorldTimeMismatch {
        expected: WorldInstant,
        actual: WorldInstant,
    },
    /// World Time may only advance monotonically.
    NonMonotonicWorldTime {
        from: WorldInstant,
        to: WorldInstant,
    },
    /// A time transition would cross a due Pending Work barrier.
    DueWorkPending,
    /// A chronology record was supplied without a Work completion, or vice
    /// versa.
    ChronologyCompletionMismatch,
    /// Chronology consumption belongs to a different World Time.
    ChronologyWorldTimeMismatch {
        expected: WorldInstant,
        actual: WorldInstant,
    },
    /// The persisted before value does not equal reconstructed consumption.
    ChronologyBeforeMismatch { expected: u64, actual: u64 },
    /// The persisted after value is not exactly one completion after before.
    ChronologyAfterMismatch { before: u64, after: u64 },
    /// A time transition and a completion budget update are ambiguous in the
    /// current M5 commit representation.
    TimeAndChronologyCombined,
}

impl fmt::Display for LogicalReplayError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::TimelineMismatch { expected, actual } => {
                write!(
                    formatter,
                    "logical history belongs to Timeline {actual}, expected {expected}"
                )
            }
            Self::JournalVersionMismatch { expected, actual } => write!(
                formatter,
                "logical journal version mismatch: expected {expected:?}, received {actual:?}"
            ),
            Self::InvalidRevisionAdvance { before, after } => write!(
                formatter,
                "logical journal revision did not advance exactly once: {before:?} -> {after:?}"
            ),
            Self::TargetVersionNotCommitted { target } => {
                write!(
                    formatter,
                    "TimelineVersion {target:?} is not a committed logical boundary"
                )
            }
            Self::EventJournalMismatch {
                version,
                expected,
                actual,
            } => write!(
                formatter,
                "Event/logical journal mismatch at {version:?}: expected {expected:?}, received {actual:?}"
            ),
            Self::EventSequenceMismatch {
                version,
                expected,
                actual,
            } => write!(
                formatter,
                "Event sequence mismatch at {version:?}: expected {}, received {}",
                expected.value(),
                actual.value()
            ),
            Self::InvalidWorkTransition {
                version,
                work_id,
                reason,
            } => write!(
                formatter,
                "invalid logical Work transition at {version:?} for {work_id:?}: {reason:?}"
            ),
            Self::InvalidLogicalCommit { version, reason } => {
                write!(
                    formatter,
                    "invalid logical commit at {version:?}: {reason:?}"
                )
            }
            Self::MaterializedReplay(error) => {
                write!(formatter, "materialized replay failed: {error}")
            }
        }
    }
}

impl fmt::Display for LogicalWorkReplayError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl fmt::Display for LogicalCommitReplayError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for LogicalReplayError {}

/// Stateless Runtime-owned Timeline replay engine.
pub struct LogicalReplayEngine;

impl LogicalReplayEngine {
    /// Reconstructs one exact `TimelineVersion` from the initial materialized
    /// snapshot, ordered committed Events and ordered logical journal.
    ///
    /// The Event ledger is replayed only through `target`; later Events and
    /// later logical commits are ignored. The supplied initial snapshot must
    /// represent the logical position immediately before the supplied Event
    /// and journal suffix. Operational Work records are deliberately not an
    /// argument, so lease/retry noise cannot alter the result.
    ///
    /// # Errors
    ///
    /// Returns a deterministic [`LogicalReplayError`] for an uncommitted
    /// target, gaps or inconsistent version/Event/Work/budget streams.
    pub fn replay(
        initial: BaseWorldSnapshot,
        events: &[CommittedEvent],
        journal: &[LogicalCommit],
        target: TimelineVersion,
    ) -> Result<HistoricalTimelineState, LogicalReplayError> {
        let timeline_id = initial.timeline_id();
        if target.state_revision.value() < initial.version().state_revision.value()
            || target.head_event_seq.value() < initial.version().head_event_seq.value()
        {
            return Err(LogicalReplayError::TargetVersionNotCommitted { target });
        }

        let mut visible_events = events
            .iter()
            .filter(|event| event.event_seq.value() <= target.head_event_seq.value())
            .cloned()
            .collect::<Vec<_>>();
        visible_events.sort_by_key(|event| (event.event_seq, event.id));

        let mut version = initial.version();
        let mut world_time = initial.world_time();
        let mut chronology_budget = 0;
        let mut works = BTreeMap::<WorkId, LogicalWorkState>::new();
        let mut logical_order_high_water = 0;
        let mut event_cursor = 0;
        let mut known_events = HashSet::new();
        let mut found_target = target == version;
        for commit in journal {
            if found_target {
                break;
            }
            if commit.timeline_id != timeline_id {
                return Err(LogicalReplayError::TimelineMismatch {
                    expected: timeline_id,
                    actual: commit.timeline_id,
                });
            }
            if commit.before_version != version {
                return Err(LogicalReplayError::JournalVersionMismatch {
                    expected: version,
                    actual: commit.before_version,
                });
            }
            validate_revision_advance(commit)?;
            validate_commit_events(
                commit,
                &visible_events,
                &mut event_cursor,
                &mut known_events,
            )?;
            apply_logical_commit(
                commit,
                &mut world_time,
                &mut chronology_budget,
                &mut works,
                &mut logical_order_high_water,
                &known_events,
                &initial,
            )?;
            version = commit.after_version;
            found_target = target == version;
        }

        if !found_target {
            return Err(LogicalReplayError::TargetVersionNotCommitted { target });
        }
        if event_cursor != visible_events.len() {
            let actual = visible_events[event_cursor..]
                .iter()
                .map(|event| event.id)
                .collect::<Vec<_>>();
            return Err(LogicalReplayError::EventJournalMismatch {
                version,
                expected: Vec::new(),
                actual,
            });
        }

        let replayed = ReplayEngine::replay(initial, &visible_events)
            .map_err(LogicalReplayError::MaterializedReplay)?;
        let materialization = replayed
            .into_materialization()
            .with_timeline_position(target, world_time);
        let mut works = works.into_values().collect::<Vec<_>>();
        works.sort_by_key(|work| {
            (
                work.effective_due_world_time,
                work.logical_schedule_order,
                work.work_id,
            )
        });

        Ok(HistoricalTimelineState {
            materialization,
            logical: TimelineLogicalState {
                timeline_id,
                version: target,
                world_time,
                works,
                chronology_budget: ChronologyBudgetState::new(world_time, chronology_budget),
            },
        })
    }
}

/// Reconstructs one exact `TimelineVersion` from the two Runtime-owned history
/// streams. This is the public convenience entry point for Replay/Fork and
/// historical query callers.
///
/// # Errors
///
/// Returns [`LogicalReplayError`] when the target is not a committed journal
/// boundary or either history stream is inconsistent.
pub fn replay_timeline(
    initial: BaseWorldSnapshot,
    events: &[CommittedEvent],
    journal: &[LogicalCommit],
    target: TimelineVersion,
) -> Result<HistoricalTimelineState, LogicalReplayError> {
    LogicalReplayEngine::replay(initial, events, journal, target)
}

fn validate_revision_advance(commit: &LogicalCommit) -> Result<(), LogicalReplayError> {
    let expected_revision = commit.before_version.state_revision.value().checked_add(1);
    let expected_head = commit.before_version.head_event_seq.value();
    if expected_revision != Some(commit.after_version.state_revision.value())
        || commit.after_version.head_event_seq.value() < expected_head
    {
        return Err(LogicalReplayError::InvalidRevisionAdvance {
            before: commit.before_version,
            after: commit.after_version,
        });
    }
    Ok(())
}

fn validate_commit_events(
    commit: &LogicalCommit,
    events: &[CommittedEvent],
    event_cursor: &mut usize,
    known_events: &mut HashSet<EventId>,
) -> Result<(), LogicalReplayError> {
    let before = commit.before_version.head_event_seq.value();
    let after = commit.after_version.head_event_seq.value();
    let event_count = after
        .checked_sub(before)
        .and_then(|count| usize::try_from(count).ok());
    let Some(event_count) = event_count else {
        return Err(LogicalReplayError::InvalidRevisionAdvance {
            before: commit.before_version,
            after: commit.after_version,
        });
    };
    if event_count != commit.event_ids.len() {
        return Err(LogicalReplayError::EventJournalMismatch {
            version: commit.after_version,
            expected: commit.event_ids.clone(),
            actual: Vec::new(),
        });
    }
    let mut actual_ids = Vec::with_capacity(event_count);
    for (offset, expected_id) in commit.event_ids.iter().enumerate() {
        let expected_seq = before
            .checked_add(u64::try_from(offset).unwrap_or(u64::MAX))
            .and_then(|value| value.checked_add(1))
            .map(EventSeq::new);
        let Some(expected_seq) = expected_seq else {
            return Err(LogicalReplayError::EventSequenceMismatch {
                version: commit.after_version,
                expected: EventSeq::new(u64::MAX),
                actual: EventSeq::new(u64::MAX),
            });
        };
        let Some(event) = events.get(*event_cursor + offset) else {
            return Err(LogicalReplayError::EventJournalMismatch {
                version: commit.after_version,
                expected: commit.event_ids.clone(),
                actual: actual_ids,
            });
        };
        if event.event_seq != expected_seq {
            return Err(LogicalReplayError::EventSequenceMismatch {
                version: commit.after_version,
                expected: expected_seq,
                actual: event.event_seq,
            });
        }
        actual_ids.push(event.id);
        if event.id != *expected_id || !known_events.insert(event.id) {
            return Err(LogicalReplayError::EventJournalMismatch {
                version: commit.after_version,
                expected: commit.event_ids.clone(),
                actual: actual_ids,
            });
        }
    }
    *event_cursor += event_count;
    Ok(())
}

#[expect(
    clippy::too_many_lines,
    reason = "one logical commit applies the journal's ordered semantic transition atomically"
)]
fn apply_logical_commit(
    commit: &LogicalCommit,
    world_time: &mut WorldInstant,
    chronology_budget: &mut u64,
    works: &mut BTreeMap<WorkId, LogicalWorkState>,
    logical_order_high_water: &mut u64,
    known_events: &HashSet<EventId>,
    initial: &BaseWorldSnapshot,
) -> Result<(), LogicalReplayError> {
    if commit.world_time.is_some() && commit.chronology_budget.is_some() {
        return Err(LogicalReplayError::InvalidLogicalCommit {
            version: commit.after_version,
            reason: LogicalCommitReplayError::TimeAndChronologyCombined,
        });
    }

    if let Some(transition) = commit.world_time {
        if transition.from != *world_time {
            return Err(LogicalReplayError::InvalidLogicalCommit {
                version: commit.after_version,
                reason: LogicalCommitReplayError::WorldTimeMismatch {
                    expected: *world_time,
                    actual: transition.from,
                },
            });
        }
        if transition.to <= transition.from {
            return Err(LogicalReplayError::InvalidLogicalCommit {
                version: commit.after_version,
                reason: LogicalCommitReplayError::NonMonotonicWorldTime {
                    from: transition.from,
                    to: transition.to,
                },
            });
        }
        if works.values().any(|work| {
            work.status == WorkStatus::Pending && work.effective_due_world_time <= *world_time
        }) {
            return Err(LogicalReplayError::InvalidLogicalCommit {
                version: commit.after_version,
                reason: LogicalCommitReplayError::DueWorkPending,
            });
        }
        *world_time = transition.to;
        *chronology_budget = 0;
    }

    let mut completion_count = 0;
    for transition in &commit.work_transitions {
        match transition {
            LogicalWorkTransition::Schedule {
                work_id,
                target,
                schema_revision,
                payload,
                effective_due_world_time,
                logical_schedule_order,
                causal_event_id,
                origin_work_id,
            } => {
                if works.contains_key(work_id) {
                    return invalid_work(commit, *work_id, LogicalWorkReplayError::DuplicateWork);
                }
                if *logical_schedule_order <= *logical_order_high_water {
                    return invalid_work(
                        commit,
                        *work_id,
                        LogicalWorkReplayError::InvalidScheduleOrder {
                            previous: *logical_order_high_water,
                            actual: *logical_schedule_order,
                        },
                    );
                }
                if let Some(event_id) = causal_event_id
                    && !known_events.contains(event_id)
                    && !initial.event_exists(*event_id)
                {
                    return invalid_work(
                        commit,
                        *work_id,
                        LogicalWorkReplayError::MissingCausalEvent {
                            event_id: *event_id,
                        },
                    );
                }
                if let Some(origin_work_id) = origin_work_id
                    && !works.contains_key(origin_work_id)
                {
                    return invalid_work(
                        commit,
                        *work_id,
                        LogicalWorkReplayError::MissingOriginWork {
                            work_id: *origin_work_id,
                        },
                    );
                }
                *logical_order_high_water = *logical_schedule_order;
                works.insert(
                    *work_id,
                    LogicalWorkState::from_schedule(
                        *work_id,
                        target.clone(),
                        *schema_revision,
                        payload.clone(),
                        *effective_due_world_time,
                        *logical_schedule_order,
                        *causal_event_id,
                        *origin_work_id,
                    ),
                );
            }
            LogicalWorkTransition::Cancel { work_id }
            | LogicalWorkTransition::Complete { work_id }
            | LogicalWorkTransition::Dead { work_id } => {
                let Some(work) = works.get_mut(work_id) else {
                    return invalid_work(commit, *work_id, LogicalWorkReplayError::WorkNotFound);
                };
                if work.status != WorkStatus::Pending {
                    return invalid_work(
                        commit,
                        *work_id,
                        LogicalWorkReplayError::NotPending {
                            status: work.status,
                        },
                    );
                }
                work.status = match transition {
                    LogicalWorkTransition::Cancel { .. } => WorkStatus::Cancelled,
                    LogicalWorkTransition::Complete { .. } => {
                        completion_count += 1;
                        WorkStatus::Completed
                    }
                    LogicalWorkTransition::Dead { .. } => WorkStatus::Dead,
                    LogicalWorkTransition::Schedule { .. } => unreachable!(),
                };
            }
        }
    }

    match (completion_count, commit.chronology_budget) {
        (0, None) => Ok(()),
        (1, Some(budget)) => {
            if budget.world_time != *world_time {
                return Err(LogicalReplayError::InvalidLogicalCommit {
                    version: commit.after_version,
                    reason: LogicalCommitReplayError::ChronologyWorldTimeMismatch {
                        expected: *world_time,
                        actual: budget.world_time,
                    },
                });
            }
            if budget.before != *chronology_budget {
                return Err(LogicalReplayError::InvalidLogicalCommit {
                    version: commit.after_version,
                    reason: LogicalCommitReplayError::ChronologyBeforeMismatch {
                        expected: *chronology_budget,
                        actual: budget.before,
                    },
                });
            }
            let expected_after = budget.before.checked_add(1);
            if expected_after != Some(budget.after) {
                return Err(LogicalReplayError::InvalidLogicalCommit {
                    version: commit.after_version,
                    reason: LogicalCommitReplayError::ChronologyAfterMismatch {
                        before: budget.before,
                        after: budget.after,
                    },
                });
            }
            *chronology_budget = budget.after;
            Ok(())
        }
        _ => Err(LogicalReplayError::InvalidLogicalCommit {
            version: commit.after_version,
            reason: LogicalCommitReplayError::ChronologyCompletionMismatch,
        }),
    }
}

fn invalid_work<T>(
    commit: &LogicalCommit,
    work_id: WorkId,
    reason: LogicalWorkReplayError,
) -> Result<T, LogicalReplayError> {
    Err(LogicalReplayError::InvalidWorkTransition {
        version: commit.after_version,
        work_id: Some(work_id),
        reason,
    })
}

#[cfg(test)]
mod tests {
    use loom_core::{
        EventId, EventSeq, EventTypeId, SchemaRevision, TimelineId, TimelineVersion, WorkHandlerId,
        WorkId, WorldId, WorldInstant,
    };
    use loom_protocol::{ProposedEvent, WorkTarget};
    use serde_json::json;
    use uuid::Uuid;

    use super::{
        LogicalCommitReplayError, LogicalReplayEngine, LogicalReplayError, LogicalWorkState,
    };
    use crate::{
        BaseWorldSnapshot, ChronologyBudgetConsumption, CommittedEvent, LogicalCommit,
        LogicalWorkTransition, TimelineSnapshot, WorkStatus, WorldTimeTransition,
    };

    fn id(value: u128) -> Uuid {
        Uuid::from_u128(value)
    }

    fn timeline() -> TimelineId {
        TimelineId::new(id(1))
    }

    fn initial() -> BaseWorldSnapshot {
        BaseWorldSnapshot::new(
            WorldId::new(id(2)),
            timeline(),
            TimelineVersion::default(),
            WorldInstant::new(0),
        )
    }

    fn event() -> CommittedEvent {
        let proposal = ProposedEvent::new(
            EventId::new(id(3)),
            EventTypeId::from("test.replayed"),
            SchemaRevision::new(1),
            json!({"event": true}),
        );
        CommittedEvent::from_proposed(
            timeline(),
            EventSeq::new(1),
            &proposal,
            WorldInstant::new(99),
        )
    }

    fn work() -> WorkId {
        WorkId::new(id(4))
    }

    fn target() -> WorkTarget {
        WorkTarget::CapabilityWork {
            owner: Some("test.owner".to_owned()),
            handler: WorkHandlerId::from("test.handler"),
        }
    }

    fn schedule_commit() -> LogicalCommit {
        LogicalCommit {
            timeline_id: timeline(),
            before_version: TimelineVersion::new(EventSeq::new(1), 1.into()),
            after_version: TimelineVersion::new(EventSeq::new(1), 2.into()),
            world_time: None,
            event_ids: Vec::new(),
            work_transitions: vec![LogicalWorkTransition::Schedule {
                work_id: work(),
                target: target(),
                schema_revision: SchemaRevision::new(1),
                payload: json!({"value": 7}),
                effective_due_world_time: WorldInstant::new(0),
                logical_schedule_order: 1,
                causal_event_id: Some(EventId::new(id(3))),
                origin_work_id: None,
            }],
            chronology_budget: None,
        }
    }

    fn history() -> (Vec<CommittedEvent>, Vec<LogicalCommit>) {
        let event_id = EventId::new(id(3));
        let events = vec![event()];
        let journal = vec![
            LogicalCommit {
                timeline_id: timeline(),
                before_version: TimelineVersion::default(),
                after_version: TimelineVersion::new(EventSeq::new(1), 1.into()),
                world_time: None,
                event_ids: vec![event_id],
                work_transitions: Vec::new(),
                chronology_budget: None,
            },
            schedule_commit(),
            LogicalCommit {
                timeline_id: timeline(),
                before_version: TimelineVersion::new(EventSeq::new(1), 2.into()),
                after_version: TimelineVersion::new(EventSeq::new(1), 3.into()),
                world_time: None,
                event_ids: Vec::new(),
                work_transitions: vec![LogicalWorkTransition::Complete { work_id: work() }],
                chronology_budget: Some(ChronologyBudgetConsumption {
                    world_time: WorldInstant::new(0),
                    before: 0,
                    after: 1,
                }),
            },
            LogicalCommit {
                timeline_id: timeline(),
                before_version: TimelineVersion::new(EventSeq::new(1), 3.into()),
                after_version: TimelineVersion::new(EventSeq::new(1), 4.into()),
                world_time: Some(WorldTimeTransition {
                    from: WorldInstant::new(0),
                    to: WorldInstant::new(10),
                }),
                event_ids: Vec::new(),
                work_transitions: Vec::new(),
                chronology_budget: None,
            },
        ];
        (events, journal)
    }

    #[test]
    fn reconstructs_initial_intervals_and_ignores_event_occurrence_time() {
        let (events, journal) = history();
        let pending = LogicalReplayEngine::replay(
            initial(),
            &events,
            &journal,
            TimelineVersion::new(EventSeq::new(1), 2.into()),
        )
        .expect("schedule boundary should replay");
        assert_eq!(pending.world_time(), WorldInstant::new(0));
        assert_eq!(pending.logical_state().works.len(), 1);
        assert_eq!(pending.logical_state().works[0].status, WorkStatus::Pending);
        assert_eq!(pending.logical_state().works[0].logical_schedule_order, 1);
        assert_eq!(pending.world_view().version().state_revision.value(), 2);
        assert!(pending.world_view().event_exists(EventId::new(id(3))));

        let completed = LogicalReplayEngine::replay(
            initial(),
            &events,
            &journal,
            TimelineVersion::new(EventSeq::new(1), 3.into()),
        )
        .expect("completion boundary should replay");
        assert_eq!(
            completed.logical_state().works[0].status,
            WorkStatus::Completed
        );
        assert_eq!(completed.logical_state().chronology_budget.consumed, 1);

        let advanced = LogicalReplayEngine::replay(
            initial(),
            &events,
            &journal,
            TimelineVersion::new(EventSeq::new(1), 4.into()),
        )
        .expect("time boundary should replay");
        assert_eq!(advanced.world_time(), WorldInstant::new(10));
        assert_eq!(advanced.logical_state().chronology_budget.consumed, 0);
        assert_eq!(
            advanced.logical_state().works[0].status,
            WorkStatus::Completed
        );
    }

    #[test]
    fn version_zero_is_addressable_and_technical_work_fields_are_not_needed() {
        let (events, journal) = history();
        let initial_state =
            LogicalReplayEngine::replay(initial(), &events, &journal, TimelineVersion::default())
                .expect("version zero should replay");
        assert!(initial_state.logical_state().works.is_empty());
        assert_eq!(initial_state.world_time(), WorldInstant::new(0));
        assert_eq!(
            initial_state.world_view().version(),
            TimelineVersion::default()
        );

        let logical_work = LogicalWorkState {
            work_id: work(),
            target: target(),
            schema_revision: SchemaRevision::new(1),
            payload: json!({"value": 7}),
            effective_due_world_time: WorldInstant::new(0),
            logical_schedule_order: 1,
            causal_event_id: Some(EventId::new(id(3))),
            origin_work_id: None,
            status: WorkStatus::Pending,
        };
        assert_eq!(logical_work.logical_schedule_order, 1);

        let current_snapshot = TimelineSnapshot::with_journal(
            BaseWorldSnapshot::new(
                WorldId::new(id(2)),
                timeline(),
                TimelineVersion::new(EventSeq::new(1), 4.into()),
                WorldInstant::new(10),
            ),
            events,
            Vec::new(),
            journal,
        );
        let from_snapshot = current_snapshot
            .replay_to(TimelineVersion::new(EventSeq::new(1), 2.into()))
            .expect("snapshot replay should not need operational Work rows");
        assert_eq!(from_snapshot.logical_state().works.len(), 1);
        assert_eq!(
            from_snapshot.logical_state().works[0].status,
            WorkStatus::Pending
        );
    }

    #[test]
    fn rejects_gapped_journal_and_invalid_budget_deterministically() {
        let (events, mut journal) = history();
        journal[1].before_version.state_revision = 9.into();
        let gap = LogicalReplayEngine::replay(
            initial(),
            &events,
            &journal,
            TimelineVersion::new(EventSeq::new(1), 2.into()),
        )
        .expect_err("journal gap must fail");
        assert!(matches!(
            gap,
            LogicalReplayError::JournalVersionMismatch { .. }
        ));

        let (events, mut journal) = history();
        journal[2].chronology_budget = Some(ChronologyBudgetConsumption {
            world_time: WorldInstant::new(0),
            before: 9,
            after: 10,
        });
        let budget = LogicalReplayEngine::replay(
            initial(),
            &events,
            &journal,
            TimelineVersion::new(EventSeq::new(1), 3.into()),
        )
        .expect_err("budget mismatch must fail");
        assert!(matches!(
            budget,
            LogicalReplayError::InvalidLogicalCommit {
                reason: LogicalCommitReplayError::ChronologyBeforeMismatch { .. },
                ..
            }
        ));
    }
}
