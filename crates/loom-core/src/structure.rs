//! Domain-independent World structure and mechanical mutation values.

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::{EntityId, FacetTypeId, RelationshipId, RelationshipTypeId, SchemaRevision, WorldId};

/// Stable identity record for an Entity in a World.
///
/// Core owns only the structural identity and World association. Mutable
/// Timeline state belongs to Facet instances and committed Events, not to this
/// record. Runtime/storage may construct or persist it; Capability code must
/// not use it as a domain-specific entity type or as a direct state write.
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub struct Entity {
    /// Stable identity of the Entity.
    pub id: EntityId,
    /// World in which this identity is defined.
    pub world_id: WorldId,
}

/// Stable semantic role assigned to a Core association.
///
/// `AssociationRole` is the neutral role value shared by Relationship
/// participants and Protocol Event associations. Core carries the structural
/// label; the Capability that owns the surrounding semantic type interprets
/// it. It is not a Capability type ID, Entity name or authorization grant.
#[derive(Clone, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct AssociationRole(String);

impl AssociationRole {
    /// Creates an association role from its semantic key.
    #[must_use]
    pub fn new(value: impl Into<String>) -> Self {
        Self(value.into())
    }

    /// Returns the role key without assigning it domain meaning.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl From<String> for AssociationRole {
    fn from(value: String) -> Self {
        Self::new(value)
    }
}

impl From<&str> for AssociationRole {
    fn from(value: &str) -> Self {
        Self::new(value)
    }
}

impl std::fmt::Display for AssociationRole {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.0)
    }
}

/// One Entity's role-bearing membership in a Relationship.
///
/// Core supports N-ary relationships by carrying a list of these values. The
/// participant set is fixed when a Relationship is created; changing the
/// participating identities requires ending the old Relationship and creating
/// another one. The association role remains semantic metadata interpreted by
/// the owning Capability.
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub struct RelationshipParticipant {
    /// Entity identity occupying the role.
    pub entity_id: EntityId,
    /// Neutral association role occupied by that Entity.
    pub role: AssociationRole,
}

impl RelationshipParticipant {
    /// Creates one role-bearing Relationship participant.
    #[must_use]
    pub fn new(entity_id: EntityId, role: impl Into<AssociationRole>) -> Self {
        Self {
            entity_id,
            role: role.into(),
        }
    }
}

/// Structural identity of a Relationship and its immutable participant set.
///
/// The `relationship_type` key is Capability-owned semantic metadata, while
/// `id`, `world_id` and the participant identities are Core structure. Use
/// `Relationship::new` to establish the participant set and access it through
/// `participants`; there is intentionally no mutation method that can silently
/// retarget an existing Relationship. Mutable terms or status belong in
/// Timeline-local Relationship Facets. This record is not a commit token.
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub struct Relationship {
    /// Stable identity of the Relationship instance.
    pub id: RelationshipId,
    /// World in which the Relationship exists.
    pub world_id: WorldId,
    /// Capability-owned semantic schema key for the Relationship.
    pub relationship_type: RelationshipTypeId,
    participants: Vec<RelationshipParticipant>,
}

impl Relationship {
    /// Creates a Relationship with its fixed participant structure.
    ///
    /// Runtime remains responsible for validating role cardinality, Entity
    /// existence and semantic ownership before a corresponding Effect is
    /// committed.
    #[must_use]
    pub fn new(
        id: RelationshipId,
        world_id: WorldId,
        relationship_type: RelationshipTypeId,
        participants: Vec<RelationshipParticipant>,
    ) -> Self {
        Self {
            id,
            world_id,
            relationship_type,
            participants,
        }
    }

    /// Borrows the participant structure without permitting retargeting.
    #[must_use]
    pub fn participants(&self) -> &[RelationshipParticipant] {
        &self.participants
    }
}

/// Identifies which structural object owns one Facet instance.
///
/// `FacetOwner` is a Core reference mechanism shared by mechanical Effects and
/// validation. The selected Facet type and value remain Capability-owned
/// semantics. It is not a storage table discriminator, Runtime authority or
/// replacement for the referenced Entity/Relationship identity.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub enum FacetOwner {
    /// The Facet belongs to an Entity identity.
    Entity(EntityId),
    /// The Facet belongs to a Relationship identity.
    Relationship(RelationshipId),
}

