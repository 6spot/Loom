//! Strong identity and semantic-key value types owned by Loom Core.

use std::{convert::Infallible, fmt, str::FromStr};

use serde::{Deserialize, Serialize};
use uuid::Uuid;

macro_rules! uuid_id {
    ($(#[$meta:meta])* $name:ident) => {
        $(#[$meta])*
        #[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
        #[serde(transparent)]
        pub struct $name(Uuid);

        impl $name {
            /// Creates this identity from an already allocated UUID.
            ///
            /// Allocation belongs to the Runtime/application boundary. Core
            /// intentionally does not choose a clock or entropy source while
            /// constructing a world identity.
            #[must_use]
            pub const fn new(value: Uuid) -> Self {
                Self(value)
            }

            /// Creates this identity from an already allocated UUID.
            ///
            /// This named constructor makes the allocation boundary explicit
            /// when a caller is converting a technical identifier into a Loom
            /// identity.
            #[must_use]
            pub const fn from_uuid(value: Uuid) -> Self {
                Self::new(value)
            }

            /// Returns the underlying UUID for storage or interoperability.
            ///
            /// The returned UUID remains a technical representation; callers
            /// must not use UUID ordering as World event ordering.
            #[must_use]
            pub const fn as_uuid(&self) -> &Uuid {
                &self.0
            }

            /// Returns the underlying UUID by value.
            ///
            /// This does not transfer Runtime authority or make the identity
            /// interchangeable with another Core identity type.
            #[must_use]
            pub const fn into_uuid(self) -> Uuid {
                self.0
            }

            /// Reports whether this identity contains the nil UUID.
            ///
            /// Core does not decide whether a nil value is valid in a specific
            /// persistence or registration context; that check belongs to the
            /// boundary that owns the relevant invariant.
            #[must_use]
            pub const fn is_nil(&self) -> bool {
                self.0.is_nil()
            }
        }

        impl From<Uuid> for $name {
            fn from(value: Uuid) -> Self {
                Self::new(value)
            }
        }

        impl From<$name> for Uuid {
            fn from(value: $name) -> Self {
                value.into_uuid()
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                self.0.fmt(formatter)
            }
        }

        impl FromStr for $name {
            type Err = uuid::Error;

            fn from_str(value: &str) -> Result<Self, Self::Err> {
                value.parse().map(Self::new)
            }
        }
    };
}

uuid_id! {
    /// Stable identity of a long-lived Loom World.
    ///
    /// `WorldId` is World structure and is owned by Core. It identifies the
    /// world boundary across Timelines; it is not a Timeline revision, request
    /// identifier or mutable state key. Runtime/application code allocates it,
    /// while Core only carries and compares it. Persisted World identity is
    /// never silently reused, and UUID ordering is not World history ordering.
    ///
    /// Unlike `TimelineId`, this value remains the same for every branch of a
    /// World. It must not be used as an Event sequence or as a domain semantic
    /// key.
    WorldId
}

uuid_id! {
    /// Stable identity of one authoritative history branch within a World.
    ///
    /// `TimelineId` belongs to Core World structure and is interpreted by
    /// Runtime/storage when selecting a Timeline. It identifies the branch,
    /// not its current version; `TimelineVersion` carries the version used by
    /// a read/commit compare-and-swap. A fork gets a new Timeline identity,
    /// while retaining the same `WorldId`.
    ///
    /// This value may scope state, Events and Durable Work, but it does not
    /// itself authorize a commit or replace `EventSeq` ordering.
    TimelineId
}

uuid_id! {
    /// Stable identity of a World Entity.
    ///
    /// Core owns the identity mechanism; mutable, Timeline-local meaning is
    /// represented by Facets and committed Effects rather than fields on this
    /// identifier. Runtime and storage use it for references and integrity
    /// checks. It is not a domain type such as person, company or account.
    ///
    /// Unlike `RelationshipId`, this value identifies one Entity and cannot be
    /// used to address a Relationship or Facet owner of that kind.
    EntityId
}

uuid_id! {
    /// Stable identity of a structural Relationship in a World.
    ///
    /// Core owns the identity and participant-structure mechanism. A
    /// Relationship may be N-ary and has a fixed participant set after
    /// creation; mutable domain meaning belongs in Relationship Facets.
    /// Runtime validates references before commit. This is not a relationship
    /// type key and not a pair of Entity IDs.
    RelationshipId
}

uuid_id! {
    /// Technical identity of a proposed or committed Event.
    ///
    /// The protocol may carry an `EventId` before commit, but the value is not
    /// World Truth until Runtime commits the associated `ProposedEvent`.
    /// Timeline-local authoritative order is supplied by `EventSeq`, never by
    /// UUID ordering. This value must not be used as a Work or Session ID.
    EventId
}

uuid_id! {
    /// Stable identity of one Durable Work obligation.
    ///
    /// Work identity belongs to the Core/Runtime future-execution mechanism.
    /// It remains distinct from an Event and from a claim lease. Forking a
    /// Timeline gives inherited pending work a branch-local Work identity;
    /// technical retries reuse the same Work identity.
    WorkId
}

uuid_id! {
    /// Identity of one Runtime execution session and its provenance record.
    ///
    /// The session is Runtime metadata about processing, not World Truth and
    /// not an Event/Work identity. Runtime creates and persists it according to
    /// its execution lifecycle; Protocol values may refer to it only through a
    /// Runtime-owned provenance boundary, not by embedding authority here.
    ExecutionSessionId
}

macro_rules! semantic_id {
    ($(#[$meta:meta])* $name:ident) => {
        $(#[$meta])*
        #[derive(Clone, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
        #[serde(transparent)]
        pub struct $name(String);

        impl $name {
            /// Creates a semantic identifier from its stable key.
            ///
            /// Ownership and uniqueness of the key are validated by the
            /// Capability registry. Core preserves the key without assigning
            /// domain meaning or normalizing it.
            #[must_use]
            pub fn new(value: impl Into<String>) -> Self {
                Self(value.into())
            }

            /// Returns the stable semantic key without transferring ownership.
            #[must_use]
            pub fn as_str(&self) -> &str {
                &self.0
            }

            /// Returns the owned semantic key.
            #[must_use]
            pub fn into_string(self) -> String {
                self.0
            }
        }

        impl From<String> for $name {
            fn from(value: String) -> Self {
                Self::new(value)
            }
        }

        impl From<&str> for $name {
            fn from(value: &str) -> Self {
                Self::new(value)
            }
        }

        impl From<$name> for String {
            fn from(value: $name) -> Self {
                value.into_string()
            }
        }

        impl FromStr for $name {
            type Err = Infallible;

            fn from_str(value: &str) -> Result<Self, Self::Err> {
                Ok(Self::new(value))
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str(&self.0)
            }
        }
    };
}

semantic_id! {
    /// Stable key naming a Capability-owned Facet schema.
    ///
    /// The key is software/Capability metadata, not a Facet instance and not
    /// Timeline state. Exactly one registered Capability owns each key. It
    /// must not be used where an Event, Action or Relationship type is needed.
    FacetTypeId
}

semantic_id! {
    /// Stable key naming a Capability-owned Relationship schema.
    ///
    /// This identifies semantic structure, while `RelationshipId` identifies
    /// one World relationship instance. Registry ownership and schema
    /// compatibility are checked outside Core.
    RelationshipTypeId
}

semantic_id! {
    /// Stable key naming a Capability-owned Event schema.
    ///
    /// The key describes Event meaning before or after a proposal is handled;
    /// it does not make a `ProposedEvent` committed World Truth and does not
    /// replace its `EventId`.
    EventTypeId
}

semantic_id! {
    /// Stable key naming a Capability-owned Action resolver.
    ///
    /// This is the semantic operation selected by an `ActionInvocation`. It
    /// is not an HTTP route, a public service method or a Runtime authority
    /// handle.
    ActionTypeId
}

semantic_id! {
    /// Stable key naming a Capability-owned Durable Work handler.
    ///
    /// The key routes future execution to a registered handler; it is not a
    /// Work identity, claim lease or autonomous background process.
    WorkHandlerId
}

/// Monotonic revision of a Capability-owned schema/value contract.
///
/// `SchemaRevision` is software metadata used to interpret and validate a
/// serialized Facet, Event payload or Work payload. It is not a Timeline
/// `StateRevision`, Event ordering primitive or Runtime revision. The owning
/// Capability defines compatibility and Runtime validates it at its boundary.
#[derive(
    Clone, Copy, Debug, Default, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize,
)]
#[serde(transparent)]
pub struct SchemaRevision(u32);

impl SchemaRevision {
    /// Creates a schema revision value.
    #[must_use]
    pub const fn new(value: u32) -> Self {
        Self(value)
    }

    /// Returns the numeric schema revision.
    #[must_use]
    pub const fn value(self) -> u32 {
        self.0
    }
}

impl fmt::Display for SchemaRevision {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl From<u32> for SchemaRevision {
    fn from(value: u32) -> Self {
        Self::new(value)
    }
}

impl From<SchemaRevision> for u32 {
    fn from(value: SchemaRevision) -> Self {
        value.value()
    }
}

#[cfg(test)]
mod tests {
    use super::{ActionTypeId, EntityId, EventId, WorldId};
    use uuid::Uuid;

    #[test]
    fn identity_newtypes_round_trip_without_becoming_interchangeable() {
        let uuid = Uuid::from_u128(1);
        let world = WorldId::new(uuid);
        let entity = EntityId::new(uuid);
        let event = EventId::new(uuid);

        assert_eq!(world.as_uuid(), &uuid);
        assert_eq!(entity.into_uuid(), uuid);
        assert_eq!(event.to_string(), uuid.to_string());

        let action = ActionTypeId::from("counter.increment");
        assert_eq!(action.as_str(), "counter.increment");
    }
}
