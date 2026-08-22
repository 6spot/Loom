//! Single-state in-memory implementation of Runtime persistence ports.
//!
//! `InMemoryStore` is a Milestone 1 adapter and test backend. Its one
//! `RwLock<StoreState>` is the authority source for all World, Timeline, Event,
//! materialized State and Durable Work data. Every fallible write clones the
//! locked state, performs validation and application against that staged copy,
//! then swaps the complete copy exactly once. A returned error therefore
//! leaves the observable adapter state unchanged.

use std::{
    collections::{BTreeMap, HashMap, HashSet},
    fmt,
    sync::RwLock,
};

use loom_core::{
    Entity, EntityId, EventId, ExecutionSessionId, FacetOwner, FacetTypeId, Relationship,
    RelationshipId, TimelineId, TimelineVersion, WorldEffect, WorldId, WorldInstant,
};
use loom_runtime::{
    AdvanceWorldTime, BaseWorldSnapshot, BindingError, ChronologyBudgetConsumption, CommitError,
    CommitResult, CommitStore, CommittedEvent, ExecutionSession, ExecutionSessionStatus,
    ExecutionSessionStore, LifecycleError, LogicalCommit, LogicalJournalStore,
    LogicalWorkTransition, PersistenceFuture, PlatformTime, ProposedEvent, ReadError,
    RuntimeRevisionDescriptor, RuntimeRevisionError, RuntimeRevisionId, RuntimeRevisionSelection,
    RuntimeRevisionStore, SessionError, TimelineSnapshot, ValidatedResolution, WorkClaim,
    WorkError, WorkLease, WorkMutation, WorkRecord, WorkStatus, WorkStore, WorkTarget,
    WorldCreation, WorldLifecycleStore, WorldRuntimeBinding, WorldRuntimeBindingStore, WorldStore,
    WorldTimeError, WorldTimeStore,
};
use serde_json::Value;

type FacetKey = (FacetOwner, FacetTypeId);

#[derive(Clone, Debug)]
struct FacetRecord {
    schema_revision: loom_core::SchemaRevision,
    value: Value,
}

#[derive(Clone, Debug)]
struct RelationshipRecord {
    relationship: Relationship,
    active: bool,
}

#[derive(Clone, Debug)]
struct TimelineState {
    world_id: WorldId,
    timeline_id: TimelineId,
    version: TimelineVersion,
    world_time: WorldInstant,
    entities: HashMap<EntityId, Entity>,
    relationships: HashMap<RelationshipId, RelationshipRecord>,
    facets: HashMap<FacetKey, FacetRecord>,
    events: Vec<CommittedEvent>,
    event_ids: HashSet<EventId>,
    works: HashMap<loom_core::WorkId, WorkRecord>,
    logical_schedule_order: u64,
    chronology_budget_consumed: u64,
    journal: Vec<LogicalCommit>,
}

impl TimelineState {
    fn empty(world_id: WorldId, timeline_id: TimelineId) -> Self {
        Self {
            world_id,
            timeline_id,
            version: TimelineVersion::default(),
            world_time: WorldInstant::default(),
            entities: HashMap::new(),
            relationships: HashMap::new(),
            facets: HashMap::new(),
            events: Vec::new(),
            event_ids: HashSet::new(),
            works: HashMap::new(),
            logical_schedule_order: 0,
            chronology_budget_consumed: 0,
            journal: Vec::new(),
        }
    }
}

#[derive(Clone, Debug, Default)]
struct StoreState {
    worlds: HashSet<WorldId>,
    world_bindings: HashMap<WorldId, WorldRuntimeBinding>,
    timelines: HashMap<TimelineId, TimelineState>,
    runtime_revisions: BTreeMap<RuntimeRevisionId, RuntimeRevisionDescriptor>,
    active_runtime_revision: Option<RuntimeRevisionSelection>,
    execution_sessions: BTreeMap<ExecutionSessionId, ExecutionSession>,
}

/// Errors raised while creating or seeding an in-memory World fixture.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SetupError {
    /// The requested World identity already exists.
    WorldAlreadyExists { world_id: WorldId },
    /// The requested Timeline identity already exists.
    TimelineAlreadyExists { timeline_id: TimelineId },
    /// The requested Timeline does not exist.
    TimelineNotFound { timeline_id: TimelineId },
    /// A seeded structural record belongs to a different World.
    WorldMismatch { expected: WorldId, actual: WorldId },
    /// A seeded Entity identity already exists in the Timeline.
    EntityAlreadyExists { entity_id: EntityId },
    /// A seeded Relationship identity already exists in the Timeline.
    RelationshipAlreadyExists { relationship_id: RelationshipId },
    /// A seeded Work identity already exists in the Timeline.
    WorkAlreadyExists { work_id: loom_core::WorkId },
    /// A seeded Relationship participant is not yet an Entity in the Timeline.
    MissingEntity { entity_id: EntityId },
    /// A seeded Facet owner is absent from the Timeline.
    MissingFacetOwner { owner: FacetOwner },
}

impl fmt::Display for SetupError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::WorldAlreadyExists { world_id } => {
                write!(formatter, "World {world_id} already exists")
            }
            Self::TimelineAlreadyExists { timeline_id } => {
                write!(formatter, "Timeline {timeline_id} already exists")
            }
            Self::TimelineNotFound { timeline_id } => {
                write!(formatter, "Timeline {timeline_id} was not found")
            }
            Self::WorldMismatch { expected, actual } => write!(
                formatter,
                "record belongs to World {actual}, expected {expected}"
            ),
            Self::EntityAlreadyExists { entity_id } => {
                write!(formatter, "Entity {entity_id} already exists")
            }
            Self::RelationshipAlreadyExists { relationship_id } => {
                write!(formatter, "Relationship {relationship_id} already exists")
            }
            Self::WorkAlreadyExists { work_id } => {
                write!(formatter, "Work {work_id} already exists")
            }
            Self::MissingEntity { entity_id } => {
                write!(formatter, "Entity {entity_id} was not found")
            }
            Self::MissingFacetOwner { owner } => {
                write!(formatter, "Facet owner {owner:?} was not found")
            }
        }
    }
}

impl std::error::Error for SetupError {}

/// A concrete, synchronous in-memory implementation of Runtime persistence.
///
/// The adapter has no clock, async runtime, database or second semantic
/// authority. Callers supply platform-time values to claim, retry and commit.
pub struct InMemoryStore {
    state: RwLock<StoreState>,
}

impl Default for InMemoryStore {
    fn default() -> Self {
        Self::new()
    }
}

impl InMemoryStore {
    /// Creates an empty in-memory authority.
    #[must_use]
    pub fn new() -> Self {
        Self {
            state: RwLock::new(StoreState::default()),
        }
    }

