//! Runtime-owned persistence ports and the read models exchanged with adapters.
//!
//! The traits in this module are the narrow dependency-inversion boundary for
//! World reads, Timeline commits and Durable Work operations. They describe
//! authority and concurrency semantics without selecting a database or a
//! locking implementation. In particular, a commit accepts only the private
//! Runtime authority token [`ValidatedResolution`]; the protocol
//! [`loom_protocol::Resolution`] never crosses this boundary.

use std::{
    collections::BTreeMap,
    fmt,
    future::Future,
    pin::Pin,
    sync::{
        Arc,
        atomic::{AtomicI64, Ordering},
    },
};

use loom_capability::{CapabilityId, CapabilityManifest};
use loom_core::{
    AssociationRole, EntityId, EventId, EventSeq, ExecutionSessionId, RelationshipId,
    SchemaRevision, StateRevision, TimelineId, TimelineVersion, WorkId, WorldEffect, WorldId,
    WorldInstant,
};
use loom_protocol::{NewWork, ProposedEvent, WorkSchedule, WorkTarget};
use semver::{Version, VersionReq};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::{
    BaseWorldSnapshot, BaseWorldView, EntropyEvidence, EntropySourceId, ResolutionBudget,
    ValidatedResolution,
};

/// Executor-neutral future returned by Runtime persistence I/O ports.
///
/// Persistence adapters may use `SQLx` or another asynchronous driver without
/// choosing an executor for Runtime. Capability code never receives this type:
/// resolvers operate on the already-pinned in-memory `BaseWorldView`.
pub type PersistenceFuture<'a, T> = Pin<Box<dyn Future<Output = T> + 'a>>;

/// Immutable semantic execution contract owned by one World.
///
/// The binding is Runtime metadata, not a Capability registry snapshot and not
/// a permanent implementation pin. Its requirements identify the semantic
/// Capability domains a World permits and the compatible software ranges that
/// may satisfy those domains in a later Execution Session. The configuration
/// is intentionally opaque to Storage and remains World-level, immutable
/// assembly data rather than evolving semantic state.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct WorldRuntimeBinding {
    requirements: BTreeMap<CapabilityId, VersionReq>,
    configuration: Value,
    revision: u64,
    template_provenance: Option<String>,
}

impl WorldRuntimeBinding {
    /// Creates one immutable World-level binding descriptor.
    ///
    /// Capability requirements are stored in deterministic key order. If the
    /// input contains a duplicate Capability ID, the last value wins while the
    /// resulting descriptor still contains exactly one semantic owner entry.
    /// Callers should construct requirements from a validated registry or
    /// template plan rather than relying on duplicate replacement.
    #[must_use]
    pub fn new<I>(
        requirements: I,
        configuration: Value,
        revision: u64,
        template_provenance: Option<String>,
    ) -> Self
    where
        I: IntoIterator<Item = (CapabilityId, VersionReq)>,
    {
        Self {
            requirements: requirements.into_iter().collect(),
            configuration,
            revision,
            template_provenance,
        }
    }

    /// Returns the semantic Capability compatibility requirements.
    #[must_use]
    pub fn requirements(&self) -> &BTreeMap<CapabilityId, VersionReq> {
        &self.requirements
    }

    /// Returns the requirement for one semantic Capability, if this World
    /// permits that Capability domain.
    #[must_use]
    pub fn requirement(&self, capability: &CapabilityId) -> Option<&VersionReq> {
        self.requirements.get(capability)
    }

    /// Reports whether the binding permits the supplied Capability version.
    #[must_use]
    pub fn allows(&self, capability: &CapabilityId, version: &semver::Version) -> bool {
        self.requirement(capability)
            .is_some_and(|requirement| requirement.matches(version))
    }

    /// Returns immutable World-level assembly configuration.
    #[must_use]
    pub const fn configuration(&self) -> &Value {
        &self.configuration
    }

    /// Returns the immutable binding revision.
    #[must_use]
    pub const fn revision(&self) -> u64 {
        self.revision
    }

    /// Returns Template/birth provenance, when the source is known.
    #[must_use]
    pub fn template_provenance(&self) -> Option<&str> {
        self.template_provenance.as_deref()
    }
}

/// Typed failures from the World Runtime Binding persistence boundary.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum BindingError {
    /// The requested World identity is not present in persistence.
    WorldNotFound { world_id: WorldId },
    /// A pre-binding legacy World has not yet gone through explicit migration.
    BindingNotFound { world_id: WorldId },
    /// A binding already exists; v0 never overwrites it.
    BindingAlreadyExists { world_id: WorldId },
    /// The persistence authority could not complete the binding operation.
    StorageUnavailable { message: String },
}

impl fmt::Display for BindingError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::WorldNotFound { world_id } => write!(formatter, "World {world_id} not found"),
            Self::BindingNotFound { world_id } => {
                write!(formatter, "World Runtime Binding for {world_id} not found")
            }
            Self::BindingAlreadyExists { world_id } => {
                write!(
                    formatter,
                    "World Runtime Binding for {world_id} already exists"
                )
            }
            Self::StorageUnavailable { message } => formatter.write_str(message),
        }
    }
}

impl std::error::Error for BindingError {}

/// An explicit platform-time coordinate used for leases and technical retry.
///
/// `PlatformTime` is operational metadata. It is deliberately distinct from
/// [`WorldInstant`], which is semantic time in a World Timeline. A retry
/// backoff or lease deadline must not advance World Time or become a World
/// Event merely because platform time moved forward.
#[derive(
    Clone, Copy, Debug, Default, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize,
)]
pub struct PlatformTime(i64);

impl PlatformTime {
    /// Creates a platform-time coordinate supplied by the caller/adapter.
    #[must_use]
    pub const fn new(value: i64) -> Self {
        Self(value)
    }

    /// Returns the underlying platform-time coordinate.
    #[must_use]
    pub const fn value(self) -> i64 {
        self.0
    }
}

impl From<i64> for PlatformTime {
    fn from(value: i64) -> Self {
        Self::new(value)
    }
}

impl From<PlatformTime> for i64 {
    fn from(value: PlatformTime) -> Self {
        value.value()
    }
}

impl fmt::Display for PlatformTime {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

/// Runtime policy for bounded automatic technical Work failure handling.
///
/// The attempt limit and backoff are platform policy. They never become
/// Timeline logical state: a retry keeps the Work identity, semantic due time
/// and logical schedule order, while only the Work's operational metadata is
/// changed. A zero attempt limit disables automatic retry and terminalizes the
/// first claimed technical failure.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FailurePolicy {
    max_automatic_attempts: u32,
    retry_backoff: i64,
}

/// Invalid Runtime `FailurePolicy` configuration.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FailurePolicyError {
    /// Backoff must not move a Work's platform availability into the past.
    NegativeBackoff,
    /// Adding the configured backoff to the supplied platform coordinate
    /// cannot be represented by [`PlatformTime`].
    PlatformTimeOverflow,
}

impl fmt::Display for FailurePolicyError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NegativeBackoff => {
                formatter.write_str("FailurePolicy backoff cannot be negative")
            }
            Self::PlatformTimeOverflow => {
                formatter.write_str("FailurePolicy backoff overflowed PlatformTime")
            }
        }
    }
}

impl std::error::Error for FailurePolicyError {}

impl FailurePolicy {
    /// Creates a bounded policy with an attempt limit and fixed Platform-Time
    /// backoff in the adapter's platform-time units.
    ///
    /// The caller may set `max_automatic_attempts` to zero when every
    /// technical failure must go directly through Runtime terminalization.
    ///
    /// # Errors
    ///
    /// Returns [`FailurePolicyError::NegativeBackoff`] when the retry backoff
    /// is negative.
    pub fn new(
        max_automatic_attempts: u32,
        retry_backoff: i64,
    ) -> Result<Self, FailurePolicyError> {
        if retry_backoff < 0 {
            return Err(FailurePolicyError::NegativeBackoff);
        }
        Ok(Self {
            max_automatic_attempts,
            retry_backoff,
        })
    }

    /// Returns the maximum number of claims allowed before automatic
    /// technical failure handling terminalizes the Work.
    #[must_use]
    pub const fn max_automatic_attempts(self) -> u32 {
        self.max_automatic_attempts
    }

    /// Returns the fixed Platform-Time backoff.
    #[must_use]
    pub const fn retry_backoff(self) -> i64 {
        self.retry_backoff
    }

    /// Reports whether the claimed attempt may be retried automatically.
    #[must_use]
    pub const fn allows_retry(self, attempt_count: u32) -> bool {
        attempt_count < self.max_automatic_attempts
    }

    /// Resolves the next platform availability without allowing a caller's
    /// legacy retry hint to bypass the configured backoff.
    ///
    /// # Errors
    ///
    /// Returns [`FailurePolicyError::PlatformTimeOverflow`] when adding the
    /// configured backoff to `now` exceeds the Platform-Time coordinate.
    pub fn next_available_at(
        self,
        now: PlatformTime,
        requested: PlatformTime,
    ) -> Result<PlatformTime, FailurePolicyError> {
        let policy_value = now
            .value()
            .checked_add(self.retry_backoff)
            .ok_or(FailurePolicyError::PlatformTimeOverflow)?;
        Ok(PlatformTime::new(policy_value.max(requested.value())))
    }
}

impl Default for FailurePolicy {
    fn default() -> Self {
        // Defaults are deliberately conservative policy values, not
        // architectural constants. Applications can replace them at Runtime
        // construction time through `with_failure_policy`.
        Self {
            max_automatic_attempts: 3,
            retry_backoff: 0,
        }
    }
}

/// Stable identity of one immutable Runtime software revision.
///
/// This is Platform History metadata. It is deliberately not a Core identity,
/// World Event key or Timeline revision. A composition root chooses the stable
/// value and must explicitly register/confirm it before activation.
#[derive(Clone, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct RuntimeRevisionId(String);

impl RuntimeRevisionId {
    /// Creates a Runtime Revision identity without granting activation
    /// authority.
    #[must_use]
    pub fn new(value: impl Into<String>) -> Self {
        Self(value.into())
    }

    /// Borrows the stable revision identity.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }

    /// Reports whether the identity is empty.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }
}

impl From<String> for RuntimeRevisionId {
    fn from(value: String) -> Self {
        Self::new(value)
    }
}

impl From<&str> for RuntimeRevisionId {
    fn from(value: &str) -> Self {
        Self::new(value)
    }
}

impl From<RuntimeRevisionId> for String {
    fn from(value: RuntimeRevisionId) -> Self {
        value.0
    }
}

impl fmt::Display for RuntimeRevisionId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

