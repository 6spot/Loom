//! Runtime-owned pinned and candidate World views.

use std::{
    collections::{HashMap, HashSet},
    sync::Mutex,
};

use loom_capability::{
    BaseWorldView as CapabilityBaseWorldView, CandidateWorldView as CapabilityCandidateWorldView,
    FacetValue, ResolutionContextError,
};
use loom_core::{
    Entity, EntityId, EventId, FacetOwner, FacetTypeId, Relationship, RelationshipId,
    RelationshipTypeId, TimelineId, TimelineVersion, WorldEffect, WorldId, WorldInstant,
};
use serde_json::Value;

use crate::{ReadDependency, ReadSet};

type FacetKey = (FacetOwner, FacetTypeId);

#[derive(Clone, Debug, PartialEq)]
struct FacetRecord {
    schema_revision: loom_core::SchemaRevision,
    value: Value,
}

#[derive(Clone, Debug)]
struct RelationshipRecord {
    relationship: Relationship,
    active: bool,
}

/// A complete, pinned description of the Runtime's base Timeline state.
///
/// `BaseWorldSnapshot` is an input to a Runtime view, not a commit handle. It
/// carries one consistent `TimelineVersion`; the Effect Engine uses it as the
/// unmodified read side while candidate Effects are applied to a separate
/// overlay. Storage adapters may populate this value, but they do not gain
/// authority to construct `ValidatedResolution` from it.
#[derive(Clone, Debug)]
pub struct BaseWorldSnapshot {
    world_id: WorldId,
    timeline_id: TimelineId,
    version: TimelineVersion,
    world_time: WorldInstant,
    entities: HashMap<EntityId, Entity>,
    relationships: HashMap<RelationshipId, RelationshipRecord>,
    facets: HashMap<FacetKey, FacetRecord>,
    events: HashSet<EventId>,
}

impl BaseWorldSnapshot {
    /// Creates an empty pinned snapshot for one World/Timeline/version tuple.
    #[must_use]
    pub fn new(
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
            entities: HashMap::new(),
            relationships: HashMap::new(),
            facets: HashMap::new(),
            events: HashSet::new(),
        }
    }

    /// Adds or replaces one Entity in the snapshot builder.
    pub fn insert_entity(&mut self, entity: Entity) {
        self.entities.insert(entity.id, entity);
    }

    /// Adds one Entity and returns the builder for concise test/composition
    /// setup.
    #[must_use]
    pub fn with_entity(mut self, entity: Entity) -> Self {
        self.insert_entity(entity);
        self
    }

    /// Adds or replaces one Relationship and its active-lifecycle marker.
    pub fn insert_relationship(&mut self, relationship: Relationship, active: bool) {
        self.relationships.insert(
            relationship.id,
            RelationshipRecord {
                relationship,
                active,
            },
        );
    }

    /// Adds one Relationship and returns the builder.
    #[must_use]
    pub fn with_relationship(mut self, relationship: Relationship, active: bool) -> Self {
        self.insert_relationship(relationship, active);
        self
    }

    /// Adds or replaces one complete Facet value in the snapshot.
    pub fn insert_facet(
        &mut self,
        owner: FacetOwner,
        facet_type: FacetTypeId,
        schema_revision: loom_core::SchemaRevision,
        value: Value,
    ) {
        self.facets.insert(
            (owner, facet_type),
            FacetRecord {
                schema_revision,
                value,
            },
        );
    }

    /// Adds one Facet and returns the builder.
    #[must_use]
    pub fn with_facet(
        mut self,
        owner: FacetOwner,
        facet_type: FacetTypeId,
        schema_revision: loom_core::SchemaRevision,
        value: Value,
    ) -> Self {
        self.insert_facet(owner, facet_type, schema_revision, value);
        self
    }

    /// Records one already committed Event identity in Timeline ancestry.
    pub fn insert_event(&mut self, event_id: EventId) {
        self.events.insert(event_id);
    }

    /// Records one committed Event and returns the builder.
    #[must_use]
    pub fn with_event(mut self, event_id: EventId) -> Self {
        self.insert_event(event_id);
        self
    }

    /// Returns the World identity pinned by the snapshot.
    #[must_use]
    pub const fn world_id(&self) -> WorldId {
        self.world_id
    }

    /// Returns the Timeline identity pinned by the snapshot.
    #[must_use]
    pub const fn timeline_id(&self) -> TimelineId {
        self.timeline_id
    }

    /// Returns the expected Timeline version for a later commit CAS.
    #[must_use]
    pub const fn version(&self) -> TimelineVersion {
        self.version
    }

    /// Returns the semantic World time observed by this snapshot.
    #[must_use]
    pub const fn world_time(&self) -> WorldInstant {
        self.world_time
    }
}

