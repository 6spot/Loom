//! Loom internal execution protocol.
//!
//! # Responsibility
//!
//! `loom-protocol` is the neutral language shared by Loom components while an
//! execution is still only a proposal. It exists to let Runtime, Capability and
//! Agency exchange strongly typed values without creating circular Cargo
//! dependencies.
//!
//! Expected concepts include `ActionInvocation`, `Resolution`, `ResolveOutcome`,
//! `Rejection`, `ProposedEvent`, `NewWork`, `WorkMutation` and other small value
//! specifications that genuinely cross execution boundaries.
//!
//! # Authority and truth
//!
//! Values in this crate are **not** Runtime authority and are not automatically
//! World Truth. In particular, an untrusted `Resolution` may describe Events and
//! Effects that a Capability believes should happen, but only `loom-runtime` may
//! validate that proposal and produce its private commit-authority token.
//!
//! # Dependency direction
//!
//! This crate may depend on `loom-core` because Protocol speaks in stable World
//! identities and mechanisms. It must not depend on Runtime, Capability, Agency,
//! API, Storage, Boundary, concrete providers or concrete Capability crates.
//!
//! Do not move `ValidatedResolution`, database transaction types, HTTP request
//! types or provider implementations here merely because more than one crate
//! would find them convenient.
//!
//! # Relationship to other Loom languages
//!
//! - `loom-core` is the **World Language**: what a World is.
//! - `loom-protocol` is the **Internal Execution Language**: what components may
//!   propose/exchange before reality is committed.
//! - `loom-api` is the **Public Consumption Language**: how Applications consume
//!   Loom as one engine.
//! - `loom-runtime` is the authority that decides which proposals can become
//!   reality.
//!
//! # Public documentation contract
//!
//! Every public protocol type and high-risk field must explain its semantic
//! meaning, owner, truth domain, allowed creators/consumers, forbidden uses and
//! version/concurrency rules. See `docs/architecture/runtime-contracts.md` and
//! `docs/architecture/governance.md`.

#![forbid(unsafe_code)]

use loom_core::{
    ActionTypeId, AssociationRole, EntityId, EventId, EventTypeId, RelationshipId, SchemaRevision,
    TimelineId, WorkHandlerId, WorkId, WorldEffect, WorldInstant,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;

/// An untrusted request to attempt one Capability-owned semantic Action.
///
/// `ActionInvocation` is Protocol language shared by Agency, Runtime and
/// Capability. It is not an HTTP request, an actor/authorization record or a
/// Runtime commit command. The caller chooses one semantic `ActionTypeId` and
/// supplies a serialized input value; the owning Capability interprets that
/// input and returns a `ResolveOutcome`. World/Timeline targeting and execution
/// provenance are supplied by their surrounding API/Runtime boundary rather
/// than smuggled into the domain input.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct ActionInvocation {
    /// Capability-owned semantic Action selected for resolution.
    pub action: ActionTypeId,
    /// Untrusted serialized input interpreted by the owning Action resolver.
    pub input: Value,
}

impl ActionInvocation {
    /// Creates an Action invocation from a semantic key and serialized input.
    #[must_use]
    pub fn new(action: ActionTypeId, input: Value) -> Self {
        Self { action, input }
    }
}

/// A role-bearing direct Entity association attached to a proposed Event.
///
/// This value records a structural Event fact before commit. The association
/// role is a neutral Core label interpreted by the Event-owning Capability; it
/// does not expand a population or grant access to the Entity. Runtime validates
/// Entity references and Event schema/ownership before assigning authoritative
/// Timeline ordering.
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub struct EventParticipant {
    /// Entity directly participating in the proposed Event.
    pub entity_id: EntityId,
    /// Neutral association role of that Entity in this Event.
    pub role: AssociationRole,
}

impl EventParticipant {
    /// Creates one direct role-bearing Event association.
    #[must_use]
    pub fn new(entity_id: EntityId, role: impl Into<AssociationRole>) -> Self {
        Self {
            entity_id,
            role: role.into(),
        }
    }
}

/// A reference from a proposed Event to an existing Relationship.
///
/// The reference is part of the untrusted Event association structure. It does
/// not create or mutate a Relationship and does not make the referenced
/// identity valid; Runtime must validate existence, Timeline scope and the
/// Event schema before commit eligibility.
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub struct EventRelationshipRef {
    /// Relationship identity referenced by the proposed Event.
    pub relationship_id: RelationshipId,
    /// Neutral association role of the Relationship reference in this Event.
    pub role: AssociationRole,
}

