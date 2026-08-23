//! Pure reconstruction of materialized World State from committed history.

use std::fmt;

use loom_core::{EntityId, EventId, EventSeq, FacetOwner, RelationshipId, TimelineId, WorldEffect};

use crate::{BaseWorldSnapshot, CandidateWorldView, CommittedEvent};

/// A deterministic structural failure found while replaying one Event's
/// frozen associations or causal links.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ReplayEventError {
    /// The Event identity is nil.
    NilIdentity,
    /// A direct Event participant is nil.
    NilParticipant { entity_id: EntityId },
    /// A direct Event participant does not exist at the Event boundary.
    MissingParticipantEntity { entity_id: EntityId },
    /// A referenced Relationship is not active at the Event boundary.
    MissingRelationshipReference { relationship_id: RelationshipId },
    /// A causal link does not point to committed ancestry or an earlier Event
    /// in the visible ordered input.
    InvalidCausalReference { cause_event_id: EventId },
}

impl fmt::Display for ReplayEventError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NilIdentity => formatter.write_str("Event identity is nil"),
            Self::NilParticipant { entity_id } => {
                write!(formatter, "Event participant Entity {entity_id} is nil")
            }
            Self::MissingParticipantEntity { entity_id } => {
                write!(formatter, "Event participant Entity {entity_id} is missing")
            }
            Self::MissingRelationshipReference { relationship_id } => write!(
                formatter,
                "Event references missing active Relationship {relationship_id}"
            ),
            Self::InvalidCausalReference { cause_event_id } => write!(
                formatter,
                "Event references unavailable causal Event {cause_event_id}"
            ),
        }
    }
}

/// A deterministic structural failure found while applying one frozen
/// [`WorldEffect`].
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ReplayEffectError {
    /// An identity-bearing Effect contains the nil identity.
    NilIdentity {
        /// Structural kind of the nil identity.
        kind: &'static str,
        /// Nil identity supplied by the history record.
        id: String,
    },
    /// An Entity creation collides with existing materialized state.
    DuplicateEntity { entity_id: EntityId },
    /// A Facet Effect targets an Entity or active Relationship that is absent.
    MissingFacetOwner { owner: FacetOwner },
    /// A Relationship creation collides with existing or ended history.
    DuplicateRelationship { relationship_id: RelationshipId },
    /// A Relationship creation has no participants.
    EmptyRelationshipParticipants { relationship_id: RelationshipId },
    /// A Relationship participant is nil.
    NilRelationshipParticipant {
        relationship_id: RelationshipId,
        entity_id: EntityId,
    },
    /// A Relationship participant Entity is absent.
    MissingRelationshipParticipant {
        relationship_id: RelationshipId,
        entity_id: EntityId,
    },
    /// A Relationship repeats one Entity in its immutable participant set.
    DuplicateRelationshipParticipant {
        relationship_id: RelationshipId,
        entity_id: EntityId,
    },
    /// An `EndRelationship` Effect targets no active Relationship.
    MissingActiveRelationship { relationship_id: RelationshipId },
}

impl fmt::Display for ReplayEffectError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NilIdentity { kind, id } => write!(formatter, "nil {kind} identity {id}"),
            Self::DuplicateEntity { entity_id } => {
                write!(formatter, "Entity {entity_id} already exists")
            }
            Self::MissingFacetOwner { owner } => {
                write!(formatter, "Facet owner {owner:?} does not exist")
            }
            Self::DuplicateRelationship { relationship_id } => {
                write!(formatter, "Relationship {relationship_id} already exists")
            }
            Self::EmptyRelationshipParticipants { relationship_id } => write!(
                formatter,
                "Relationship {relationship_id} has no participants"
            ),
            Self::NilRelationshipParticipant {
                relationship_id,
                entity_id,
            } => write!(
                formatter,
                "Relationship {relationship_id} participant Entity {entity_id} is nil"
            ),
            Self::MissingRelationshipParticipant {
                relationship_id,
                entity_id,
            } => write!(
                formatter,
                "Relationship {relationship_id} participant Entity {entity_id} is missing"
            ),
            Self::DuplicateRelationshipParticipant {
                relationship_id,
                entity_id,
            } => write!(
                formatter,
                "Relationship {relationship_id} repeats Entity {entity_id}"
            ),
            Self::MissingActiveRelationship { relationship_id } => write!(
                formatter,
                "Relationship {relationship_id} is missing or already ended"
            ),
        }
    }
}

