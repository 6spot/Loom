#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one marker, found {count}: {old[:80]!r}")
    write(path, content.replace(old, new, 1))


# loom-api: public World bootstrap contract and unified API aggregation.
api = "crates/loom-api/src/lib.rs"
replace_once(
    api,
    "/// A public request to resolve one semantic Action on a World Timeline.\n",
    '''/// Public request to create one empty Loom World and its initial Timeline.\n///\n/// World creation is structural bootstrap, not a domain Event and not a direct\n/// State mutation escape hatch. Runtime allocates the technical World/Timeline\n/// identities and asks its lifecycle persistence port to create them atomically.\n/// The only caller-controlled temporal value is `initial_world_time`, which is\n/// semantic World Time and is never inferred from platform/database time.\n///\n/// After creation, all semantic World mutations still flow through Actions or\n/// Durable Work into Runtime validation and the normal commit authority path.\n#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]\npub struct CreateWorldRequest {\n    /// Semantic time of the new Timeline before any committed Event exists.\n    pub initial_world_time: WorldInstant,\n}\n\nimpl CreateWorldRequest {\n    /// Creates a World bootstrap request at an explicit semantic World time.\n    #[must_use]\n    pub const fn new(initial_world_time: WorldInstant) -> Self {\n        Self { initial_world_time }\n    }\n}\n\n/// A public request to resolve one semantic Action on a World Timeline.\n''',
)
replace_once(
    api,
    "/// Executes semantic Actions against a World Timeline.\n",
    '''/// Creates long-lived World identity through the unified Loom API.\n///\n/// This service exposes only the semantic lifecycle boundary. Callers do not\n/// choose UUID algorithms, access storage transactions or obtain Runtime\n/// authority tokens. A successful creation returns the initial public Timeline\n/// snapshot with an empty version and the requested World semantic time.\n///\n/// World bootstrap itself is not a committed domain Event. Once the World\n/// exists, changing its truth requires the same semantic Action / Durable Work\n/// and Runtime commit path used by every other Timeline.\npub trait WorldService {\n    /// Creates one World and its initial Timeline atomically.\n    ///\n    /// # Errors\n    ///\n    /// Returns a conflict if Runtime-allocated identities already exist, or an\n    /// availability/internal error when lifecycle persistence cannot complete.\n    fn create_world(&self, request: CreateWorldRequest) -> ApiFuture<'_, TimelineSnapshot>;\n}\n\n/// Executes semantic Actions against a World Timeline.\n''',
)
replace_once(
    api,
    "/// This World-facing service is intentionally limited to observation. It does\n/// not create/fork Timelines or expose Runtime administration; those concerns\n/// belong to separate future contracts.\n",
    "/// This service is intentionally limited to observation. Initial World/Timeline\n/// creation belongs to [`WorldService`]; Timeline fork/ancestry remains a separate\n/// future contract rather than an inspection side effect.\n",
)
replace_once(
    api,
    '''pub trait LoomApi:\n    ActionService + CatalogService + HistoryService + QueryService + TimelineService\n{\n}\n\nimpl<T> LoomApi for T where\n    T: ActionService + CatalogService + HistoryService + QueryService + TimelineService\n{\n}\n''',
    '''pub trait LoomApi:\n    ActionService\n    + CatalogService\n    + HistoryService\n    + QueryService\n    + TimelineService\n    + WorldService\n{\n}\n\nimpl<T> LoomApi for T where\n    T: ActionService\n        + CatalogService\n        + HistoryService\n        + QueryService\n        + TimelineService\n        + WorldService\n{\n}\n''',
)
replace_once(
    api,
    '''        ApiResult, CapabilityDescriptor, CapabilityId, CatalogService, CatalogSnapshot,\n        CommittedEvent, EventQuery, ExecutionResult, FacetQuery, FacetSnapshot, HistoryService,\n        LoomApi, QueryService, TimelineService, TimelineSnapshot, TimelineTarget,\n''',
    '''        ApiResult, CapabilityDescriptor, CapabilityId, CatalogService, CatalogSnapshot,\n        CommittedEvent, CreateWorldRequest, EventQuery, ExecutionResult, FacetQuery,\n        FacetSnapshot, HistoryService, LoomApi, QueryService, TimelineService, TimelineSnapshot,\n        TimelineTarget, WorldService,\n''',
)
replace_once(
    api,
    "    impl ActionService for StubApi {\n",
    '''    impl WorldService for StubApi {\n        fn create_world(&self, request: CreateWorldRequest) -> ApiFuture<'_, TimelineSnapshot> {\n            Box::pin(async move {\n                Ok(TimelineSnapshot::new(\n                    target(),\n                    TimelineVersion::default(),\n                    request.initial_world_time,\n                ))\n            })\n        }\n    }\n\n    impl ActionService for StubApi {\n''',
)
replace_once(
    api,
    '''        let api = StubApi;\n        assert_complete_api(&api);\n\n        let result = api\n''',
    '''        let api = StubApi;\n        assert_complete_api(&api);\n\n        let created = api\n            .create_world(CreateWorldRequest::new(WorldInstant::new(11)))\n            .await\n            .expect("World should be creatable");\n        assert_eq!(created.target, target());\n        assert_eq!(created.version, TimelineVersion::default());\n        assert_eq!(created.world_time.value(), 11);\n\n        let result = api\n''',
)