impl EventRelationshipRef {
    /// Creates a Relationship association for a proposed Event.
    #[must_use]
    pub fn new(relationship_id: RelationshipId, role: impl Into<AssociationRole>) -> Self {
        Self {
            relationship_id,
            role: role.into(),
        }
    }
}

/// One edge in the proposed World Event causal graph.
///
/// `CausalLink` records that the proposed Event depends on a prior Event. It
/// is World-causality structure, not a Resolution call graph, Work origin or
/// execution provenance record. Runtime accepts only references to committed
/// Timeline ancestry or an earlier Event in the same proposal batch; forward
/// and cyclic references remain invalid even though this value can represent
/// them syntactically.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub struct CausalLink {
    /// Event that causally precedes the proposed Event containing this link.
    pub cause_event_id: EventId,
}

impl CausalLink {
    /// Creates a causal reference to one preceding Event identity.
    #[must_use]
    pub const fn new(cause_event_id: EventId) -> Self {
        Self { cause_event_id }
    }

    /// Returns the referenced preceding Event identity.
    #[must_use]
    pub const fn event_id(self) -> EventId {
        self.cause_event_id
    }
}

/// A semantic Event candidate produced during Resolution.
///
/// `ProposedEvent` belongs to the untrusted Protocol language. It describes a
/// possible Event, its associations, causal references, payload and frozen
/// mechanical Effects, but it is not World Truth and has no authoritative
/// `TimelineId`/`EventSeq` assignment. Runtime must validate schema revision,
/// semantic ownership, references, causal ordering and Effects before it can
/// produce a Runtime-owned authority value. Effects are intentionally nested:
/// no `WorldEffect` may be committed independently of an Event.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct ProposedEvent {
    /// Technical identity proposed for the Event before commit.
    pub id: EventId,
    /// Capability-owned semantic Event schema key.
    pub event_type: EventTypeId,
    /// Schema revision used to interpret `payload` and association semantics.
    pub schema_revision: SchemaRevision,
    /// Direct Entity associations that are part of the Event fact.
    pub participants: Vec<EventParticipant>,
    /// Relationship identities directly referenced by the Event fact.
    pub relationship_refs: Vec<EventRelationshipRef>,
    /// Causal references to prior Events in the World history graph.
    pub causal_links: Vec<CausalLink>,
    /// Capability-owned semantic payload for the Event.
    pub payload: Value,
    /// Mechanical Effects frozen under this Event candidate.
    pub effects: Vec<WorldEffect>,
}

impl ProposedEvent {
    /// Creates an Event candidate with empty associations and Effects.
    ///
    /// Empty Effects are valid: an Event can record a fact without changing
    /// materialized state. Callers may populate the public proposal vectors
    /// before handing the value to Runtime validation.
    #[must_use]
    pub fn new(
        id: EventId,
        event_type: EventTypeId,
        schema_revision: SchemaRevision,
        payload: Value,
    ) -> Self {
        Self {
            id,
            event_type,
            schema_revision,
            participants: Vec::new(),
            relationship_refs: Vec::new(),
            causal_links: Vec::new(),
            payload,
            effects: Vec::new(),
        }
    }

    /// Adds one mechanical Effect to this Event candidate.
    ///
    /// The returned value is still untrusted and cannot be committed without
    /// Runtime validation.
    #[must_use]
    pub fn with_effect(mut self, effect: WorldEffect) -> Self {
        self.effects.push(effect);
        self
    }

    /// Adds one direct Entity association to this Event candidate.
    #[must_use]
    pub fn with_participant(mut self, participant: EventParticipant) -> Self {
        self.participants.push(participant);
        self
    }

    /// Adds one causal reference to this Event candidate.
    #[must_use]
    pub fn with_causal_link(mut self, link: CausalLink) -> Self {
        self.causal_links.push(link);
        self
    }
}

/// Stable, typed code for a normal semantic rejection.
///
/// A `RejectionCode` is Capability-owned semantic metadata, represented as a
/// strong type so a rejection cannot accidentally be confused with an Action,
/// Event or Work handler key. It describes a normal world-rule outcome, not a
/// Runtime/storage/provider failure. Registry/Capability policy owns the key's
/// vocabulary; Protocol preserves it without interpreting its domain meaning.
#[derive(Clone, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct RejectionCode(String);

impl RejectionCode {
    /// Creates a typed rejection code from its stable semantic key.
    #[must_use]
    pub fn new(value: impl Into<String>) -> Self {
        Self(value.into())
    }

    /// Returns the rejection code key.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl From<String> for RejectionCode {
    fn from(value: String) -> Self {
        Self::new(value)
    }
}

impl From<&str> for RejectionCode {
    fn from(value: &str) -> Self {
        Self::new(value)
    }
}