    /// Persists one immutable started Session in the in-memory Platform
    /// History authority.
    ///
    /// # Errors
    ///
    /// Returns a typed duplicate or lifecycle error when the identity has
    /// already been recorded or the supplied value is not `Started`.
    pub fn start_session(&self, session: ExecutionSession) -> Result<(), SessionError> {
        let mut guard = self.write_state();
        let mut staged = guard.clone();
        let session_id = session.id();
        if staged.execution_sessions.contains_key(&session_id) {
            return Err(SessionError::SessionAlreadyExists { session_id });
        }
        if session.status() != ExecutionSessionStatus::Started {
            return Err(SessionError::InvalidTransition {
                session_id,
                from: session.status(),
                to: ExecutionSessionStatus::Started,
            });
        }
        staged.execution_sessions.insert(session_id, session);
        *guard = staged;
        Ok(())
    }

    /// Linearizes one terminal Session lifecycle transition.
    ///
    /// # Errors
    ///
    /// Returns a typed missing-Session or invalid-transition error when the
    /// identity is absent or already terminal.
    pub fn finish_session(
        &self,
        session_id: ExecutionSessionId,
        status: ExecutionSessionStatus,
        ended_at: PlatformTime,
    ) -> Result<ExecutionSession, SessionError> {
        let mut guard = self.write_state();
        let mut staged = guard.clone();
        let current = staged
            .execution_sessions
            .get(&session_id)
            .cloned()
            .ok_or(SessionError::SessionNotFound { session_id })?;
        if current.status() != ExecutionSessionStatus::Started {
            if current.status() == status {
                return Ok(current);
            }
            return Err(SessionError::InvalidTransition {
                session_id,
                from: current.status(),
                to: status,
            });
        }
        let finished = current.finish(status, ended_at)?;
        staged
            .execution_sessions
            .insert(session_id, finished.clone());
        *guard = staged;
        Ok(finished)
    }

    /// Reads one Session record without exposing mutable adapter state.
    ///
    /// # Errors
    ///
    /// Returns [`SessionError::SessionNotFound`] when the identity is absent.
    pub fn read_session(
        &self,
        session_id: ExecutionSessionId,
    ) -> Result<ExecutionSession, SessionError> {
        let guard = self.read_state();
        guard
            .execution_sessions
            .get(&session_id)
            .cloned()
            .ok_or(SessionError::SessionNotFound { session_id })
    }

    /// Reads all Session records in deterministic identity order.
    ///
    /// # Errors
    ///
    /// This operation currently has no expected in-memory failure, but keeps
    /// the port's typed error contract for adapter parity.
    pub fn list_sessions(&self) -> Result<Vec<ExecutionSession>, SessionError> {
        let guard = self.read_state();
        Ok(guard.execution_sessions.values().cloned().collect())
    }

    /// Registers one World identity for later Timeline creation.
    ///
    /// This is adapter/bootstrap setup, not a World mutation path. Runtime
    /// semantic State still changes only through a validated commit.
    ///
    /// # Errors
    ///
    /// Returns [`SetupError::WorldAlreadyExists`] when the identity is already
    /// registered.
    pub fn create_world(&self, world_id: WorldId) -> Result<(), SetupError> {
        let mut guard = self.write_state();
        let mut staged = guard.clone();
        if !staged.worlds.insert(world_id) {
            return Err(SetupError::WorldAlreadyExists { world_id });
        }
        *guard = staged;
        Ok(())
    }

    /// Creates an empty Timeline with version `(EventSeq(0), StateRevision(0))`.
    ///
    /// The World identity is registered automatically when this setup helper is
    /// used, which keeps small in-memory fixtures focused on their Timeline.
    ///
    /// # Errors
    ///
    /// Returns [`SetupError::TimelineAlreadyExists`] when the identity is
    /// already registered.
    pub fn create_timeline(
        &self,
        world_id: WorldId,
        timeline_id: TimelineId,
    ) -> Result<(), SetupError> {
        let mut guard = self.write_state();
        let mut staged = guard.clone();
        if staged.timelines.contains_key(&timeline_id) {
            return Err(SetupError::TimelineAlreadyExists { timeline_id });
        }
        staged.worlds.insert(world_id);
        staged
            .timelines
            .insert(timeline_id, TimelineState::empty(world_id, timeline_id));
        *guard = staged;
        Ok(())
    }

    /// Seeds an Entity into a bootstrap Timeline fixture.
    ///
    /// Production Runtime code must create identities through a committed
    /// `WorldEffect`; this helper exists only to construct an initial snapshot
    /// for validation/adapter tests.
    ///
    /// # Errors
    ///
    /// Returns a setup error when the Timeline is missing, the Entity belongs
    /// to another World or its identity is already present.
    pub fn seed_entity(&self, timeline_id: TimelineId, entity: Entity) -> Result<(), SetupError> {
        let mut guard = self.write_state();
        let mut staged = guard.clone();
        let timeline = staged
            .timelines
            .get_mut(&timeline_id)
            .ok_or(SetupError::TimelineNotFound { timeline_id })?;
        if entity.world_id != timeline.world_id {
            return Err(SetupError::WorldMismatch {
                expected: timeline.world_id,
                actual: entity.world_id,
            });
        }
        if timeline.entities.contains_key(&entity.id) {
            return Err(SetupError::EntityAlreadyExists {
                entity_id: entity.id,
            });
        }
        timeline.entities.insert(entity.id, entity);
        *guard = staged;
        Ok(())
    }

    /// Seeds a Relationship into a bootstrap Timeline fixture.
    ///
    /// # Errors
    ///
    /// Returns a setup error when the Timeline or participant Entity is
    /// missing, the Relationship belongs to another World or its identity is
    /// already present.
    pub fn seed_relationship(
        &self,
        timeline_id: TimelineId,
        relationship: Relationship,
        active: bool,
    ) -> Result<(), SetupError> {
        let mut guard = self.write_state();
        let mut staged = guard.clone();
        let timeline = staged
            .timelines
            .get_mut(&timeline_id)
            .ok_or(SetupError::TimelineNotFound { timeline_id })?;
        if relationship.world_id != timeline.world_id {
            return Err(SetupError::WorldMismatch {
                expected: timeline.world_id,
                actual: relationship.world_id,
            });
        }
        if timeline.relationships.contains_key(&relationship.id) {
            return Err(SetupError::RelationshipAlreadyExists {
                relationship_id: relationship.id,
            });
        }
        for participant in relationship.participants() {
            if !timeline.entities.contains_key(&participant.entity_id) {
                return Err(SetupError::MissingEntity {
                    entity_id: participant.entity_id,
                });
            }
        }
        timeline.relationships.insert(
            relationship.id,
            RelationshipRecord {
                relationship,
                active,
            },
        );
        *guard = staged;
        Ok(())
    }

    /// Seeds one current Facet value into a bootstrap Timeline fixture.
    ///
    /// # Errors
    ///
    /// Returns [`SetupError::TimelineNotFound`] or
    /// [`SetupError::MissingFacetOwner`] when the target is unavailable.
    pub fn seed_facet(
        &self,
        timeline_id: TimelineId,
        owner: FacetOwner,
        facet_type: FacetTypeId,
        schema_revision: loom_core::SchemaRevision,
        value: Value,
    ) -> Result<(), SetupError> {
        let mut guard = self.write_state();
        let mut staged = guard.clone();
        let timeline = staged
            .timelines
            .get_mut(&timeline_id)
            .ok_or(SetupError::TimelineNotFound { timeline_id })?;
        if !owner_exists(timeline, owner) {
            return Err(SetupError::MissingFacetOwner { owner });
        }
        timeline.facets.insert(
            (owner, facet_type),
            FacetRecord {
                schema_revision,
                value,
            },
        );
        *guard = staged;
        Ok(())
    }