/// A typed, deterministic failure while reconstructing materialized World
/// State from an Event ledger.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ReplayError {
    /// The supplied Event sequence is not the next contiguous Timeline value.
    NonContiguousEventSeq {
        /// Sequence required after the initial materialization or prior Event.
        expected: EventSeq,
        /// Sequence found in the history record.
        actual: EventSeq,
    },
    /// A history record targets another Timeline.
    TimelineMismatch {
        /// Timeline represented by the initial materialization.
        expected: TimelineId,
        /// Timeline carried by the Event record.
        actual: TimelineId,
        /// Sequence of the mismatched record.
        event_seq: EventSeq,
    },
    /// An Event record has an invalid identity or duplicate ancestry identity.
    InvalidEvent {
        /// Event record sequence.
        event_seq: EventSeq,
        /// Event identity carried by the record.
        event_id: EventId,
        /// Structural reason for rejection.
        reason: ReplayEventError,
    },
    /// An Event identity appears in initial ancestry or earlier visible history.
    DuplicateEvent {
        /// Repeated Event identity.
        event_id: EventId,
        /// Sequence of the repeated record.
        event_seq: EventSeq,
    },
    /// A frozen Effect cannot be applied to the materialized state at this
    /// exact Event position.
    ImpossibleEffect {
        /// Event containing the Effect.
        event_id: EventId,
        /// Sequence of the Event containing the Effect.
        event_seq: EventSeq,
        /// Structural reason the Effect is impossible.
        reason: ReplayEffectError,
    },
    /// Event associations or causal links are inconsistent with the state at
    /// the Event boundary.
    InvalidEventReference {
        /// Event containing the invalid reference.
        event_id: EventId,
        /// Sequence of the Event containing the invalid reference.
        event_seq: EventSeq,
        /// Structural reason for rejection.
        reason: ReplayEventError,
    },
    /// The initial Event head cannot be advanced to the next representable
    /// sequence value.
    EventSeqOverflow { event_seq: EventSeq },
}

impl fmt::Display for ReplayError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NonContiguousEventSeq { expected, actual } => write!(
                formatter,
                "non-contiguous EventSeq: expected {}, received {}",
                expected.value(),
                actual.value()
            ),
            Self::TimelineMismatch {
                expected,
                actual,
                event_seq,
            } => write!(
                formatter,
                "Event {} belongs to Timeline {actual}, expected {expected}",
                event_seq.value()
            ),
            Self::InvalidEvent {
                event_seq,
                event_id,
                reason,
            } => write!(
                formatter,
                "invalid Event {event_id} at sequence {}: {reason}",
                event_seq.value()
            ),
            Self::DuplicateEvent {
                event_id,
                event_seq,
            } => write!(
                formatter,
                "duplicate Event {event_id} at sequence {}",
                event_seq.value()
            ),
            Self::ImpossibleEffect {
                event_id,
                event_seq,
                reason,
            } => write!(
                formatter,
                "impossible Effect in Event {event_id} at sequence {}: {reason}",
                event_seq.value()
            ),
            Self::InvalidEventReference {
                event_id,
                event_seq,
                reason,
            } => write!(
                formatter,
                "invalid references in Event {event_id} at sequence {}: {reason}",
                event_seq.value()
            ),
            Self::EventSeqOverflow { event_seq } => {
                write!(formatter, "EventSeq overflow after {}", event_seq.value())
            }
        }
    }
}

impl std::error::Error for ReplayError {}

/// Materialized World State and Event head returned by pure replay.
#[derive(Clone, Debug)]
pub struct ReplayResult {
    /// Entity/Relationship/Facet materialization after the supplied history.
    materialization: BaseWorldSnapshot,
    /// Last authoritative Event sequence represented by the result.
    head_event_seq: EventSeq,
}

impl ReplayResult {
    /// Returns the reconstructed materialization as a Runtime read snapshot.
    #[must_use]
    pub const fn materialization(&self) -> &BaseWorldSnapshot {
        &self.materialization
    }