# Runtime identity allocator is explicit, injectable, and implementation-owned.
write(
    "crates/loom-runtime/src/identity.rs",
    '''//! Runtime-owned technical identity allocation boundary.\n//!\n//! Core carries strong identity values but deliberately does not choose a clock\n//! or entropy source. Runtime owns when World/Timeline identities are allocated,\n//! while applications/tests may inject a deterministic allocator. Capability\n//! resolution and the public Loom API never receive the allocator itself.\n\nuse loom_core::{TimelineId, WorldId};\n\n/// Allocates fresh technical identities for Runtime-owned World lifecycle work.\n///\n/// Implementations select the UUID/time/random mechanism. Returned values are\n/// technical identity only: their ordering is not World history, their clock is\n/// not World Time, and possession of an ID grants no commit authority. Runtime\n/// requires non-nil results before lifecycle persistence is attempted.\npub trait IdentityAllocator {\n    /// Allocates a fresh World identity.\n    fn allocate_world_id(&self) -> WorldId;\n\n    /// Allocates a fresh Timeline identity.\n    fn allocate_timeline_id(&self) -> TimelineId;\n}\n\n/// Default Runtime allocator using RFC 9562 UUID version 7 identities.\n///\n/// UUIDv7's platform timestamp/randomness is used only to create sortable\n/// technical identifiers. It never determines semantic World Time or Timeline\n/// Event order; committed Event ordering remains `EventSeq`.\n#[derive(Clone, Copy, Debug, Default)]\npub struct UuidV7IdentityAllocator;\n\nimpl IdentityAllocator for UuidV7IdentityAllocator {\n    fn allocate_world_id(&self) -> WorldId {\n        WorldId::from_uuid(uuid::Uuid::now_v7())\n    }\n\n    fn allocate_timeline_id(&self) -> TimelineId {\n        TimelineId::from_uuid(uuid::Uuid::now_v7())\n    }\n}\n\n#[cfg(test)]\nmod tests {\n    use super::{IdentityAllocator, UuidV7IdentityAllocator};\n\n    #[test]\n    fn default_allocator_produces_non_nil_v7_identifiers() {\n        let allocator = UuidV7IdentityAllocator;\n        let world = allocator.allocate_world_id();\n        let timeline = allocator.allocate_timeline_id();\n\n        assert!(!world.is_nil());\n        assert!(!timeline.is_nil());\n        assert_eq!(world.as_uuid().get_version_num(), 7);\n        assert_eq!(timeline.as_uuid().get_version_num(), 7);\n        assert_ne!(world.to_string(), timeline.to_string());\n    }\n}\n''',
)

runtime_cargo = "crates/loom-runtime/Cargo.toml"
replace_once(runtime_cargo, 'serde_json = "1"\n', 'serde_json = "1"\nuuid = { version = "1", features = ["v7"] }\n')