/// Exact Capability software metadata available under one Runtime Revision.
///
/// `implementation_id` is a non-secret composition/build identity. The
/// semantic Capability ID and exact implementation version are kept separate
/// so a later Execution Session can pin both the implementation identity and
/// the compatibility facts used against a World Runtime Binding.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RuntimeRevisionCapability {
    capability_id: CapabilityId,
    implementation_id: String,
    version: Version,
    loom_compatibility: VersionReq,
}

impl RuntimeRevisionCapability {
    /// Creates one exact installed Capability implementation record.
    #[must_use]
    pub fn new(
        capability_id: impl Into<CapabilityId>,
        implementation_id: impl Into<String>,
        version: Version,
        loom_compatibility: VersionReq,
    ) -> Self {
        Self {
            capability_id: capability_id.into(),
            implementation_id: implementation_id.into(),
            version,
            loom_compatibility,
        }
    }

    /// Creates the minimum implementation record represented by a registered
    /// Capability manifest. Composition roots with a distinct build identity
    /// should use [`Self::new`] and supply that identity explicitly.
    #[must_use]
    pub fn from_manifest(
        manifest: &CapabilityManifest,
        implementation_id: impl Into<String>,
    ) -> Self {
        Self::new(
            manifest.id.clone(),
            implementation_id,
            manifest.version.clone(),
            manifest.loom_compatibility.clone(),
        )
    }

    /// Returns the semantic Capability identity.
    #[must_use]
    pub const fn capability_id(&self) -> &CapabilityId {
        &self.capability_id
    }

    /// Returns the non-secret exact implementation/build identity.
    #[must_use]
    pub fn implementation_id(&self) -> &str {
        &self.implementation_id
    }

    /// Returns the exact installed Capability version.
    #[must_use]
    pub const fn version(&self) -> &Version {
        &self.version
    }

    /// Returns the Loom contract compatibility requirement declared by the
    /// implementation.
    #[must_use]
    pub const fn loom_compatibility(&self) -> &VersionReq {
        &self.loom_compatibility
    }
}

/// Errors found while constructing an immutable Runtime Revision descriptor.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RuntimeRevisionDescriptorError {
    /// A stable revision identity is required.
    EmptyRevisionId,
    /// A non-secret core build/ref is required by the publication record.
    EmptyCoreBuildRef,
    /// Each installed implementation needs a stable non-secret identity.
    EmptyImplementationId { capability_id: CapabilityId },
    /// A descriptor may contain one exact implementation per semantic
    /// Capability identity.
    DuplicateCapability { capability_id: CapabilityId },
    /// The implementation cannot run against the descriptor's Loom contract.
    IncompatibleLoomVersion {
        capability_id: CapabilityId,
        required: VersionReq,
        found: Version,
    },
}

impl fmt::Display for RuntimeRevisionDescriptorError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::EmptyRevisionId => formatter.write_str("Runtime Revision identity is empty"),
            Self::EmptyCoreBuildRef => formatter.write_str("Runtime core build/ref is empty"),
            Self::EmptyImplementationId { capability_id } => write!(
                formatter,
                "implementation identity for Capability {capability_id} is empty"
            ),
            Self::DuplicateCapability { capability_id } => write!(
                formatter,
                "Runtime Revision contains duplicate Capability {capability_id}"
            ),
            Self::IncompatibleLoomVersion {
                capability_id,
                required,
                found,
            } => write!(
                formatter,
                "Capability {capability_id} requires Loom {required}, found {found}"
            ),
        }
    }
}

impl std::error::Error for RuntimeRevisionDescriptorError {}

/// Immutable publication descriptor for one Runtime software revision.
///
/// The descriptor is Platform History only. It contains non-secret build and
/// compatibility metadata, never provider secrets/raw configuration, and it
/// cannot be changed after registration. Exact selected implementations are
/// later copied into a root Execution Assembly by the Session boundary.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RuntimeRevisionDescriptor {
    id: RuntimeRevisionId,
    published_at: PlatformTime,
    core_build_ref: String,
    loom_version: Version,
    capabilities: BTreeMap<CapabilityId, RuntimeRevisionCapability>,
}

impl RuntimeRevisionDescriptor {
    /// Builds and validates one immutable publication descriptor.
    ///
    /// # Errors
    ///
    /// Returns a typed error when publication metadata is incomplete,
    /// Capability identities are duplicated or a Capability cannot run
    /// against the descriptor's Loom contract version.
    pub fn new<I>(
        id: impl Into<RuntimeRevisionId>,
        published_at: PlatformTime,
        core_build_ref: impl Into<String>,
        loom_version: Version,
        capabilities: I,
    ) -> Result<Self, RuntimeRevisionDescriptorError>
    where
        I: IntoIterator<Item = RuntimeRevisionCapability>,
    {
        let id = id.into();
        if id.is_empty() {
            return Err(RuntimeRevisionDescriptorError::EmptyRevisionId);
        }
        let core_build_ref = core_build_ref.into();
        if core_build_ref.is_empty() {
            return Err(RuntimeRevisionDescriptorError::EmptyCoreBuildRef);
        }

        let mut installed = BTreeMap::new();
        for capability in capabilities {
            let capability_id = capability.capability_id.clone();
            if capability.implementation_id.is_empty() {
                return Err(RuntimeRevisionDescriptorError::EmptyImplementationId {
                    capability_id,
                });
            }
            if installed.contains_key(&capability_id) {
                return Err(RuntimeRevisionDescriptorError::DuplicateCapability { capability_id });
            }
            installed.insert(capability_id, capability);
        }

        for capability in installed.values() {
            if !capability.loom_compatibility.matches(&loom_version) {
                return Err(RuntimeRevisionDescriptorError::IncompatibleLoomVersion {
                    capability_id: capability.capability_id.clone(),
                    required: capability.loom_compatibility.clone(),
                    found: loom_version.clone(),
                });
            }
        }

        Ok(Self {
            id,
            published_at,
            core_build_ref,
            loom_version,
            capabilities: installed,
        })
    }

    /// Returns the stable revision identity.
    #[must_use]
    pub const fn id(&self) -> &RuntimeRevisionId {
        &self.id
    }

    /// Returns the publication platform-time metadata.
    #[must_use]
    pub const fn published_at(&self) -> PlatformTime {
        self.published_at
    }

    /// Returns the non-secret core build/ref metadata.
    #[must_use]
    pub fn core_build_ref(&self) -> &str {
        &self.core_build_ref
    }

    /// Returns the Loom contract version used to validate installed
    /// Capability compatibility.
    #[must_use]
    pub const fn loom_version(&self) -> &Version {
        &self.loom_version
    }

    /// Returns exact installed Capability metadata in deterministic key order.
    #[must_use]
    pub const fn capabilities(&self) -> &BTreeMap<CapabilityId, RuntimeRevisionCapability> {
        &self.capabilities
    }

    /// Looks up one exact installed Capability implementation.
    #[must_use]
    pub fn capability(&self, capability_id: &CapabilityId) -> Option<&RuntimeRevisionCapability> {
        self.capabilities.get(capability_id)
    }

    /// Checks this active revision against a World Runtime Binding and returns
    /// the exact compatible implementation assembly for a future Session.
    ///
    /// This method only reads immutable descriptors. It never changes the
    /// Binding, active selection, World history or Timeline state.
    ///
    /// # Errors
    ///
    /// Returns a typed missing-Capability or version-mismatch error when the
    /// active revision cannot satisfy the immutable Binding.
    pub fn compatible_with(
        &self,
        binding: &WorldRuntimeBinding,
    ) -> Result<RuntimeRevisionAssembly, RuntimeRevisionCompatibilityError> {
        let mut selected = BTreeMap::new();
        for (capability_id, requirement) in binding.requirements() {
            let Some(installed) = self.capabilities.get(capability_id) else {
                return Err(RuntimeRevisionCompatibilityError::MissingCapability {
                    capability_id: capability_id.clone(),
                    required: requirement.clone(),
                });
            };
            if !requirement.matches(&installed.version) {
                return Err(RuntimeRevisionCompatibilityError::VersionMismatch {
                    capability_id: capability_id.clone(),
                    required: requirement.clone(),
                    found: installed.version.clone(),
                });
            }
            selected.insert(capability_id.clone(), installed.clone());
        }
        Ok(RuntimeRevisionAssembly {
            revision_id: self.id.clone(),
            capabilities: selected,
        })
    }
}

/// Exact compatible implementation set selected for one future Session.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RuntimeRevisionAssembly {
    revision_id: RuntimeRevisionId,
    capabilities: BTreeMap<CapabilityId, RuntimeRevisionCapability>,
}

impl RuntimeRevisionAssembly {
    /// Returns the Runtime Revision pinned by this assembly.
    #[must_use]
    pub const fn revision_id(&self) -> &RuntimeRevisionId {
        &self.revision_id
    }

    /// Returns the exact compatible implementation set.
    #[must_use]
    pub const fn capabilities(&self) -> &BTreeMap<CapabilityId, RuntimeRevisionCapability> {
        &self.capabilities
    }

    /// Looks up the exact implementation selected for one semantic Capability
    /// in this immutable Session assembly.
    #[must_use]
    pub fn capability(&self, capability_id: &CapabilityId) -> Option<&RuntimeRevisionCapability> {
        self.capabilities.get(capability_id)
    }
}

/// Typed incompatibility between an active Runtime Revision and a World
/// Runtime Binding.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RuntimeRevisionCompatibilityError {
    /// The active revision has no implementation for a required semantic
    /// Capability domain.
    MissingCapability {
        capability_id: CapabilityId,
        required: VersionReq,
    },
    /// The installed implementation version does not satisfy the immutable
    /// World requirement.
    VersionMismatch {
        capability_id: CapabilityId,
        required: VersionReq,
        found: Version,
    },
}

impl fmt::Display for RuntimeRevisionCompatibilityError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::MissingCapability {
                capability_id,
                required,
            } => write!(
                formatter,
                "Runtime Revision is missing Capability {capability_id} required by {required}"
            ),
            Self::VersionMismatch {
                capability_id,
                required,
                found,
            } => write!(
                formatter,
                "Capability {capability_id} version {found} does not satisfy World requirement {required}"
            ),
        }
    }
}

impl std::error::Error for RuntimeRevisionCompatibilityError {}

/// Active Runtime Revision selection returned by the Runtime port.
///
/// The generation is the CAS token for the selection pointer. The embedded
/// descriptor is cloned at read/activation time, so a Session can retain it
/// even if a later activation changes the active pointer.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RuntimeRevisionSelection {
    revision: RuntimeRevisionDescriptor,
    generation: u64,
    activated_at: PlatformTime,
}

