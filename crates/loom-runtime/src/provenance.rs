//! Runtime-owned execution provenance for candidate validation.

use loom_capability::{CapabilityId, EntropyRequest, EntropySample};
use loom_core::{ActionTypeId, EntityId, EventId, FacetOwner, FacetTypeId, RelationshipId};
use serde::{Deserialize, Serialize};

use crate::EntropySourceId;

/// One ordered Runtime-observed entropy request and returned sample.
///
/// This is execution provenance, not a World Event or a Capability-supplied
/// record. The ordinal makes ordering explicit for later durable M9 storage;
/// the vector order remains the in-memory observation order.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct EntropyObservation {
    /// Zero-based order in which Runtime accepted the request.
    pub ordinal: usize,
    /// Mediated request supplied by the resolver.
    pub request: EntropyRequest,
    /// Frozen value returned to the resolver.
    pub sample: EntropySample,
}

/// Ordered entropy provenance for one pinned Execution Session.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct EntropyEvidence {
    source_id: EntropySourceId,
    observations: Vec<EntropyObservation>,
}

impl EntropyEvidence {
    /// Creates empty evidence for the source pinned by an Execution Assembly.
    #[must_use]
    pub fn new(source_id: EntropySourceId) -> Self {
        Self {
            source_id,
            observations: Vec::new(),
        }
    }

    /// Returns the source identity captured with the evidence.
    #[must_use]
    pub const fn source_id(&self) -> &EntropySourceId {
        &self.source_id
    }

    /// Returns ordered request/sample observations.
    #[must_use]
    pub fn observations(&self) -> &[EntropyObservation] {
        &self.observations
    }

    /// Returns the number of accepted entropy requests.
    #[must_use]
    pub const fn len(&self) -> usize {
        self.observations.len()
    }

    /// Reports whether no entropy request has been accepted.
    #[must_use]
    pub const fn is_empty(&self) -> bool {
        self.observations.is_empty()
    }

    pub(crate) fn record(&mut self, request: EntropyRequest, sample: EntropySample) {
        self.observations.push(EntropyObservation {
            ordinal: self.observations.len(),
            request,
            sample,
        });
    }
}

impl Default for EntropyEvidence {
    fn default() -> Self {
        Self::new(EntropySourceId::from("unknown"))
    }
}

/// One Runtime-mediated edge in a root Resolution call graph.
///
/// A `ResolutionCallEdge` records that one resolver invoked another registered
/// Action during the same root execution. It belongs to Execution Provenance,
/// not World Truth: it must never be translated into a
/// `loom_protocol::CausalLink`, Event participant, Work origin or other World
/// Event association. Runtime creates these edges after Action input and
/// dependency authorization pass; Capability code cannot forge or edit them.
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct ResolutionCallEdge {
    /// Capability that owned the resolver making the subresolution request.
    pub caller_capability: CapabilityId,
    /// Action frame active at the call site.
    pub caller_action: ActionTypeId,
    /// Capability that owns the routed child Action.
    pub target_capability: CapabilityId,
    /// Registered child Action selected by the request.
    pub target_action: ActionTypeId,
}

/// Ordered Runtime provenance for subresolution calls in one root execution.
///
/// The edge list is independent from the flattened Resolution and the World
/// Event causal graph. It is observable through a Runtime-owned
/// `ValidatedResolution` for tests and operator diagnostics, while it is not a
/// public Loom API payload or a Capability-provided authorization record.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct CallProvenance {
    edges: Vec<ResolutionCallEdge>,
}

impl CallProvenance {
    /// Returns call edges in the order Runtime observed them.
    #[must_use]
    pub fn edges(&self) -> &[ResolutionCallEdge] {
        &self.edges
    }

    /// Returns the number of observed subresolution edges.
    #[must_use]
    pub const fn len(&self) -> usize {
        self.edges.len()
    }

    /// Reports whether no subresolution edge was observed.
    #[must_use]
    pub const fn is_empty(&self) -> bool {
        self.edges.is_empty()
    }

    pub(crate) fn record(&mut self, edge: ResolutionCallEdge) {
        self.edges.push(edge);
    }
}

/// One fact or negative lookup observed while validating a Resolution.
///
/// `ReadDependency` belongs to Runtime execution provenance. It records what
/// the current validation actually inspected; it is not a Capability-declared
/// dependency list, a commit authorization, or a fine-grained MVCC predicate.
/// The v0 commit correctness boundary remains the pinned `TimelineVersion`.
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum ReadDependency {
    /// A pinned-base Entity existence lookup and whether it was present.
    Entity {
        /// Entity identity inspected by the Runtime view.
        entity_id: EntityId,
        /// Whether the lookup found the identity in the pinned base state.
        present: bool,
    },
    /// A pinned-base Relationship lookup and whether it was active.
    Relationship {
        /// Relationship identity inspected by the Runtime view.
        relationship_id: RelationshipId,
        /// Whether the pinned base contained an active Relationship.
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
/// CAS. The entries preserve first-observation order and are deduplicated so
/// diagnostics can explain how a candidate result was reached.
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
        for dependency in other.entries {
            self.record(dependency);
        }
    }

    pub(crate) fn record(&mut self, dependency: ReadDependency) {
        if !self.entries.contains(&dependency) {
            self.entries.push(dependency);
        }
    }
}
