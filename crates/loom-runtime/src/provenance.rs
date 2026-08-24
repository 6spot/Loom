//! Runtime-owned execution provenance for candidate validation.

use loom_agency::{
    AgentRef, CognitiveError, CognitiveMetadata, ContextBudgetUsage, ExecutionPolicy,
};
use loom_capability::{CapabilityId, EntropyRequest, EntropySample, SemanticIndexId};
use loom_core::{
    ActionTypeId, EntityId, EventId, EventRef, FacetOwner, FacetTypeId, RelationshipId,
    SchemaRevision, TimelineId, TimelineVersion, WorldInstant,
};
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
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
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
#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
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

/// The result classification retained for one `CognitiveExecutor` invocation.
///
/// The decision variants are intentionally not copied into World History. An
/// `Act` is still an untrusted `ActionInvocation` proposal and must pass the
/// normal Runtime Action authority; a cognitive error is technical execution
/// failure, not the determined `NoAction` result.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum CognitiveOutcome {
    /// Cognition produced an Action proposal for normal Runtime validation.
    Act,
    /// Cognition determined that this wake should take no Action.
    NoAction,
    /// Cognition could not determine a decision.
    Error(CognitiveError),
}

/// How Runtime accounted for one cognition observation.
///
/// A fresh observation is the result of an executor call. A reused observation
/// records an explicitly configured deterministic decision that was checked
/// against a new pinned context. A discarded observation records cognition
/// that lost the Timeline CAS and therefore did not become logical truth.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub enum CognitiveDisposition {
    /// The executor was invoked for the pinned context.
    #[default]
    Fresh,
    /// A deterministic decision was reused under a fresh pinned context.
    Reused,
    /// The observation lost the logical commit race and was discarded.
    Discarded,
}

/// One ordered, audit-safe `CognitiveExecutor` observation.
///
/// This value records the pinned Agency request coordinate, policy, metadata,
/// context budget usage and the Runtime-mediated context `ReadSet`. It contains
/// no provider client, credentials, raw network payload or mutation authority.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CognitiveObservation {
    /// Zero-based invocation order within one root Execution Session.
    pub ordinal: usize,
    /// Pinned executor/provider/model identity.
    pub metadata: CognitiveMetadata,
    /// Pinned Agency execution policy.
    pub policy: ExecutionPolicy,
    /// Agent whose subjective context was supplied.
    pub agent: AgentRef,
    /// Timeline represented by the subjective context.
    pub timeline_id: TimelineId,
    /// Exact Timeline version represented by the subjective context.
    pub version: TimelineVersion,
    /// World semantic time represented by the subjective context.
    pub world_time: WorldInstant,
    /// Measured context consumption supplied to cognition.
    pub context_usage: ContextBudgetUsage,
    /// Runtime reads used to assemble the subjective context.
    pub context_read_set: ReadSet,
    /// Typed result classification returned by the executor.
    pub outcome: CognitiveOutcome,
    /// Explicit accounting of whether this cognition became reusable truth.
    #[serde(default)]
    pub disposition: CognitiveDisposition,
}

/// Ordered `CognitiveExecutor` provenance for one pinned Execution Session.
#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub struct CognitiveEvidence {
    observations: Vec<CognitiveObservation>,
}

impl CognitiveEvidence {
    /// Returns observations in the order Runtime invoked cognition.
    #[must_use]
    pub fn observations(&self) -> &[CognitiveObservation] {
        &self.observations
    }

    /// Returns the number of recorded cognitive invocations.
    #[must_use]
    pub const fn len(&self) -> usize {
        self.observations.len()
    }

    /// Reports whether no cognitive invocation has been recorded.
    #[must_use]
    pub const fn is_empty(&self) -> bool {
        self.observations.is_empty()
    }

    /// Returns the number of executor samples recorded for this Session.
    #[must_use]
    pub fn fresh_count(&self) -> usize {
        self.observations
            .iter()
            .filter(|observation| observation.disposition == CognitiveDisposition::Fresh)
            .count()
    }

    /// Returns the number of explicitly reused decisions recorded for this
    /// Session.
    #[must_use]
    pub fn reused_count(&self) -> usize {
        self.observations
            .iter()
            .filter(|observation| observation.disposition == CognitiveDisposition::Reused)
            .count()
    }

    /// Returns the number of cognition observations discarded after a CAS
    /// conflict.
    #[must_use]
    pub fn discarded_count(&self) -> usize {
        self.observations
            .iter()
            .filter(|observation| observation.disposition == CognitiveDisposition::Discarded)
            .count()
    }

    /// Returns the measured context bytes charged to all observations.
    #[must_use]
    pub fn context_bytes(&self) -> u64 {
        self.observations
            .iter()
            .map(|observation| observation.context_usage.bytes)
            .sum()
    }

    /// Returns the measured context entries charged to all observations.
    #[must_use]
    pub fn context_entries(&self) -> u64 {
        self.observations
            .iter()
            .map(|observation| u64::from(observation.context_usage.entries))
            .sum()
    }

    /// Marks the most recent cognition observation as discarded. Runtime calls
    /// this only after a Timeline CAS conflict proves the result did not become
    /// logical truth.
    pub(crate) fn mark_last_discarded(&mut self) {
        if let Some(observation) = self.observations.last_mut() {
            observation.disposition = CognitiveDisposition::Discarded;
        }
    }