runtime_lib = "crates/loom-runtime/src/lib.rs"
replace_once(runtime_lib, "mod budget;\n", "mod budget;\nmod identity;\n")
replace_once(
    runtime_lib,
    "pub use budget::{BudgetDimension, BudgetError, BudgetUsage, ResolutionBudget};\n",
    "pub use budget::{BudgetDimension, BudgetError, BudgetUsage, ResolutionBudget};\npub use identity::{IdentityAllocator, UuidV7IdentityAllocator};\n",
)
replace_once(
    runtime_lib,
    '''    CommitError, CommitResult, CommitStore, CommittedEvent, ManualPlatformClock, PersistenceFuture,\n    PlatformClock, PlatformTime, ReadError, TimelineSnapshot, WorkClaim, WorkError, WorkLease,\n    WorkRecord, WorkStatus, WorkStore, WorldStore,\n''',
    '''    CommitError, CommitResult, CommitStore, CommittedEvent, LifecycleError, ManualPlatformClock,\n    PersistenceFuture, PlatformClock, PlatformTime, ReadError, TimelineSnapshot, WorkClaim,\n    WorkError, WorkLease, WorkRecord, WorkStatus, WorkStore, WorldCreation, WorldLifecycleStore,\n    WorldStore,\n''',
)

persistence = "crates/loom-runtime/src/persistence.rs"
replace_once(
    persistence,
    '''    AssociationRole, EntityId, EventId, EventSeq, RelationshipId, TimelineId, TimelineVersion,\n    WorkHandlerId, WorkId, WorldEffect, WorldInstant,\n''',
    '''    AssociationRole, EntityId, EventId, EventSeq, RelationshipId, StateRevision, TimelineId,\n    TimelineVersion, WorkHandlerId, WorkId, WorldEffect, WorldId, WorldInstant,\n''',
)
replace_once(
    persistence,
    "/// Runtime read port required by validation and public history projections.\n",
    '''/// Result of atomically creating one World and its initial Timeline.\n///\n/// This is Runtime lifecycle metadata, not a domain Event or mutable World\n/// proposal. A successful value means the persistence adapter has durably\n/// established both identities as one bootstrap operation. The initial\n/// Timeline version is always zero by construction; future truth changes must\n/// use the normal validated commit path.\n#[derive(Clone, Copy, Debug, Eq, PartialEq)]\npub struct WorldCreation {\n    world_id: WorldId,\n    timeline_id: TimelineId,\n    version: TimelineVersion,\n    world_time: WorldInstant,\n}\n\nimpl WorldCreation {\n    /// Creates the canonical empty-Timeline lifecycle result.\n    #[must_use]\n    pub fn new(world_id: WorldId, timeline_id: TimelineId, world_time: WorldInstant) -> Self {\n        Self {\n            world_id,\n            timeline_id,\n            version: TimelineVersion::new(EventSeq::new(0), StateRevision::new(0)),\n            world_time,\n        }\n    }\n\n    /// Returns the newly persisted World identity.\n    #[must_use]\n    pub const fn world_id(self) -> WorldId {\n        self.world_id\n    }\n\n    /// Returns the initial Timeline identity.\n    #[must_use]\n    pub const fn timeline_id(self) -> TimelineId {\n        self.timeline_id\n    }\n\n    /// Returns the authoritative empty Timeline version.\n    #[must_use]\n    pub const fn version(self) -> TimelineVersion {\n        self.version\n    }\n\n    /// Returns the explicit semantic World time selected for bootstrap.\n    #[must_use]\n    pub const fn world_time(self) -> WorldInstant {\n        self.world_time\n    }\n}\n\n/// Typed failures from Runtime-owned World lifecycle persistence.\n///\n/// Identity conflicts are distinct from infrastructure unavailability so the\n/// public service can report a safe conflict without leaking database errors.\n#[derive(Clone, Debug, Eq, PartialEq)]\npub enum LifecycleError {\n    /// The allocated World identity is already authoritative.\n    WorldAlreadyExists { world_id: WorldId },\n    /// The allocated Timeline identity is already authoritative.\n    TimelineAlreadyExists { timeline_id: TimelineId },\n    /// The persistence authority could not finish lifecycle bootstrap.\n    StorageUnavailable { message: String },\n}\n\nimpl fmt::Display for LifecycleError {\n    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {\n        match self {\n            Self::WorldAlreadyExists { world_id } => {\n                write!(formatter, "World {world_id} already exists")\n            }\n            Self::TimelineAlreadyExists { timeline_id } => {\n                write!(formatter, "Timeline {timeline_id} already exists")\n            }\n            Self::StorageUnavailable { message } => formatter.write_str(message),\n        }\n    }\n}\n\nimpl std::error::Error for LifecycleError {}\n\n/// Runtime-owned persistence port for structural World bootstrap.\n///\n/// Implementations must create the World identity and its initial Timeline in\n/// one atomic operation. This port is intentionally separate from\n/// [`CommitStore`]: bootstrap establishes the empty authority container and does\n/// not fabricate a domain Event or accept an unvalidated Resolution. Once\n/// created, all semantic mutation uses the normal Runtime commit authority.\npub trait WorldLifecycleStore {\n    /// Atomically creates one World plus its initial empty Timeline.\n    ///\n    /// # Errors\n    ///\n    /// Returns a typed identity conflict or storage availability error. A\n    /// failure must leave neither a partial World nor a partial Timeline.\n    fn create_world(\n        &self,\n        world_id: WorldId,\n        timeline_id: TimelineId,\n        initial_world_time: WorldInstant,\n    ) -> PersistenceFuture<'_, Result<WorldCreation, LifecycleError>>;\n}\n\n/// Runtime read port required by validation and public history projections.\n''',
)