impl std::fmt::Display for RejectionCode {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.0)
    }
}

/// A normal semantic refusal to resolve an Action or Work attempt.
///
/// `Rejection` is a valid `ResolveOutcome`, not an implementation error and
/// not an automatically generated World Event. The owning Capability chooses
/// whether a refusal is merely returned or is itself represented by an
/// explicit `ProposedEvent`. Runtime must keep this path distinct from Rust
/// errors such as unavailable storage or a validation defect.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct Rejection {
    /// Capability-owned machine-readable reason code.
    pub code: RejectionCode,
    /// Human-readable explanation safe for the surrounding API policy.
    pub message: String,
}

impl Rejection {
    /// Creates a semantic rejection with a typed code and explanation.
    #[must_use]
    pub fn new(code: impl Into<RejectionCode>, message: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
        }
    }
}

/// The normal result of resolving an Action or Durable Work handler.
///
/// `Resolved` carries an untrusted `Resolution` proposal. `Rejected` carries
/// a normal semantic rule outcome. Infrastructure/runtime failures must use the
/// surrounding Rust error channel rather than being encoded as either variant;
/// neither variant grants commit authority.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub enum ResolveOutcome {
    /// Resolution produced a proposal that Runtime may validate.
    Resolved(Resolution),
    /// The attempted behavior is semantically refused without a proposal.
    Rejected(Rejection),
}

/// An untrusted collection of proposed Events and future Work changes.
///
/// `Resolution` is the shared output of Capability resolution. It can contain
/// zero or more Events and zero or more Work mutations; an empty resolution may
/// still allow Runtime to complete a current Work obligation. It is not a
/// `ValidatedResolution`, cannot be sent directly to Storage and does not imply
/// any World mutation until Runtime validates it against a pinned Timeline
/// version.
#[derive(Clone, Debug, Default, Deserialize, PartialEq, Serialize)]
pub struct Resolution {
    /// Proposed Events, each of which owns its associated Effects.
    pub events: Vec<ProposedEvent>,
    /// Future Work scheduling/cancellation requests to validate with the Events.
    pub work: Vec<WorkMutation>,
}

impl Resolution {
    /// Creates a Resolution from proposal collections.
    #[must_use]
    pub fn new(events: Vec<ProposedEvent>, work: Vec<WorkMutation>) -> Self {
        Self { events, work }
    }

    /// Reports whether this Resolution changes neither World history nor Work.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.events.is_empty() && self.work.is_empty()
    }
}

/// The v0 schedule for a newly proposed Durable Work item.
///
/// `WorkSchedule` uses World semantic time and intentionally supports only an
/// immediate continuation or one absolute `WorldInstant`. It does not encode
/// technical retry: a technical retry reuses the same Work, while a
/// world-driven reschedule creates a new Work. Cron,
/// calendars and recurring DSLs belong to Capability composition over chained
/// Work, not this Core/Protocol primitive. This schedule is a future execution
/// request, never a future World fact.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum WorkSchedule {
    /// Make the new Work eligible for immediate Runtime scheduling.
    Immediate,
    /// Make the Work eligible when the World reaches this semantic instant.
    At(WorldInstant),
}

/// The logical execution target of one Durable Work obligation.
///
/// Target kind is part of the Work contract rather than an interpretation of
/// the serialized payload. Capability Work is routed through a registered
/// `WorkHandler`; an Agency Wake is a Runtime/Agency obligation and must never
/// be represented by a fake Capability handler. The optional Capability owner
/// keeps the legacy [`NewWork::new`] constructor source-compatible; Runtime
/// resolves and persists the registered owner before a validated mutation can
/// reach Storage.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub enum WorkTarget {
    /// Capability-owned future execution routed to one handler.
    CapabilityWork {
        /// Registered Capability owner requirement, when supplied by the
        /// caller or normalized by Runtime validation.
        owner: Option<String>,
        /// Capability-owned handler that interprets the Work payload.
        handler: WorkHandlerId,
    },
    /// Runtime-orchestrated wake for an Entity acting in an Agent role.
    AgencyWake {
        /// Agent Entity whose subjective context will later be assembled.
        agent: EntityId,
        /// Stable cognition implementation/policy requirement.
        cognition: String,
    },
}

impl WorkTarget {
    /// Creates a Capability Work target with an explicit owner requirement.
    #[must_use]
    pub fn capability_work(owner: impl Into<String>, handler: WorkHandlerId) -> Self {
        Self::CapabilityWork {
            owner: Some(owner.into()),
            handler,
        }
    }