impl RuntimeRevisionSelection {
    /// Creates one active-selection snapshot after the persistence adapter has
    /// linearized its generation CAS.
    #[must_use]
    pub const fn new(
        revision: RuntimeRevisionDescriptor,
        generation: u64,
        activated_at: PlatformTime,
    ) -> Self {
        Self {
            revision,
            generation,
            activated_at,
        }
    }

    /// Returns the immutable selected descriptor.
    #[must_use]
    pub const fn revision(&self) -> &RuntimeRevisionDescriptor {
        &self.revision
    }

    /// Returns the active-selection CAS generation.
    #[must_use]
    pub const fn generation(&self) -> u64 {
        self.generation
    }

    /// Returns the platform-time activation metadata.
    #[must_use]
    pub const fn activated_at(&self) -> PlatformTime {
        self.activated_at
    }
}

/// The Runtime-visible source of a root execution.
///
/// Origin is execution metadata, not a World actor, Event payload or
/// authorization grant. The value is pinned into one Session before semantic
/// resolution begins. Work and Template bootstrap roots use `Runtime` until
/// their later target-specific public contracts provide a richer origin value.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub enum ExecutionOrigin {
    /// A direct application/API Action request.
    Application,
    /// A durable external envelope. The M8 Ingress contract supplies this
    /// origin when that boundary is implemented.
    Ingress,
    /// An explicitly operator-authorized execution.
    Operator,
    /// A Runtime-owned root such as Durable Work or Template bootstrap.
    Runtime,
}

/// Immutable exact software and World contract used by one root Session.
///
/// This value is constructed only by Runtime after one coherent Timeline read,
/// one World Runtime Binding read and one active Runtime Revision selection.
/// It is passed by shared reference to root dispatch and every subresolution;
/// no child may re-select the active revision or mutate the Binding. The
/// `ResolutionBudget` is the currently defined v0 execution policy. The
/// `entropy_source_id` identifies the controlled entropy environment pinned for
/// this Session; the source handle itself remains Runtime-owned and is never
/// serialized into Capability-visible state.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ExecutionAssembly {
    session_id: ExecutionSessionId,
    world_id: WorldId,
    timeline_id: TimelineId,
    expected_version: TimelineVersion,
    world_time: WorldInstant,
    binding: WorldRuntimeBinding,
    runtime_revision: RuntimeRevisionSelection,
    implementations: RuntimeRevisionAssembly,
    execution_policy: ResolutionBudget,
    #[serde(default)]
    entropy_source_id: EntropySourceId,
}

impl ExecutionAssembly {
    #[expect(
        clippy::too_many_arguments,
        reason = "constructor mirrors the frozen Execution Assembly fields"
    )]
    pub(crate) fn new(
        session_id: ExecutionSessionId,
        world_id: WorldId,
        timeline_id: TimelineId,
        expected_version: TimelineVersion,
        world_time: WorldInstant,
        binding: WorldRuntimeBinding,
        runtime_revision: RuntimeRevisionSelection,
        implementations: RuntimeRevisionAssembly,
        execution_policy: ResolutionBudget,
        entropy_source_id: EntropySourceId,
    ) -> Self {
        Self {
            session_id,
            world_id,
            timeline_id,
            expected_version,
            world_time,
            binding,
            runtime_revision,
            implementations,
            execution_policy,
            entropy_source_id,
        }
    }

    /// Returns the Session identity owning this assembly.
    #[must_use]
    pub const fn session_id(&self) -> ExecutionSessionId {
        self.session_id
    }

    /// Returns the pinned World identity.
    #[must_use]
    pub const fn world_id(&self) -> WorldId {
        self.world_id
    }

    /// Returns the pinned Timeline identity.
    #[must_use]
    pub const fn timeline_id(&self) -> TimelineId {
        self.timeline_id
    }

    /// Returns the `TimelineVersion` used for reads and the later commit CAS.
    #[must_use]
    pub const fn expected_version(&self) -> TimelineVersion {
        self.expected_version
    }

    /// Returns the World Time observed at Session start.
    #[must_use]
    pub const fn world_time(&self) -> WorldInstant {
        self.world_time
    }

    /// Returns the immutable World Runtime Binding pinned for this Session.
    #[must_use]
    pub const fn binding(&self) -> &WorldRuntimeBinding {
        &self.binding
    }

    /// Returns the active Runtime Revision snapshot pinned for this Session.
    #[must_use]
    pub const fn runtime_revision(&self) -> &RuntimeRevisionSelection {
        &self.runtime_revision
    }

    /// Returns the exact compatible Capability implementations pinned for this
    /// Session.
    #[must_use]
    pub const fn implementations(&self) -> &RuntimeRevisionAssembly {
        &self.implementations
    }

    /// Returns the immutable Runtime execution policy pinned for this Session.
    #[must_use]
    pub const fn execution_policy(&self) -> ResolutionBudget {
        self.execution_policy
    }

    /// Returns the controlled entropy source identity pinned for this Session.
    #[must_use]
    pub const fn entropy_source_id(&self) -> &EntropySourceId {
        &self.entropy_source_id
    }
}

/// Lifecycle state of one persisted Runtime execution Session.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub enum ExecutionSessionStatus {
    /// The assembly was persisted and semantic execution is in flight.
    Started,
    /// The root reached a successful Runtime commit (including no-change
    /// logical completion where the root had no semantic mutation).
    Committed,
    /// The Capability returned a normal semantic rejection.
    Rejected,
    /// Runtime or persistence authority rejected the technical execution.
    Failed,
}

impl ExecutionSessionStatus {
    /// Reports whether the Session has reached a terminal lifecycle state.
    #[must_use]
    pub const fn is_terminal(self) -> bool {
        !matches!(self, Self::Started)
    }
}

/// Minimum durable Session lifecycle/provenance record.
///
/// The record stores the complete pinned assembly, lifecycle state and the
/// ordered entropy evidence observed by the root execution. It remains Platform
/// History and never a World Event or Timeline logical state transition.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ExecutionSession {
    id: ExecutionSessionId,
    origin: ExecutionOrigin,
    assembly: ExecutionAssembly,
    started_at: PlatformTime,
    status: ExecutionSessionStatus,
    ended_at: Option<PlatformTime>,
    #[serde(default)]
    entropy_evidence: EntropyEvidence,
}

impl ExecutionSession {
    pub(crate) fn new(
        id: ExecutionSessionId,
        origin: ExecutionOrigin,
        assembly: ExecutionAssembly,
        started_at: PlatformTime,
    ) -> Self {
        let entropy_source_id = assembly.entropy_source_id().clone();
        Self {
            id,
            origin,
            assembly,
            started_at,
            status: ExecutionSessionStatus::Started,
            ended_at: None,
            entropy_evidence: EntropyEvidence::new(entropy_source_id),
        }
    }

    /// Returns the stable Runtime Session identity.
    #[must_use]
    pub const fn id(&self) -> ExecutionSessionId {
        self.id
    }

    /// Returns the pinned root origin.
    #[must_use]
    pub const fn origin(&self) -> ExecutionOrigin {
        self.origin
    }

    /// Returns the immutable Execution Assembly.
    #[must_use]
    pub const fn assembly(&self) -> &ExecutionAssembly {
        &self.assembly
    }

    /// Returns the platform metadata captured when the Session was persisted.
    #[must_use]
    pub const fn started_at(&self) -> PlatformTime {
        self.started_at
    }

    /// Returns the current lifecycle state.
    #[must_use]
    pub const fn status(&self) -> ExecutionSessionStatus {
        self.status
    }

    /// Returns the terminal platform timestamp, when the Session ended.
    #[must_use]
    pub const fn ended_at(&self) -> Option<PlatformTime> {
        self.ended_at
    }

    /// Returns ordered Runtime entropy evidence captured for this Session.
    #[must_use]
    pub const fn entropy_evidence(&self) -> &EntropyEvidence {
        &self.entropy_evidence
    }

    /// Returns a terminal copy used by persistence adapters at the lifecycle
    /// transition linearization point.
    ///
    /// # Errors
    ///
    /// A terminal Session cannot be transitioned a second time, because doing
    /// so would hide the first execution outcome in the provenance ledger.
    pub fn finish(
        &self,
        status: ExecutionSessionStatus,
        ended_at: PlatformTime,
    ) -> Result<Self, SessionError> {
        self.finish_with_entropy(status, ended_at, self.entropy_evidence.clone())
    }

    /// Returns a terminal copy while attaching ordered entropy evidence from
    /// the same pinned source environment.
    ///
    /// # Errors
    ///
    /// Returns a lifecycle error when the Session is already terminal or the
    /// evidence belongs to a different pinned entropy source.
    pub fn finish_with_entropy(
        &self,
        status: ExecutionSessionStatus,
        ended_at: PlatformTime,
        entropy_evidence: EntropyEvidence,
    ) -> Result<Self, SessionError> {
        if !status.is_terminal() {
            return Err(SessionError::InvalidTransition {
                session_id: self.id,
                from: self.status,
                to: status,
            });
        }
        if self.status != ExecutionSessionStatus::Started {
            return Err(SessionError::InvalidTransition {
                session_id: self.id,
                from: self.status,
                to: status,
            });
        }
        if entropy_evidence.source_id() != self.assembly.entropy_source_id() {
            return Err(SessionError::EntropySourceMismatch {
                session_id: self.id,
            });
        }
        let mut finished = self.clone();
        finished.status = status;
        finished.ended_at = Some(ended_at);
        finished.entropy_evidence = entropy_evidence;
        Ok(finished)
    }
}

/// Typed failures at the Runtime execution Session persistence boundary.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SessionError {
    /// A Session identity was already persisted.
    SessionAlreadyExists { session_id: ExecutionSessionId },
    /// The requested Session identity is absent.
    SessionNotFound { session_id: ExecutionSessionId },
    /// A lifecycle transition would overwrite a terminal outcome.
    InvalidTransition {
        session_id: ExecutionSessionId,
        from: ExecutionSessionStatus,
        to: ExecutionSessionStatus,
    },
    /// Evidence was produced by a source other than the Session's pinned
    /// entropy environment.
    EntropySourceMismatch { session_id: ExecutionSessionId },
    /// The persistence adapter does not implement the entropy evidence port.
    EntropyEvidenceUnavailable { session_id: ExecutionSessionId },
    /// The persistence authority could not complete the Session operation.
    StorageUnavailable { message: String },
}

impl fmt::Display for SessionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::SessionAlreadyExists { session_id } => {
                write!(formatter, "Execution Session {session_id} already exists")
            }
            Self::SessionNotFound { session_id } => {
                write!(formatter, "Execution Session {session_id} was not found")
            }
            Self::InvalidTransition {
                session_id,
                from,
                to,
            } => write!(
                formatter,
                "Execution Session {session_id} cannot transition from {from:?} to {to:?}"
            ),
            Self::EntropySourceMismatch { session_id } => write!(
                formatter,
                "entropy evidence does not belong to Execution Session {session_id}"
            ),
            Self::EntropyEvidenceUnavailable { session_id } => write!(
                formatter,
                "entropy evidence cannot be persisted for Execution Session {session_id}"
            ),
            Self::StorageUnavailable { message } => formatter.write_str(message),
        }
    }
}

