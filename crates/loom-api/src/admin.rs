//! Isolated Runtime administration and Timeline-control contract.
//!
//! This module is intentionally separate from the ordinary World-facing
//! service traits.  It exposes only stable Loom values and operation-specific
//! requests; Runtime authority tokens, SQL rows, registry objects, provider
//! configuration and credentials cannot cross this boundary.

use std::{fmt, future::Future, pin::Pin};

use serde::{Deserialize, Serialize};

use crate::{
    ActionTypeId, ApiError, ApiResult, EventRef, ExecutionSessionId, FacetOwner, FacetTypeId,
    RelationshipId, SchemaRevision, StateRevision, TimelineTarget, TimelineVersion, WorkId,
    WorldId, WorldInstant,
};

/// Stable namespace used by HTTP clients for Runtime administration.
pub const ADMIN_API_PREFIX: &str = "/v1/admin";

/// Operation identity supplied to an external authorization hook.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub enum AdminOperation {
    /// Read the active Runtime Revision selection.
    ReadActiveRevision,
    /// List immutable Runtime Revision publications.
    ListRevisions,
    /// Read one immutable Runtime Revision publication.
    ReadRevision,
    /// Activate an already published compatible Runtime Revision.
    ActivateRevision,
    /// List durable execution Sessions.
    ListSessions,
    /// Read one durable execution Session and its safe provenance projection.
    ReadSession,
    /// Resolve a committed Event to its producing Session.
    SessionForEvent,
    /// Inspect a Timeline's logical state and chronology position.
    ReadTimelineLogicalStatus,
    /// Inspect a due Work head blocked on a missing implementation.
    ReadMissingImplementation,
    /// Apply a Runtime-owned Pending -> Dead/Cancelled logical transition.
    TerminalizeWork,
    /// Apply an explicit Runtime-owned World-Time logical transition.
    AdvanceWorldTime,
}

/// Stable Runtime Revision capability metadata safe for operator inspection.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AdminRuntimeRevisionCapability {
    /// Semantic Capability identity.
    pub capability_id: String,
    /// Non-secret implementation/build identity.
    pub implementation_id: String,
    /// Exact installed semantic version.
    pub version: String,
    /// Loom contract compatibility requirement.
    pub loom_compatibility: String,
}

/// Public projection of one immutable Runtime Revision publication.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AdminRuntimeRevision {
    /// Stable publication identity.
    pub revision_id: String,
    /// Operational publication timestamp, represented as a platform integer.
    pub published_at: i64,
    /// Non-secret core build/ref metadata.
    pub core_build_ref: String,
    /// Loom contract version.
    pub loom_version: String,
    /// Exact installed Capability metadata in deterministic order.
    pub capabilities: Vec<AdminRuntimeRevisionCapability>,
    /// Non-secret execution policy identifier, when published.
    pub execution_policy_id: Option<String>,
    /// Non-secret provider policy identifier, never provider credentials.
    pub provider_policy_id: Option<String>,
    /// Human-readable publication summary.
    pub change_summary: Option<String>,
    /// Whether future Sessions may have changed semantic behavior.
    pub semantic_behavior_changed: bool,
}

/// Active Runtime Revision pointer projected for admin consumers.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AdminRuntimeRevisionSelection {
    /// Immutable selected publication.
    pub revision: AdminRuntimeRevision,
    /// Generation used for activation CAS.
    pub generation: u64,
    /// Operational activation timestamp.
    pub activated_at: i64,
}

/// Runtime Revision lookup request.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AdminRuntimeRevisionRequest {
    /// Stable Runtime Revision identity.
    pub revision_id: String,
}

/// Revision activation request.  Runtime supplies the platform timestamp.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AdminActivateRuntimeRevisionRequest {
    /// Previously published Runtime Revision to activate.
    pub revision_id: String,
    /// Expected active-selection generation; `None` means no active pointer.
    pub expected_generation: Option<u64>,
}

/// Stable execution origin visible in Session provenance.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum AdminExecutionOrigin {
    /// Direct application/API request.
    Application,
    /// Durable external ingress request.
    Ingress,
    /// Explicitly operator-authorized execution.
    Operator,
    /// Runtime-owned execution such as Work or bootstrap.
    Runtime,
}

/// Stable execution lifecycle visible in Session inspection.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum AdminExecutionSessionStatus {
    /// Semantic execution is in flight.
    Started,
    /// Execution committed Runtime state.
    Committed,
    /// Execution completed without World/Work mutation.
    NoChange,
    /// Capability returned a normal semantic rejection.
    Rejected,
    /// Runtime or persistence rejected the execution technically.
    Failed,
    /// Execution remained blocked on an operational prerequisite.
    Blocked,
}