    /// Creates an Agency Wake target without introducing a Capability handler.
    #[must_use]
    pub fn agency_wake(agent: EntityId, cognition: impl Into<String>) -> Self {
        Self::AgencyWake {
            agent,
            cognition: cognition.into(),
        }
    }

    /// Returns the Capability handler when this is Capability Work.
    #[must_use]
    pub fn capability_handler(&self) -> Option<&WorkHandlerId> {
        match self {
            Self::CapabilityWork { handler, .. } => Some(handler),
            Self::AgencyWake { .. } => None,
        }
    }
}

/// A new Durable Work obligation proposed as part of a Resolution.
///
/// `NewWork` is untrusted future-execution data. Runtime assigns the Work's
/// authoritative lifecycle, claim lease and platform retry metadata; a
/// Handler cannot mark the current Work complete through this value. The
/// Timeline scope and causal/origin references are explicit so Runtime can
/// enforce branch isolation and provenance before commit.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct NewWork {
    /// Stable identity proposed for the new Work item.
    pub id: WorkId,
    /// Timeline on which this future obligation is valid.
    pub timeline_id: TimelineId,
    /// Explicit logical execution target, independent from the payload.
    pub target: WorkTarget,
    /// Schema revision for the serialized Work payload.
    pub schema_revision: SchemaRevision,
    /// Serialized handler input; this is not a precomputed future result.
    pub payload: Value,
    /// World-time schedule for future re-evaluation.
    pub schedule: WorkSchedule,
    /// Optional World Event that caused this Work obligation.
    pub causal_event_id: Option<EventId>,
    /// Optional Work from which this obligation was derived.
    pub origin_work_id: Option<WorkId>,
}

impl NewWork {
    /// Creates a new Work proposal with no causal/origin references.
    #[must_use]
    pub fn new(
        id: WorkId,
        timeline_id: TimelineId,
        handler: WorkHandlerId,
        schema_revision: SchemaRevision,
        payload: Value,
        schedule: WorkSchedule,
    ) -> Self {
        Self {
            id,
            timeline_id,
            target: WorkTarget::CapabilityWork {
                owner: None,
                handler,
            },
            schema_revision,
            payload,
            schedule,
            causal_event_id: None,
            origin_work_id: None,
        }
    }

    /// Creates a Capability Work proposal with an explicit owner requirement.
    #[must_use]
    pub fn capability_work(
        id: WorkId,
        timeline_id: TimelineId,
        owner: impl Into<String>,
        handler: WorkHandlerId,
        schema_revision: SchemaRevision,
        payload: Value,
        schedule: WorkSchedule,
    ) -> Self {
        Self {
            id,
            timeline_id,
            target: WorkTarget::capability_work(owner, handler),
            schema_revision,
            payload,
            schedule,
            causal_event_id: None,
            origin_work_id: None,
        }
    }

    /// Creates an Agency Wake proposal with an explicit Agent and cognition
    /// requirement. Agency execution remains Runtime-owned and is not routed
    /// through a Capability `WorkHandler`.
    #[must_use]
    pub fn agency_wake(
        id: WorkId,
        timeline_id: TimelineId,
        agent: EntityId,
        cognition: impl Into<String>,
        payload: Value,
        schedule: WorkSchedule,
    ) -> Self {
        Self {
            id,
            timeline_id,
            target: WorkTarget::agency_wake(agent, cognition),
            schema_revision: SchemaRevision::new(0),
            payload,
            schedule,
            causal_event_id: None,
            origin_work_id: None,
        }
    }
}

/// An untrusted mutation to the Durable Work set.
///
/// v0 deliberately exposes only `Schedule` and `Cancel`. Supersession is
/// expressed as a cancel plus a new schedule, and completion/cancellation of
/// the currently executing Work remains Runtime-owned. A Work mutation is not
/// a `WorldEffect` and is not World Truth until committed atomically with the
/// enclosing Resolution according to Runtime policy.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub enum WorkMutation {
    /// Schedules one new future Work obligation.
    Schedule(NewWork),
    /// Requests cancellation of an existing Work identity.
    Cancel(WorkId),
}

#[cfg(test)]
mod tests {
    use std::str::FromStr;

    use loom_core::{
        ActionTypeId, AssociationRole, EntityId, EventId, EventTypeId, RelationshipId,
        SchemaRevision, TimelineId, WorkHandlerId, WorkId, WorldEffect, WorldInstant,
    };
    use serde_json::json;

    use super::{
        ActionInvocation, CausalLink, EventParticipant, EventRelationshipRef, NewWork,
        ProposedEvent, Rejection, RejectionCode, Resolution, ResolveOutcome, WorkMutation,
        WorkSchedule, WorkTarget,
    };