    /// Consumes the result and returns the reconstructed materialization.
    #[must_use]
    pub fn into_materialization(self) -> BaseWorldSnapshot {
        self.materialization
    }

    /// Returns a read-only World view over the reconstructed materialization.
    #[must_use]
    pub fn world_view(&self) -> crate::BaseWorldView {
        crate::BaseWorldView::new(self.materialization.clone())
    }

    /// Returns the last Event sequence represented by the result.
    #[must_use]
    pub const fn head_event_seq(&self) -> EventSeq {
        self.head_event_seq
    }
}

/// Stateless Runtime-owned pure replay engine.
pub struct ReplayEngine;

impl ReplayEngine {
    /// Applies visible committed Events and their frozen Effects in
    /// authoritative sequence order.
    ///
    /// Replay intentionally has no Capability registry, resolver, clock,
    /// provider, entropy or cognition input. `CommittedEvent::occurred_at` is
    /// historical metadata and is ignored; it never reconstructs World Time.
    /// Only structural history invariants needed by the existing materialized
    /// World-state boundary are checked.
    ///
    /// # Errors
    ///
    /// Returns a deterministic [`ReplayError`] for sequence gaps, Timeline
    /// mismatches, duplicate identities, invalid Event references or Effects
    /// that cannot apply to the current materialization.
    pub fn replay(
        initial: BaseWorldSnapshot,
        events: &[CommittedEvent],
    ) -> Result<ReplayResult, ReplayError> {
        let mut candidate = CandidateWorldView::from_base(&crate::BaseWorldView::new(initial));
        let timeline_id = candidate.timeline_id();
        let initial_head = candidate.version().head_event_seq;
        let mut expected_seq = initial_head;
        let mut head = initial_head;

        for event in events {
            let next_seq = expected_seq
                .value()
                .checked_add(1)
                .map(EventSeq::new)
                .ok_or(ReplayError::EventSeqOverflow {
                    event_seq: expected_seq,
                })?;
            if event.timeline_id != timeline_id {
                return Err(ReplayError::TimelineMismatch {
                    expected: timeline_id,
                    actual: event.timeline_id,
                    event_seq: event.event_seq,
                });
            }
            if event.event_seq != next_seq {
                return Err(ReplayError::NonContiguousEventSeq {
                    expected: next_seq,
                    actual: event.event_seq,
                });
            }
            if event.id.is_nil() {
                return Err(ReplayError::InvalidEvent {
                    event_seq: event.event_seq,
                    event_id: event.id,
                    reason: ReplayEventError::NilIdentity,
                });
            }
            if candidate.event_exists(event.id) {
                return Err(ReplayError::DuplicateEvent {
                    event_id: event.id,
                    event_seq: event.event_seq,
                });
            }
            candidate = replay_event(&candidate, event)?;
            head = event.event_seq;
            expected_seq = event.event_seq;
        }

        let materialization = candidate.into_base_snapshot().with_event_head(head);
        Ok(ReplayResult {
            materialization,
            head_event_seq: head,
        })
    }
}

/// Convenience entry point for stateless World-State replay.
///
/// # Errors
///
/// Returns the same deterministic history failures as
/// [`ReplayEngine::replay`].
pub fn replay_world_state(
    initial: BaseWorldSnapshot,
    events: &[CommittedEvent],
) -> Result<ReplayResult, ReplayError> {
    ReplayEngine::replay(initial, events)
}

