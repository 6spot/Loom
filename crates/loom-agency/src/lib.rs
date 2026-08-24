//! Loom Agency: agent-local perception, context and decision extension contracts.
//!
//! # Responsibility
//!
//! This crate defines the boundary between a persistent Agent identity and any
//! cognitive executor used to choose an attempted action. It owns `AgentWorldView`
//! composition contracts, context selection, decision contracts and
//! cognitive-executor SPI. LLMs, rules, humans or hybrid executors are
//! implementations of cognition; none of them define Agent identity.
//!
//! # Knowledge boundary
//!
//! Agency never receives the authoritative `BaseWorldView` directly. Agent input
//! must be constructed from observation, information, knowledge, memory,
//! visibility and context-budget rules so subjective knowledge cannot collapse
//! into omniscient World Truth.
//!
//! # Protocol and dependency boundary
//!
//! Cognition ultimately returns a `Decision`: attempt one `ActionInvocation` or
//! take no action. `ActionInvocation` belongs to `loom-protocol`, allowing Agency
//! to express its decision without depending on `loom-runtime`.
//!
//! ```text
//! loom-agency -> loom-core
//! loom-agency -> loom-protocol
//! loom-agency -X-> loom-runtime
//! ```
//!
//! Concrete Cognitive Provider adapters depend on this Agency SPI and are wired
//! by an Application composition root. This crate must not embed a vendor SDK,
//! network client or Runtime implementation merely because cognition will later
//! be executed by Runtime.
//!
//! # Output boundary
//!
//! Cognitive execution cannot emit committed Events, World Effects,
//! `Resolution` or `ValidatedResolution`. Long-lived goals/desires belong to
//! Capability-owned state rather than a generic Runtime `Intent` object.
//!
//! > Cognition decides what to attempt; Capability decides what that attempt
//! > means; Runtime decides what becomes reality.
//!
//! # Public exposure
//!
//! Agency is an engine extension contract, not an external Loom API. GPUI/HTTP/
//! CLI/SDK consumers use `loom-api`; they do not import Agency internals to invoke
//! cognition directly as a public engine surface.
//!
//! # Core distinction
//!
//! `World Truth`, `Information Space` and `Agent Knowledge` are separate domains.
//! Agency explains what an Agent can perceive/recall/consider and what it chooses
//! to attempt; Capability/Runtime explain what that attempt actually means and
//! whether it becomes reality.
//!
//! # Documentation contract
//!
//! Every public Agency abstraction must document whether it represents
//! perception, knowledge, context, cognition or decision; what authoritative
//! information it is intentionally prevented from seeing; and how it hands off
//! through Protocol to the execution engine. See
//! `docs/architecture/runtime-contracts.md` and
//! `docs/architecture/governance.md`.

#![forbid(unsafe_code)]

use std::{error::Error, fmt, future::Future, pin::Pin};

use loom_core::{EntityId, TimelineId, TimelineVersion, WorldInstant};
use loom_protocol::ActionInvocation;
use serde::{Deserialize, Serialize};
use serde_json::Value;

/// The Core Entity identity used by an Agent.
///
/// Agency does not create a second Agent identity hierarchy. An Agent is an
/// Entity that has the relevant Actor/Agent role and Capability-owned state;
/// this alias keeps that fact visible at Agency call sites without changing
/// the underlying Core identity or granting any authority.
pub type AgentId = EntityId;

/// A role-bearing reference to the Entity acting as an Agent.
///
/// `AgentRef` is a reference value, not a new Core object or an authorization
/// token. Runtime and the World Binding determine whether the referenced
/// Entity may act as an Agent for a particular wake. The reference carries no
/// storage handle, mutable state, visibility grant or commit authority.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub struct AgentRef {
    /// Core identity of the Entity taking the Agent role.
    pub entity_id: EntityId,
}

impl AgentRef {
    /// Creates an Agent reference over an existing Core Entity identity.
    #[must_use]
    pub const fn new(entity_id: EntityId) -> Self {
        Self { entity_id }
    }