impl std::error::Error for SessionError {}

/// Runtime-owned Platform History port for Session lifecycle records.
///
/// Implementations must persist the immutable assembly supplied at start and
/// linearize exactly one terminal transition. Session operations never append
/// World Events, advance World Time or mutate World Runtime Binding.
pub trait ExecutionSessionStore {
    /// Persists one newly started Session before semantic dispatch begins.
    fn start_session(
        &self,
        session: ExecutionSession,
    ) -> PersistenceFuture<'_, Result<(), SessionError>>;

    /// Persists one terminal Session lifecycle transition.
    fn finish_session(
        &self,
        session_id: ExecutionSessionId,
        status: ExecutionSessionStatus,
        ended_at: PlatformTime,
    ) -> PersistenceFuture<'_, Result<ExecutionSession, SessionError>>;

    /// Persists a terminal Session transition together with ordered entropy
    /// evidence. Runtime-owned adapters persist the evidence in their existing
    /// Session record envelope without a schema migration. An older adapter
    /// using the default can still finish Sessions with no samples, but must
    /// not silently discard non-empty evidence.
    fn finish_session_with_entropy(
        &self,
        session_id: ExecutionSessionId,
        status: ExecutionSessionStatus,
        ended_at: PlatformTime,
        entropy_evidence: EntropyEvidence,
    ) -> PersistenceFuture<'_, Result<ExecutionSession, SessionError>> {
        if !entropy_evidence.is_empty() {
            return Box::pin(async move {
                Err(SessionError::EntropyEvidenceUnavailable { session_id })
            });
        }
        self.finish_session(session_id, status, ended_at)
    }

    /// Reads one Session record for audit/restart linkage.
    fn read_session(
        &self,
        session_id: ExecutionSessionId,
    ) -> PersistenceFuture<'_, Result<ExecutionSession, SessionError>>;

    /// Reads all Session records in deterministic identity order.
    fn list_sessions(&self) -> PersistenceFuture<'_, Result<Vec<ExecutionSession>, SessionError>>;
}

/// Errors from the immutable Runtime Revision and active-selection port.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RuntimeRevisionError {
    /// A publication with this stable identity is already present.
    RevisionAlreadyExists { revision_id: RuntimeRevisionId },
    /// The requested immutable publication is absent.
    RevisionNotFound { revision_id: RuntimeRevisionId },
    /// A confirmation supplied metadata different from the immutable row.
    RevisionDescriptorMismatch { revision_id: RuntimeRevisionId },
    /// A concurrent activation changed the selection pointer.
    ActiveRevisionConflict {
        expected_generation: Option<u64>,
        actual_generation: Option<u64>,
    },
    /// The active-selection generation cannot advance further.
    ActivationGenerationOverflow,
    /// The Runtime Revision authority could not complete the operation.
    StorageUnavailable { message: String },
}

impl fmt::Display for RuntimeRevisionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::RevisionAlreadyExists { revision_id } => {
                write!(formatter, "Runtime Revision {revision_id} already exists")
            }
            Self::RevisionNotFound { revision_id } => {
                write!(formatter, "Runtime Revision {revision_id} was not found")
            }
            Self::RevisionDescriptorMismatch { revision_id } => write!(
                formatter,
                "Runtime Revision {revision_id} does not match the confirmed descriptor"
            ),
            Self::ActiveRevisionConflict {
                expected_generation,
                actual_generation,
            } => write!(
                formatter,
                "active Runtime Revision generation conflict: expected {expected_generation:?}, actual {actual_generation:?}"
            ),
            Self::ActivationGenerationOverflow => {
                formatter.write_str("active Runtime Revision generation overflowed")
            }
            Self::StorageUnavailable { message } => formatter.write_str(message),
        }
    }
}

impl std::error::Error for RuntimeRevisionError {}

/// Runtime-owned Platform History port for immutable revision publication and
/// explicit active-revision selection.
///
/// Implementations must keep revision descriptors immutable and linearize
/// activation through the supplied generation CAS. No method writes World,
/// Timeline, Event, materialized State or World Runtime Binding data.
pub trait RuntimeRevisionStore {
    /// Publishes one immutable revision descriptor exactly once.
    fn register_revision(
        &self,
        revision: RuntimeRevisionDescriptor,
    ) -> PersistenceFuture<'_, Result<(), RuntimeRevisionError>>;

    /// Confirms a known descriptor, registering it only when its stable ID is
    /// absent. A different descriptor under the same ID is rejected.
    fn confirm_revision(
        &self,
        revision: RuntimeRevisionDescriptor,
    ) -> PersistenceFuture<'_, Result<RuntimeRevisionDescriptor, RuntimeRevisionError>>;

    /// Reads one immutable revision publication.
    fn read_revision(
        &self,
        revision_id: RuntimeRevisionId,
    ) -> PersistenceFuture<'_, Result<RuntimeRevisionDescriptor, RuntimeRevisionError>>;

    /// Reads all immutable publications in deterministic ID order.
    fn list_revisions(
        &self,
    ) -> PersistenceFuture<'_, Result<Vec<RuntimeRevisionDescriptor>, RuntimeRevisionError>>;

    /// Reads the current active selection. `None` means no semantic revision
    /// has been explicitly activated yet.
    fn read_active_revision(
        &self,
    ) -> PersistenceFuture<'_, Result<Option<RuntimeRevisionSelection>, RuntimeRevisionError>>;

    /// Alias used by Session-start code to emphasize selection/pinning.
    fn select_active_revision(
        &self,
    ) -> PersistenceFuture<'_, Result<Option<RuntimeRevisionSelection>, RuntimeRevisionError>> {
        self.read_active_revision()
    }

    /// Activates a previously registered revision if the active-selection
    /// generation still equals `expected_generation` (`None` means no active
    /// revision). The revision descriptor itself is never changed.
    fn activate_revision(
        &self,
        revision_id: RuntimeRevisionId,
        expected_generation: Option<u64>,
        activated_at: PlatformTime,
    ) -> PersistenceFuture<'_, Result<RuntimeRevisionSelection, RuntimeRevisionError>>;
}

/// Compatibility aliases matching the architecture's shorter terminology.
pub type RuntimeRevision = RuntimeRevisionDescriptor;
pub type RuntimeCapabilityImplementation = RuntimeRevisionCapability;
pub type ActiveRuntimeRevision = RuntimeRevisionSelection;

/// Runtime-owned source of operational platform time.
///
/// Platform time is infrastructure metadata for leases, retry availability
/// and adapter commit metadata. It is not World Time, and this port is
/// intentionally not part of the Capability resolution context. The
/// application composition root may inject a system-clock adapter; tests can
/// inject a deterministic implementation without giving a Capability access
/// to that clock.
pub trait PlatformClock {
    /// Returns the platform time for the current Runtime execution boundary.
    fn now(&self) -> PlatformTime;
}

impl<T> PlatformClock for Arc<T>
where
    T: PlatformClock + ?Sized,
{
    fn now(&self) -> PlatformTime {
        (**self).now()
    }
}

/// A deterministic, Runtime-injectable platform clock for tests and fixtures.
///
/// Clones share the same value, so a test can advance the clock after it has
/// been injected into a Runtime. It never reads wall-clock state.
#[derive(Clone, Debug)]
pub struct ManualPlatformClock {
    value: Arc<AtomicI64>,
}

impl ManualPlatformClock {
    /// Creates a manual clock at the supplied platform time.
    #[must_use]
    pub fn new(value: PlatformTime) -> Self {
        Self {
            value: Arc::new(AtomicI64::new(value.value())),
        }
    }

    /// Sets the value returned by subsequent [`PlatformClock::now`] calls.
    pub fn set(&self, value: PlatformTime) {
        self.value.store(value.value(), Ordering::Relaxed);
    }
}

impl Default for ManualPlatformClock {
    fn default() -> Self {
        Self::new(PlatformTime::default())
    }
}

impl PlatformClock for ManualPlatformClock {
    fn now(&self) -> PlatformTime {
        PlatformTime::new(self.value.load(Ordering::Relaxed))
    }
}

/// The only durable semantic statuses supported by v0 Durable Work.
///
/// Lease ownership, retry availability and attempt counts are separate
/// Runtime metadata. Claiming a `Pending` Work therefore never changes this
/// enum to a transient `Running` or `Retrying` variant.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum WorkStatus {
    /// Work is eligible for execution when its schedule/availability allows.
    Pending,
    /// Runtime atomically completed this Work with its accepted outcome.
    Completed,
    /// Runtime or operator policy cancelled this Work.
    Cancelled,
    /// Runtime permanently stopped this Work after its retry policy was spent.
    Dead,
}

impl fmt::Display for WorkStatus {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let name = match self {
            Self::Pending => "Pending",
            Self::Completed => "Completed",
            Self::Cancelled => "Cancelled",
            Self::Dead => "Dead",
        };
        formatter.write_str(name)
    }
}

/// Operational lease metadata kept separate from durable [`WorkStatus`].
///
/// A fence is monotonically replaced on every successful claim. A worker may
/// submit a commit only while the stored fence matches its claim and the
/// supplied platform time is strictly before `claimed_until`.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct WorkLease {
    claimed_until: PlatformTime,
    fence: u64,
}

impl WorkLease {
    /// Creates lease metadata for one fence generation.
    #[must_use]
    pub const fn new(claimed_until: PlatformTime, fence: u64) -> Self {
        Self {
            claimed_until,
            fence,
        }
    }

    /// Returns the explicit platform deadline of the lease.
    #[must_use]
    pub const fn claimed_until(self) -> PlatformTime {
        self.claimed_until
    }

    /// Returns the monotonic claim fence.
    #[must_use]
    pub const fn fence(self) -> u64 {
        self.fence
    }
}

/// Runtime-owned claim evidence required to complete one current Work.
///
/// Storage adapters return this value from [`WorkStore::claim`]. Callers must
/// pass the same value to [`CommitStore::commit`]; the adapter rechecks the
/// Work status, stored fence and lease deadline at the commit linearization
/// point. The public constructor makes this a typed value, but does not grant
/// commit authority: a forged or stale fence is rejected by the adapter.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct WorkClaim {
    timeline_id: TimelineId,
    work_id: WorkId,
    claimed_until: PlatformTime,
    fence: u64,
    attempt_count: u32,
}