    /// Seeds a pending Work item into a bootstrap Timeline fixture.
    ///
    /// # Errors
    ///
    /// Returns [`SetupError::TimelineNotFound`] or
    /// [`SetupError::WorkAlreadyExists`] when the target is unavailable.
    pub fn seed_work(&self, work: WorkRecord) -> Result<(), SetupError> {
        let mut guard = self.write_state();
        let mut staged = guard.clone();
        let timeline =
            staged
                .timelines
                .get_mut(&work.timeline_id)
                .ok_or(SetupError::TimelineNotFound {
                    timeline_id: work.timeline_id,
                })?;
        if timeline.works.contains_key(&work.id) {
            return Err(SetupError::WorkAlreadyExists { work_id: work.id });
        }
        timeline.logical_schedule_order = timeline
            .logical_schedule_order
            .max(work.logical_schedule_order);
        timeline.works.insert(work.id, work);
        *guard = staged;
        Ok(())
    }

    /// Reads one coherent Timeline snapshot through the Runtime read port.
    ///
    /// # Errors
    ///
    /// Returns [`ReadError::TimelineNotFound`] when the Timeline is absent.
    pub fn snapshot(&self, timeline_id: TimelineId) -> Result<TimelineSnapshot, ReadError> {
        let guard = self.read_state();
        let timeline = guard
            .timelines
            .get(&timeline_id)
            .ok_or(ReadError::TimelineNotFound { timeline_id })?;
        Ok(snapshot_from_timeline(timeline))
    }

    /// Reads the Timeline Logical Commit journal in its persisted logical
    /// revision order.
    ///
    /// # Errors
    ///
    /// Returns [`ReadError::TimelineNotFound`] when the Timeline is absent.
    pub fn read_logical_journal(
        &self,
        timeline_id: TimelineId,
    ) -> Result<Vec<LogicalCommit>, ReadError> {
        let guard = self.read_state();
        let timeline = guard
            .timelines
            .get(&timeline_id)
            .ok_or(ReadError::TimelineNotFound { timeline_id })?;
        Ok(timeline.journal.clone())
    }

    /// Reads the immutable World-level Runtime Binding independently of any
    /// Timeline materialized-state snapshot.
    ///
    /// # Errors
    ///
    /// Returns [`BindingError::WorldNotFound`] when the World is absent or
    /// [`BindingError::BindingNotFound`] for an unmigrated M3 World.
    pub fn read_binding(&self, world_id: WorldId) -> Result<WorldRuntimeBinding, BindingError> {
        let guard = self.read_state();
        if !guard.worlds.contains(&world_id) {
            return Err(BindingError::WorldNotFound { world_id });
        }
        guard
            .world_bindings
            .get(&world_id)
            .cloned()
            .ok_or(BindingError::BindingNotFound { world_id })
    }

    /// Persists one World Runtime Binding without an overwrite path.
    ///
    /// # Errors
    ///
    /// Returns [`BindingError::WorldNotFound`] when the World is absent or
    /// [`BindingError::BindingAlreadyExists`] when v0 immutability rejects the
    /// second descriptor.
    pub fn persist_binding(
        &self,
        world_id: WorldId,
        binding: WorldRuntimeBinding,
    ) -> Result<(), BindingError> {
        let mut guard = self.write_state();
        let mut staged = guard.clone();
        if !staged.worlds.contains(&world_id) {
            return Err(BindingError::WorldNotFound { world_id });
        }
        if staged.world_bindings.contains_key(&world_id) {
            return Err(BindingError::BindingAlreadyExists { world_id });
        }
        staged.world_bindings.insert(world_id, binding);
        *guard = staged;
        Ok(())
    }

    /// Reads a binding or performs the explicit one-time M3 compatibility
    /// migration for a World whose binding row predates the current schema.
    ///
    /// # Errors
    ///
    /// Returns [`BindingError::WorldNotFound`] when the World is absent.
    pub fn ensure_binding(
        &self,
        world_id: WorldId,
        legacy_binding: WorldRuntimeBinding,
    ) -> Result<WorldRuntimeBinding, BindingError> {
        let mut guard = self.write_state();
        let mut staged = guard.clone();
        if !staged.worlds.contains(&world_id) {
            return Err(BindingError::WorldNotFound { world_id });
        }
        if let Some(binding) = staged.world_bindings.get(&world_id) {
            return Ok(binding.clone());
        }
        staged
            .world_bindings
            .insert(world_id, legacy_binding.clone());
        *guard = staged;
        Ok(legacy_binding)
    }

    /// Publishes one immutable Runtime Revision descriptor.
    ///
    /// # Errors
    ///
    /// Returns [`RuntimeRevisionError::RevisionAlreadyExists`] when the stable
    /// identity has already been published.
    pub fn register_revision(
        &self,
        revision: RuntimeRevisionDescriptor,
    ) -> Result<(), RuntimeRevisionError> {
        let mut guard = self.write_state();
        let mut staged = guard.clone();
        let revision_id = revision.id().clone();
        if staged
            .runtime_revisions
            .insert(revision_id.clone(), revision)
            .is_some()
        {
            return Err(RuntimeRevisionError::RevisionAlreadyExists { revision_id });
        }
        *guard = staged;
        Ok(())
    }

    /// Confirms an existing immutable descriptor or registers it when absent.
    ///
    /// # Errors
    ///
    /// Returns [`RuntimeRevisionError::RevisionDescriptorMismatch`] when the
    /// supplied descriptor differs from the immutable publication.
    pub fn confirm_revision(
        &self,
        revision: RuntimeRevisionDescriptor,
    ) -> Result<RuntimeRevisionDescriptor, RuntimeRevisionError> {
        let mut guard = self.write_state();
        let mut staged = guard.clone();
        let revision_id = revision.id().clone();
        if let Some(existing) = staged.runtime_revisions.get(&revision_id) {
            if existing != &revision {
                return Err(RuntimeRevisionError::RevisionDescriptorMismatch { revision_id });
            }
            return Ok(existing.clone());
        }
        staged
            .runtime_revisions
            .insert(revision_id, revision.clone());
        *guard = staged;
        Ok(revision)
    }

    /// Reads one immutable Runtime Revision descriptor.
    ///
    /// # Errors
    ///
    /// Returns [`RuntimeRevisionError::RevisionNotFound`] when the identity is
    /// absent.
    pub fn read_revision(
        &self,
        revision_id: RuntimeRevisionId,
    ) -> Result<RuntimeRevisionDescriptor, RuntimeRevisionError> {
        let guard = self.read_state();
        guard
            .runtime_revisions
            .get(&revision_id)
            .cloned()
            .ok_or(RuntimeRevisionError::RevisionNotFound { revision_id })
    }