/// Safe root references attached to one execution Session.
#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub struct AdminExecutionRoot {
    /// Root semantic Action, when present.
    pub action: Option<ActionTypeId>,
    /// Target Durable Work identity, when present.
    pub target_work: Option<WorkId>,
    /// Current Work claim identity, when present.
    pub current_work: Option<WorkId>,
    /// Durable external input identity, when present.
    pub ingress: Option<String>,
    /// Immutable bootstrap provenance label, when present.
    pub bootstrap: Option<String>,
    /// Agency provenance label, when present.
    pub agency: Option<String>,
}

/// Safe projection of one Runtime-observed read dependency.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", content = "value")]
pub enum AdminReadDependency {
    /// Entity existence observation.
    Entity {
        entity_id: crate::EntityId,
        present: bool,
    },
    /// Relationship presence observation.
    Relationship {
        relationship_id: RelationshipId,
        present: bool,
    },
    /// Facet schema observation without the Facet value.
    Facet {
        owner: FacetOwner,
        facet_type: FacetTypeId,
        schema_revision: Option<SchemaRevision>,
    },
    /// Event ancestry observation.
    Event {
        event_id: crate::EventId,
        present: bool,
    },
    /// Semantic projection observation without provider/storage internals.
    Semantic {
        index_id: String,
        query_fingerprint: String,
        source_schema_revision: SchemaRevision,
        projection_revision: u64,
        model_revision: String,
        source_refs: Vec<EventRef>,
    },
}

/// Safe projection of Runtime-mediated subresolution provenance.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AdminResolutionCallEdge {
    /// Calling Capability identity.
    pub caller_capability: String,
    /// Calling semantic Action.
    pub caller_action: ActionTypeId,
    /// Target Capability identity.
    pub target_capability: String,
    /// Target semantic Action.
    pub target_action: ActionTypeId,
}

/// One bounded entropy observation with sample bytes intentionally omitted.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AdminEntropyObservation {
    /// Runtime observation order.
    pub ordinal: usize,
    /// Number of bytes requested from the controlled source.
    pub requested_bytes: usize,
}

/// Safe entropy provenance summary.  Random sample bytes are not an admin
/// response because they may be application-sensitive data.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AdminEntropyEvidence {
    /// Controlled source identity.
    pub source_id: String,
    /// Ordered request metadata, with sample bytes omitted.
    pub observations: Vec<AdminEntropyObservation>,
}

/// Safe projection of the authority proposal linkage retained by a Session.
/// Logical Work payloads are intentionally summarized rather than returned.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AdminCommitProvenance {
    /// Root Session identity.
    pub session_id: ExecutionSessionId,
    /// Durable Ingress identity owning the proposal.
    pub ingress_id: String,
    /// Deterministic proposal identity/fingerprint.
    pub proposal_identity: String,
    /// Expected Timeline version after authority commit, when known.
    pub expected_after_version: Option<TimelineVersion>,
    /// Event identities expected by the authority commit.
    pub expected_event_ids: Vec<crate::EventId>,
    /// Count of logical Work transitions, without exposing Work payloads.
    pub logical_work_transition_count: u64,
}

/// Public projection of one durable execution Session.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AdminExecutionSession {
    /// Durable Session identity.
    pub id: ExecutionSessionId,
    /// Root execution origin.
    pub origin: AdminExecutionOrigin,
    /// Pinned World and Timeline.
    pub target: TimelineTarget,
    /// Timeline version pinned by the Session.
    pub expected_version: TimelineVersion,
    /// World Time observed at Session start.
    pub world_time: WorldInstant,
    /// Pinned Runtime Revision identity.
    pub runtime_revision_id: String,
    /// Safe root provenance references.
    pub root: AdminExecutionRoot,
    /// Session start platform coordinate.
    pub started_at: i64,
    /// Terminal platform coordinate, when terminal.
    pub ended_at: Option<i64>,
    /// Lifecycle status.
    pub status: AdminExecutionSessionStatus,
    /// Explicit no-change marker.
    pub no_change: bool,
    /// Committed Event identities linked at the commit boundary.
    pub event_refs: Vec<EventRef>,
    /// Runtime-observed read dependencies.
    pub read_set: Vec<AdminReadDependency>,
    /// Runtime-mediated call graph edges.
    pub call_provenance: Vec<AdminResolutionCallEdge>,
    /// Safe entropy provenance summary.
    pub entropy_evidence: AdminEntropyEvidence,
    /// Safe authority proposal linkage, when present.
    pub commit_provenance: Option<AdminCommitProvenance>,
}