    /// Returns the referenced Core Entity identity.
    #[must_use]
    pub const fn entity_id(self) -> EntityId {
        self.entity_id
    }
}

/// The kind of semantic source from which one context entry was selected.
///
/// These labels describe provenance of an already-filtered value; they do not
/// grant the executor access to the corresponding Capability state. Runtime
/// and Capability semantics decide whether a source is visible before an entry
/// crosses into Agency.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub enum ContextSource {
    /// A direct, Runtime-mediated observation selected for this Agent.
    Observation,
    /// Information made available to the Agent by Capability semantics.
    Information,
    /// Knowledge eligible for this Agent under the relevant World policy.
    Knowledge,
    /// Agent-local or Capability-owned memory selected under the context budget.
    Memory,
}

/// One bounded, visibility-checked value included in an Agent context.
///
/// The JSON value is an opaque context value, not a Core state patch or a
/// Runtime command. A context builder must only place values here after
/// applying World Binding, visibility and budget rules. The key and source are
/// provenance labels; neither lets a `CognitiveExecutor` query World state.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct AgentContextEntry {
    /// Semantic key assigned by the Capability or context producer.
    pub key: String,
    /// Provenance category of the selected context value.
    pub source: ContextSource,
    /// Already-filtered value presented to cognition.
    pub value: Value,
}

impl AgentContextEntry {
    /// Creates one context entry from a semantic key and filtered value.
    #[must_use]
    pub fn new(key: impl Into<String>, source: ContextSource, value: Value) -> Self {
        Self {
            key: key.into(),
            source,
            value,
        }
    }
}

/// The finite resource envelope used when selecting Agent context.
///
/// This is a logical budget, not a platform timeout and not a provider quota.
/// Runtime owns enforcement and provenance of consumption; Agency carries the
/// contract without choosing an executor, provider or worker topology.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(default)]
pub struct ContextBudget {
    /// Maximum number of entries that may cross into one context snapshot.
    pub max_entries: u32,
    /// Maximum serialized context bytes permitted by the host policy.
    pub max_bytes: u64,
    /// Maximum number of Runtime-mediated Entity reads used by one context.
    pub max_entities: u32,
    /// Maximum number of Runtime-mediated Relationship reads used by one context.
    pub max_relationships: u32,
    /// Maximum number of Runtime-mediated Event reads used by one context.
    pub max_events: u32,
    /// Maximum number of semantic retrieval hits used by one context.
    pub max_semantic_results: u32,
    /// Maximum semantic traversal depth permitted in one context.
    pub max_depth: u32,
    /// Maximum number of semantic retrieval requests used by one context.
    pub max_semantic_queries: u32,
}

impl ContextBudget {
    /// Creates a context budget from entry and byte limits.
    #[must_use]
    pub const fn new(max_entries: u32, max_bytes: u64) -> Self {
        Self {
            max_entries,
            max_bytes,
            max_entities: max_entries,
            max_relationships: max_entries,
            max_events: max_entries,
            max_semantic_results: max_entries,
            max_depth: 8,
            max_semantic_queries: max_entries,
        }
    }

    /// Sets the maximum number of Entity reads for one context.
    #[must_use]
    pub const fn with_max_entities(mut self, limit: u32) -> Self {
        self.max_entities = limit;
        self
    }

    /// Sets the maximum number of Relationship reads for one context.
    #[must_use]
    pub const fn with_max_relationships(mut self, limit: u32) -> Self {
        self.max_relationships = limit;
        self
    }

    /// Sets the maximum number of Event reads for one context.
    #[must_use]
    pub const fn with_max_events(mut self, limit: u32) -> Self {
        self.max_events = limit;
        self
    }

    /// Sets the maximum number of semantic hits for one context.
    #[must_use]
    pub const fn with_max_semantic_results(mut self, limit: u32) -> Self {
        self.max_semantic_results = limit;
        self
    }