    /// Reads all immutable Runtime Revision descriptors in stable ID order.
    ///
    /// # Errors
    ///
    /// Returns a typed Runtime Revision persistence error.
    pub fn list_revisions(&self) -> Result<Vec<RuntimeRevisionDescriptor>, RuntimeRevisionError> {
        let guard = self.read_state();
        Ok(guard.runtime_revisions.values().cloned().collect())
    }

    /// Reads the active Runtime Revision selection without touching World data.
    ///
    /// # Errors
    ///
    /// Returns a typed Runtime Revision persistence error.
    pub fn read_active_revision(
        &self,
    ) -> Result<Option<RuntimeRevisionSelection>, RuntimeRevisionError> {
        let guard = self.read_state();
        Ok(guard.active_runtime_revision.clone())
    }

    /// Activates a known revision through an in-memory generation CAS.
    ///
    /// # Errors
    ///
    /// Returns a missing-revision, stale-generation or generation-overflow
    /// error without changing the active pointer.
    #[expect(
        clippy::needless_pass_by_value,
        reason = "matches the owned RuntimeRevisionStore activation port"
    )]
    pub fn activate_revision(
        &self,
        revision_id: RuntimeRevisionId,
        expected_generation: Option<u64>,
        activated_at: PlatformTime,
    ) -> Result<RuntimeRevisionSelection, RuntimeRevisionError> {
        let mut guard = self.write_state();
        let mut staged = guard.clone();
        let revision = staged
            .runtime_revisions
            .get(&revision_id)
            .cloned()
            .ok_or_else(|| RuntimeRevisionError::RevisionNotFound {
                revision_id: revision_id.clone(),
            })?;
        let actual_generation = staged
            .active_runtime_revision
            .as_ref()
            .map(RuntimeRevisionSelection::generation);
        if actual_generation != expected_generation {
            return Err(RuntimeRevisionError::ActiveRevisionConflict {
                expected_generation,
                actual_generation,
            });
        }
        let generation = actual_generation
            .unwrap_or_default()
            .checked_add(1)
            .ok_or(RuntimeRevisionError::ActivationGenerationOverflow)?;
        let selection = RuntimeRevisionSelection::new(revision, generation, activated_at);
        staged.active_runtime_revision = Some(selection.clone());
        *guard = staged;
        Ok(selection)
    }

    /// Reads one Work record without exposing the mutable adapter state.
    ///
    /// # Errors
    ///
    /// Returns [`ReadError::TimelineNotFound`] when the Timeline is absent.
    pub fn work(
        &self,
        timeline_id: TimelineId,
        work_id: loom_core::WorkId,
    ) -> Result<Option<WorkRecord>, ReadError> {
        let guard = self.read_state();
        let timeline = guard
            .timelines
            .get(&timeline_id)
            .ok_or(ReadError::TimelineNotFound { timeline_id })?;
        Ok(timeline.works.get(&work_id).cloned())
    }

    /// Atomically commits one Runtime-validated proposal.
    ///
    /// # Errors
    ///
    /// Returns a typed [`CommitError`] before swapping staged state when CAS,
    /// Event/Effect, Work or claim checks fail.
    #[expect(
        clippy::too_many_lines,
        reason = "the atomic in-memory commit keeps authority, Work and journal staging together"
    )]
    pub fn commit(
        &self,
        resolution: &ValidatedResolution,
        current_work: Option<&WorkClaim>,
        now: PlatformTime,
    ) -> Result<CommitResult, CommitError> {
        let mut guard = self.write_state();
        let mut staged = guard.clone();
        let timeline_id = resolution.timeline_id();
        let timeline = staged
            .timelines
            .get_mut(&timeline_id)
            .ok_or(CommitError::TimelineNotFound { timeline_id })?;

        if timeline.version != resolution.base_version() {
            return Err(CommitError::TimelineConflict {
                expected: resolution.base_version(),
                actual: timeline.version,
            });
        }
        if let Some(claim) = current_work {
            validate_claim(timeline, claim, now)?;
        }
        let before_version = timeline.version;
        let before_budget = timeline.chronology_budget_consumed;
        let changes_runtime_state = !resolution.events().is_empty()
            || !resolution.work().is_empty()
            || current_work.is_some();

        let mut committed_events = Vec::with_capacity(resolution.events().len());
        let mut event_ids = Vec::with_capacity(resolution.events().len());
        let mut seen_events = HashSet::new();
        let mut next_sequence = timeline.version.head_event_seq.value();
        for event in resolution.events() {
            *timeline = validate_event(timeline, event, &seen_events)?;
            next_sequence = next_sequence
                .checked_add(1)
                .ok_or(CommitError::RevisionOverflow)?;
            let committed = CommittedEvent::from_proposed(
                timeline.timeline_id,
                loom_core::EventSeq::new(next_sequence),
                event,
                resolution.pinned_world_time(),
            );
            timeline.events.push(committed.clone());
            timeline.event_ids.insert(event.id);
            seen_events.insert(event.id);
            event_ids.push(event.id);
            committed_events.push(committed);
        }

        let mut work_transitions = apply_work_mutations(
            timeline,
            resolution.work(),
            resolution.pinned_world_time(),
            now,
        )?;

        let completed_work = if let Some(claim) = current_work {
            work_transitions.push(complete_current_work(timeline, claim)?);
            Some(claim.work_id())
        } else {
            None
        };

        let chronology_budget = if current_work.is_some() {
            let after = before_budget.checked_add(1).ok_or(CommitError::Work(
                WorkError::ChronologyBudgetOverflow { timeline_id },
            ))?;
            timeline.chronology_budget_consumed = after;
            Some(ChronologyBudgetConsumption {
                world_time: timeline.world_time,
                before: before_budget,
                after,
            })
        } else {
            None
        };

        let next_state_revision = if changes_runtime_state {
            timeline
                .version
                .state_revision
                .value()
                .checked_add(1)
                .ok_or(CommitError::RevisionOverflow)?
        } else {
            timeline.version.state_revision.value()
        };
        let next_head = if committed_events.is_empty() {
            timeline.version.head_event_seq
        } else {
            loom_core::EventSeq::new(next_sequence)
        };
        timeline.version = TimelineVersion::new(
            next_head,
            loom_core::StateRevision::new(next_state_revision),
        );

        if changes_runtime_state {
            timeline.journal.push(LogicalCommit {
                timeline_id,
                before_version,
                after_version: timeline.version,
                world_time: None,
                event_ids,
                work_transitions,
                chronology_budget,
            });
        }

        let result = CommitResult {
            timeline_id,
            version: timeline.version,
            events: committed_events,
            completed_work,
        };
        *guard = staged;
        Ok(result)
    }

    /// Applies an explicit monotonic World-Time transition with Timeline CAS.
    ///
    /// # Errors
    ///
    /// Returns a typed World-Time error when the Timeline is missing, the
    /// expected version or current time is stale, or the revision overflows.
    pub fn advance_world_time(
        &self,
        transition: AdvanceWorldTime,
    ) -> Result<TimelineVersion, WorldTimeError> {
        let mut guard = self.write_state();
        let mut staged = guard.clone();
        let timeline = staged.timelines.get_mut(&transition.timeline_id()).ok_or(
            WorldTimeError::TimelineNotFound {
                timeline_id: transition.timeline_id(),
            },
        )?;
        if timeline.version != transition.expected_version() {
            return Err(WorldTimeError::TimelineConflict {
                expected: transition.expected_version(),
                actual: timeline.version,
            });
        }
        if timeline.world_time != transition.current() {
            return Err(WorldTimeError::CurrentTimeMismatch {
                expected: transition.current(),
                actual: timeline.world_time,
            });
        }
        let before_version = timeline.version;
        let state_revision = timeline
            .version
            .state_revision
            .value()
            .checked_add(1)
            .ok_or(WorldTimeError::RevisionOverflow)?;
        timeline.world_time = transition.next();
        timeline.chronology_budget_consumed = 0;
        timeline.version = TimelineVersion::new(
            timeline.version.head_event_seq,
            loom_core::StateRevision::new(state_revision),
        );
        timeline.journal.push(LogicalCommit {
            timeline_id: transition.timeline_id(),
            before_version,
            after_version: timeline.version,
            world_time: Some(loom_runtime::WorldTimeTransition {
                from: transition.current(),
                to: transition.next(),
            }),
            event_ids: Vec::new(),
            work_transitions: Vec::new(),
            chronology_budget: None,
        });
        let version = timeline.version;
        *guard = staged;
        Ok(version)
    }

    /// Claims one pending Work with explicit platform-time bounds.
    ///
    /// # Errors
    ///
    /// Returns a typed [`WorkError`] when the Work is unavailable, leased,
    /// expired, stale or not Pending.
    pub fn claim(
        &self,
        timeline_id: TimelineId,
        work_id: loom_core::WorkId,
        now: PlatformTime,
        claimed_until: PlatformTime,
    ) -> Result<WorkClaim, WorkError> {
        let mut guard = self.write_state();
        let mut staged = guard.clone();
        let timeline = staged
            .timelines
            .get_mut(&timeline_id)
            .ok_or(WorkError::TimelineNotFound { timeline_id })?;
        let work = timeline
            .works
            .get_mut(&work_id)
            .ok_or(WorkError::WorkNotFound {
                timeline_id,
                work_id,
            })?;
        if !work.is_pending() {
            return Err(WorkError::NotPending {
                work_id,
                status: work.status,
            });
        }
        if now < work.available_at {
            return Err(WorkError::NotAvailable {
                work_id,
                available_at: work.available_at,
                now,
            });
        }
        if let Some(lease) = work.lease
            && now < lease.claimed_until()
        {
            return Err(WorkError::AlreadyClaimed {
                work_id,
                claimed_until: lease.claimed_until(),
            });
        }
        if claimed_until <= now {
            return Err(WorkError::InvalidLease {
                work_id,
                now,
                claimed_until,
            });
        }
        let next_fence = work
            .claim_generation
            .checked_add(1)
            .ok_or(WorkError::AttemptOverflow { work_id })?;
        work.attempt_count = work
            .attempt_count
            .checked_add(1)
            .ok_or(WorkError::AttemptOverflow { work_id })?;
        work.claim_generation = next_fence;
        work.lease = Some(WorkLease::new(claimed_until, next_fence));
        let claim = WorkClaim::new(timeline_id, work_id, claimed_until, next_fence);
        *guard = staged;
        Ok(claim)
    }

    /// Updates technical retry metadata while preserving Work identity/status.
    ///
    /// # Errors
    ///
    /// Returns a typed [`WorkError`] when the supplied claim is stale, expired,
    /// missing or no longer Pending.
    pub fn retry(
        &self,
        claim: &WorkClaim,
        now: PlatformTime,
        available_at: PlatformTime,
        last_error: Option<String>,
    ) -> Result<WorkRecord, WorkError> {
        let mut guard = self.write_state();
        let mut staged = guard.clone();
        let timeline =
            staged
                .timelines
                .get_mut(&claim.timeline_id())
                .ok_or(WorkError::TimelineNotFound {
                    timeline_id: claim.timeline_id(),
                })?;
        validate_claim(timeline, claim, now)?;
        let work = timeline
            .works
            .get_mut(&claim.work_id())
            .ok_or(WorkError::WorkNotFound {
                timeline_id: claim.timeline_id(),
                work_id: claim.work_id(),
            })?;
        work.lease = None;
        work.available_at = available_at;
        work.last_error = last_error;
        let result = work.clone();
        *guard = staged;
        Ok(result)
    }

    fn read_state(&self) -> std::sync::RwLockReadGuard<'_, StoreState> {
        self.state
            .read()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    fn write_state(&self) -> std::sync::RwLockWriteGuard<'_, StoreState> {
        self.state
            .write()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