orchestration = "crates/loom-runtime/src/orchestration.rs"
replace_once(
    orchestration,
    '''    ActionDescriptor, ActionRequest, ActionService, ApiError, ApiFuture, ApiResult, CatalogService,\n    CatalogSnapshot, CommittedEvent as ApiCommittedEvent, EventQuery, ExecutionResult, FacetQuery,\n    FacetSnapshot as ApiFacetSnapshot, HistoryService, QueryService, TimelineService,\n    TimelineSnapshot as ApiTimelineSnapshot, TimelineTarget,\n''',
    '''    ActionDescriptor, ActionRequest, ActionService, ApiError, ApiFuture, ApiResult, CatalogService,\n    CatalogSnapshot, CommittedEvent as ApiCommittedEvent, CreateWorldRequest, EventQuery,\n    ExecutionResult, FacetQuery, FacetSnapshot as ApiFacetSnapshot, HistoryService, QueryService,\n    TimelineService, TimelineSnapshot as ApiTimelineSnapshot, TimelineTarget, WorldService,\n''',
)
replace_once(
    orchestration,
    '''    BudgetUsage, CallProvenance, CommitError, CommitStore, CommittedEvent, EffectEngine,\n    ManualPlatformClock, PersistenceFuture, PlatformClock, PlatformTime, ReadError,\n    ResolutionBudget, RuntimeError, TimelineSnapshot, ValidatedResolution, ValidationError,\n    WorkClaim, WorkError, WorkRecord, WorkStore, WorldStore,\n''',
    '''    BudgetUsage, CallProvenance, CommitError, CommitStore, CommittedEvent, EffectEngine,\n    IdentityAllocator, LifecycleError, ManualPlatformClock, PersistenceFuture, PlatformClock,\n    PlatformTime, ReadError, ResolutionBudget, RuntimeError, TimelineSnapshot,\n    UuidV7IdentityAllocator, ValidatedResolution, ValidationError, WorkClaim, WorkError, WorkRecord,\n    WorkStore, WorldLifecycleStore, WorldStore,\n''',
)
replace_once(
    orchestration,
    '''    platform_clock: Arc<dyn PlatformClock>,\n    resolution_budget: ResolutionBudget,\n''',
    '''    platform_clock: Arc<dyn PlatformClock>,\n    identity_allocator: Arc<dyn IdentityAllocator>,\n    resolution_budget: ResolutionBudget,\n''',
)
replace_once(
    orchestration,
    '''            registry,\n            store,\n            platform_clock: Arc::new(ManualPlatformClock::default()),\n            resolution_budget: ResolutionBudget::unlimited(),\n''',
    '''            registry,\n            store,\n            platform_clock: Arc::new(ManualPlatformClock::default()),\n            identity_allocator: Arc::new(UuidV7IdentityAllocator),\n            resolution_budget: ResolutionBudget::unlimited(),\n''',
)
replace_once(
    orchestration,
    '''    /// Injects the Runtime policy limiting one root Resolution execution.\n''',
    '''    /// Injects the Runtime-owned technical identity allocator.\n    ///\n    /// Applications normally use the UUIDv7 default. Tests and deterministic\n    /// composition roots can supply a controlled allocator without exposing it\n    /// through `loom-api` or Capability resolution. The allocator supplies\n    /// identity only; it does not supply World Time or commit authority.\n    #[must_use]\n    pub fn with_identity_allocator<A>(mut self, allocator: A) -> Self\n    where\n        A: IdentityAllocator + 'static,\n    {\n        self.identity_allocator = Arc::new(allocator);\n        self\n    }\n\n    /// Injects the Runtime policy limiting one root Resolution execution.\n''',
)
replace_once(
    orchestration,
    "impl<T> WorldStore for &T\n",
    '''impl<T> WorldLifecycleStore for &T\nwhere\n    T: WorldLifecycleStore + ?Sized,\n{\n    fn create_world(\n        &self,\n        world_id: loom_core::WorldId,\n        timeline_id: TimelineId,\n        initial_world_time: loom_core::WorldInstant,\n    ) -> PersistenceFuture<'_, Result<crate::WorldCreation, LifecycleError>> {\n        (**self).create_world(world_id, timeline_id, initial_world_time)\n    }\n}\n\nimpl<T> WorldStore for &T\n''',
)
replace_once(
    orchestration,
    "impl<S> ActionService for Runtime<S>\n",
    '''impl<S> WorldService for Runtime<S>\nwhere\n    S: WorldStore + CommitStore + WorkStore + WorldLifecycleStore,\n{\n    fn create_world(&self, request: CreateWorldRequest) -> ApiFuture<'_, ApiTimelineSnapshot> {\n        Box::pin(async move {\n            let world_id = self.identity_allocator.allocate_world_id();\n            let timeline_id = self.identity_allocator.allocate_timeline_id();\n            if world_id.is_nil() || timeline_id.is_nil() {\n                return Err(ApiError::internal(\n                    "Runtime identity allocator returned an invalid identity",\n                ));\n            }\n            let created = self\n                .store\n                .create_world(world_id, timeline_id, request.initial_world_time)\n                .await\n                .map_err(|error| map_lifecycle_error(&error))?;\n            let target = TimelineTarget::new(created.world_id(), created.timeline_id());\n            Ok(ApiTimelineSnapshot::new(\n                target,\n                created.version(),\n                created.world_time(),\n            ))\n        })\n    }\n}\n\nimpl<S> ActionService for Runtime<S>\n''',
)
replace_once(
    orchestration,
    "fn map_read_error(error: &ReadError) -> ApiError {\n",
    '''fn map_lifecycle_error(error: &LifecycleError) -> ApiError {\n    match error {\n        LifecycleError::WorldAlreadyExists { world_id } => {\n            ApiError::conflict(format!("World {world_id} already exists"))\n        }\n        LifecycleError::TimelineAlreadyExists { timeline_id } => {\n            ApiError::conflict(format!("Timeline {timeline_id} already exists"))\n        }\n        LifecycleError::StorageUnavailable { .. } => {\n            ApiError::unavailable("Persistence authority is temporarily unavailable")\n        }\n    }\n}\n\nfn map_read_error(error: &ReadError) -> ApiError {\n''',
)

