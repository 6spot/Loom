//! Runtime-owned execution provenance for candidate validation.

use loom_core::{EntityId, EventId, FacetOwner, FacetTypeId, RelationshipId};

/// One fact or negative lookup observed while validating a Resolution.
///
/// `ReadDependency` belongs to Runtime execution provenance. It records what
/// the current validation actually inspected; it is not a Capability-declared
/// dependency list, a commit authorization, or a fine-grained MVCC predicate.
/// The v0 commit correctness boundary remains the pinned `TimelineVersion`.
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum ReadDependency {
    /// An Entity existence lookup and whether the candidate contained it.
    Entity {
        /// Entity identity inspected by the Runtime view.
        entity_id: EntityId,
        /// Whether the lookup found the identity in candidate state.
        present: bool,
    },
    /// A Relationship existence/structure lookup and whether it was active.
    Relationship {
        /// Relationship identity inspected by the Runtime view.
        relationship_id: RelationshipId,
        /// Whether the lookup found an active Relationship.
        present: bool,
    },
    /// A Facet lookup, including the candidate schema revision when present.
    Facet {
        /// Structural owner of the Facet instance inspected.
        owner: FacetOwner,
        /// Capability-owned Facet semantic key inspected.
        facet_type: FacetTypeId,
        /// Schema revision observed, or `None` for a negative lookup.
        schema_revision: Option<loom_core::SchemaRevision>,
    },
    /// An Event ancestry lookup used by causal validation.
    Event {
        /// Event identity inspected in the pinned ancestry/batch prefix.
        event_id: EventId,
        /// Whether the Event was available before the current proposed Event.
        present: bool,
    },
}

/// The Runtime record of facts observed during one Resolution validation.
///
/// `ReadSet` is produced by Runtime-owned Base/Candidate views and is exposed
/// only as provenance. Capability code does not supply or edit it, and callers
/// must not mistake it for a permission grant or a replacement for Timeline
/// CAS. The entries preserve lookup order so diagnostics can explain how a
/// candidate result was reached.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct ReadSet {
    entries: Vec<ReadDependency>,
}

impl ReadSet {
    /// Returns the ordered observations made during validation.
    #[must_use]
    pub fn entries(&self) -> &[ReadDependency] {
        &self.entries
    }

    /// Returns the number of observations recorded so far.
    #[must_use]
    pub const fn len(&self) -> usize {
        self.entries.len()
    }

    /// Reports whether no world lookup has been observed.
    #[must_use]
    pub const fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    pub(crate) fn extend(&mut self, other: Self) {
        self.entries.extend(other.entries);
    }

    pub(crate) fn record(&mut self, dependency: ReadDependency) {
        self.entries.push(dependency);
    }
}