    /// Sets the maximum semantic traversal depth for one context.
    #[must_use]
    pub const fn with_max_depth(mut self, limit: u32) -> Self {
        self.max_depth = limit;
        self
    }

    /// Sets the maximum number of semantic queries for one context.
    #[must_use]
    pub const fn with_max_semantic_queries(mut self, limit: u32) -> Self {
        self.max_semantic_queries = limit;
        self
    }
}

impl Default for ContextBudget {
    fn default() -> Self {
        Self::new(128, 64 * 1024)
    }
}

/// Measured logical context consumption reported with a snapshot.
///
/// Usage is evidence about the selected subjective context, not an authority
/// to exceed the corresponding [`ContextBudget`]. Runtime may reject or trim a
/// snapshot that violates its pinned policy before cognition begins.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(default)]
pub struct ContextBudgetUsage {
    /// Number of entries selected into the snapshot.
    pub entries: u32,
    /// Serialized bytes charged to the snapshot by the host policy.
    pub bytes: u64,
    /// Number of Entity reads used by the snapshot.
    pub entities: u32,
    /// Number of Relationship reads used by the snapshot.
    pub relationships: u32,
    /// Number of Event reads used by the snapshot.
    pub events: u32,
    /// Number of semantic hits used by the snapshot.
    pub semantic_results: u32,
    /// Maximum semantic traversal depth used by the snapshot.
    pub depth: u32,
    /// Number of semantic queries used by the snapshot.
    pub semantic_queries: u32,
}

impl ContextBudgetUsage {
    /// Creates a measured context usage value.
    #[must_use]
    pub const fn new(entries: u32, bytes: u64) -> Self {
        Self {
            entries,
            bytes,
            entities: 0,
            relationships: 0,
            events: 0,
            semantic_results: 0,
            depth: 0,
            semantic_queries: 0,
        }
    }

    /// Creates measured usage including Runtime read dimensions.
    #[must_use]
    #[expect(
        clippy::too_many_arguments,
        reason = "the usage dimensions mirror the frozen context budget contract"
    )]
    pub const fn with_reads(
        entries: u32,
        bytes: u64,
        entities: u32,
        relationships: u32,
        events: u32,
        semantic_results: u32,
        depth: u32,
        semantic_queries: u32,
    ) -> Self {
        Self {
            entries,
            bytes,
            entities,
            relationships,
            events,
            semantic_results,
            depth,
            semantic_queries,
        }
    }
}

/// A context-builder request for one pinned Agent wake.
///
/// The request identifies the Agent and the exact read coordinate for which a
/// subjective context is needed. It is not a `BaseWorldView`, a storage query,
/// or a visibility grant. Runtime remains responsible for mediating the reads
/// and ensuring all returned values belong to the requested `TimelineVersion`.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AgentContextRequest {
    /// Entity whose Agent-local context is being assembled.
    pub agent: AgentRef,
    /// Timeline whose pinned logical state is being considered.
    pub timeline_id: TimelineId,
    /// Exact Timeline version used for all context reads.
    pub version: TimelineVersion,
    /// World semantic time visible at the pinned version.
    pub world_time: WorldInstant,
    /// Maximum context selection budget for this request.
    pub budget: ContextBudget,
}

impl AgentContextRequest {
    /// Creates a request tied to one pinned Timeline coordinate.
    #[must_use]
    pub const fn new(
        agent: AgentRef,
        timeline_id: TimelineId,
        version: TimelineVersion,
        world_time: WorldInstant,
        budget: ContextBudget,
    ) -> Self {
        Self {
            agent,
            timeline_id,
            version,
            world_time,
            budget,
        }
    }
}