# InMemoryStore lifecycle port uses the same staged-copy atomicity as commits.
in_memory = "crates/loom-storage/src/in_memory.rs"
replace_once(
    in_memory,
    '''    BaseWorldSnapshot, CommitError, CommitResult, CommitStore, CommittedEvent, PersistenceFuture,\n    PlatformTime, ProposedEvent, ReadError, TimelineSnapshot, ValidatedResolution, WorkClaim,\n    WorkError, WorkLease, WorkMutation, WorkRecord, WorkStatus, WorkStore, WorldStore,\n''',
    '''    BaseWorldSnapshot, CommitError, CommitResult, CommitStore, CommittedEvent, LifecycleError,\n    PersistenceFuture, PlatformTime, ProposedEvent, ReadError, TimelineSnapshot,\n    ValidatedResolution, WorkClaim, WorkError, WorkLease, WorkMutation, WorkRecord, WorkStatus,\n    WorkStore, WorldCreation, WorldLifecycleStore, WorldStore,\n''',
)
replace_once(
    in_memory,
    "impl WorldStore for InMemoryStore {\n",
    '''impl WorldLifecycleStore for InMemoryStore {\n    fn create_world(\n        &self,\n        world_id: WorldId,\n        timeline_id: TimelineId,\n        initial_world_time: WorldInstant,\n    ) -> PersistenceFuture<'_, Result<WorldCreation, LifecycleError>> {\n        Box::pin(async move {\n            let mut guard = self.write_state();\n            let mut staged = guard.clone();\n            if staged.worlds.contains(&world_id) {\n                return Err(LifecycleError::WorldAlreadyExists { world_id });\n            }\n            if staged.timelines.contains_key(&timeline_id) {\n                return Err(LifecycleError::TimelineAlreadyExists { timeline_id });\n            }\n\n            let mut timeline = TimelineState::empty(world_id, timeline_id);\n            timeline.world_time = initial_world_time;\n            staged.worlds.insert(world_id);\n            staged.timelines.insert(timeline_id, timeline);\n            *guard = staged;\n            Ok(WorldCreation::new(\n                world_id,\n                timeline_id,\n                initial_world_time,\n            ))\n        })\n    }\n}\n\nimpl WorldStore for InMemoryStore {\n''',
)