/// A read-only Runtime view over one pinned `BaseWorldSnapshot`.
///
/// Resolver-facing code may inspect this view, but it cannot mutate the base
/// state or obtain a storage transaction. Every lookup records an observed
/// dependency in Runtime-owned provenance. Candidate mutation is available only
/// through `CandidateWorldView` during validation.
#[derive(Debug)]
pub struct BaseWorldView {
    snapshot: BaseWorldSnapshot,
    reads: Mutex<ReadSet>,
}

impl Clone for BaseWorldView {
    fn clone(&self) -> Self {
        Self {
            snapshot: self.snapshot.clone(),
            reads: Mutex::new(self.read_set()),
        }
    }
}

impl BaseWorldView {
    /// Creates a read-only view over one pinned snapshot.
    #[must_use]
    pub fn new(snapshot: BaseWorldSnapshot) -> Self {
        Self {
            snapshot,
            reads: Mutex::new(ReadSet::default()),
        }
    }

    /// Returns the World identity visible through this view.
    #[must_use]
    pub const fn world_id(&self) -> WorldId {
        self.snapshot.world_id()
    }

    /// Returns the Timeline identity visible through this view.
    #[must_use]
    pub const fn timeline_id(&self) -> TimelineId {
        self.snapshot.timeline_id()
    }

    /// Returns the pinned Timeline version used by the view.
    #[must_use]
    pub const fn version(&self) -> TimelineVersion {
        self.snapshot.version()
    }

    /// Returns the pinned semantic World time.
    #[must_use]
    pub const fn world_time(&self) -> WorldInstant {
        self.snapshot.world_time()
    }

    /// Looks up one Entity identity in the pinned base state.
    #[must_use]
    pub fn entity(&self, entity_id: EntityId) -> Option<Entity> {
        let result = self.snapshot.entities.get(&entity_id).cloned();
        self.record(ReadDependency::Entity {
            entity_id,
            present: result.is_some(),
        });
        result
    }

    /// Looks up one active Relationship and its immutable structure.
    #[must_use]
    pub fn relationship(&self, relationship_id: RelationshipId) -> Option<RelationshipSnapshot> {
        let result = self
            .snapshot
            .relationships
            .get(&relationship_id)
            .filter(|record| record.active)
            .map(|record| RelationshipSnapshot {
                relationship: record.relationship.clone(),
                active: record.active,
            });
        self.record(ReadDependency::Relationship {
            relationship_id,
            present: result.is_some(),
        });
        result
    }

    /// Looks up one complete Facet value in the pinned base state.
    #[must_use]
    pub fn facet(&self, owner: FacetOwner, facet_type: &FacetTypeId) -> Option<FacetSnapshot> {
        let key = (owner, facet_type.clone());
        let result = self.snapshot.facets.get(&key).map(|record| FacetSnapshot {
            owner,
            facet_type: facet_type.clone(),
            schema_revision: record.schema_revision,
            value: record.value.clone(),
        });
        self.record(ReadDependency::Facet {
            owner,
            facet_type: facet_type.clone(),
            schema_revision: result.as_ref().map(FacetSnapshot::schema_revision),
        });
        result
    }

    /// Reports whether an Event identity belongs to pinned Timeline ancestry.
    #[must_use]
    pub fn event_exists(&self, event_id: EventId) -> bool {
        let present = self.snapshot.events.contains(&event_id);
        self.record(ReadDependency::Event { event_id, present });
        present
    }

    /// Returns the provenance observed through this base view so far.
    #[must_use]
    pub fn read_set(&self) -> ReadSet {
        self.reads
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone()
    }

    pub(crate) fn snapshot(&self) -> &BaseWorldSnapshot {
        &self.snapshot
    }

    fn record(&self, dependency: ReadDependency) {
        self.reads
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .record(dependency);
    }
}

impl CapabilityBaseWorldView for BaseWorldView {
    fn timeline_id(&self) -> TimelineId {
        self.timeline_id()
    }

    fn version(&self) -> TimelineVersion {
        self.version()
    }

    fn world_time(&self) -> WorldInstant {
        self.world_time()
    }

    fn get_entity(&self, entity_id: EntityId) -> Result<Option<Entity>, ResolutionContextError> {
        Ok(self.entity(entity_id))
    }

    fn get_relationship(
        &self,
        relationship_id: RelationshipId,
    ) -> Result<Option<Relationship>, ResolutionContextError> {
        Ok(self
            .relationship(relationship_id)
            .map(|snapshot| snapshot.relationship().clone()))
    }

    fn get_facet(
        &self,
        owner: FacetOwner,
        facet_type: &FacetTypeId,
    ) -> Result<Option<FacetValue>, ResolutionContextError> {
        Ok(self
            .facet(owner, facet_type)
            .map(|snapshot| FacetValue::new(snapshot.schema_revision(), snapshot.value().clone())))
    }
}