/// Session lookup by durable identity.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AdminExecutionSessionRequest {
    /// Session identity to inspect.
    pub session_id: ExecutionSessionId,
}

/// Durable mapping from a committed Event to its producing Session.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AdminEventSessionLookup {
    /// Event identity queried.
    pub event_ref: EventRef,
    /// Producing Session, when the Event has one.
    pub session_id: Option<ExecutionSessionId>,
}

/// Chronology-budget position at one Timeline World Time.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AdminChronologyBudget {
    /// World Time to which this consumption applies.
    pub world_time: WorldInstant,
    /// Successful Scheduler completions consumed at that instant.
    pub consumed: u64,
}

/// Public Work lifecycle values permitted by Runtime Control.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub enum AdminWorkStatus {
    /// Work remains eligible for execution.
    Pending,
    /// Runtime completed the Work.
    Completed,
    /// Runtime Control cancelled the Work.
    Cancelled,
    /// Runtime failure policy or control terminalized the Work.
    Dead,
}

/// Stable summary of one logical Work item in Timeline status.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AdminLogicalWorkStatus {
    /// Work identity.
    pub work_id: WorkId,
    /// Logical lifecycle status.
    pub status: AdminWorkStatus,
    /// Semantic due World Time.
    pub effective_due_world_time: WorldInstant,
    /// Timeline-local scheduling order.
    pub logical_schedule_order: u64,
}

/// Runtime logical status of one Timeline, with no SQL/storage projection.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AdminTimelineLogicalStatus {
    /// Addressed World and Timeline.
    pub target: TimelineTarget,
    /// Current Timeline CAS version.
    pub version: TimelineVersion,
    /// Current semantic World Time.
    pub world_time: WorldInstant,
    /// Reconstructable same-instant chronology position.
    pub chronology_budget: AdminChronologyBudget,
    /// Last logical state revision represented by the journal.
    pub logical_revision: StateRevision,
    /// Number of authoritative logical journal commits visible at this read.
    pub logical_commit_count: u64,
    /// Logical Work summaries in deterministic current-snapshot order.
    pub works: Vec<AdminLogicalWorkStatus>,
}

/// Due Work target that cannot be assembled by the active Runtime Revision.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AdminMissingImplementationBlock {
    /// World containing the blocked Timeline.
    pub world_id: WorldId,
    /// Blocked Timeline.
    pub timeline_id: crate::TimelineId,
    /// Due Work head.
    pub work_id: WorkId,
    /// Stable semantic requirement projection.
    pub semantic_requirement: serde_json::Value,
    /// Active Runtime Revision considered by the observation.
    pub active_runtime_revision: String,
    /// First observation platform coordinate, when available.
    pub first_observed_platform_time: Option<i64>,
    /// Last observation platform coordinate.
    pub last_observed_platform_time: i64,
}

/// Request for missing-implementation inspection.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AdminMissingImplementationRequest {
    /// World and Timeline to inspect.
    pub target: TimelineTarget,
    /// Due Work identity to inspect.
    pub work_id: WorkId,
}

/// Explicit Runtime Control terminal state.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub enum AdminTerminalWorkState {
    /// Permanently dead logical Work.
    Dead,
    /// Explicitly cancelled logical Work.
    Cancelled,
}

/// Request for Pending Work terminalization.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AdminTerminalizeWorkRequest {
    /// World and Timeline containing the Work.
    pub target: TimelineTarget,
    /// Pending Work identity.
    pub work_id: WorkId,
    /// Timeline CAS version expected by the operator.
    pub expected_version: TimelineVersion,
    /// Allowed terminal logical state.
    pub terminal_state: AdminTerminalWorkState,
}

/// Result of a successful logical Work terminalization.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AdminTerminalizeWorkResult {
    /// Addressed World and Timeline.
    pub target: TimelineTarget,
    /// Timeline version after the logical journal commit.
    pub version: TimelineVersion,
    /// State committed by Runtime Control.
    pub terminal_state: AdminTerminalWorkState,
}

/// Request for an explicit semantic World-Time transition.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AdminAdvanceWorldTimeRequest {
    /// World and Timeline to advance.
    pub target: TimelineTarget,
    /// Timeline CAS version expected by the operator.
    pub expected_version: TimelineVersion,
    /// Current World Time expected by the operator.
    pub current: WorldInstant,
    /// Strictly later World Time to commit.
    pub next: WorldInstant,
}

/// Result of a successful explicit World-Time logical transition.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AdminAdvanceWorldTimeResult {
    /// Addressed World and Timeline.
    pub target: TimelineTarget,
    /// World Time before the logical commit.
    pub from: WorldInstant,
    /// World Time after the logical commit.
    pub to: WorldInstant,
    /// Timeline version after the logical journal commit.
    pub version: TimelineVersion,
}