/// The selected, bounded subjective context crossing from a context builder
/// into an [`AgentWorldView`].
///
/// A snapshot contains only values already filtered for the Agent. It is not a
/// full World snapshot and has no query methods, storage reference, Event
/// mutation, or commit capability. Capability semantics own the meaning of
/// each entry; Agency owns only this composition shape.
#[derive(Clone, Debug, Default, Deserialize, PartialEq, Serialize)]
pub struct AgentContextSnapshot {
    /// Visibility-checked context entries in host-selected order.
    pub entries: Vec<AgentContextEntry>,
    /// Logical budget usage charged to the selected entries.
    pub usage: ContextBudgetUsage,
}

impl AgentContextSnapshot {
    /// Creates a snapshot with measured usage.
    #[must_use]
    pub fn new(entries: Vec<AgentContextEntry>, usage: ContextBudgetUsage) -> Self {
        Self { entries, usage }
    }

    /// Returns whether the subjective context contains no selected entries.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
}

/// Compatibility name for the selected Agent context value.
///
/// This is an alias, not a second context model. The snapshot remains the
/// bounded, provenance-labelled value supplied by Runtime/application code.
pub type AgentContext = AgentContextSnapshot;

/// The subjective Agent view supplied to cognition for one pinned wake.
///
/// `AgentWorldView` is intentionally not `loom-runtime::BaseWorldView`: it
/// contains a finite, visibility-limited context and no authoritative World
/// query boundary. The pinned coordinates make it possible for Runtime to
/// prove that all selected values came from one logical read position, while
/// the context prevents an executor from seeing unrestricted World Truth.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct AgentWorldView {
    /// Agent reference for which this subjective view was assembled.
    pub agent: AgentRef,
    /// Timeline represented by the selected context.
    pub timeline_id: TimelineId,
    /// Exact Timeline version represented by every selected context value.
    pub version: TimelineVersion,
    /// World semantic time represented by the selected context.
    pub world_time: WorldInstant,
    /// Visibility-checked and budgeted subjective context.
    pub context: AgentContextSnapshot,
}

impl AgentWorldView {
    /// Creates a subjective view at one pinned Timeline coordinate.
    #[must_use]
    pub const fn new(
        agent: AgentRef,
        timeline_id: TimelineId,
        version: TimelineVersion,
        world_time: WorldInstant,
        context: AgentContextSnapshot,
    ) -> Self {
        Self {
            agent,
            timeline_id,
            version,
            world_time,
            context,
        }
    }
}

/// The policy for a cognition result that loses the Timeline CAS boundary.
///
/// `Resample` is the v0 default. Reuse is an explicit deterministic policy,
/// and any reused decision must still be revalidated against a fresh pinned
/// context, Binding and normal Action authority. Neither variant makes a
/// cognition result a commit token.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub enum DecisionReusePolicy {
    /// Discard the stale result and execute cognition again under fresh input.
    #[default]
    Resample,
    /// Permit reuse only when the host has explicitly configured deterministic
    /// reuse and records that choice in execution provenance.
    ReuseDeterministic,
}

/// Runtime-selected policy values pinned for one cognitive execution.
///
/// The policy is configuration/provenance data, not a Scheduler, timeout,
/// provider client or commit authority. Runtime owns interpretation of retry,
/// lease, Binding and CAS outcomes; Agency exposes only the values needed to
/// keep those choices explicit at the cognition boundary.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ExecutionPolicy {
    /// Stable semantic identifier of the policy configuration.
    pub policy_id: String,
    /// Revision of the policy pinned for this execution.
    pub revision: String,
    /// Context budget applied before the executor is called.
    pub context_budget: ContextBudget,
    /// Explicit result handling policy after a Timeline CAS loss.
    pub decision_reuse: DecisionReusePolicy,
}

impl ExecutionPolicy {
    /// Creates an execution policy with explicit identity, revision and budget.
    #[must_use]
    pub fn new(
        policy_id: impl Into<String>,
        revision: impl Into<String>,
        context_budget: ContextBudget,
    ) -> Self {
        Self {
            policy_id: policy_id.into(),
            revision: revision.into(),
            context_budget,
            decision_reuse: DecisionReusePolicy::default(),
        }
    }