impl WorkClaim {
    /// Creates claim evidence returned by a Work adapter.
    #[must_use]
    pub const fn new(
        timeline_id: TimelineId,
        work_id: WorkId,
        claimed_until: PlatformTime,
        fence: u64,
    ) -> Self {
        Self::with_attempt_count(timeline_id, work_id, claimed_until, fence, 0)
    }

    /// Creates claim evidence including the authoritative attempt number
    /// assigned by the successful claim linearization point.
    #[must_use]
    pub const fn with_attempt_count(
        timeline_id: TimelineId,
        work_id: WorkId,
        claimed_until: PlatformTime,
        fence: u64,
        attempt_count: u32,
    ) -> Self {
        Self {
            timeline_id,
            work_id,
            claimed_until,
            fence,
            attempt_count,
        }
    }

    /// Returns the Timeline containing the claimed Work.
    #[must_use]
    pub const fn timeline_id(self) -> TimelineId {
        self.timeline_id
    }

    /// Returns the claimed Work identity.
    #[must_use]
    pub const fn work_id(self) -> WorkId {
        self.work_id
    }

    /// Returns the platform deadline captured by the claim.
    #[must_use]
    pub const fn claimed_until(self) -> PlatformTime {
        self.claimed_until
    }

    /// Returns the fence generation captured by the claim.
    #[must_use]
    pub const fn fence(self) -> u64 {
        self.fence
    }

    /// Returns the authoritative attempt number associated with this claim.
    ///
    /// The value is operational metadata and is never part of Timeline logical
    /// journal history. It is carried in the claim so `FailurePolicy` decisions
    /// do not need a second, non-linearized Work read.
    #[must_use]
    pub const fn attempt_count(self) -> u32 {
        self.attempt_count
    }
}

/// The two Runtime-authorized terminal logical states for a Pending Work.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub enum WorkTerminalState {
    /// Runtime `FailurePolicy` or authorized control permanently stopped Work.
    Dead,
    /// Authorized Runtime control cancelled Work.
    Cancelled,
}

impl WorkTerminalState {
    /// Converts the control state to the durable Work lifecycle status.
    #[must_use]
    pub const fn as_work_status(self) -> WorkStatus {
        match self {
            Self::Dead => WorkStatus::Dead,
            Self::Cancelled => WorkStatus::Cancelled,
        }
    }
}

/// Runtime-owned authority input for a Pending -> Dead/Cancelled transition.
///
/// The expected Timeline version is checked together with the Work lifecycle
/// mutation and logical journal append by the persistence adapter. Automatic
/// `FailurePolicy` terminalization carries its claim/fence; explicit control may
/// omit the claim and invalidates any existing lease as part of the same
/// logical transition.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WorkTerminalization {
    timeline_id: TimelineId,
    expected_version: TimelineVersion,
    work_id: WorkId,
    terminal_state: WorkTerminalState,
    claim: Option<WorkClaim>,
    now: PlatformTime,
    last_error: Option<String>,
}

impl WorkTerminalization {
    /// Creates an explicitly authorized terminalization request.
    #[must_use]
    pub const fn new(
        timeline_id: TimelineId,
        expected_version: TimelineVersion,
        work_id: WorkId,
        terminal_state: WorkTerminalState,
        now: PlatformTime,
    ) -> Self {
        Self {
            timeline_id,
            expected_version,
            work_id,
            terminal_state,
            claim: None,
            now,
            last_error: None,
        }
    }

    /// Attaches the claim/fence that authorizes automatic terminalization of
    /// the currently executing Work.
    #[must_use]
    pub const fn with_claim(mut self, claim: WorkClaim) -> Self {
        self.claim = Some(claim);
        self
    }

    /// Retains an operational terminal error for operator inspection without
    /// representing that error in the logical journal.
    #[must_use]
    pub fn with_last_error(mut self, last_error: impl Into<String>) -> Self {
        self.last_error = Some(last_error.into());
        self
    }

    /// Returns the targeted Timeline.
    #[must_use]
    pub const fn timeline_id(&self) -> TimelineId {
        self.timeline_id
    }

    /// Returns the expected Timeline CAS version.
    #[must_use]
    pub const fn expected_version(&self) -> TimelineVersion {
        self.expected_version
    }

    /// Returns the targeted Work identity.
    #[must_use]
    pub const fn work_id(&self) -> WorkId {
        self.work_id
    }

    /// Returns the requested terminal logical state.
    #[must_use]
    pub const fn terminal_state(&self) -> WorkTerminalState {
        self.terminal_state
    }

    /// Returns the optional automatic-failure claim/fence.
    #[must_use]
    pub const fn claim(&self) -> Option<WorkClaim> {
        self.claim
    }

    /// Returns the Platform-Time coordinate used for lease validation.
    #[must_use]
    pub const fn now(&self) -> PlatformTime {
        self.now
    }

    /// Returns the optional operational terminal error.
    #[must_use]
    pub fn last_error(&self) -> Option<&str> {
        self.last_error.as_deref()
    }
}

/// Operator-visible liveness condition for a due Pending Work whose target
/// cannot be assembled by the active Runtime Revision.
///
/// This is derived from the coherent Timeline snapshot, immutable World
/// Binding and current installed/active Runtime metadata. It is not World
/// Truth, does not consume a technical attempt and does not advance the
/// Timeline logical revision.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct TimelineBlockedOnMissingImplementation {
    /// World containing the blocked Timeline.
    pub world_id: WorldId,
    /// Timeline whose logical head remains blocked.
    pub timeline_id: TimelineId,
    /// Due Pending Work that prevents later scheduler progression.
    pub work_id: WorkId,
    /// Semantic Capability handler or Agency cognition requirement.
    pub semantic_requirement: WorkTarget,
    /// Active Runtime Revision considered by the observation.
    pub active_runtime_revision: RuntimeRevisionId,
    /// First observation is optional because this condition is derived rather
    /// than persisted as semantic state.
    pub first_observed_platform_time: Option<PlatformTime>,
    /// Platform time at which this observation was produced.
    pub last_observed_platform_time: PlatformTime,
}

/// A read model of one Durable Work item and its independent runtime metadata.
///
/// `target`, `effective_due_world_time` and `logical_schedule_order` are
/// persistent logical Work state. `available_at`, `lease`, `attempt_count` and
/// `last_error` are platform/runtime metadata and do not belong to the World
/// Event ledger. Technical retry/reclaim must not alter the three logical
/// fields.
#[derive(Clone, Debug, PartialEq)]
pub struct WorkRecord {
    /// Stable Work identity reused across technical retries.
    pub id: WorkId,
    /// Timeline-local scope of the Work obligation.
    pub timeline_id: TimelineId,
    /// Explicit Capability Work or Agency Wake execution target.
    pub target: WorkTarget,
    /// Schema revision for the serialized handler payload.
    pub schema_revision: loom_core::SchemaRevision,
    /// Serialized handler input, not a precomputed future result.
    pub payload: Value,
    /// Non-null World-semantic time at which the Work becomes due.
    pub effective_due_world_time: WorldInstant,
    /// Timeline-local persistent order assigned by the scheduling commit.
    pub logical_schedule_order: u64,
    /// Optional causal Event that scheduled the Work.
    pub causal_event_id: Option<EventId>,
    /// Optional preceding Work from which this Work was derived.
    pub origin_work_id: Option<WorkId>,
    /// Durable semantic lifecycle status.
    pub status: WorkStatus,
    /// Number of execution claims/attempts made for this Work.
    pub attempt_count: u32,
    /// Monotonic fence generation retained even when no lease is active.
    pub claim_generation: u64,
    /// Platform time at which another claim may be attempted.
    pub available_at: PlatformTime,
    /// Most recent technical failure, if any.
    pub last_error: Option<String>,
    /// Current operational lease, independent from `status`.
    pub lease: Option<WorkLease>,
}

impl WorkRecord {
    /// Builds a pending Work record from a validated `NewWork` proposal.
    #[must_use]
    pub fn from_new_work(work: &NewWork, available_at: PlatformTime) -> Self {
        let effective_due_world_time = match work.schedule {
            // This compatibility constructor has no pinned Timeline World
            // Time. Commit adapters must use `from_scheduled_work` for
            // authoritative scheduling and replace this placeholder.
            WorkSchedule::Immediate => WorldInstant::default(),
            WorkSchedule::At(instant) => instant,
        };
        Self::from_scheduled_work(work, effective_due_world_time, 0, available_at)
    }

    /// Builds a pending Work record with the logical position assigned by its
    /// scheduling Logical Commit.
    #[must_use]
    pub fn from_scheduled_work(
        work: &NewWork,
        effective_due_world_time: WorldInstant,
        logical_schedule_order: u64,
        available_at: PlatformTime,
    ) -> Self {
        Self {
            id: work.id,
            timeline_id: work.timeline_id,
            target: work.target.clone(),
            schema_revision: work.schema_revision,
            payload: work.payload.clone(),
            effective_due_world_time,
            logical_schedule_order,
            causal_event_id: work.causal_event_id,
            origin_work_id: work.origin_work_id,
            status: WorkStatus::Pending,
            attempt_count: 0,
            claim_generation: 0,
            available_at,
            last_error: None,
            lease: None,
        }
    }

    /// Returns whether the Work can still be claimed/completed as Pending.
    #[must_use]
    pub const fn is_pending(&self) -> bool {
        matches!(self.status, WorkStatus::Pending)
    }
}

/// One logical Work transition captured by a Timeline Logical Commit.
///
/// These records describe semantic future state only. Lease, fence, retry,
/// availability and technical error metadata deliberately do not have a
/// journal representation. A scheduled record carries the fields required to
/// reconstruct the Work chronology without consulting the current Work table.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub enum LogicalWorkTransition {
    /// A new logical Work obligation entered the Timeline's future.
    Schedule {
        /// Stable Work identity.
        work_id: WorkId,
        /// Explicit logical execution target.
        target: WorkTarget,
        /// Schema revision for the serialized Work payload.
        schema_revision: SchemaRevision,
        /// Serialized logical Work input required for historical reconstruction.
        payload: Value,
        /// World-semantic due coordinate resolved by the scheduling commit.
        effective_due_world_time: WorldInstant,
        /// Timeline-local persistent chronology order.
        logical_schedule_order: u64,
        /// Optional Event that caused the Work.
        causal_event_id: Option<EventId>,
        /// Optional preceding Work from which this Work was derived.
        origin_work_id: Option<WorkId>,
    },
    /// A Pending Work obligation was logically cancelled.
    Cancel {
        /// Stable Work identity.
        work_id: WorkId,
    },
    /// A Pending Work obligation was successfully completed by the Runtime.
    Complete {
        /// Stable Work identity.
        work_id: WorkId,
    },
    /// A Pending Work obligation was logically terminalized as dead.
    ///
    /// M5-T3 supplies the policy/control path that creates this transition;
    /// the journal shape is defined here so all logical Work terminal states
    /// share one reconstruction contract.
    Dead {
        /// Stable Work identity.
        work_id: WorkId,
    },
}