impl FacetOwner {
    /// Creates an Entity-owned Facet reference.
    #[must_use]
    pub const fn entity(entity_id: EntityId) -> Self {
        Self::Entity(entity_id)
    }

    /// Creates a Relationship-owned Facet reference.
    #[must_use]
    pub const fn relationship(relationship_id: RelationshipId) -> Self {
        Self::Relationship(relationship_id)
    }
}

/// Mechanical World mutation that can be carried by a proposed Event.
///
/// `WorldEffect` is owned by Core and deliberately contains only structural
/// primitives: identity creation, complete Facet replacement/removal and
/// Relationship lifecycle. It is not a domain action, database patch,
/// standalone commit value or Runtime authority. Domain concepts such as
/// money transfer, damage or employment must be resolved by a Capability into
/// a `ProposedEvent` plus these mechanical Effects. Runtime validation must
/// reject any Effect that is not associated with a proposed Event.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub enum WorldEffect {
    /// Creates a new Entity identity in the current World/Timeline context.
    CreateEntity {
        /// Identity to create; it must not already exist in the candidate state.
        entity_id: EntityId,
    },
    /// Replaces one complete Capability-owned Facet value in candidate state.
    PutFacet {
        /// Entity or Relationship whose Facet is being replaced.
        owner: FacetOwner,
        /// Capability-owned Facet schema key.
        facet_type: FacetTypeId,
        /// Schema revision used to interpret `value`.
        schema_revision: SchemaRevision,
        /// Complete candidate value; this is not a JSON Patch fragment.
        value: Value,
    },
    /// Removes one Facet instance from candidate state.
    RemoveFacet {
        /// Entity or Relationship whose Facet is being removed.
        owner: FacetOwner,
        /// Capability-owned Facet schema key.
        facet_type: FacetTypeId,
    },
    /// Creates a structural N-ary Relationship with a fixed participant set.
    CreateRelationship {
        /// Identity to create; it must not already exist in the candidate state.
        relationship_id: RelationshipId,
        /// Capability-owned Relationship schema key.
        relationship_type: RelationshipTypeId,
        /// Entity identities and semantic roles fixed by this creation Effect.
        participants: Vec<RelationshipParticipant>,
    },
    /// Ends an existing Relationship without changing its historical identity.
    EndRelationship {
        /// Relationship identity whose active lifecycle ends.
        relationship_id: RelationshipId,
    },
}

#[cfg(test)]
mod tests {
    use serde_json::json;
    use uuid::Uuid;

    use super::{AssociationRole, FacetOwner, RelationshipParticipant, WorldEffect};
    use crate::{EntityId, FacetTypeId, RelationshipId, RelationshipTypeId, SchemaRevision};

    #[test]
    fn mechanical_effect_serialization_round_trip() {
        let entity_id = EntityId::new(Uuid::from_u128(1));
        let effect = WorldEffect::PutFacet {
            owner: FacetOwner::entity(entity_id),
            facet_type: FacetTypeId::from("counter.value"),
            schema_revision: SchemaRevision::new(1),
            value: json!({"value": 2}),
        };

        let encoded = serde_json::to_string(&effect).expect("effect should serialize");
        let decoded: WorldEffect =
            serde_json::from_str(&encoded).expect("effect should deserialize");
        assert_eq!(decoded, effect);
    }

    #[test]
    fn relationship_participants_keep_typed_role_and_identity() {
        let participant = RelationshipParticipant::new(
            EntityId::new(Uuid::from_u128(2)),
            AssociationRole::new("member"),
        );
        let effect = WorldEffect::CreateRelationship {
            relationship_id: RelationshipId::new(Uuid::from_u128(3)),
            relationship_type: RelationshipTypeId::from("group.membership"),
            participants: vec![participant.clone()],
        };

        assert_eq!(participant.role.as_str(), "member");
        assert!(matches!(effect, WorldEffect::CreateRelationship { .. }));
    }
}