    /// Selects explicit decision reuse behavior for CAS conflicts.
    #[must_use]
    pub const fn with_decision_reuse(mut self, policy: DecisionReusePolicy) -> Self {
        self.decision_reuse = policy;
        self
    }
}

impl Default for ExecutionPolicy {
    fn default() -> Self {
        Self::new("default", "1", ContextBudget::default())
    }
}

/// Non-secret identity and revision of a cognitive executor implementation.
///
/// These fields are audit labels only. They must never contain credentials,
/// bearer tokens, raw provider configuration, prompts, model input or model
/// output. The concrete executor remains outside the Agency crate.
#[derive(Clone, Debug, Default, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub struct ExecutorMetadata {
    /// Stable non-secret implementation identifier.
    pub id: String,
    /// Non-secret implementation revision or compatibility label.
    pub revision: String,
}

impl ExecutorMetadata {
    /// Creates non-secret executor metadata.
    #[must_use]
    pub fn new(id: impl Into<String>, revision: impl Into<String>) -> Self {
        Self {
            id: id.into(),
            revision: revision.into(),
        }
    }
}

/// Non-secret provider identity and revision retained for execution evidence.
///
/// This value has no endpoint, credential, request header, raw configuration or
/// client handle. Provider adapters may attach it to [`CognitiveMetadata`].
#[derive(Clone, Debug, Default, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub struct ProviderMetadata {
    /// Stable non-secret provider identifier.
    pub id: String,
    /// Non-secret provider adapter or policy revision.
    pub revision: String,
}

impl ProviderMetadata {
    /// Creates non-secret provider metadata.
    #[must_use]
    pub fn new(id: impl Into<String>, revision: impl Into<String>) -> Self {
        Self {
            id: id.into(),
            revision: revision.into(),
        }
    }
}

/// Non-secret model identity and revision retained for execution evidence.
///
/// Model metadata is descriptive provenance, not a model client or a promise
/// that the model can access World state. Inputs, outputs and secrets are kept
/// outside this contract unless a separate Runtime provenance policy explicitly
/// hashes or retains them.
#[derive(Clone, Debug, Default, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub struct ModelMetadata {
    /// Stable non-secret model identifier.
    pub id: String,
    /// Non-secret model revision or deployment label.
    pub revision: String,
}

impl ModelMetadata {
    /// Creates non-secret model metadata.
    #[must_use]
    pub fn new(id: impl Into<String>, revision: impl Into<String>) -> Self {
        Self {
            id: id.into(),
            revision: revision.into(),
        }
    }
}

/// Audit-safe metadata for one cognitive execution implementation.
///
/// The metadata is provenance-ready but deliberately incomplete as a provider
/// configuration: it identifies selected executor/provider/model revisions and
/// carries no secret or transport object. Runtime/application composition owns
/// the actual implementation and records this value with the Session evidence.
#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub struct CognitiveMetadata {
    /// Selected executor implementation metadata.
    pub executor: ExecutorMetadata,
    /// Selected provider metadata, when the executor uses one.
    pub provider: Option<ProviderMetadata>,
    /// Selected model metadata, when the executor uses one.
    pub model: Option<ModelMetadata>,
}

impl CognitiveMetadata {
    /// Creates metadata for an executor without provider/model assumptions.
    #[must_use]
    pub fn new(executor: ExecutorMetadata) -> Self {
        Self {
            executor,
            provider: None,
            model: None,
        }
    }

    /// Attaches non-secret provider metadata.
    #[must_use]
    pub fn with_provider(mut self, provider: ProviderMetadata) -> Self {
        self.provider = Some(provider);
        self
    }

    /// Attaches non-secret model metadata.
    #[must_use]
    pub fn with_model(mut self, model: ModelMetadata) -> Self {
        self.model = Some(model);
        self
    }
}