/// Executor-neutral future used by Admin service implementations.
pub type AdminFuture<'a, T> = Pin<Box<dyn Future<Output = ApiResult<T>> + 'a>>;

/// Separate Runtime/platform administration contract.
pub trait AdminService {
    /// Reads the active Runtime Revision pointer.
    fn active_runtime_revision(&self) -> AdminFuture<'_, Option<AdminRuntimeRevisionSelection>> {
        Box::pin(async {
            Err(ApiError::unavailable(
                "Admin Runtime Revision reads are not implemented",
            ))
        })
    }

    /// Lists immutable Runtime Revision publications.
    fn list_runtime_revisions(&self) -> AdminFuture<'_, Vec<AdminRuntimeRevision>> {
        Box::pin(async {
            Err(ApiError::unavailable(
                "Admin Runtime Revision reads are not implemented",
            ))
        })
    }

    /// Reads one immutable Runtime Revision publication.
    fn get_runtime_revision(
        &self,
        _request: AdminRuntimeRevisionRequest,
    ) -> AdminFuture<'_, AdminRuntimeRevision> {
        Box::pin(async {
            Err(ApiError::unavailable(
                "Admin Runtime Revision reads are not implemented",
            ))
        })
    }

    /// Activates a published Runtime Revision through Runtime's generation CAS.
    fn activate_runtime_revision(
        &self,
        _request: AdminActivateRuntimeRevisionRequest,
    ) -> AdminFuture<'_, AdminRuntimeRevisionSelection> {
        Box::pin(async {
            Err(ApiError::unavailable(
                "Admin Runtime Revision activation is not implemented",
            ))
        })
    }

    /// Lists durable execution Sessions.
    fn list_execution_sessions(&self) -> AdminFuture<'_, Vec<AdminExecutionSession>> {
        Box::pin(async {
            Err(ApiError::unavailable(
                "Admin Session reads are not implemented",
            ))
        })
    }

    /// Reads one durable execution Session.
    fn get_execution_session(
        &self,
        _request: AdminExecutionSessionRequest,
    ) -> AdminFuture<'_, AdminExecutionSession> {
        Box::pin(async {
            Err(ApiError::unavailable(
                "Admin Session reads are not implemented",
            ))
        })
    }

    /// Resolves one committed Event to its producing Session.
    fn session_for_event(&self, _event_ref: EventRef) -> AdminFuture<'_, AdminEventSessionLookup> {
        Box::pin(async {
            Err(ApiError::unavailable(
                "Admin Event-to-Session lookup is not implemented",
            ))
        })
    }

    /// Reads Timeline logical state, chronology position and Work status.
    fn timeline_logical_status(
        &self,
        _target: TimelineTarget,
    ) -> AdminFuture<'_, AdminTimelineLogicalStatus> {
        Box::pin(async {
            Err(ApiError::unavailable(
                "Admin Timeline logical reads are not implemented",
            ))
        })
    }

    /// Reads a due Work head blocked on a missing implementation.
    fn missing_implementation(
        &self,
        _request: AdminMissingImplementationRequest,
    ) -> AdminFuture<'_, Option<AdminMissingImplementationBlock>> {
        Box::pin(async {
            Err(ApiError::unavailable(
                "Admin liveness reads are not implemented",
            ))
        })
    }

    /// Terminalizes Pending Work through Runtime-owned logical CAS/journal.
    fn terminalize_work(
        &self,
        _request: AdminTerminalizeWorkRequest,
    ) -> AdminFuture<'_, AdminTerminalizeWorkResult> {
        Box::pin(async {
            Err(ApiError::unavailable(
                "Admin Work control is not implemented",
            ))
        })
    }

    /// Advances World Time through Runtime-owned quiescence/CAS/journal.
    fn advance_world_time(
        &self,
        _request: AdminAdvanceWorldTimeRequest,
    ) -> AdminFuture<'_, AdminAdvanceWorldTimeResult> {
        Box::pin(async {
            Err(ApiError::unavailable(
                "Admin World-Time control is not implemented",
            ))
        })
    }
}

/// Compatibility aliases for clients that use shorter domain names.
pub type RuntimeRevisionAdmin = AdminRuntimeRevision;
/// Compatibility alias for the Runtime Revision activation result.
pub type RuntimeRevisionActivationAdmin = AdminRuntimeRevisionSelection;

impl fmt::Display for AdminTerminalWorkState {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::Dead => "dead",
            Self::Cancelled => "cancelled",
        })
    }
}