    pub(crate) fn record(&mut self, mut observation: CognitiveObservation) {
        observation.ordinal = self.observations.len();
        self.observations.push(observation);
    }

    fn append(&mut self, additional: &Self) {
        for observation in &additional.observations {
            self.record(observation.clone());
        }
    }
}

/// One fact or negative lookup observed while validating a Resolution.
///
/// `ReadDependency` belongs to Runtime execution provenance. It records what
/// the current validation actually inspected; it is not a Capability-declared
/// dependency list, a commit authorization, or a fine-grained MVCC predicate.
/// The v0 commit correctness boundary remains the pinned `TimelineVersion`.
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
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
    /// One Runtime-mediated semantic projection read and its ordered sources.
    Semantic {
        /// Capability-owned semantic index identity.
        index_id: SemanticIndexId,
        /// Stable normalized query fingerprint.
        query_fingerprint: String,
        /// Canonical normalized query specification.
        query_spec: String,
        /// Source schema revision accepted at the read boundary.
        source_schema_revision: SchemaRevision,
        /// Projection revision observed by the adapter snapshot.
        projection_revision: u64,
        /// Model revision observed by the adapter snapshot.
        model_revision: String,
        /// Returned source references in exact result order.
        source_refs: Vec<EventRef>,
    },
}

/// The Runtime record of facts observed during one Resolution validation.
///
/// `ReadSet` is produced by Runtime-owned Base/Candidate views and is exposed
/// only as provenance. Capability code does not supply or edit it, and callers
/// must not mistake it for a permission grant or a replacement for Timeline
/// CAS. The entries preserve first-observation order and are deduplicated so
/// diagnostics can explain how a candidate result was reached.
#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub struct ReadSet {
    entries: Vec<ReadDependency>,
}

/// Complete Runtime-observed evidence produced by one root execution.
///
/// The three ordered collections are Runtime-owned observations. They are
/// deliberately separate from World Events and from Capability input: a
/// persistence adapter serializes the supplied values but does not inspect a
/// Capability implementation to infer provenance. Evidence can be appended
/// in root/child order while preserving deterministic `ReadSet` de-duplication,
/// call-edge order and entropy ordinals.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ExecutionEvidence {
    /// Point, Facet, Relationship, Event and semantic projection reads.
    pub read_set: ReadSet,
    /// Runtime-mediated subresolution edges.
    pub call_provenance: CallProvenance,
    /// Runtime-mediated entropy requests and returned samples.
    pub entropy_evidence: EntropyEvidence,
    /// Runtime-mediated cognition/provider/model and context evidence.
    #[serde(default)]
    pub cognitive_evidence: CognitiveEvidence,
    /// Explicit Runtime outcome marker for a successful no-change execution.
    /// Rejections remain semantically distinct and do not set this marker.
    #[serde(default)]
    pub no_change: bool,
}

impl ExecutionEvidence {
    /// Creates empty evidence for a pinned entropy source.
    #[must_use]
    pub fn new(source_id: EntropySourceId) -> Self {
        Self {
            read_set: ReadSet::default(),
            call_provenance: CallProvenance::default(),
            entropy_evidence: EntropyEvidence::new(source_id),
            cognitive_evidence: CognitiveEvidence::default(),
            no_change: false,
        }
    }

    /// Creates evidence from one Runtime execution state.
    #[must_use]
    pub fn from_parts(
        read_set: ReadSet,
        call_provenance: CallProvenance,
        entropy_evidence: EntropyEvidence,
    ) -> Self {
        Self {
            read_set,
            call_provenance,
            entropy_evidence,
            cognitive_evidence: CognitiveEvidence::default(),
            no_change: false,
        }
    }

    /// Attaches ordered cognition evidence to this Runtime execution record.
    #[must_use]
    pub fn with_cognitive_evidence(mut self, cognitive_evidence: CognitiveEvidence) -> Self {
        self.cognitive_evidence = cognitive_evidence;
        self
    }

    /// Marks this evidence as a successful execution with no World/Work
    /// mutation while retaining its normal Runtime observations.
    #[must_use]
    pub const fn with_no_change(mut self, no_change: bool) -> Self {
        self.no_change = no_change;
        self
    }

    /// Reports whether no Runtime observation was retained.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.read_set.is_empty()
            && self.call_provenance.is_empty()
            && self.entropy_evidence.is_empty()
            && self.cognitive_evidence.is_empty()
    }

    /// Appends another root/child execution's observations in execution order.
    pub fn append(&mut self, additional: &Self) {
        self.no_change |= additional.no_change;
        self.read_set.extend(additional.read_set.clone());
        for edge in additional.call_provenance.edges() {
            self.call_provenance.record(edge.clone());
        }
        let mut entropy = EntropyEvidence::new(self.entropy_evidence.source_id().clone());
        for observation in self
            .entropy_evidence
            .observations()
            .iter()
            .chain(additional.entropy_evidence.observations())
        {
            entropy.record(observation.request.clone(), observation.sample.clone());
        }
        self.entropy_evidence = entropy;
        self.cognitive_evidence
            .append(&additional.cognitive_evidence);
    }
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