fn replay_event(
    candidate: &CandidateWorldView,
    event: &CommittedEvent,
) -> Result<CandidateWorldView, ReplayError> {
    let mut event_candidate = candidate.fork();
    let mut reference_candidate = candidate.fork();
    for causal_link in &event.causal_links {
        let cause_event_id = causal_link.event_id();
        if !candidate.event_exists(cause_event_id) {
            return Err(ReplayError::InvalidEventReference {
                event_id: event.id,
                event_seq: event.event_seq,
                reason: ReplayEventError::InvalidCausalReference { cause_event_id },
            });
        }
    }

    for effect in &event.effects {
        validate_and_apply_effect(&mut event_candidate, event, effect)?;
        if matches!(
            effect,
            WorldEffect::CreateEntity { .. } | WorldEffect::CreateRelationship { .. }
        ) {
            reference_candidate.apply_effect(effect);
        }
    }

    for participant in &event.participants {
        if participant.entity_id.is_nil() {
            return Err(ReplayError::InvalidEventReference {
                event_id: event.id,
                event_seq: event.event_seq,
                reason: ReplayEventError::NilParticipant {
                    entity_id: participant.entity_id,
                },
            });
        }
        if reference_candidate.entity(participant.entity_id).is_none() {
            return Err(ReplayError::InvalidEventReference {
                event_id: event.id,
                event_seq: event.event_seq,
                reason: ReplayEventError::MissingParticipantEntity {
                    entity_id: participant.entity_id,
                },
            });
        }
    }
    for relationship in &event.relationship_refs {
        if reference_candidate
            .relationship(relationship.relationship_id)
            .is_none()
        {
            return Err(ReplayError::InvalidEventReference {
                event_id: event.id,
                event_seq: event.event_seq,
                reason: ReplayEventError::MissingRelationshipReference {
                    relationship_id: relationship.relationship_id,
                },
            });
        }
    }

    event_candidate.note_event(event.id);
    Ok(event_candidate)
}

fn validate_and_apply_effect(
    candidate: &mut CandidateWorldView,
    event: &CommittedEvent,
    effect: &WorldEffect,
) -> Result<(), ReplayError> {
    let reason = match effect {
        WorldEffect::CreateEntity { entity_id } => {
            if entity_id.is_nil() {
                Some(ReplayEffectError::NilIdentity {
                    kind: "Entity",
                    id: entity_id.to_string(),
                })
            } else if candidate.entity(*entity_id).is_some() {
                Some(ReplayEffectError::DuplicateEntity {
                    entity_id: *entity_id,
                })
            } else {
                None
            }
        }
        WorldEffect::PutFacet { owner, .. } | WorldEffect::RemoveFacet { owner, .. } => {
            if owner_exists(candidate, *owner) {
                None
            } else {
                Some(ReplayEffectError::MissingFacetOwner { owner: *owner })
            }
        }
        WorldEffect::CreateRelationship {
            relationship_id,
            participants,
            ..
        } => {
            if relationship_id.is_nil() {
                Some(ReplayEffectError::NilIdentity {
                    kind: "Relationship",
                    id: relationship_id.to_string(),
                })
            } else if candidate.relationship_identity_exists(*relationship_id) {
                Some(ReplayEffectError::DuplicateRelationship {
                    relationship_id: *relationship_id,
                })
            } else if participants.is_empty() {
                Some(ReplayEffectError::EmptyRelationshipParticipants {
                    relationship_id: *relationship_id,
                })
            } else {
                let mut seen = std::collections::HashSet::new();
                let mut failure = None;
                for participant in participants {
                    if participant.entity_id.is_nil() {
                        failure = Some(ReplayEffectError::NilRelationshipParticipant {
                            relationship_id: *relationship_id,
                            entity_id: participant.entity_id,
                        });
                        break;
                    }
                    if candidate.entity(participant.entity_id).is_none() {
                        failure = Some(ReplayEffectError::MissingRelationshipParticipant {
                            relationship_id: *relationship_id,
                            entity_id: participant.entity_id,
                        });
                        break;
                    }
                    if !seen.insert(participant.entity_id) {
                        failure = Some(ReplayEffectError::DuplicateRelationshipParticipant {
                            relationship_id: *relationship_id,
                            entity_id: participant.entity_id,
                        });
                        break;
                    }
                }
                failure
            }
        }
        WorldEffect::EndRelationship { relationship_id } => {
            if candidate.relationship(*relationship_id).is_none() {
                Some(ReplayEffectError::MissingActiveRelationship {
                    relationship_id: *relationship_id,
                })
            } else {
                None
            }
        }
    };

    if let Some(reason) = reason {
        return Err(ReplayError::ImpossibleEffect {
            event_id: event.id,
            event_seq: event.event_seq,
            reason,
        });
    }
    candidate.apply_effect(effect);
    Ok(())
}

fn owner_exists(candidate: &CandidateWorldView, owner: FacetOwner) -> bool {
    match owner {
        FacetOwner::Entity(entity_id) => candidate.entity(entity_id).is_some(),
        FacetOwner::Relationship(relationship_id) => {
            candidate.relationship(relationship_id).is_some()
        }
    }
}