# PgStorage gets the minimum complete lifecycle implementation so Runtime<PgStorage>
# remains a complete LoomApi. T2 adds dedicated conflict/rollback integration gates.
postgres = "crates/loom-storage/src/postgres.rs"
replace_once(
    postgres,
    '''    BaseWorldSnapshot, CommittedEvent, PersistenceFuture, PlatformTime, ProposedEvent, ReadError,\n    TimelineSnapshot, WorkLease, WorkRecord, WorkStatus, WorldStore,\n''',
    '''    BaseWorldSnapshot, CommittedEvent, LifecycleError, PersistenceFuture, PlatformTime,\n    ProposedEvent, ReadError, TimelineSnapshot, WorkLease, WorkRecord, WorkStatus, WorldCreation,\n    WorldLifecycleStore, WorldStore,\n''',
)
replace_once(
    postgres,
    "impl WorldStore for PgStorage {\n",
    '''impl WorldLifecycleStore for PgStorage {\n    fn create_world(\n        &self,\n        world_id: WorldId,\n        timeline_id: TimelineId,\n        initial_world_time: WorldInstant,\n    ) -> PersistenceFuture<'_, Result<WorldCreation, LifecycleError>> {\n        Box::pin(async move {\n            let mut transaction = self.pool.begin().await.map_err(sql_lifecycle_error)?;\n\n            if let Err(error) = sqlx::query("INSERT INTO loom_world (world_id) VALUES ($1::uuid)")\n                .bind(world_id.to_string())\n                .execute(&mut *transaction)\n                .await\n            {\n                let _ = transaction.rollback().await;\n                if is_unique_violation(&error) {\n                    return Err(LifecycleError::WorldAlreadyExists { world_id });\n                }\n                return Err(sql_lifecycle_error(error));\n            }\n\n            if let Err(error) = sqlx::query(\n                "INSERT INTO loom_timeline \\\n                 (timeline_id, world_id, head_event_seq, state_revision, world_time) \\\n                 VALUES ($1::uuid, $2::uuid, 0, 0, $3)",\n            )\n            .bind(timeline_id.to_string())\n            .bind(world_id.to_string())\n            .bind(initial_world_time.value())\n            .execute(&mut *transaction)\n            .await\n            {\n                let _ = transaction.rollback().await;\n                if is_unique_violation(&error) {\n                    return Err(LifecycleError::TimelineAlreadyExists { timeline_id });\n                }\n                return Err(sql_lifecycle_error(error));\n            }\n\n            transaction.commit().await.map_err(sql_lifecycle_error)?;\n            Ok(WorldCreation::new(\n                world_id,\n                timeline_id,\n                initial_world_time,\n            ))\n        })\n    }\n}\n\nimpl WorldStore for PgStorage {\n''',
)
replace_once(
    postgres,
    "fn corrupt(message: impl Into<String>) -> ReadError {\n",
    '''fn sql_lifecycle_error(error: sqlx::Error) -> LifecycleError {\n    LifecycleError::StorageUnavailable {\n        message: format!("PostgreSQL lifecycle persistence failed: {error}"),\n    }\n}\n\nfn is_unique_violation(error: &sqlx::Error) -> bool {\n    error\n        .as_database_error()\n        .and_then(sqlx::error::DatabaseError::code)\n        .is_some_and(|code| code == "23505")\n}\n\nfn corrupt(message: impl Into<String>) -> ReadError {\n''',
)