/// An explicit World-Time transition recorded by a Logical Commit.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct WorldTimeTransition {
    /// World Time before the logical transition.
    pub from: WorldInstant,
    /// World Time after the logical transition.
    pub to: WorldInstant,
}

/// The same-World-Time chronology consumption caused by one successful
/// Scheduler Work completion.
///
/// The before/after values are persisted with the Work completion's journal
/// record, so a restart or later historical reader can reconstruct the
/// liveness position without treating an operational attempt counter as
/// semantic history.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ChronologyBudgetConsumption {
    /// World instant whose chronology budget was consumed.
    pub world_time: WorldInstant,
    /// Consumption before this Logical Commit.
    pub before: u64,
    /// Consumption after this Logical Commit.
    pub after: u64,
}

/// One ordered Runtime-owned Timeline Logical Commit journal record.
///
/// A record is appended atomically with the authority mutation it describes.
/// It is not a World Event and never contains lease/retry/error bookkeeping.
/// `after_version.state_revision` is the Timeline-local logical order key: a
/// successful non-empty logical commit advances it exactly once, so ordered
/// reads do not depend on database row order, UUID order or platform time.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct LogicalCommit {
    /// Timeline containing this logical commit.
    pub timeline_id: TimelineId,
    /// Timeline version immediately before the commit.
    pub before_version: TimelineVersion,
    /// Timeline version immediately after the commit.
    pub after_version: TimelineVersion,
    /// Explicit World-Time transition, when this commit advances time.
    pub world_time: Option<WorldTimeTransition>,
    /// Event identities appended by this commit.
    pub event_ids: Vec<EventId>,
    /// Logical Work transitions appended by this commit.
    pub work_transitions: Vec<LogicalWorkTransition>,
    /// Same-instant chronology consumption, when this commit completes Work.
    pub chronology_budget: Option<ChronologyBudgetConsumption>,
}

/// Compatibility name for callers that describe the ordered records as a
/// logical journal rather than individual commits.
pub type LogicalJournalRecord = LogicalCommit;

impl LogicalCommit {
    /// Returns the Timeline-local logical revision after this commit.
    #[must_use]
    pub const fn logical_revision(&self) -> StateRevision {
        self.after_version.state_revision
    }
}

/// One committed Event in authoritative Timeline-local order.
///
/// This read model is produced only after a successful commit. Its `event_seq`
/// is allocated by the commit adapter, never copied from `EventId` ordering or
/// supplied by Protocol.
#[derive(Clone, Debug, PartialEq)]
pub struct CommittedEvent {
    /// Technical Event identity carried by the validated proposal.
    pub id: EventId,
    /// Timeline containing this committed Event.
    pub timeline_id: TimelineId,
    /// Authoritative contiguous sequence assigned at commit.
    pub event_seq: EventSeq,
    /// Capability-owned Event semantic key.
    pub event_type: loom_core::EventTypeId,
    /// Event schema revision.
    pub schema_revision: loom_core::SchemaRevision,
    /// World semantic time carried by the committed Event.
    pub occurred_at: WorldInstant,
    /// Direct Entity associations frozen into the Event.
    pub participants: Vec<loom_protocol::EventParticipant>,
    /// Relationship associations frozen into the Event.
    pub relationship_refs: Vec<loom_protocol::EventRelationshipRef>,
    /// Causal references frozen into the Event.
    pub causal_links: Vec<loom_protocol::CausalLink>,
    /// Capability-owned payload frozen into history.
    pub payload: Value,
    /// Mechanical Effects applied to materialized state.
    pub effects: Vec<WorldEffect>,
}

impl CommittedEvent {
    /// Builds an authoritative read model from one proposal and assigned seq.
    #[must_use]
    pub fn from_proposed(
        timeline_id: TimelineId,
        event_seq: EventSeq,
        event: &ProposedEvent,
        occurred_at: WorldInstant,
    ) -> Self {
        Self {
            id: event.id,
            timeline_id,
            event_seq,
            event_type: event.event_type.clone(),
            schema_revision: event.schema_revision,
            occurred_at,
            participants: event.participants.clone(),
            relationship_refs: event.relationship_refs.clone(),
            causal_links: event.causal_links.clone(),
            payload: event.payload.clone(),
            effects: event.effects.clone(),
        }
    }

    /// Adds a persisted direct Entity association while rebuilding history.
    pub fn push_participant(&mut self, entity_id: EntityId, role: AssociationRole) {
        self.participants
            .push(loom_protocol::EventParticipant::new(entity_id, role));
    }

    /// Adds a persisted Relationship association while rebuilding history.
    pub fn push_relationship_ref(
        &mut self,
        relationship_id: RelationshipId,
        role: AssociationRole,
    ) {
        self.relationship_refs
            .push(loom_protocol::EventRelationshipRef::new(
                relationship_id,
                role,
            ));
    }

    /// Adds a persisted causal edge while rebuilding committed history.
    pub fn push_causal_link(&mut self, cause_event_id: EventId) {
        self.causal_links
            .push(loom_protocol::CausalLink::new(cause_event_id));
    }

    /// Returns the assigned sequence using the API-oriented name.
    #[must_use]
    pub const fn sequence(&self) -> EventSeq {
        self.event_seq
    }
}

/// Runtime-owned authority value for an explicit Timeline World-Time change.
///
/// The expected version and current time are both pinned by the caller. The
/// persistence port must compare them with the authoritative Timeline at its
/// linearization point before changing the logical revision.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AdvanceWorldTime {
    timeline_id: TimelineId,
    expected_version: TimelineVersion,
    current: WorldInstant,
    next: WorldInstant,
}

/// Validation or persistence failures for an explicit World-Time transition.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum WorldTimeError {
    /// The transition target is not strictly later than its source.
    NonMonotonic {
        current: WorldInstant,
        next: WorldInstant,
    },
    /// The Timeline does not exist in the persistence authority.
    TimelineNotFound { timeline_id: TimelineId },
    /// The expected logical position lost a race with another commit.
    TimelineConflict {
        expected: TimelineVersion,
        actual: TimelineVersion,
    },
    /// The expected source World Time no longer matches the Timeline.
    CurrentTimeMismatch {
        expected: WorldInstant,
        actual: WorldInstant,
    },
    /// The logical revision cannot be incremented.
    RevisionOverflow,
    /// The persistence authority could not complete the transition.
    StorageUnavailable { message: String },
}

impl fmt::Display for WorldTimeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NonMonotonic { current, next } => {
                write!(
                    formatter,
                    "World Time transition {current:?} -> {next:?} is not monotonic"
                )
            }
            Self::TimelineNotFound { timeline_id } => {
                write!(formatter, "Timeline {timeline_id} not found")
            }
            Self::TimelineConflict { expected, actual } => {
                write!(
                    formatter,
                    "Timeline CAS conflict: expected {expected:?}, actual {actual:?}"
                )
            }
            Self::CurrentTimeMismatch { expected, actual } => {
                write!(
                    formatter,
                    "World Time mismatch: expected {expected:?}, actual {actual:?}"
                )
            }
            Self::RevisionOverflow => formatter.write_str("Timeline revision overflow"),
            Self::StorageUnavailable { message } => formatter.write_str(message),
        }
    }
}

impl std::error::Error for WorldTimeError {}

impl AdvanceWorldTime {
    /// Validates and pins an explicit World-Time transition.
    ///
    /// # Errors
    ///
    /// Returns [`WorldTimeError::NonMonotonic`] when `next` does not strictly
    /// follow `current`.
    pub fn new(
        timeline_id: TimelineId,
        expected_version: TimelineVersion,
        current: WorldInstant,
        next: WorldInstant,
    ) -> Result<Self, WorldTimeError> {
        if next <= current {
            return Err(WorldTimeError::NonMonotonic { current, next });
        }
        Ok(Self {
            timeline_id,
            expected_version,
            current,
            next,
        })
    }

    #[must_use]
    pub const fn timeline_id(self) -> TimelineId {
        self.timeline_id
    }

    #[must_use]
    pub const fn expected_version(self) -> TimelineVersion {
        self.expected_version
    }

    #[must_use]
    pub const fn current(self) -> WorldInstant {
        self.current
    }

    #[must_use]
    pub const fn next(self) -> WorldInstant {
        self.next
    }
}

/// A coherent Runtime read snapshot of one Timeline.
///
/// `base` is suitable for constructing a [`BaseWorldView`]. `events` and
/// `works` and `journal` are read models from the same authority snapshot, so
/// callers never observe an Event ledger from one revision with materialized
/// state or logical history from another revision.
#[derive(Clone, Debug)]
pub struct TimelineSnapshot {
    /// Pinned materialized World state used by Runtime validation.
    pub base: BaseWorldSnapshot,
    /// Committed Event ledger in Timeline-local sequence order.
    pub events: Vec<CommittedEvent>,
    /// Durable Work records visible in this Timeline snapshot.
    pub works: Vec<WorkRecord>,
    /// Ordered Timeline Logical Commit records visible in this snapshot.
    pub journal: Vec<LogicalCommit>,
}

impl TimelineSnapshot {
    /// Creates a coherent Timeline snapshot from its Runtime read models.
    #[must_use]
    pub const fn new(
        base: BaseWorldSnapshot,
        events: Vec<CommittedEvent>,
        works: Vec<WorkRecord>,
    ) -> Self {
        Self {
            base,
            events,
            works,
            journal: Vec::new(),
        }
    }

    /// Creates a coherent Timeline snapshot including ordered logical
    /// history. The journal is copied from the same authority snapshot as the
    /// materialized state, Events and Work records.
    #[must_use]
    pub fn with_journal(
        base: BaseWorldSnapshot,
        events: Vec<CommittedEvent>,
        works: Vec<WorkRecord>,
        journal: Vec<LogicalCommit>,
    ) -> Self {
        Self {
            base,
            events,
            works,
            journal,
        }
    }

    /// Returns the ordered logical journal for historical reconstruction.
    #[must_use]
    pub fn logical_journal(&self) -> &[LogicalCommit] {
        &self.journal
    }

    /// Returns the pinned Timeline identity.
    #[must_use]
    pub const fn timeline_id(&self) -> TimelineId {
        self.base.timeline_id()
    }

    /// Returns the World identity containing this Timeline.
    #[must_use]
    pub const fn world_id(&self) -> loom_core::WorldId {
        self.base.world_id()
    }