#[cfg(test)]
mod tests {
    use loom_core::{
        AssociationRole, Entity, EventTypeId, FacetTypeId, RelationshipParticipant,
        RelationshipTypeId, SchemaRevision, StateRevision, TimelineVersion, WorldId, WorldInstant,
    };
    use loom_protocol::{EventParticipant, EventRelationshipRef, ProposedEvent};
    use serde_json::json;
    use uuid::Uuid;

    use super::*;

    fn world() -> WorldId {
        WorldId::new(Uuid::from_u128(1))
    }

    fn timeline() -> TimelineId {
        TimelineId::new(Uuid::from_u128(2))
    }

    fn entity(value: u128) -> EntityId {
        EntityId::new(Uuid::from_u128(value))
    }

    fn relationship(value: u128) -> RelationshipId {
        RelationshipId::new(Uuid::from_u128(value))
    }

    fn event(value: u128) -> EventId {
        EventId::new(Uuid::from_u128(value))
    }

    fn initial() -> BaseWorldSnapshot {
        BaseWorldSnapshot::new(
            world(),
            timeline(),
            TimelineVersion::new(EventSeq::new(0), StateRevision::new(0)),
            WorldInstant::new(7),
        )
        .with_entity(Entity {
            id: entity(10),
            world_id: world(),
        })
        .with_entity(Entity {
            id: entity(11),
            world_id: world(),
        })
    }

    fn committed(seq: u64, value: u128, effects: Vec<WorldEffect>) -> CommittedEvent {
        let proposal = ProposedEvent {
            id: event(value),
            event_type: EventTypeId::from("history.fact"),
            schema_revision: SchemaRevision::new(1),
            participants: Vec::new(),
            relationship_refs: Vec::new(),
            causal_links: Vec::new(),
            payload: json!({"value": value}),
            effects,
        };
        CommittedEvent::from_proposed(
            timeline(),
            EventSeq::new(seq),
            &proposal,
            WorldInstant::new(999),
        )
    }

    #[test]
    fn replays_all_mechanical_effects_and_same_event_structural_introduction() {
        let created_entity = entity(20);
        let created_relationship = relationship(30);
        let facet_type = FacetTypeId::from("history.value");
        let events = vec![
            committed(
                1,
                100,
                vec![
                    WorldEffect::CreateEntity {
                        entity_id: created_entity,
                    },
                    WorldEffect::PutFacet {
                        owner: FacetOwner::entity(created_entity),
                        facet_type: facet_type.clone(),
                        schema_revision: SchemaRevision::new(1),
                        value: json!({"value": 1}),
                    },
                    WorldEffect::CreateRelationship {
                        relationship_id: created_relationship,
                        relationship_type: RelationshipTypeId::from("history.link"),
                        participants: vec![
                            RelationshipParticipant::new(
                                created_entity,
                                AssociationRole::from("left"),
                            ),
                            RelationshipParticipant::new(
                                entity(10),
                                AssociationRole::from("right"),
                            ),
                        ],
                    },
                    WorldEffect::PutFacet {
                        owner: FacetOwner::relationship(created_relationship),
                        facet_type: facet_type.clone(),
                        schema_revision: SchemaRevision::new(1),
                        value: json!({"value": 2}),
                    },
                ],
            ),
            committed(
                2,
                101,
                vec![WorldEffect::RemoveFacet {
                    owner: FacetOwner::entity(created_entity),
                    facet_type: facet_type.clone(),
                }],
            ),
            committed(
                3,
                102,
                vec![WorldEffect::EndRelationship {
                    relationship_id: created_relationship,
                }],
            ),
        ];

        let replayed = ReplayEngine::replay(initial(), &events).expect("history should replay");
        let view = replayed.world_view();
        assert_eq!(replayed.head_event_seq(), EventSeq::new(3));
        assert_eq!(
            replayed.materialization().version().head_event_seq,
            EventSeq::new(3)
        );
        assert!(view.entity(created_entity).is_some());
        assert!(
            view.facet(FacetOwner::entity(created_entity), &facet_type)
                .is_none()
        );
        assert!(view.relationship(created_relationship).is_none());
        assert_eq!(
            view.facet(FacetOwner::relationship(created_relationship), &facet_type)
                .expect("Relationship Facet should remain materialized after lifecycle end")
                .value(),
            &json!({"value": 2})
        );
    }