impl WorldLifecycleStore for InMemoryStore {
    fn create_world(
        &self,
        world_id: WorldId,
        timeline_id: TimelineId,
        initial_world_time: WorldInstant,
    ) -> PersistenceFuture<'_, Result<WorldCreation, LifecycleError>> {
        Box::pin(async move {
            self.create_world_internal(world_id, timeline_id, initial_world_time, None)
        })
    }

    fn create_world_with_binding(
        &self,
        world_id: WorldId,
        timeline_id: TimelineId,
        initial_world_time: WorldInstant,
        binding: WorldRuntimeBinding,
    ) -> PersistenceFuture<'_, Result<WorldCreation, LifecycleError>> {
        Box::pin(async move {
            self.create_world_internal(world_id, timeline_id, initial_world_time, Some(binding))
        })
    }

    fn create_world_with_bootstrap<'a>(
        &'a self,
        world_id: WorldId,
        timeline_id: TimelineId,
        initial_world_time: WorldInstant,
        binding: WorldRuntimeBinding,
        bootstrap: &'a [ValidatedResolution],
        now: PlatformTime,
    ) -> PersistenceFuture<'a, Result<WorldCreation, LifecycleError>> {
        Box::pin(async move {
            self.create_world_with_bootstrap_internal(
                world_id,
                timeline_id,
                initial_world_time,
                binding,
                bootstrap,
                now,
            )
        })
    }
}

impl InMemoryStore {
    fn create_world_internal(
        &self,
        world_id: WorldId,
        timeline_id: TimelineId,
        initial_world_time: WorldInstant,
        binding: Option<WorldRuntimeBinding>,
    ) -> Result<WorldCreation, LifecycleError> {
        let mut guard = self.write_state();
        let mut staged = guard.clone();
        if staged.worlds.contains(&world_id) {
            return Err(LifecycleError::WorldAlreadyExists { world_id });
        }
        if staged.timelines.contains_key(&timeline_id) {
            return Err(LifecycleError::TimelineAlreadyExists { timeline_id });
        }

        let mut timeline = TimelineState::empty(world_id, timeline_id);
        timeline.world_time = initial_world_time;
        staged.worlds.insert(world_id);
        if let Some(binding) = binding {
            staged.world_bindings.insert(world_id, binding);
        }
        staged.timelines.insert(timeline_id, timeline);
        *guard = staged;
        Ok(WorldCreation::new(
            world_id,
            timeline_id,
            initial_world_time,
        ))
    }