/// The only semantic result that cognition may return.
///
/// `Act` contains an untrusted Protocol `ActionInvocation`; it does not
/// contain an Event, Effect, Resolution, `ValidatedResolution` or commit token.
/// Runtime must send the invocation through normal Action ownership, Binding,
/// schema, resolution and validation authority. `NoAction` is a determined
/// cognitive result; Runtime decides how the current Wake is completed.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub enum Decision {
    /// Attempt one normal Capability-owned Action through Runtime authority.
    Act(ActionInvocation),
    /// Take no Action for this wake.
    NoAction,
}

impl Decision {
    /// Creates an Action decision from an untrusted Protocol invocation.
    #[must_use]
    pub const fn act(invocation: ActionInvocation) -> Self {
        Self::Act(invocation)
    }

    /// Creates a no-action decision.
    #[must_use]
    pub const fn no_action() -> Self {
        Self::NoAction
    }
}

/// A cognition failure that prevents a `Decision` from being determined.
///
/// These are technical/execution failures, distinct from `Decision::NoAction`
/// and from semantic rejection of an `Act` by the normal Runtime Action path.
/// Error text is boundary-safe and must not contain credentials, raw provider
/// payloads or unrestricted World data.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum CognitiveError {
    /// No compatible cognitive implementation is available for the pinned run.
    Unavailable {
        /// Boundary-safe explanation suitable for execution evidence.
        reason: String,
    },
    /// The selected executor/provider failed technically.
    Failed {
        /// Boundary-safe explanation suitable for bounded failure policy.
        reason: String,
    },
    /// The host cancelled cognition before a decision was produced.
    Cancelled,
    /// The pinned Agency execution budget was exhausted.
    BudgetExceeded {
        /// Logical budget dimension that was exhausted.
        resource: String,
    },
}

impl CognitiveError {
    /// Creates an unavailable-executor error.
    #[must_use]
    pub fn unavailable(reason: impl Into<String>) -> Self {
        Self::Unavailable {
            reason: reason.into(),
        }
    }

    /// Creates a technical executor failure.
    #[must_use]
    pub fn failed(reason: impl Into<String>) -> Self {
        Self::Failed {
            reason: reason.into(),
        }
    }

    /// Creates a budget-exhaustion failure.
    #[must_use]
    pub fn budget_exceeded(resource: impl Into<String>) -> Self {
        Self::BudgetExceeded {
            resource: resource.into(),
        }
    }
}

impl fmt::Display for CognitiveError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Unavailable { reason } => {
                write!(formatter, "cognitive executor unavailable: {reason}")
            }
            Self::Failed { reason } => write!(formatter, "cognitive execution failed: {reason}"),
            Self::Cancelled => formatter.write_str("cognitive execution cancelled"),
            Self::BudgetExceeded { resource } => {
                write!(formatter, "cognitive execution budget exceeded: {resource}")
            }
        }
    }
}

impl Error for CognitiveError {}

/// The input presented to one cognitive executor invocation.
///
/// A request contains only Agency-owned subjective values and a pinned policy.
/// It deliberately has no `BaseWorldView`, Runtime, Storage, network, provider
/// or commit handle. The Agent view is immutable by convention and any `Act`
/// returned from it remains an untrusted proposal until Runtime validates it.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct CognitiveRequest {
    /// Subjective, visibility-limited view assembled for this invocation.
    pub view: AgentWorldView,
    /// Execution policy pinned for this invocation.
    pub policy: ExecutionPolicy,
}

impl CognitiveRequest {
    /// Creates a cognitive request from a subjective view and pinned policy.
    #[must_use]
    pub const fn new(view: AgentWorldView, policy: ExecutionPolicy) -> Self {
        Self { view, policy }
    }

    /// Returns the Agent reference carried by the subjective view.
    #[must_use]
    pub const fn agent(&self) -> AgentRef {
        self.view.agent
    }
}

/// Result returned by a [`CognitiveExecutor`].
pub type CognitiveResult = Result<Decision, CognitiveError>;