    /// Returns the pinned optimistic-concurrency version.
    #[must_use]
    pub const fn version(&self) -> TimelineVersion {
        self.base.version()
    }

    /// Returns the pinned World semantic time.
    #[must_use]
    pub const fn world_time(&self) -> WorldInstant {
        self.base.world_time()
    }

    /// Creates the Runtime validation view for this coherent snapshot.
    #[must_use]
    pub fn world_view(&self) -> BaseWorldView {
        BaseWorldView::new(self.base.clone())
    }
}

/// Result of a successful atomic Timeline commit.
#[derive(Clone, Debug, PartialEq)]
pub struct CommitResult {
    /// Timeline targeted by the commit.
    pub timeline_id: TimelineId,
    /// Version after the commit linearization point. A successful commit with
    /// no Events, Work mutations or current-Work completion returns the
    /// unchanged version rather than advancing `state_revision`.
    pub version: TimelineVersion,
    /// Events appended by this commit, in assigned sequence order.
    pub events: Vec<CommittedEvent>,
    /// Current Work completed by this commit, if a claim was supplied.
    pub completed_work: Option<WorkId>,
}

/// A failure reading a Runtime Timeline snapshot.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ReadError {
    /// The requested Timeline does not exist in the adapter authority.
    TimelineNotFound { timeline_id: TimelineId },
    /// The persistence authority could not complete a coherent read.
    StorageUnavailable { message: String },
}

impl fmt::Display for ReadError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::TimelineNotFound { timeline_id } => {
                write!(formatter, "Timeline {timeline_id} was not found")
            }
            Self::StorageUnavailable { message } => formatter.write_str(message),
        }
    }
}

impl std::error::Error for ReadError {}

/// Typed failures for Durable Work claim, retry and completion checks.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum WorkError {
    /// The requested Timeline does not exist.
    TimelineNotFound { timeline_id: TimelineId },
    /// The requested Work does not exist in the Timeline.
    WorkNotFound {
        timeline_id: TimelineId,
        work_id: WorkId,
    },
    /// A token or proposal targets a different Timeline than the Work.
    TimelineMismatch {
        expected: TimelineId,
        actual: TimelineId,
    },
    /// Claiming/completing is only valid for Pending Work.
    NotPending { work_id: WorkId, status: WorkStatus },
    /// A live lease already owns this Pending Work.
    AlreadyClaimed {
        work_id: WorkId,
        claimed_until: PlatformTime,
    },
    /// The requested claim deadline is not after the supplied current time.
    InvalidLease {
        work_id: WorkId,
        now: PlatformTime,
        claimed_until: PlatformTime,
    },
    /// The Work is waiting for technical retry availability.
    NotAvailable {
        work_id: WorkId,
        available_at: PlatformTime,
        now: PlatformTime,
    },
    /// A worker attempted to commit at or after its lease deadline.
    LeaseExpired {
        work_id: WorkId,
        claimed_until: PlatformTime,
        now: PlatformTime,
    },
    /// The supplied claim fence no longer owns the Work.
    StaleClaim {
        work_id: WorkId,
        expected_fence: u64,
        actual_fence: Option<u64>,
    },
    /// The Work was expected to have a lease but none is stored.
    MissingLease { work_id: WorkId },
    /// The Work cannot represent another execution attempt.
    AttemptOverflow { work_id: WorkId },
    /// A Work identity would be scheduled twice in one atomic commit.
    DuplicateWork { work_id: WorkId },
    /// A Timeline cannot allocate another persistent logical Work order.
    LogicalScheduleOrderOverflow { timeline_id: TimelineId },
    /// A Timeline cannot represent another same-World-Time budget unit.
    ChronologyBudgetOverflow { timeline_id: TimelineId },
    /// A scheduled Work points at an Event absent from the staged ledger.
    MissingCausalEvent { work_id: WorkId, event_id: EventId },
    /// The persistence authority could not complete a Work I/O operation.
    StorageUnavailable { message: String },
}

impl fmt::Display for WorkError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::TimelineNotFound { timeline_id } => {
                write!(formatter, "Timeline {timeline_id} was not found")
            }
            Self::WorkNotFound {
                timeline_id,
                work_id,
            } => write!(
                formatter,
                "Work {work_id} was not found in Timeline {timeline_id}"
            ),
            Self::TimelineMismatch { expected, actual } => write!(
                formatter,
                "Work claim targets Timeline {actual}, expected {expected}"
            ),
            Self::NotPending { work_id, status } => {
                write!(formatter, "Work {work_id} is {status}, not Pending")
            }
            Self::AlreadyClaimed {
                work_id,
                claimed_until,
            } => write!(
                formatter,
                "Work {work_id} is leased until platform time {claimed_until}"
            ),
            Self::InvalidLease {
                work_id,
                now,
                claimed_until,
            } => write!(
                formatter,
                "Work {work_id} lease deadline {claimed_until} is not after now {now}"
            ),
            Self::NotAvailable {
                work_id,
                available_at,
                now,
            } => write!(
                formatter,
                "Work {work_id} is unavailable until platform time {available_at}, now {now}"
            ),
            Self::LeaseExpired {
                work_id,
                claimed_until,
                now,
            } => write!(
                formatter,
                "Work {work_id} lease expired at {claimed_until}; commit time is {now}"
            ),
            Self::StaleClaim {
                work_id,
                expected_fence,
                actual_fence,
            } => write!(
                formatter,
                "Work {work_id} claim fence {expected_fence} is stale; stored fence {actual_fence:?}"
            ),
            Self::MissingLease { work_id } => {
                write!(formatter, "Work {work_id} has no active lease")
            }
            Self::AttemptOverflow { work_id } => {
                write!(formatter, "Work {work_id} attempt count overflowed")
            }
            Self::DuplicateWork { work_id } => {
                write!(formatter, "Work {work_id} is scheduled more than once")
            }
            Self::LogicalScheduleOrderOverflow { timeline_id } => write!(
                formatter,
                "Timeline {timeline_id} logical Work schedule order overflowed"
            ),
            Self::ChronologyBudgetOverflow { timeline_id } => write!(
                formatter,
                "Timeline {timeline_id} chronology budget overflowed"
            ),
            Self::MissingCausalEvent { work_id, event_id } => write!(
                formatter,
                "Work {work_id} references missing causal Event {event_id}"
            ),
            Self::StorageUnavailable { message } => formatter.write_str(message),
        }
    }
}

impl std::error::Error for WorkError {}

/// Typed failures raised before the atomic commit swap.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CommitError {
    /// The validated token targets a missing Timeline.
    TimelineNotFound { timeline_id: TimelineId },
    /// The token's pinned version is stale at the commit linearization point.
    TimelineConflict {
        expected: TimelineVersion,
        actual: TimelineVersion,
    },
    /// A claim token targets a different Timeline than the validated token.
    TimelineMismatch {
        expected: TimelineId,
        actual: TimelineId,
    },
    /// An Event identity is already present in the Timeline ledger/batch.
    DuplicateEvent { event_id: EventId },
    /// A proposed Event or association violates the storage hard boundary.
    InvalidEvent { event_id: EventId, message: String },
    /// A frozen Effect cannot be applied to the staged materialized state.
    InvalidEffect { event_id: EventId, message: String },
    /// A Work mutation or current Work claim failed its typed checks.
    Work(WorkError),
    /// The persistence authority could not complete the atomic transaction.
    StorageUnavailable { message: String },
    /// The revision or Event sequence cannot be represented by its value type.
    RevisionOverflow,
}

impl fmt::Display for CommitError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::TimelineNotFound { timeline_id } => {
                write!(formatter, "Timeline {timeline_id} was not found")
            }
            Self::TimelineConflict { expected, actual } => write!(
                formatter,
                "Timeline CAS conflict: expected {expected:?}, actual {actual:?}"
            ),
            Self::TimelineMismatch { expected, actual } => write!(
                formatter,
                "commit claim targets Timeline {actual}, expected {expected}"
            ),
            Self::DuplicateEvent { event_id } => {
                write!(
                    formatter,
                    "Event {event_id} is already committed or duplicated"
                )
            }
            Self::InvalidEvent { event_id, message } => {
                write!(formatter, "Event {event_id} is invalid: {message}")
            }
            Self::InvalidEffect { event_id, message } => {
                write!(
                    formatter,
                    "Effect under Event {event_id} is invalid: {message}"
                )
            }
            Self::Work(error) => error.fmt(formatter),
            Self::StorageUnavailable { message } => formatter.write_str(message),
            Self::RevisionOverflow => {
                formatter.write_str("Timeline revision or Event sequence overflow")
            }
        }
    }
}

impl std::error::Error for CommitError {}

impl From<WorkError> for CommitError {
    fn from(value: WorkError) -> Self {
        Self::Work(value)
    }
}

/// Result of atomically creating one World and its initial Timeline.
///
/// This is Runtime lifecycle metadata, not a domain Event or mutable World
/// proposal. A successful value means the persistence adapter has durably
/// established both identities as one bootstrap operation. Empty lifecycle
/// creation returns version zero; Template birth returns the final version after
/// its validated bootstrap mutations. Future truth changes must use the normal
/// validated commit path.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct WorldCreation {
    world_id: WorldId,
    timeline_id: TimelineId,
    version: TimelineVersion,
    world_time: WorldInstant,
}

impl WorldCreation {
    /// Creates the canonical empty-Timeline lifecycle result.
    #[must_use]
    pub fn new(world_id: WorldId, timeline_id: TimelineId, world_time: WorldInstant) -> Self {
        Self::with_version(
            world_id,
            timeline_id,
            TimelineVersion::new(EventSeq::new(0), StateRevision::new(0)),
            world_time,
        )
    }

    /// Creates a lifecycle result with the final version of an atomic birth.
    ///
    /// The version is supplied only by a persistence adapter after its one
    /// authority transaction has applied all validated bootstrap mutations.
    #[must_use]
    pub const fn with_version(
        world_id: WorldId,
        timeline_id: TimelineId,
        version: TimelineVersion,
        world_time: WorldInstant,
    ) -> Self {
        Self {
            world_id,
            timeline_id,
            version,
            world_time,
        }
    }

    /// Returns the newly persisted World identity.
    #[must_use]
    pub const fn world_id(self) -> WorldId {
        self.world_id
    }

    /// Returns the initial Timeline identity.
    #[must_use]
    pub const fn timeline_id(self) -> TimelineId {
        self.timeline_id
    }

    /// Returns the authoritative Timeline version after lifecycle/bootstrap.
    #[must_use]
    pub const fn version(self) -> TimelineVersion {
        self.version
    }

    /// Returns the explicit semantic World time selected for bootstrap.
    #[must_use]
    pub const fn world_time(self) -> WorldInstant {
        self.world_time
    }
}