    #[test]
    fn replays_zero_effect_event_and_multi_event_batch_in_order() {
        let facet_type = FacetTypeId::from("history.value");
        let events = vec![
            committed(1, 200, Vec::new()),
            committed(
                2,
                201,
                vec![WorldEffect::PutFacet {
                    owner: FacetOwner::entity(entity(10)),
                    facet_type: facet_type.clone(),
                    schema_revision: SchemaRevision::new(1),
                    value: json!({"value": 3}),
                }],
            ),
            committed(
                3,
                202,
                vec![WorldEffect::PutFacet {
                    owner: FacetOwner::entity(entity(10)),
                    facet_type: facet_type.clone(),
                    schema_revision: SchemaRevision::new(1),
                    value: json!({"value": 4}),
                }],
            ),
        ];

        let replayed = replay_world_state(initial(), &events).expect("batch should replay");
        assert_eq!(replayed.head_event_seq(), EventSeq::new(3));
        assert_eq!(
            replayed
                .world_view()
                .facet(FacetOwner::entity(entity(10)), &facet_type)
                .expect("last Event should win")
                .value(),
            &json!({"value": 4})
        );
    }

    #[test]
    fn preserves_event_boundary_references_for_structural_introduction() {
        let created_entity = entity(40);
        let created_relationship = relationship(41);
        let mut event = committed(
            1,
            300,
            vec![
                WorldEffect::CreateEntity {
                    entity_id: created_entity,
                },
                WorldEffect::CreateRelationship {
                    relationship_id: created_relationship,
                    relationship_type: RelationshipTypeId::from("history.link"),
                    participants: vec![RelationshipParticipant::new(created_entity, "member")],
                },
            ],
        );
        event.participants = vec![EventParticipant::new(created_entity, "created")];
        event.relationship_refs = vec![EventRelationshipRef::new(created_relationship, "created")];

        ReplayEngine::replay(initial(), &[event]).expect("same-Event references should replay");
    }

    #[test]
    fn rejects_non_contiguous_and_impossible_history_with_typed_errors() {
        let gap = ReplayEngine::replay(initial(), &[committed(2, 400, Vec::new())])
            .expect_err("EventSeq gap must fail");
        assert!(matches!(gap, ReplayError::NonContiguousEventSeq { .. }));

        let impossible = ReplayEngine::replay(
            initial(),
            &[committed(
                1,
                401,
                vec![WorldEffect::PutFacet {
                    owner: FacetOwner::entity(entity(999)),
                    facet_type: FacetTypeId::from("history.value"),
                    schema_revision: SchemaRevision::new(1),
                    value: json!(true),
                }],
            )],
        )
        .expect_err("missing Facet owner must fail");
        assert!(matches!(
            impossible,
            ReplayError::ImpossibleEffect {
                reason: ReplayEffectError::MissingFacetOwner { .. },
                ..
            }
        ));
    }

    #[test]
    fn occurred_at_does_not_change_materialization_or_world_time() {
        let mut first = committed(
            1,
            500,
            vec![WorldEffect::PutFacet {
                owner: FacetOwner::entity(entity(10)),
                facet_type: FacetTypeId::from("history.value"),
                schema_revision: SchemaRevision::new(1),
                value: json!(1),
            }],
        );
        let mut second = first.clone();
        first.occurred_at = WorldInstant::new(-10_000);
        second.occurred_at = WorldInstant::new(10_000);
        let first_result = ReplayEngine::replay(initial(), &[first]).expect("first history");
        let second_result = ReplayEngine::replay(initial(), &[second]).expect("second history");
        assert_eq!(
            first_result.head_event_seq(),
            second_result.head_event_seq()
        );
        assert_eq!(first_result.world_view().world_time(), WorldInstant::new(7));
        assert_eq!(
            second_result.world_view().world_time(),
            WorldInstant::new(7)
        );
        assert_eq!(
            first_result.world_view().facet(
                FacetOwner::entity(entity(10)),
                &FacetTypeId::from("history.value")
            ),
            second_result.world_view().facet(
                FacetOwner::entity(entity(10)),
                &FacetTypeId::from("history.value")
            )
        );
    }
}