/// Executor-neutral asynchronous result channel for cognition.
///
/// The boxed Future uses only the standard library. It does not select Tokio,
/// an executor, a thread model, `Send`/`Sync` topology or a provider SDK for
/// the host. Runtime/application code chooses how to poll it.
pub type CognitiveFuture<'a> = Pin<Box<dyn Future<Output = CognitiveResult> + 'a>>;

/// Object-safe SPI implemented by rule, policy, behavior-tree, model, human or
/// hybrid cognitive executors.
///
/// Implementations receive only a [`CognitiveRequest`] and may return only a
/// [`Decision`] or [`CognitiveError`]. They cannot emit World Events/Effects,
/// Protocol `Resolution`, Runtime `ValidatedResolution`, Scheduler commands or
/// commit authority through this trait. Provider adapters and concrete async
/// runtimes live outside `loom-agency`.
pub trait CognitiveExecutor {
    /// Returns non-secret implementation/provider/model metadata for evidence.
    ///
    /// The default is an explicit unknown label so small deterministic fakes
    /// can implement the SPI without inventing provider metadata. Production
    /// composition should override it with stable identifiers and revisions.
    fn metadata(&self) -> CognitiveMetadata {
        CognitiveMetadata::new(ExecutorMetadata::new("unspecified", "unspecified"))
    }

    /// Runs cognition against the immutable, subjective request.
    fn execute<'a>(&'a self, request: &'a CognitiveRequest) -> CognitiveFuture<'a>;
}

#[cfg(test)]
mod tests {
    use super::{
        AgentContextEntry, AgentContextSnapshot, AgentRef, AgentWorldView, CognitiveExecutor,
        CognitiveFuture, CognitiveMetadata, CognitiveRequest, ContextBudgetUsage, ContextSource,
        Decision, ExecutionPolicy, ExecutorMetadata,
    };
    use loom_core::{ActionTypeId, EventSeq, StateRevision, TimelineVersion, WorldInstant};
    use loom_protocol::ActionInvocation;
    use serde_json::json;

    struct NoopExecutor;

    impl CognitiveExecutor for NoopExecutor {
        fn metadata(&self) -> CognitiveMetadata {
            CognitiveMetadata::new(ExecutorMetadata::new("test.noop", "1"))
        }

        fn execute<'a>(&'a self, _request: &'a CognitiveRequest) -> CognitiveFuture<'a> {
            Box::pin(async { Ok(Decision::NoAction) })
        }
    }

    #[test]
    fn subjective_view_and_decision_are_protocol_values() {
        let entity_id = "00000000-0000-0000-0000-000000000001"
            .parse()
            .expect("valid EntityId");
        let view = AgentWorldView::new(
            AgentRef::new(entity_id),
            "00000000-0000-0000-0000-000000000002"
                .parse()
                .expect("valid TimelineId"),
            TimelineVersion::new(EventSeq::new(3), StateRevision::new(4)),
            WorldInstant::new(9),
            AgentContextSnapshot::new(
                vec![AgentContextEntry::new(
                    "visible.balance",
                    ContextSource::Observation,
                    json!({"value": 7}),
                )],
                ContextBudgetUsage::new(1, 17),
            ),
        );
        let request = CognitiveRequest::new(view, ExecutionPolicy::default());
        let decision = Decision::act(ActionInvocation::new(
            ActionTypeId::from("trade.execute"),
            json!({"quantity": 1}),
        ));
        let encoded = serde_json::to_string(&decision).expect("Decision serializes");
        let decoded: Decision = serde_json::from_str(&encoded).expect("Decision decodes");

        assert_eq!(decoded, decision);
        assert_eq!(request.agent().entity_id(), entity_id);
        assert_eq!(request.view.context.entries.len(), 1);
    }

    #[test]
    fn executor_spi_is_object_safe_and_decision_only() {
        let executor: &dyn CognitiveExecutor = &NoopExecutor;
        assert_eq!(executor.metadata().executor.id, "test.noop");
    }
}