    fn create_world_with_bootstrap_internal(
        &self,
        world_id: WorldId,
        timeline_id: TimelineId,
        initial_world_time: WorldInstant,
        binding: WorldRuntimeBinding,
        bootstrap: &[ValidatedResolution],
        now: PlatformTime,
    ) -> Result<WorldCreation, LifecycleError> {
        let mut guard = self.write_state();
        let mut staged = guard.clone();
        if staged.worlds.contains(&world_id) {
            return Err(LifecycleError::WorldAlreadyExists { world_id });
        }
        if staged.timelines.contains_key(&timeline_id) {
            return Err(LifecycleError::TimelineAlreadyExists { timeline_id });
        }

        let mut timeline = TimelineState::empty(world_id, timeline_id);
        timeline.world_time = initial_world_time;
        staged.worlds.insert(world_id);
        staged.world_bindings.insert(world_id, binding);
        staged.timelines.insert(timeline_id, timeline);

        let timeline = staged
            .timelines
            .get_mut(&timeline_id)
            .expect("the birth Timeline was inserted above");
        let mut seen_events = HashSet::new();
        let mut next_sequence = timeline.version.head_event_seq.value();
        let mut changes_runtime_state = false;
        let mut event_ids = Vec::new();
        let mut work_transitions = Vec::new();

        for resolution in bootstrap {
            if resolution.timeline_id() != timeline_id
                || resolution.base_version() != TimelineVersion::default()
                || resolution.pinned_world_time() != initial_world_time
            {
                return Err(LifecycleError::StorageUnavailable {
                    message: "validated Template birth targets a different Timeline snapshot"
                        .to_owned(),
                });
            }
            for event in resolution.events() {
                *timeline = validate_event(timeline, event, &seen_events)
                    .map_err(|error| birth_commit_error(&error))?;
                next_sequence = next_sequence
                    .checked_add(1)
                    .ok_or_else(|| birth_commit_error(&CommitError::RevisionOverflow))?;
                let committed = CommittedEvent::from_proposed(
                    timeline.timeline_id,
                    loom_core::EventSeq::new(next_sequence),
                    event,
                    initial_world_time,
                );
                timeline.events.push(committed);
                timeline.event_ids.insert(event.id);
                seen_events.insert(event.id);
                event_ids.push(event.id);
                changes_runtime_state = true;
            }
            work_transitions.extend(
                apply_work_mutations(timeline, resolution.work(), initial_world_time, now)
                    .map_err(|error| birth_commit_error(&error))?,
            );
            changes_runtime_state |= !resolution.work().is_empty();
        }

        if changes_runtime_state {
            let state_revision = timeline
                .version
                .state_revision
                .value()
                .checked_add(1)
                .ok_or_else(|| birth_commit_error(&CommitError::RevisionOverflow))?;
            timeline.version = TimelineVersion::new(
                loom_core::EventSeq::new(next_sequence),
                loom_core::StateRevision::new(state_revision),
            );
            timeline.journal.push(LogicalCommit {
                timeline_id,
                before_version: TimelineVersion::default(),
                after_version: timeline.version,
                world_time: None,
                event_ids,
                work_transitions,
                chronology_budget: None,
            });
        }
        let version = timeline.version;
        *guard = staged;
        Ok(WorldCreation::with_version(
            world_id,
            timeline_id,
            version,
            initial_world_time,
        ))
    }
}

impl WorldStore for InMemoryStore {
    fn snapshot(
        &self,
        timeline_id: TimelineId,
    ) -> PersistenceFuture<'_, Result<TimelineSnapshot, ReadError>> {
        Box::pin(async move { InMemoryStore::snapshot(self, timeline_id) })
    }
}

impl LogicalJournalStore for InMemoryStore {
    fn read_logical_journal(
        &self,
        timeline_id: TimelineId,
    ) -> PersistenceFuture<'_, Result<Vec<LogicalCommit>, ReadError>> {
        Box::pin(async move { InMemoryStore::read_logical_journal(self, timeline_id) })
    }
}

impl WorldRuntimeBindingStore for InMemoryStore {
    fn read_binding(
        &self,
        world_id: WorldId,
    ) -> PersistenceFuture<'_, Result<WorldRuntimeBinding, BindingError>> {
        Box::pin(async move { InMemoryStore::read_binding(self, world_id) })
    }

    fn persist_binding(
        &self,
        world_id: WorldId,
        binding: WorldRuntimeBinding,
    ) -> PersistenceFuture<'_, Result<(), BindingError>> {
        Box::pin(async move { InMemoryStore::persist_binding(self, world_id, binding) })
    }

    fn ensure_binding(
        &self,
        world_id: WorldId,
        legacy_binding: WorldRuntimeBinding,
    ) -> PersistenceFuture<'_, Result<WorldRuntimeBinding, BindingError>> {
        Box::pin(async move { InMemoryStore::ensure_binding(self, world_id, legacy_binding) })
    }
}

impl RuntimeRevisionStore for InMemoryStore {
    fn register_revision(
        &self,
        revision: RuntimeRevisionDescriptor,
    ) -> PersistenceFuture<'_, Result<(), RuntimeRevisionError>> {
        Box::pin(async move { InMemoryStore::register_revision(self, revision) })
    }

    fn confirm_revision(
        &self,
        revision: RuntimeRevisionDescriptor,
    ) -> PersistenceFuture<'_, Result<RuntimeRevisionDescriptor, RuntimeRevisionError>> {
        Box::pin(async move { InMemoryStore::confirm_revision(self, revision) })
    }

    fn read_revision(
        &self,
        revision_id: RuntimeRevisionId,
    ) -> PersistenceFuture<'_, Result<RuntimeRevisionDescriptor, RuntimeRevisionError>> {
        Box::pin(async move { InMemoryStore::read_revision(self, revision_id) })
    }

    fn list_revisions(
        &self,
    ) -> PersistenceFuture<'_, Result<Vec<RuntimeRevisionDescriptor>, RuntimeRevisionError>> {
        Box::pin(async move { InMemoryStore::list_revisions(self) })
    }

    fn read_active_revision(
        &self,
    ) -> PersistenceFuture<'_, Result<Option<RuntimeRevisionSelection>, RuntimeRevisionError>> {
        Box::pin(async move { InMemoryStore::read_active_revision(self) })
    }

    fn activate_revision(
        &self,
        revision_id: RuntimeRevisionId,
        expected_generation: Option<u64>,
        activated_at: PlatformTime,
    ) -> PersistenceFuture<'_, Result<RuntimeRevisionSelection, RuntimeRevisionError>> {
        Box::pin(async move {
            InMemoryStore::activate_revision(self, revision_id, expected_generation, activated_at)
        })
    }
}