# Focused composition contract: public create -> normal semantic Action -> conflict.
composition_cargo = "tests/loom-composition/Cargo.toml"
replace_once(
    composition_cargo,
    '''[[test]]\nname = "subresolution"\npath = "subresolution.rs"\n\n[lints]\n''',
    '''[[test]]\nname = "subresolution"\npath = "subresolution.rs"\n\n[[test]]\nname = "world_creation"\npath = "world_creation.rs"\n\n[lints]\n''',
)
write(
    "tests/loom-composition/world_creation.rs",
    '''use std::str::FromStr;\n\nuse loom_api::{\n    ActionRequest, ApiErrorCode, CreateWorldRequest, EventQuery, LoomApi, WorldService,\n};\nuse loom_capability::{\n    ActionDefinition, ActionResolver, Capability, CapabilityManifest, CapabilityRegistrar,\n    CapabilityRegistry, EventDefinition, RegistrationError, ResolutionContext, ResolverError,\n};\nuse loom_core::{\n    ActionTypeId, EntityId, EventId, EventTypeId, SchemaRevision, TimelineId, TimelineVersion,\n    WorldEffect, WorldId, WorldInstant,\n};\nuse loom_protocol::{ActionInvocation, ProposedEvent, Resolution, ResolveOutcome};\nuse loom_runtime::{IdentityAllocator, Runtime};\nuse loom_storage::InMemoryStore;\nuse serde_json::{Value, json};\n\nconst CAPABILITY: &str = "bootstrap.basic";\nconst ACTION: &str = "bootstrap.create_entity";\nconst EVENT: &str = "bootstrap.entity_created";\n\nfn id<T>(value: u128) -> T\nwhere\n    T: FromStr,\n    T::Err: std::fmt::Debug,\n{\n    format!("00000000-0000-0000-0000-{value:012x}")\n        .parse()\n        .expect("test identity should parse")\n}\n\n#[derive(Clone, Copy)]\nstruct FixedIdentityAllocator {\n    world_id: WorldId,\n    timeline_id: TimelineId,\n}\n\nimpl IdentityAllocator for FixedIdentityAllocator {\n    fn allocate_world_id(&self) -> WorldId {\n        self.world_id\n    }\n\n    fn allocate_timeline_id(&self) -> TimelineId {\n        self.timeline_id\n    }\n}\n\nstruct BootstrapCapability {\n    manifest: CapabilityManifest,\n}\n\nimpl Capability for BootstrapCapability {\n    fn manifest(&self) -> &CapabilityManifest {\n        &self.manifest\n    }\n\n    fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {\n        registrar.register_event(EventDefinition::new(\n            EventTypeId::from(EVENT),\n            SchemaRevision::new(1),\n        ))?;\n        registrar.register_action(\n            ActionDefinition::new(ActionTypeId::from(ACTION), SchemaRevision::new(1)),\n            CreateEntityResolver,\n        )?;\n        Ok(())\n    }\n}\n\nstruct CreateEntityResolver;\n\nimpl ActionResolver for CreateEntityResolver {\n    fn resolve(\n        &self,\n        context: &dyn ResolutionContext,\n        input: &Value,\n    ) -> Result<ResolveOutcome, ResolverError> {\n        let event_id = parse_id::<EventId>(input, "event_id")?;\n        let entity_id = parse_id::<EntityId>(input, "entity_id")?;\n        let event = ProposedEvent::new(\n            event_id,\n            EventTypeId::from(EVENT),\n            SchemaRevision::new(1),\n            context.world_time(),\n            json!({"entity_id": entity_id.to_string()}),\n        )\n        .with_effect(WorldEffect::CreateEntity { entity_id });\n        Ok(ResolveOutcome::Resolved(Resolution::new(\n            vec![event],\n            Vec::new(),\n        )))\n    }\n}\n\nfn parse_id<T>(input: &Value, field: &str) -> Result<T, ResolverError>\nwhere\n    T: FromStr,\n{\n    input\n        .get(field)\n        .and_then(Value::as_str)\n        .ok_or_else(|| ResolverError::new(format!("{field} must be a UUID string")))?\n        .parse()\n        .map_err(|_| ResolverError::new(format!("{field} must be a UUID string")))\n}\n\nfn registry() -> CapabilityRegistry {\n    CapabilityRegistry::assemble([BootstrapCapability {\n        manifest: CapabilityManifest::parse(CAPABILITY, "0.1.0")\n            .expect("bootstrap manifest should parse"),\n    }])\n    .expect("bootstrap registry should assemble")\n}\n\n#[tokio::test]\nasync fn public_world_creation_is_atomic_and_immediately_usable() {\n    let store = InMemoryStore::new();\n    let world_id = id::<WorldId>(0x3001);\n    let timeline_id = id::<TimelineId>(0x3002);\n    let runtime = Runtime::new(&store, registry())\n        .expect("Runtime should assemble")\n        .with_identity_allocator(FixedIdentityAllocator {\n            world_id,\n            timeline_id,\n        });\n    let api: &dyn LoomApi = &runtime;\n\n    let created = api\n        .create_world(CreateWorldRequest::new(WorldInstant::new(42)))\n        .await\n        .expect("public World creation should succeed");\n    assert_eq!(created.target.world_id, world_id);\n    assert_eq!(created.target.timeline_id, timeline_id);\n    assert_eq!(created.version, TimelineVersion::default());\n    assert_eq!(created.world_time, WorldInstant::new(42));\n\n    let event_id = id::<EventId>(0x3010);\n    let entity_id = id::<EntityId>(0x3020);\n    let committed = api\n        .invoke(ActionRequest::new(\n            created.target,\n            ActionInvocation::new(\n                ActionTypeId::from(ACTION),\n                json!({\n                    "event_id": event_id.to_string(),\n                    "entity_id": entity_id.to_string(),\n                }),\n            ),\n        ))\n        .await\n        .expect("created Timeline should immediately accept semantic Actions");\n    assert!(committed.is_committed());\n\n    let history = api\n        .list_events(EventQuery::all(created.target))\n        .await\n        .expect("created Timeline history should be readable");\n    assert_eq!(history.len(), 1);\n    assert_eq!(history[0].id, event_id);\n    assert_eq!(history[0].occurred_at, WorldInstant::new(42));\n    assert!(matches!(\n        history[0].effects.as_slice(),\n        [WorldEffect::CreateEntity { entity_id: actual }] if *actual == entity_id\n    ));\n\n    let duplicate = WorldService::create_world(\n        api,\n        CreateWorldRequest::new(WorldInstant::new(99)),\n    )\n    .await\n    .expect_err("deterministically reused World identity must conflict");\n    assert_eq!(duplicate.code, ApiErrorCode::Conflict);\n\n    let after_conflict = api\n        .inspect_timeline(created.target)\n        .await\n        .expect("failed bootstrap must not damage the existing Timeline");\n    assert_eq!(after_conflict.world_time, WorldInstant::new(42));\n    let history_after_conflict = api\n        .list_events(EventQuery::all(created.target))\n        .await\n        .expect("existing history should survive failed duplicate bootstrap");\n    assert_eq!(history_after_conflict, history);\n}\n''',
)

print("M3-T1 source transformation applied")
