//! World time, ordering and Timeline version values.

use serde::{Deserialize, Serialize};

use crate::{EventRef, TimelineId};

/// Monotonic semantic time in a World Timeline.
///
/// `WorldInstant` is interpreted by the World/Capability contract and is
/// intentionally independent of UTC, a platform timestamp or the operating
/// system clock. Runtime supplies the clock boundary that chooses values.
/// Platform receipt/commit timestamps and retry backoff must not be represented
/// with this type. It is a value used by proposals and state, not a commit
/// authority token.
#[derive(
    Clone, Copy, Debug, Default, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize,
)]
#[serde(transparent)]
pub struct WorldInstant(i64);

impl WorldInstant {
    /// Creates a World semantic time coordinate.
    #[must_use]
    pub const fn new(value: i64) -> Self {
        Self(value)
    }

    /// Returns the underlying World time coordinate.
    #[must_use]
    pub const fn value(self) -> i64 {
        self.0
    }
}

impl From<i64> for WorldInstant {
    fn from(value: i64) -> Self {
        Self::new(value)
    }
}

impl From<WorldInstant> for i64 {
    fn from(value: WorldInstant) -> Self {
        value.value()
    }
}

/// A signed duration in World semantic time units.
///
/// The unit and calendar interpretation belong to the World contract. This
/// value is not a platform retry duration and cannot make a scheduled Work a
/// future fact by itself. Runtime/Capability code applies it only according to
/// an explicit World clock policy.
#[derive(
    Clone, Copy, Debug, Default, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize,
)]
#[serde(transparent)]
pub struct WorldDuration(i64);

impl WorldDuration {
    /// Creates a World semantic duration.
    #[must_use]
    pub const fn new(value: i64) -> Self {
        Self(value)
    }

    /// Returns the underlying World duration coordinate.
    #[must_use]
    pub const fn value(self) -> i64 {
        self.0
    }
}

impl From<i64> for WorldDuration {
    fn from(value: i64) -> Self {
        Self::new(value)
    }
}

impl From<WorldDuration> for i64 {
    fn from(value: WorldDuration) -> Self {
        value.value()
    }
}

/// Timeline-local authoritative ordering for committed Events.
///
/// `EventSeq` is allocated at the Timeline commit linearization point and is
/// contiguous within a Timeline commit stream. It is the source of World Event
/// ordering; `UUIDv7`/`EventId` ordering must not be used as a substitute. A
/// protocol proposal may carry an `EventId` before it has an `EventSeq`.
#[derive(
    Clone, Copy, Debug, Default, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize,
)]
#[serde(transparent)]
pub struct EventSeq(u64);

impl EventSeq {
    /// Creates an Event sequence value.
    #[must_use]
    pub const fn new(value: u64) -> Self {
        Self(value)
    }

    /// Returns the Timeline-local sequence number.
    #[must_use]
    pub const fn value(self) -> u64 {
        self.0
    }
}

impl From<u64> for EventSeq {
    fn from(value: u64) -> Self {
        Self::new(value)
    }
}

impl From<EventSeq> for u64 {
    fn from(value: EventSeq) -> Self {
        value.value()
    }
}

/// Revision of the materialized state observed on a Timeline.
///
/// Runtime advances `StateRevision` together with the authoritative Timeline
/// commit. It is distinct from Event ordering, schema metadata and platform
/// timestamps. A resolver must not treat a revision value as proof that its
/// proposal has committed.
#[derive(
    Clone, Copy, Debug, Default, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize,
)]
#[serde(transparent)]
pub struct StateRevision(u64);

impl StateRevision {
    /// Creates a state revision value.
    #[must_use]
    pub const fn new(value: u64) -> Self {
        Self(value)
    }

    /// Returns the state revision number.
    #[must_use]
    pub const fn value(self) -> u64 {
        self.0
    }
}

impl From<u64> for StateRevision {
    fn from(value: u64) -> Self {
        Self::new(value)
    }
}

impl From<StateRevision> for u64 {
    fn from(value: StateRevision) -> Self {
        value.value()
    }
}

/// The optimistic-concurrency version pinned by a Resolution.
///
/// `TimelineVersion` identifies the expected Timeline head at the start of a
/// resolution. Runtime must compare both `head_event_seq` and `state_revision`
/// at the short commit transaction's CAS boundary. A mismatch means the
/// proposal may be stale and must not be blindly persisted; it is not a domain
/// `Rejection`. This value is Runtime concurrency metadata, not World Truth and
/// not a replacement for the Timeline identity.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub struct TimelineVersion {
    /// Last committed Event sequence observed in the pinned Timeline snapshot.
    pub head_event_seq: EventSeq,
    /// Materialized-state revision observed in the same snapshot.
    pub state_revision: StateRevision,
}

impl TimelineVersion {
    /// Creates a Timeline compare-and-swap version from one consistent snapshot.
    #[must_use]
    pub const fn new(head_event_seq: EventSeq, state_revision: StateRevision) -> Self {
        Self {
            head_event_seq,
            state_revision,
        }
    }
}

/// Immutable ancestry position recorded for a Timeline fork.
///
/// Root Timelines have no parent. A child records the exact parent Timeline
/// and version at the atomic fork boundary; when the parent had an Event at
/// that boundary, the qualified Event reference is recorded as well. This is
/// structural Timeline metadata, not a duplicated Event or Session row.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub struct TimelineAncestry {
    /// Parent Timeline in the same World, when this Timeline is a fork.
    pub parent_timeline_id: Option<TimelineId>,
    /// Exact parent version observed at the fork linearization point.
    pub fork_parent_version: Option<TimelineVersion>,
    /// Last parent Event at the fork point, when one exists.
    pub fork_parent_event: Option<EventRef>,
}

impl TimelineAncestry {
    /// Returns root ancestry metadata.
    #[must_use]
    pub const fn root() -> Self {
        Self {
            parent_timeline_id: None,
            fork_parent_version: None,
            fork_parent_event: None,
        }
    }

    /// Creates ancestry metadata for one atomic head fork.
    #[must_use]
    pub const fn fork(
        parent_timeline_id: TimelineId,
        fork_parent_version: TimelineVersion,
        fork_parent_event: Option<EventRef>,
    ) -> Self {
        Self {
            parent_timeline_id: Some(parent_timeline_id),
            fork_parent_version: Some(fork_parent_version),
            fork_parent_event,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{EventSeq, StateRevision, TimelineVersion, WorldDuration, WorldInstant};

    #[test]
    fn time_and_version_values_preserve_semantics() {
        let instant = WorldInstant::new(42);
        let duration = WorldDuration::new(-3);
        let version = TimelineVersion::new(EventSeq::new(7), StateRevision::new(8));

        assert_eq!(instant.value(), 42);
        assert_eq!(duration.value(), -3);
        assert_eq!(version.head_event_seq.value(), 7);
        assert_eq!(version.state_revision.value(), 8);
        assert_ne!(
            version.head_event_seq.value(),
            version.state_revision.value()
        );
    }
}