impl ExecutionSessionStore for InMemoryStore {
    fn start_session(
        &self,
        session: ExecutionSession,
    ) -> PersistenceFuture<'_, Result<(), SessionError>> {
        Box::pin(async move { InMemoryStore::start_session(self, session) })
    }

    fn finish_session(
        &self,
        session_id: ExecutionSessionId,
        status: ExecutionSessionStatus,
        ended_at: PlatformTime,
    ) -> PersistenceFuture<'_, Result<ExecutionSession, SessionError>> {
        Box::pin(async move { InMemoryStore::finish_session(self, session_id, status, ended_at) })
    }

    fn read_session(
        &self,
        session_id: ExecutionSessionId,
    ) -> PersistenceFuture<'_, Result<ExecutionSession, SessionError>> {
        Box::pin(async move { InMemoryStore::read_session(self, session_id) })
    }

    fn list_sessions(&self) -> PersistenceFuture<'_, Result<Vec<ExecutionSession>, SessionError>> {
        Box::pin(async move { InMemoryStore::list_sessions(self) })
    }
}

impl CommitStore for InMemoryStore {
    fn commit<'a>(
        &'a self,
        resolution: &'a ValidatedResolution,
        current_work: Option<&'a WorkClaim>,
        now: PlatformTime,
    ) -> PersistenceFuture<'a, Result<CommitResult, CommitError>> {
        Box::pin(async move { InMemoryStore::commit(self, resolution, current_work, now) })
    }
}

impl WorldTimeStore for InMemoryStore {
    fn advance_world_time(
        &self,
        transition: AdvanceWorldTime,
    ) -> PersistenceFuture<'_, Result<TimelineVersion, WorldTimeError>> {
        Box::pin(async move { InMemoryStore::advance_world_time(self, transition) })
    }
}

impl WorkStore for InMemoryStore {
    fn claim(
        &self,
        timeline_id: TimelineId,
        work_id: loom_core::WorkId,
        now: PlatformTime,
        claimed_until: PlatformTime,
    ) -> PersistenceFuture<'_, Result<WorkClaim, WorkError>> {
        Box::pin(
            async move { InMemoryStore::claim(self, timeline_id, work_id, now, claimed_until) },
        )
    }

    fn retry<'a>(
        &'a self,
        claim: &'a WorkClaim,
        now: PlatformTime,
        available_at: PlatformTime,
        last_error: Option<String>,
    ) -> PersistenceFuture<'a, Result<WorkRecord, WorkError>> {
        Box::pin(async move { InMemoryStore::retry(self, claim, now, available_at, last_error) })
    }

    fn work(
        &self,
        timeline_id: TimelineId,
        work_id: loom_core::WorkId,
    ) -> PersistenceFuture<'_, Result<Option<WorkRecord>, ReadError>> {
        Box::pin(async move { InMemoryStore::work(self, timeline_id, work_id) })
    }
}

fn snapshot_from_timeline(timeline: &TimelineState) -> TimelineSnapshot {
    let mut base = BaseWorldSnapshot::new(
        timeline.world_id,
        timeline.timeline_id,
        timeline.version,
        timeline.world_time,
    );
    for entity in timeline.entities.values() {
        base.insert_entity(entity.clone());
    }
    for relationship in timeline.relationships.values() {
        base.insert_relationship(relationship.relationship.clone(), relationship.active);
    }
    for ((owner, facet_type), facet) in &timeline.facets {
        base.insert_facet(
            *owner,
            facet_type.clone(),
            facet.schema_revision,
            facet.value.clone(),
        );
    }
    for event in &timeline.events {
        base.insert_event(event.id);
    }
    let mut works: Vec<_> = timeline.works.values().cloned().collect();
    works.sort_by_key(|work| (work.effective_due_world_time, work.logical_schedule_order));
    TimelineSnapshot::with_journal(
        base,
        timeline.events.clone(),
        works,
        timeline.journal.clone(),
    )
}

fn validate_event(
    timeline: &TimelineState,
    event: &ProposedEvent,
    seen_events: &HashSet<EventId>,
) -> Result<TimelineState, CommitError> {
    if event.id.is_nil() {
        return Err(CommitError::InvalidEvent {
            event_id: event.id,
            message: "Event identity is nil".to_owned(),
        });
    }
    if timeline.event_ids.contains(&event.id) || seen_events.contains(&event.id) {
        return Err(CommitError::DuplicateEvent { event_id: event.id });
    }
    let mut event_timeline = timeline.clone();
    let mut reference_timeline = timeline.clone();
    for effect in &event.effects {
        apply_effect(&mut event_timeline, event.id, effect)?;
        if matches!(
            effect,
            WorldEffect::CreateEntity { .. } | WorldEffect::CreateRelationship { .. }
        ) {
            apply_effect(&mut reference_timeline, event.id, effect)?;
        }
    }

    for participant in &event.participants {
        if !reference_timeline
            .entities
            .contains_key(&participant.entity_id)
        {
            return Err(CommitError::InvalidEvent {
                event_id: event.id,
                message: format!("missing participant Entity {}", participant.entity_id),
            });
        }
    }
    for relationship in &event.relationship_refs {
        if !reference_timeline
            .relationships
            .get(&relationship.relationship_id)
            .is_some_and(|record| record.active)
        {
            return Err(CommitError::InvalidEvent {
                event_id: event.id,
                message: format!(
                    "missing active Relationship {}",
                    relationship.relationship_id
                ),
            });
        }
    }
    for causal_link in &event.causal_links {
        let cause_event_id = causal_link.event_id();
        if !timeline.event_ids.contains(&cause_event_id) && !seen_events.contains(&cause_event_id) {
            return Err(CommitError::InvalidEvent {
                event_id: event.id,
                message: format!(
                    "causal Event {cause_event_id} is not committed ancestry or prior batch"
                ),
            });
        }
    }
    Ok(event_timeline)
}

fn apply_effect(
    timeline: &mut TimelineState,
    event_id: EventId,
    effect: &WorldEffect,
) -> Result<(), CommitError> {
    match effect {
        WorldEffect::CreateEntity { entity_id } => {
            if entity_id.is_nil() || timeline.entities.contains_key(entity_id) {
                return Err(invalid_effect(
                    event_id,
                    "Entity identity is nil or already exists",
                ));
            }
            timeline.entities.insert(
                *entity_id,
                Entity {
                    id: *entity_id,
                    world_id: timeline.world_id,
                },
            );
        }
        WorldEffect::PutFacet {
            owner,
            facet_type,
            schema_revision,
            value,
        } => {
            if !owner_exists(timeline, *owner) {
                return Err(invalid_effect(event_id, "Facet owner does not exist"));
            }
            timeline.facets.insert(
                (*owner, facet_type.clone()),
                FacetRecord {
                    schema_revision: *schema_revision,
                    value: value.clone(),
                },
            );
        }
        WorldEffect::RemoveFacet { owner, facet_type } => {
            if !owner_exists(timeline, *owner) {
                return Err(invalid_effect(event_id, "Facet owner does not exist"));
            }
            timeline.facets.remove(&(*owner, facet_type.clone()));
        }
        WorldEffect::CreateRelationship {
            relationship_id,
            relationship_type,
            participants,
        } => {
            if relationship_id.is_nil()
                || timeline.relationships.contains_key(relationship_id)
                || participants.is_empty()
            {
                return Err(invalid_effect(
                    event_id,
                    "Relationship identity is invalid, duplicated, or has no participants",
                ));
            }
            let mut participant_ids = HashSet::new();
            for participant in participants {
                if participant.entity_id.is_nil()
                    || !timeline.entities.contains_key(&participant.entity_id)
                {
                    return Err(invalid_effect(
                        event_id,
                        "Relationship participant Entity does not exist",
                    ));
                }
                if !participant_ids.insert(participant.entity_id) {
                    return Err(invalid_effect(
                        event_id,
                        "Relationship contains a duplicate participant Entity",
                    ));
                }
            }
            let relationship = Relationship::new(
                *relationship_id,
                timeline.world_id,
                relationship_type.clone(),
                participants.clone(),
            );
            timeline.relationships.insert(
                *relationship_id,
                RelationshipRecord {
                    relationship,
                    active: true,
                },
            );
        }
        WorldEffect::EndRelationship { relationship_id } => {
            let Some(record) = timeline.relationships.get_mut(relationship_id) else {
                return Err(invalid_effect(event_id, "Relationship does not exist"));
            };
            if !record.active {
                return Err(invalid_effect(event_id, "Relationship is already ended"));
            }
            record.active = false;
        }
    }
    Ok(())
}