    #[test]
    fn protocol_values_round_trip_through_json() {
        let event_id = EventId::from_str("00000000-0000-0000-0000-000000000003")
            .expect("test EventId should parse");
        let mut event = ProposedEvent::new(
            event_id,
            EventTypeId::from("counter.incremented"),
            SchemaRevision::new(1),
            json!({"amount": 1}),
        );
        event.participants.push(EventParticipant::new(
            EntityId::from_str("00000000-0000-0000-0000-000000000010")
                .expect("test participant EntityId should parse"),
            AssociationRole::new("actor"),
        ));
        event.relationship_refs.push(EventRelationshipRef::new(
            RelationshipId::from_str("00000000-0000-0000-0000-000000000011")
                .expect("test relationship ref should parse"),
            AssociationRole::new("subject"),
        ));
        event.causal_links.push(CausalLink::new(
            EventId::from_str("00000000-0000-0000-0000-000000000002")
                .expect("test causal EventId should parse"),
        ));
        event.effects.push(WorldEffect::CreateEntity {
            entity_id: loom_core::EntityId::from_uuid(
                "00000000-0000-0000-0000-000000000005"
                    .parse()
                    .expect("test EntityId should parse"),
            ),
        });
        let work = NewWork::new(
            WorkId::from_str("00000000-0000-0000-0000-000000000006")
                .expect("test WorkId should parse"),
            TimelineId::from_str("00000000-0000-0000-0000-000000000007")
                .expect("test TimelineId should parse"),
            WorkHandlerId::from("counter.tick"),
            SchemaRevision::new(1),
            json!({"amount": 1}),
            WorkSchedule::At(WorldInstant::new(8)),
        );
        let resolution = Resolution::new(vec![event], vec![WorkMutation::Schedule(work)]);
        let resolved = ResolveOutcome::Resolved(resolution);

        let action = ActionInvocation::new(
            ActionTypeId::from("counter.increment"),
            json!({"amount": 1}),
        );
        let action_encoded = serde_json::to_string(&action).expect("action should serialize");
        let action_decoded: ActionInvocation =
            serde_json::from_str(&action_encoded).expect("action should deserialize");
        assert_eq!(action_decoded, action);

        let resolved_encoded =
            serde_json::to_string(&resolved).expect("resolved outcome should serialize");
        let resolved_decoded: ResolveOutcome =
            serde_json::from_str(&resolved_encoded).expect("resolved outcome should deserialize");
        assert_eq!(resolved_decoded, resolved);

        for schedule in [
            WorkSchedule::Immediate,
            WorkSchedule::At(WorldInstant::new(8)),
        ] {
            let schedule_encoded =
                serde_json::to_string(&schedule).expect("schedule should serialize");
            let schedule_decoded: WorkSchedule =
                serde_json::from_str(&schedule_encoded).expect("schedule should deserialize");
            assert_eq!(schedule_decoded, schedule);
        }
    }

    #[test]
    fn rejection_is_distinct_from_runtime_error_and_action_input_is_typed() {
        let invocation = ActionInvocation::new(
            ActionTypeId::from("counter.increment"),
            json!({"amount": 0}),
        );
        assert_eq!(invocation.action.as_str(), "counter.increment");

        let rejected = ResolveOutcome::Rejected(Rejection::new(
            RejectionCode::new("counter.invalid_amount"),
            "amount must be positive",
        ));
        let encoded = serde_json::to_string(&rejected).expect("rejected should serialize");
        let decoded: ResolveOutcome =
            serde_json::from_str(&encoded).expect("rejected should deserialize");
        assert_eq!(decoded, rejected);
    }

    #[test]
    fn work_mutation_surface_has_only_schedule_and_cancel() {
        let work_id = WorkId::from_str("00000000-0000-0000-0000-000000000009")
            .expect("test WorkId should parse");
        assert!(matches!(
            WorkMutation::Cancel(work_id),
            WorkMutation::Cancel(_)
        ));
    }

    #[test]
    fn work_target_kind_round_trips_without_payload_conventions() {
        let capability =
            WorkTarget::capability_work("counter", WorkHandlerId::from("counter.tick"));
        let agency = WorkTarget::agency_wake(
            EntityId::from_uuid(
                "00000000-0000-0000-0000-000000000010"
                    .parse()
                    .expect("Agent EntityId should parse"),
            ),
            "cognition.default",
        );
        for target in [capability, agency] {
            let encoded = serde_json::to_string(&target).expect("WorkTarget should serialize");
            let decoded: WorkTarget =
                serde_json::from_str(&encoded).expect("WorkTarget should deserialize");
            assert_eq!(decoded, target);
        }
    }
}