/// A complete Facet value visible in a Runtime World view.
///
/// This is a read model, not a `WorldEffect` and not a mutable JSON patch. A
/// `PutFacet` replacement shadows the base value only inside the current
/// candidate Resolution until its enclosing Event is committed.
#[derive(Clone, Debug, PartialEq)]
pub struct FacetSnapshot {
    owner: FacetOwner,
    facet_type: FacetTypeId,
    schema_revision: loom_core::SchemaRevision,
    value: Value,
}

impl FacetSnapshot {
    /// Returns the structural owner of this Facet.
    #[must_use]
    pub const fn owner(&self) -> FacetOwner {
        self.owner
    }

    /// Returns the Facet semantic key.
    #[must_use]
    pub fn facet_type(&self) -> &FacetTypeId {
        &self.facet_type
    }

    /// Returns the value schema revision observed.
    #[must_use]
    pub const fn schema_revision(&self) -> loom_core::SchemaRevision {
        self.schema_revision
    }

    /// Returns the complete immutable value observed.
    #[must_use]
    pub fn value(&self) -> &Value {
        &self.value
    }
}

/// A Relationship structure visible in a Runtime World view.
///
/// The `active` marker is Runtime lifecycle state. The embedded Core
/// `Relationship` participant set remains immutable; an ended Relationship is
/// not returned as an active candidate reference.
#[derive(Clone, Debug)]
pub struct RelationshipSnapshot {
    relationship: Relationship,
    active: bool,
}

impl RelationshipSnapshot {
    /// Returns the stable Relationship identity.
    #[must_use]
    pub const fn id(&self) -> RelationshipId {
        self.relationship.id
    }

    /// Returns the World identity containing the Relationship.
    #[must_use]
    pub const fn world_id(&self) -> WorldId {
        self.relationship.world_id
    }

    /// Returns the Relationship semantic type key.
    #[must_use]
    pub const fn relationship_type(&self) -> &RelationshipTypeId {
        &self.relationship.relationship_type
    }

    /// Returns the immutable participant structure.
    #[must_use]
    pub fn participants(&self) -> &[loom_core::RelationshipParticipant] {
        self.relationship.participants()
    }

    /// Borrows the complete Core Relationship read model.
    #[must_use]
    pub const fn relationship(&self) -> &Relationship {
        &self.relationship
    }

    /// Reports whether the Relationship is active in candidate state.
    #[must_use]
    pub const fn is_active(&self) -> bool {
        self.active
    }
}

#[derive(Clone, Debug)]
enum CandidateRelationship {
    Created(Relationship),
    Ended,
}

/// Runtime's `Base + Mutation Overlay` candidate view.
///
/// The Effect Engine applies each already-validated Effect to this view in
/// Resolution order. Queries first consult the overlay and then fall back to
/// the pinned base, so a later Event/schema/invariant read observes prior
/// candidate mutations. The overlay is not a persistence transaction and does
/// not itself make World Truth.
#[derive(Debug)]
pub struct CandidateWorldView {
    base: BaseWorldSnapshot,
    created_entities: HashMap<EntityId, Entity>,
    relationships: HashMap<RelationshipId, CandidateRelationship>,
    facets: HashMap<FacetKey, Option<FacetRecord>>,
    available_events: HashSet<EventId>,
    reads: Mutex<ReadSet>,
}

impl CandidateWorldView {
    /// Creates a fresh candidate view from one pinned base view.
    #[must_use]
    pub fn from_base(base: &BaseWorldView) -> Self {
        Self {
            base: base.snapshot().clone(),
            created_entities: HashMap::new(),
            relationships: HashMap::new(),
            facets: HashMap::new(),
            available_events: base.snapshot().events.clone(),
            reads: Mutex::new(ReadSet::default()),
        }
    }

    /// Returns the World identity visible in candidate state.
    #[must_use]
    pub const fn world_id(&self) -> WorldId {
        self.base.world_id()
    }

    /// Returns the Timeline identity visible in candidate state.
    #[must_use]
    pub const fn timeline_id(&self) -> TimelineId {
        self.base.timeline_id()
    }

    /// Returns the pinned version from which this candidate was built.
    #[must_use]
    pub const fn version(&self) -> TimelineVersion {
        self.base.version()
    }

    /// Returns the semantic World time pinned by the candidate's base view.
    #[must_use]
    pub const fn world_time(&self) -> WorldInstant {
        self.base.world_time()
    }

    /// Looks up an Entity after applying prior candidate identity creations.
    #[must_use]
    pub fn entity(&self, entity_id: EntityId) -> Option<Entity> {
        let result = self
            .created_entities
            .get(&entity_id)
            .cloned()
            .or_else(|| self.base.entities.get(&entity_id).cloned());
        self.record(ReadDependency::Entity {
            entity_id,
            present: result.is_some(),
        });
        result
    }