fn apply_work_mutations(
    timeline: &mut TimelineState,
    mutations: &[WorkMutation],
    world_time: WorldInstant,
    now: PlatformTime,
) -> Result<Vec<LogicalWorkTransition>, CommitError> {
    let mut transitions = Vec::with_capacity(mutations.len());
    for mutation in mutations {
        match mutation {
            WorkMutation::Schedule(work) => {
                if work.timeline_id != timeline.timeline_id {
                    return Err(WorkError::TimelineMismatch {
                        expected: timeline.timeline_id,
                        actual: work.timeline_id,
                    }
                    .into());
                }
                if timeline.works.contains_key(&work.id) {
                    return Err(WorkError::DuplicateWork { work_id: work.id }.into());
                }
                if let Some(event_id) = work.causal_event_id
                    && !timeline.event_ids.contains(&event_id)
                {
                    return Err(WorkError::MissingCausalEvent {
                        work_id: work.id,
                        event_id,
                    }
                    .into());
                }
                if let WorkTarget::AgencyWake { agent, .. } = &work.target
                    && !timeline.entities.contains_key(agent)
                {
                    return Err(WorkError::StorageUnavailable {
                        message: format!(
                            "Agency Wake Agent Entity {agent} was not found in Timeline {}",
                            timeline.timeline_id
                        ),
                    }
                    .into());
                }
                let logical_schedule_order = timeline.logical_schedule_order.checked_add(1).ok_or(
                    WorkError::LogicalScheduleOrderOverflow {
                        timeline_id: timeline.timeline_id,
                    },
                )?;
                timeline.logical_schedule_order = logical_schedule_order;
                let effective_due_world_time = match work.schedule {
                    loom_runtime::WorkSchedule::Immediate => world_time,
                    loom_runtime::WorkSchedule::At(instant) => instant,
                };
                timeline.works.insert(
                    work.id,
                    WorkRecord::from_scheduled_work(
                        work,
                        effective_due_world_time,
                        logical_schedule_order,
                        now,
                    ),
                );
                transitions.push(LogicalWorkTransition::Schedule {
                    work_id: work.id,
                    target: work.target.clone(),
                    schema_revision: work.schema_revision,
                    payload: work.payload.clone(),
                    effective_due_world_time,
                    logical_schedule_order,
                    causal_event_id: work.causal_event_id,
                    origin_work_id: work.origin_work_id,
                });
            }
            WorkMutation::Cancel(work_id) => {
                let work = timeline
                    .works
                    .get_mut(work_id)
                    .ok_or(WorkError::WorkNotFound {
                        timeline_id: timeline.timeline_id,
                        work_id: *work_id,
                    })?;
                if !work.is_pending() {
                    return Err(WorkError::NotPending {
                        work_id: *work_id,
                        status: work.status,
                    }
                    .into());
                }
                work.status = WorkStatus::Cancelled;
                work.lease = None;
                transitions.push(LogicalWorkTransition::Cancel { work_id: *work_id });
            }
        }
    }
    Ok(transitions)
}

fn validate_claim(
    timeline: &TimelineState,
    claim: &WorkClaim,
    now: PlatformTime,
) -> Result<(), WorkError> {
    if claim.timeline_id() != timeline.timeline_id {
        return Err(WorkError::TimelineMismatch {
            expected: timeline.timeline_id,
            actual: claim.timeline_id(),
        });
    }
    let work = timeline
        .works
        .get(&claim.work_id())
        .ok_or(WorkError::WorkNotFound {
            timeline_id: timeline.timeline_id,
            work_id: claim.work_id(),
        })?;
    if !work.is_pending() {
        return Err(WorkError::NotPending {
            work_id: claim.work_id(),
            status: work.status,
        });
    }
    let Some(lease) = work.lease else {
        return Err(WorkError::MissingLease {
            work_id: claim.work_id(),
        });
    };
    if lease.fence() != claim.fence() || lease.claimed_until() != claim.claimed_until() {
        return Err(WorkError::StaleClaim {
            work_id: claim.work_id(),
            expected_fence: claim.fence(),
            actual_fence: Some(lease.fence()),
        });
    }
    if now >= lease.claimed_until() {
        return Err(WorkError::LeaseExpired {
            work_id: claim.work_id(),
            claimed_until: lease.claimed_until(),
            now,
        });
    }
    Ok(())
}

fn complete_current_work(
    timeline: &mut TimelineState,
    claim: &WorkClaim,
) -> Result<LogicalWorkTransition, CommitError> {
    let work = timeline
        .works
        .get_mut(&claim.work_id())
        .ok_or(WorkError::WorkNotFound {
            timeline_id: timeline.timeline_id,
            work_id: claim.work_id(),
        })?;
    if !work.is_pending() {
        return Err(WorkError::NotPending {
            work_id: claim.work_id(),
            status: work.status,
        }
        .into());
    }
    work.status = WorkStatus::Completed;
    work.lease = None;
    work.last_error = None;
    Ok(LogicalWorkTransition::Complete {
        work_id: claim.work_id(),
    })
}

fn owner_exists(timeline: &TimelineState, owner: FacetOwner) -> bool {
    match owner {
        FacetOwner::Entity(entity_id) => timeline.entities.contains_key(&entity_id),
        FacetOwner::Relationship(relationship_id) => timeline
            .relationships
            .get(&relationship_id)
            .is_some_and(|record| record.active),
    }
}

fn invalid_effect(event_id: EventId, message: &str) -> CommitError {
    CommitError::InvalidEffect {
        event_id,
        message: message.to_owned(),
    }
}

fn birth_commit_error(error: &CommitError) -> LifecycleError {
    LifecycleError::StorageUnavailable {
        message: format!("atomic Template bootstrap failed: {error}"),
    }
}