/// Typed failures from Runtime-owned World lifecycle persistence.
///
/// Identity conflicts are distinct from infrastructure unavailability so the
/// public service can report a safe conflict without leaking database errors.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LifecycleError {
    /// The allocated World identity is already authoritative.
    WorldAlreadyExists { world_id: WorldId },
    /// The allocated Timeline identity is already authoritative.
    TimelineAlreadyExists { timeline_id: TimelineId },
    /// The persistence authority could not finish lifecycle bootstrap.
    StorageUnavailable { message: String },
}

impl fmt::Display for LifecycleError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::WorldAlreadyExists { world_id } => {
                write!(formatter, "World {world_id} already exists")
            }
            Self::TimelineAlreadyExists { timeline_id } => {
                write!(formatter, "Timeline {timeline_id} already exists")
            }
            Self::StorageUnavailable { message } => formatter.write_str(message),
        }
    }
}

impl std::error::Error for LifecycleError {}

/// Runtime-owned persistence port for structural World bootstrap.
///
/// Implementations must create the World identity and its initial Timeline in
/// one atomic operation. This port is intentionally separate from
/// [`CommitStore`]: the legacy lifecycle entrypoint establishes an empty
/// authority container, while Template birth accepts only Runtime-validated
/// resolutions and applies them in the same authority transaction. No entrypoint
/// fabricates a domain Event or accepts an unvalidated Resolution. Once created,
/// all later semantic mutation uses the normal Runtime commit authority.
pub trait WorldLifecycleStore {
    /// Atomically creates one World plus its initial empty Timeline.
    ///
    /// # Errors
    ///
    /// Returns a typed identity conflict or storage availability error. A
    /// failure must leave neither a partial World nor a partial Timeline.
    fn create_world(
        &self,
        world_id: WorldId,
        timeline_id: TimelineId,
        initial_world_time: WorldInstant,
    ) -> PersistenceFuture<'_, Result<WorldCreation, LifecycleError>>;

    /// Atomically creates one World, its initial Timeline and its immutable
    /// World Runtime Binding.
    ///
    /// This additive entrypoint is used by the empty compatibility birth path.
    /// The legacy [`Self::create_world`] entrypoint remains available so adapters
    /// can represent M3-era rows that are migrated explicitly through
    /// [`WorldRuntimeBindingStore::ensure_binding`]. Production adapters must
    /// associate the supplied binding in the same transaction/state swap as
    /// the World and initial Timeline.
    fn create_world_with_binding(
        &self,
        world_id: WorldId,
        timeline_id: TimelineId,
        initial_world_time: WorldInstant,
        binding: WorldRuntimeBinding,
    ) -> PersistenceFuture<'_, Result<WorldCreation, LifecycleError>> {
        let _ = binding;
        self.create_world(world_id, timeline_id, initial_world_time)
    }

    /// Atomically creates a World, its initial Timeline and Binding, then
    /// applies the already Runtime-validated bootstrap resolutions in order.
    ///
    /// The slice contains Runtime authority tokens produced from ordinary
    /// Action/Resolution validation. Adapters must apply all structural and
    /// semantic birth records in one transaction/state swap; this default is a
    /// deliberate failure rather than an empty-World fallback.
    fn create_world_with_bootstrap<'a>(
        &'a self,
        world_id: WorldId,
        timeline_id: TimelineId,
        initial_world_time: WorldInstant,
        binding: WorldRuntimeBinding,
        bootstrap: &'a [ValidatedResolution],
        now: PlatformTime,
    ) -> PersistenceFuture<'a, Result<WorldCreation, LifecycleError>> {
        let _ = (
            world_id,
            timeline_id,
            initial_world_time,
            binding,
            bootstrap,
            now,
        );
        Box::pin(async {
            Err(LifecycleError::StorageUnavailable {
                message: "atomic Template birth is unsupported by this persistence adapter"
                    .to_owned(),
            })
        })
    }
}

/// Runtime read port required by validation and public history projections.
pub trait WorldStore {
    /// Reads one coherent Timeline snapshot asynchronously.
    ///
    /// The returned base state, Event ledger and Work records correspond to
    /// one adapter snapshot. Implementations must not expose a mixture of
    /// revisions. The Future is executor-neutral and must not be exposed to
    /// Capability semantic code.
    ///
    /// # Errors
    ///
    /// Returns [`ReadError::TimelineNotFound`] when the Timeline is absent, or
    /// [`ReadError::StorageUnavailable`] when the authority cannot be read.
    fn snapshot(
        &self,
        timeline_id: TimelineId,
    ) -> PersistenceFuture<'_, Result<TimelineSnapshot, ReadError>>;

    /// Alias emphasizing the read-side operation for callers that use the
    /// port as a `read_snapshot` dependency.
    fn read_snapshot(
        &self,
        timeline_id: TimelineId,
    ) -> PersistenceFuture<'_, Result<TimelineSnapshot, ReadError>> {
        self.snapshot(timeline_id)
    }
}

/// Runtime-owned read port for deterministic Timeline Logical Commit history.
///
/// The returned vector is ordered by the persisted logical revision after each
/// commit. Implementations must read this history from the authority journal,
/// never reconstruct it from the current Work table or operational metadata.
pub trait LogicalJournalStore {
    /// Reads all logical commits for one Timeline in deterministic order.
    fn read_logical_journal(
        &self,
        timeline_id: TimelineId,
    ) -> PersistenceFuture<'_, Result<Vec<LogicalCommit>, ReadError>>;
}

/// Runtime-owned persistence port for World-level Runtime Binding metadata.
///
/// Binding reads are keyed by `WorldId`, never `TimelineId`, so every Timeline
/// branch of one World observes the same immutable descriptor independently of
/// its materialized state snapshot. `ensure_binding` is the explicit one-time
/// compatibility path for M3 Worlds whose rows predate this metadata; once a
/// descriptor exists, the supplied legacy candidate is ignored.
pub trait WorldRuntimeBindingStore {
    /// Reads the persisted immutable binding for one World.
    fn read_binding(
        &self,
        world_id: WorldId,
    ) -> PersistenceFuture<'_, Result<WorldRuntimeBinding, BindingError>>;

    /// Persists a binding exactly once for an existing World.
    ///
    /// Implementations must reject a second binding rather than overwrite the
    /// existing descriptor, which is the v0 immutability gate.
    fn persist_binding(
        &self,
        world_id: WorldId,
        binding: WorldRuntimeBinding,
    ) -> PersistenceFuture<'_, Result<(), BindingError>>;

    /// Reads an existing binding or atomically persists the supplied explicit
    /// legacy compatibility descriptor when the World predates bindings.
    fn ensure_binding(
        &self,
        world_id: WorldId,
        legacy_binding: WorldRuntimeBinding,
    ) -> PersistenceFuture<'_, Result<WorldRuntimeBinding, BindingError>>;
}

/// Runtime-owned port for explicit, monotonic World-Time transitions.
pub trait WorldTimeStore {
    /// Applies one transition using the expected Timeline version as CAS.
    fn advance_world_time(
        &self,
        transition: AdvanceWorldTime,
    ) -> PersistenceFuture<'_, Result<TimelineVersion, WorldTimeError>>;
}

/// Runtime commit port whose semantic input is exclusively authority-gated.
pub trait CommitStore {
    /// Atomically commits one Runtime-validated proposal.
    ///
    /// `resolution.base_version()` is the expected Timeline CAS version and
    /// `resolution.timeline_id()` is the immutable commit target. If
    /// `current_work` is present, the implementation must verify its Pending
    /// status, live lease and fence at the same linearization point. The
    /// supplied `now` is explicit platform time and is never World Time.
    /// When the validated Resolution is empty and no current Work claim is
    /// supplied, a successful no-op must leave the Timeline version and
    /// observable World/Work state unchanged.
    ///
    /// # Errors
    ///
    /// Returns a typed error before changing observable state. In particular,
    /// [`CommitError::TimelineConflict`] does not partially append Events or
    /// mutate State/Work.
    fn commit<'a>(
        &'a self,
        resolution: &'a ValidatedResolution,
        current_work: Option<&'a WorkClaim>,
        now: PlatformTime,
    ) -> PersistenceFuture<'a, Result<CommitResult, CommitError>>;
}

/// Runtime Work/claim port for operational metadata and current-Work fences.
pub trait WorkStore {
    /// Claims one Pending Work until an explicit platform deadline.
    ///
    /// Claiming only updates lease/attempt metadata. It does not change Work
    /// status or Timeline version. The returned Future is executor-neutral so
    /// SQL-backed adapters never need to block inside Runtime.
    ///
    /// # Errors
    ///
    /// Returns [`WorkError::AlreadyClaimed`], [`WorkError::NotAvailable`] or a
    /// typed identity/status/infrastructure error when the claim cannot linearize.
    fn claim(
        &self,
        timeline_id: TimelineId,
        work_id: WorkId,
        now: PlatformTime,
        claimed_until: PlatformTime,
    ) -> PersistenceFuture<'_, Result<WorkClaim, WorkError>>;

    /// Records a technical retry without changing World Truth.
    ///
    /// The same Work identity remains `Pending`; only platform availability,
    /// attempt metadata and the last error change. No Event, Facet, structure,
    /// Timeline version or World Time is advanced.
    ///
    /// # Errors
    ///
    /// Returns a typed stale/expired claim, Work lifecycle or infrastructure error.
    fn retry<'a>(
        &'a self,
        claim: &'a WorkClaim,
        now: PlatformTime,
        available_at: PlatformTime,
        last_error: Option<String>,
    ) -> PersistenceFuture<'a, Result<WorkRecord, WorkError>>;

    /// Reads one Work record from a Timeline.
    ///
    /// `Ok(None)` means the Timeline exists but has no such Work identity.
    ///
    /// # Errors
    ///
    /// Returns [`ReadError::TimelineNotFound`] for an unknown Timeline or a
    /// storage-unavailable error when the authority cannot be read.
    fn work(
        &self,
        timeline_id: TimelineId,
        work_id: WorkId,
    ) -> PersistenceFuture<'_, Result<Option<WorkRecord>, ReadError>>;
}

/// Runtime-owned persistence port for authorized logical Work terminalization.
///
/// Implementations must linearize the Timeline CAS, Pending-state check, lease
/// invalidation and Logical Journal append atomically. This port is distinct
/// from the untrusted Protocol `WorkMutation` surface so a Capability cannot
/// mark its own current Work `Dead` or `Cancelled`.
pub trait RuntimeControlStore {
    /// Applies one Pending -> Dead/Cancelled transition.
    fn terminalize_work<'a>(
        &'a self,
        terminalization: &'a WorkTerminalization,
    ) -> PersistenceFuture<'a, Result<TimelineVersion, CommitError>>;
}