    /// Looks up an active Relationship after applying prior lifecycle Effects.
    #[must_use]
    pub fn relationship(&self, relationship_id: RelationshipId) -> Option<RelationshipSnapshot> {
        let result = match self.relationships.get(&relationship_id) {
            Some(CandidateRelationship::Created(relationship)) => Some(RelationshipSnapshot {
                relationship: relationship.clone(),
                active: true,
            }),
            Some(CandidateRelationship::Ended) => None,
            None => self
                .base
                .relationships
                .get(&relationship_id)
                .filter(|record| record.active)
                .map(|record| RelationshipSnapshot {
                    relationship: record.relationship.clone(),
                    active: record.active,
                }),
        };
        self.record(ReadDependency::Relationship {
            relationship_id,
            present: result.is_some(),
        });
        result
    }

    /// Looks up a Facet after applying prior complete replacements/removals.
    #[must_use]
    pub fn facet(&self, owner: FacetOwner, facet_type: &FacetTypeId) -> Option<FacetSnapshot> {
        let key = (owner, facet_type.clone());
        let result = match self.facets.get(&key) {
            Some(Some(record)) => Some(FacetSnapshot {
                owner,
                facet_type: facet_type.clone(),
                schema_revision: record.schema_revision,
                value: record.value.clone(),
            }),
            Some(None) => None,
            None => self.base.facets.get(&key).map(|record| FacetSnapshot {
                owner,
                facet_type: facet_type.clone(),
                schema_revision: record.schema_revision,
                value: record.value.clone(),
            }),
        };
        self.record(ReadDependency::Facet {
            owner,
            facet_type: facet_type.clone(),
            schema_revision: result.as_ref().map(FacetSnapshot::schema_revision),
        });
        result
    }

    /// Reports whether an Event is in pinned ancestry or an earlier batch
    /// position.
    #[must_use]
    pub fn event_exists(&self, event_id: EventId) -> bool {
        let present = self.available_events.contains(&event_id);
        self.record(ReadDependency::Event { event_id, present });
        present
    }

    /// Returns all lookup observations made through the candidate view.
    #[must_use]
    pub fn read_set(&self) -> ReadSet {
        self.reads
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone()
    }

    pub(crate) fn note_event(&mut self, event_id: EventId) {
        self.available_events.insert(event_id);
    }

    fn record(&self, dependency: ReadDependency) {
        self.reads
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .record(dependency);
    }

    pub(crate) fn apply_effect(&mut self, effect: &WorldEffect) {
        match effect {
            WorldEffect::CreateEntity { entity_id } => {
                self.created_entities.insert(
                    *entity_id,
                    Entity {
                        id: *entity_id,
                        world_id: self.base.world_id(),
                    },
                );
            }
            WorldEffect::PutFacet {
                owner,
                facet_type,
                schema_revision,
                value,
            } => {
                self.facets.insert(
                    (*owner, facet_type.clone()),
                    Some(FacetRecord {
                        schema_revision: *schema_revision,
                        value: value.clone(),
                    }),
                );
            }
            WorldEffect::RemoveFacet { owner, facet_type } => {
                self.facets.insert((*owner, facet_type.clone()), None);
            }
            WorldEffect::CreateRelationship {
                relationship_id,
                relationship_type,
                participants,
            } => {
                self.relationships.insert(
                    *relationship_id,
                    CandidateRelationship::Created(Relationship::new(
                        *relationship_id,
                        self.base.world_id(),
                        relationship_type.clone(),
                        participants.clone(),
                    )),
                );
            }
            WorldEffect::EndRelationship { relationship_id } => {
                self.relationships
                    .insert(*relationship_id, CandidateRelationship::Ended);
            }
        }
    }
}

impl CapabilityCandidateWorldView for CandidateWorldView {}

impl CapabilityBaseWorldView for CandidateWorldView {
    fn timeline_id(&self) -> TimelineId {
        self.timeline_id()
    }

    fn version(&self) -> TimelineVersion {
        self.version()
    }

    fn world_time(&self) -> WorldInstant {
        self.base.world_time
    }

    fn get_entity(&self, entity_id: EntityId) -> Result<Option<Entity>, ResolutionContextError> {
        Ok(self.entity(entity_id))
    }

    fn get_relationship(
        &self,
        relationship_id: RelationshipId,
    ) -> Result<Option<Relationship>, ResolutionContextError> {
        Ok(self
            .relationship(relationship_id)
            .map(|snapshot| snapshot.relationship().clone()))
    }

    fn get_facet(
        &self,
        owner: FacetOwner,
        facet_type: &FacetTypeId,
    ) -> Result<Option<FacetValue>, ResolutionContextError> {
        Ok(self
            .facet(owner, facet_type)
            .map(|snapshot| FacetValue::new(snapshot.schema_revision(), snapshot.value().clone())))
    }
}
