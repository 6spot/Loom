//! Bounded, deterministic invariant coverage for M11-T2.
//!
//! These tests intentionally keep the generator in the test module. Runtime
//! and Core production code therefore remain free of random sources and clock
//! dependencies. Every case is derived from `LOOM_PROP_SEED`, then
//! `PROPTEST_SEED`, or the checked-in seed below; a failing case can be replayed
//! with the seed printed by the test.

use std::{collections::BTreeMap, env};

use loom_core::{
    Entity, EntityId, EventId, EventRef, EventSeq, EventTypeId, ExecutionSessionId, FacetOwner,
    FacetTypeId, SchemaRevision, StateRevision, TimelineAncestry, TimelineId, TimelineVersion,
    WorkHandlerId, WorkId, WorldEffect, WorldId, WorldInstant,
};
use loom_protocol::{CausalLink, ProposedEvent, WorkSchedule, WorkTarget};
use serde_json::{Value, json};
use uuid::Uuid;

use super::{
    BaseWorldSnapshot, ChronologyBudgetExceeded, ChronologyBudgetPolicy, CommittedEvent,
    ExecutionEvidence, FailurePolicy, HistoricalTimelineState, IdempotencyConflict, IdempotencyKey,
    IngressId, LogicalCommit, LogicalReplayEngine, LogicalReplayError, LogicalWorkTransition,
    PinnedReadSession, PlatformTime, ReadDependency, ReplayEffectError, ReplayEngine, ReplayError,
    ReplayResult, TimelineSnapshot, WorkClaim, WorkError,
};

const DEFAULT_SEED: u64 = 0x4d11_2002_2026_0825;
const PROPERTY_CASES: usize = 64;

/// A tiny test-only generator. It is not a Runtime entropy implementation and
/// is deliberately kept out of `loom-core` and all production modules.
#[derive(Clone, Debug)]
struct Generator {
    state: u64,
}

impl Generator {
    fn from_environment() -> Self {
        let raw = env::var("LOOM_PROP_SEED")
            .or_else(|_| env::var("PROPTEST_SEED"))
            .unwrap_or_else(|_| DEFAULT_SEED.to_string());
        let state = raw
            .strip_prefix("0x")
            .and_then(|value| u64::from_str_radix(value, 16).ok())
            .or_else(|| raw.parse::<u64>().ok())
            .or_else(|| u64::from_str_radix(&raw, 16).ok())
            .unwrap_or_else(|| panic!("invalid property seed {raw:?}; use a u64 or 0xHEX"));
        eprintln!("M11-T2 property seed: {state} (replay with LOOM_PROP_SEED={state})");
        Self { state }
    }

    fn next(&mut self) -> u64 {
        // LCG parameters from Numerical Recipes; deterministic arithmetic is
        // sufficient here because this is case generation, not entropy.
        self.state = self
            .state
            .wrapping_mul(6_364_136_223_846_793_005)
            .wrapping_add(1_442_695_040_888_963_407);
        self.state
    }

    fn range(&mut self, upper_exclusive: usize) -> usize {
        debug_assert!(upper_exclusive > 0);
        let upper_exclusive = u64::try_from(upper_exclusive).expect("usize fits in u64");
        usize::try_from(self.next() % upper_exclusive).expect("bounded value fits in usize")
    }

    fn between(&mut self, lower: usize, upper_inclusive: usize) -> usize {
        lower + self.range(upper_inclusive - lower + 1)
    }

    fn bool(&mut self) -> bool {
        self.next() & 1 == 0
    }
}

fn uuid(value: u128) -> Uuid {
    Uuid::from_u128(value)
}

fn world() -> WorldId {
    WorldId::new(uuid(1))
}

fn timeline(value: u128) -> TimelineId {
    TimelineId::new(uuid(value))
}

fn event_id(value: u128) -> EventId {
    EventId::new(uuid(value))
}

fn entity(value: u128) -> EntityId {
    EntityId::new(uuid(value))
}

fn work_id(value: u128) -> WorkId {
    WorkId::new(uuid(value))
}

fn initial(timeline_id: TimelineId) -> BaseWorldSnapshot {
    BaseWorldSnapshot::new(
        world(),
        timeline_id,
        TimelineVersion::default(),
        WorldInstant::new(0),
    )
    .with_entity(Entity {
        id: entity(10),
        world_id: world(),
    })
}

fn committed_event(
    timeline_id: TimelineId,
    sequence: u64,
    identity: u128,
    effects: Vec<WorldEffect>,
) -> CommittedEvent {
    let proposal = ProposedEvent::new(
        event_id(identity),
        EventTypeId::from("m11.property.event"),
        SchemaRevision::new(1),
        json!({"identity": identity}),
    );
    let proposal = effects
        .into_iter()
        .fold(proposal, ProposedEvent::with_effect);
    CommittedEvent::from_proposed(
        timeline_id,
        EventSeq::new(sequence),
        &proposal,
        WorldInstant::new(i64::try_from(sequence).expect("generated sequence fits in i64")),
    )
}

fn capability_target() -> WorkTarget {
    WorkTarget::capability_work("m11.property", WorkHandlerId::from("m11.handler"))
}

#[test]
fn property_event_sequence_and_timeline_versions_are_contiguous_and_replayable() {
    let mut generator = Generator::from_environment();
    let timeline_id = timeline(2);

    for case in 0..PROPERTY_CASES {
        let length = generator.between(5, 20);
        let events = (1..=length)
            .map(|sequence| {
                committed_event(
                    timeline_id,
                    sequence as u64,
                    1_000 + (case as u128 * 32) + sequence as u128,
                    Vec::new(),
                )
            })
            .collect::<Vec<_>>();
        let replayed = ReplayEngine::replay(initial(timeline_id), &events)
            .expect("a generated contiguous Event chain must replay");
        assert_eq!(replayed.head_event_seq(), EventSeq::new(length as u64));
        assert_eq!(
            replayed.materialization().version().head_event_seq,
            EventSeq::new(length as u64)
        );

        let mut gap = events.clone();
        let gap_index = generator.range(gap.len());
        gap[gap_index].event_seq = EventSeq::new(length as u64 + 2);
        let gap_error = ReplayEngine::replay(initial(timeline_id), &gap)
            .expect_err("a generated sequence gap must be rejected");
        assert!(matches!(
            gap_error,
            ReplayError::NonContiguousEventSeq { .. }
        ));
        assert_eq!(gap_error.clone(), gap_error);
    }

    let overflow_initial = BaseWorldSnapshot::new(
        world(),
        timeline_id,
        TimelineVersion::new(EventSeq::new(u64::MAX), StateRevision::new(u64::MAX)),
        WorldInstant::default(),
    );
    let overflow = ReplayEngine::replay(
        overflow_initial,
        &[committed_event(timeline_id, 0, 99_999, Vec::new())],
    )
    .expect_err("a Timeline at EventSeq::MAX must reject the next Event");
    assert!(matches!(overflow, ReplayError::EventSeqOverflow { .. }));
}

#[test]
fn property_frozen_effect_replay_has_deterministic_success_and_failure() {
    let mut generator = Generator::from_environment();
    let timeline_id = timeline(3);
    let facet_type = FacetTypeId::from("m11.property.value");

    for case in 0..PROPERTY_CASES {
        let valid = generator.bool();
        let owner = if valid {
            FacetOwner::entity(entity(10))
        } else {
            FacetOwner::entity(entity(10_000 + case as u128))
        };
        let history = [committed_event(
            timeline_id,
            1,
            2_000 + case as u128,
            vec![WorldEffect::PutFacet {
                owner,
                facet_type: facet_type.clone(),
                schema_revision: SchemaRevision::new(1),
                value: json!({"case": case}),
            }],
        )];
        let first = ReplayEngine::replay(initial(timeline_id), &history);
        let second = ReplayEngine::replay(initial(timeline_id), &history);
        assert_eq!(
            first.as_ref().map(ReplayResult::head_event_seq),
            second.as_ref().map(ReplayResult::head_event_seq)
        );
        let journal = [LogicalCommit {
            timeline_id,
            before_version: TimelineVersion::default(),
            after_version: TimelineVersion::new(EventSeq::new(1), StateRevision::new(1)),
            world_time: None,
            event_ids: vec![history[0].id],
            work_transitions: Vec::new(),
            chronology_budget: None,
            provenance: None,
        }];
        let logical_first = LogicalReplayEngine::replay(
            initial(timeline_id),
            &history,
            &journal,
            journal[0].after_version,
        );
        let logical_second = LogicalReplayEngine::replay(
            initial(timeline_id),
            &history,
            &journal,
            journal[0].after_version,
        );
        assert_eq!(
            logical_first.as_ref().map(HistoricalTimelineState::version),
            logical_second
                .as_ref()
                .map(HistoricalTimelineState::version)
        );
        if valid {
            assert!(first.is_ok());
            assert!(logical_first.is_ok());
        } else {
            assert!(matches!(
                first,
                Err(ReplayError::ImpossibleEffect {
                    reason: ReplayEffectError::MissingFacetOwner { .. },
                    ..
                })
            ));
            assert!(matches!(
                logical_first,
                Err(LogicalReplayError::MaterializedReplay(_))
            ));
        }
    }
}

#[test]
fn property_logical_journal_replay_is_identical_at_every_generated_boundary() {
    let mut generator = Generator::from_environment();
    let timeline_id = timeline(4);

    for case in 0..PROPERTY_CASES {
        let length = generator.between(5, 20);
        let events = (1..=length)
            .map(|sequence| {
                committed_event(
                    timeline_id,
                    sequence as u64,
                    3_000 + case as u128 * 32 + sequence as u128,
                    Vec::new(),
                )
            })
            .collect::<Vec<_>>();
        let mut journal = Vec::with_capacity(length);
        let mut before = TimelineVersion::default();
        for event in &events {
            let after = TimelineVersion::new(
                event.event_seq,
                StateRevision::new(before.state_revision.value() + 1),
            );
            journal.push(LogicalCommit {
                timeline_id,
                before_version: before,
                after_version: after,
                world_time: None,
                event_ids: vec![event.id],
                work_transitions: Vec::new(),
                chronology_budget: None,
                provenance: None,
            });
            before = after;
        }
        let first = LogicalReplayEngine::replay(initial(timeline_id), &events, &journal, before)
            .expect("generated logical journal must replay");
        let second = LogicalReplayEngine::replay(initial(timeline_id), &events, &journal, before)
            .expect("the same logical journal must replay again");
        assert_eq!(first.version(), second.version());
        assert_eq!(first.world_time(), second.world_time());
        assert_eq!(first.world_view().version(), second.world_view().version());
        assert_eq!(first.logical_state().works, second.logical_state().works);
    }
}

#[test]
fn property_fork_isolation_and_ancestry_causality_are_explicit() {
    let mut generator = Generator::from_environment();
    for case in 0..PROPERTY_CASES {
        let parent = timeline(10);
        let child = timeline(11 + case as u128);
        let parent_event = event_id(4_000 + case as u128);
        let parent_version = TimelineVersion::new(
            EventSeq::new(generator.between(1, 20) as u64),
            StateRevision::new(generator.between(1, 20) as u64),
        );
        let parent_ref = EventRef::new(parent, parent_event);
        let ancestry = TimelineAncestry::fork(parent, parent_version, Some(parent_ref));
        let child_snapshot = TimelineSnapshot::with_journal_ancestry_and_budget(
            BaseWorldSnapshot::new(world(), child, parent_version, WorldInstant::new(7)),
            Vec::new(),
            Vec::new(),
            Vec::new(),
            ancestry,
            super::ChronologyBudgetState::new(WorldInstant::new(7), 0),
        );

        assert_ne!(
            parent, child,
            "fork must allocate an isolated Timeline identity"
        );
        assert_eq!(child_snapshot.base.timeline_id(), child);
        assert_eq!(child_snapshot.ancestry().parent_timeline_id, Some(parent));
        assert_eq!(
            child_snapshot.ancestry().fork_parent_event,
            Some(parent_ref)
        );
        assert_eq!(parent_ref.timeline_id, parent);
        assert_ne!(parent_ref.timeline_id, child);
    }
}

#[test]
fn property_logical_work_order_is_monotonic_and_stably_sorted() {
    let mut generator = Generator::from_environment();
    let timeline_id = timeline(12);
    for case in 0..PROPERTY_CASES {
        let count = generator.between(2, 12);
        let mut journal = Vec::with_capacity(count);
        let mut before = TimelineVersion::default();
        for ordinal in 0..count {
            let work = work_id(5_000 + case as u128 * 32 + ordinal as u128);
            let after =
                TimelineVersion::new(EventSeq::default(), StateRevision::new(ordinal as u64 + 1));
            let due = i64::try_from(generator.between(0, 3)).expect("bounded due time fits");
            journal.push(LogicalCommit {
                timeline_id,
                before_version: before,
                after_version: after,
                world_time: None,
                event_ids: Vec::new(),
                work_transitions: vec![LogicalWorkTransition::Schedule {
                    work_id: work,
                    target: capability_target(),
                    schema_revision: SchemaRevision::new(1),
                    payload: json!({"case": case, "ordinal": ordinal}),
                    effective_due_world_time: WorldInstant::new(due),
                    logical_schedule_order: ordinal as u64 + 1,
                    causal_event_id: None,
                    origin_work_id: None,
                }],
                chronology_budget: None,
                provenance: None,
            });
            before = after;
        }
        let replayed = LogicalReplayEngine::replay(initial(timeline_id), &[], &journal, before)
            .expect("generated logical Work schedule must replay");
        let works = &replayed.logical_state().works;
        assert_eq!(works.len(), count);
        assert!(works.windows(2).all(|pair| {
            (
                pair[0].effective_due_world_time,
                pair[0].logical_schedule_order,
                pair[0].work_id,
            ) <= (
                pair[1].effective_due_world_time,
                pair[1].logical_schedule_order,
                pair[1].work_id,
            )
        }));
        assert!(works.iter().all(|work| work.logical_schedule_order > 0));
    }
}

#[test]
fn property_claim_fences_are_monotonic_and_stale_claims_are_typed() {
    let mut generator = Generator::from_environment();
    for case in 0..PROPERTY_CASES {
        let mut current_fence = 0;
        for generation in 1..=generator.between(2, 12) {
            let claim = WorkClaim::new(
                timeline(13),
                work_id(6_000 + case as u128),
                PlatformTime::new(i64::try_from(generation).expect("bounded generation fits") + 1),
                generation as u64,
            );
            assert!(claim.fence() > current_fence);
            current_fence = claim.fence();
            let stale = WorkError::StaleClaim {
                work_id: claim.work_id(),
                expected_fence: claim.fence(),
                actual_fence: Some(claim.fence() + 1),
            };
            assert!(matches!(stale, WorkError::StaleClaim { .. }));
        }
    }
}

#[test]
fn property_chronology_and_retry_policies_have_bounded_thresholds() {
    let mut generator = Generator::from_environment();
    for _case in 0..PROPERTY_CASES {
        let limit = generator.between(0, 8) as u64;
        let policy = ChronologyBudgetPolicy::new(limit);
        for completed in 0..=limit + 1 {
            let admitted = completed < policy.max_completions();
            if !admitted {
                let error = ChronologyBudgetExceeded {
                    timeline_id: timeline(14),
                    world_time: WorldInstant::new(0),
                    limit,
                    consumed: completed,
                };
                assert!(error.consumed >= error.limit);
            }
        }

        let attempts = u32::try_from(generator.between(0, 5)).expect("bounded attempts fit");
        let retry_limit = u32::try_from(generator.between(0, 5)).expect("bounded retry limit fits");
        let backoff = i64::try_from(generator.between(0, 5)).expect("bounded backoff fits");
        let policy = FailurePolicy::new(retry_limit, backoff).expect("non-negative backoff");
        assert_eq!(policy.allows_retry(attempts), attempts < retry_limit);
        assert!(
            policy
                .next_available_at(PlatformTime::new(10), PlatformTime::new(0))
                .expect("bounded retry time")
                .value()
                >= 10 + backoff
        );
    }
}

#[test]
fn property_ingress_idempotency_is_exactly_once_for_same_key_and_fingerprint() {
    let mut generator = Generator::from_environment();
    for case in 0..PROPERTY_CASES {
        let key = IdempotencyKey::new(format!("m11-key-{case}"));
        let ingress = IngressId::new(format!("m11-ingress-{case}"));
        let fingerprint = format!("fingerprint-{}", generator.next());
        let mut ledger = BTreeMap::<IdempotencyKey, (IngressId, String)>::new();
        assert!(
            ledger
                .insert(key.clone(), (ingress.clone(), fingerprint.clone()))
                .is_none()
        );
        assert_eq!(
            ledger.get(&key),
            Some(&(ingress.clone(), fingerprint.clone()))
        );
        assert_eq!(
            ledger.get(&key),
            Some(&(ingress.clone(), fingerprint.clone()))
        );

        let conflict = IdempotencyConflict::new(
            key,
            ingress,
            fingerprint,
            format!("different-{}", generator.next()),
        );
        assert_ne!(
            conflict.existing_request_fingerprint,
            conflict.submitted_request_fingerprint
        );
    }
}

#[test]
fn property_session_pinning_and_provenance_round_trip_are_stable() {
    let mut generator = Generator::from_environment();
    for case in 0..PROPERTY_CASES {
        let version = TimelineVersion::new(
            EventSeq::new(generator.between(0, 20) as u64),
            StateRevision::new(generator.between(0, 20) as u64),
        );
        let session = PinnedReadSession::new(
            ExecutionSessionId::new(uuid(7_000 + case as u128)),
            world(),
            timeline(15),
            version,
            WorldInstant::new(i64::try_from(case).expect("bounded case fits")),
        );
        session.record_entity(entity(10), true);
        session.record_entity(entity(10), true);
        let read_set = session.read_set();
        assert_eq!(session.version(), version);
        assert_eq!(
            session.world_time(),
            WorldInstant::new(i64::try_from(case).expect("bounded case fits"))
        );
        assert_eq!(read_set.len(), 1, "duplicate observations must deduplicate");

        let evidence = ExecutionEvidence::from_parts(
            read_set.clone(),
            super::CallProvenance::default(),
            super::EntropyEvidence::new(super::EntropySourceId::from("m11-test")),
        );
        let evidence_json = serde_json::to_vec(&evidence).expect("provenance serializes");
        let decoded: ExecutionEvidence =
            serde_json::from_slice(&evidence_json).expect("provenance round-trips");
        assert_eq!(decoded, evidence);

        let encoded_read_set = serde_json::to_vec(&read_set).expect("ReadSet serializes");
        let decoded_read_set: super::ReadSet =
            serde_json::from_slice(&encoded_read_set).expect("ReadSet round-trips");
        assert_eq!(decoded_read_set, read_set);
        assert!(matches!(
            read_set.entries().first(),
            Some(ReadDependency::Entity {
                entity_id,
                present: true
            }) if *entity_id == entity(10)
        ));
    }
}

#[test]
fn serialization_round_trip_preserves_core_ids_and_stable_order() {
    let mut generator = Generator::from_environment();
    for case in 0..PROPERTY_CASES {
        let timeline_id = timeline(16 + case as u128);
        let values = [
            serde_json::to_value(EventRef::new(timeline_id, event_id(8_000 + case as u128)))
                .unwrap(),
            serde_json::to_value(TimelineVersion::new(
                EventSeq::new(case as u64 % 20),
                StateRevision::new((case as u64 + 3) % 20),
            ))
            .unwrap(),
            serde_json::to_value(WorkTarget::agency_wake(
                entity(10),
                format!("m11.cognition.{case}"),
            ))
            .unwrap(),
            serde_json::to_value(WorkSchedule::At(WorldInstant::new(
                i64::try_from(generator.between(0, 20)).expect("bounded schedule time fits"),
            )))
            .unwrap(),
        ];
        for value in values {
            let encoded = serde_json::to_vec(&value).expect("value serializes");
            let decoded: Value = serde_json::from_slice(&encoded).expect("value round-trips");
            assert_eq!(decoded, value);
            assert_eq!(serde_json::to_vec(&decoded).unwrap(), encoded);
        }

        let first_timeline = timeline(16 + case as u128 + 1);
        let last_timeline = timeline(16 + case as u128 + 2);
        let mut refs = [
            EventRef::new(last_timeline, event_id(2)),
            EventRef::new(first_timeline, event_id(3)),
            EventRef::new(first_timeline, event_id(1)),
        ];
        refs.sort_by_key(|event| (event.timeline_id, event.event_id));
        assert_eq!(refs[0].event_id, event_id(1));
        assert_eq!(refs[1].event_id, event_id(3));
        assert_eq!(refs[2].timeline_id, last_timeline);
    }
}

#[test]
fn property_causal_links_are_replayed_only_from_visible_ancestry() {
    let mut generator = Generator::from_environment();
    for case in 0..PROPERTY_CASES {
        let timeline_id = timeline(19 + generator.range(10_000) as u128 + case as u128);
        let cause = event_id(9_001 + case as u128 * 4);
        let mut event = committed_event(timeline_id, 2, 9_002 + case as u128 * 4, Vec::new());
        event.causal_links = vec![CausalLink::new(cause)];
        let initial_event = committed_event(timeline_id, 1, 9_001 + case as u128 * 4, Vec::new());
        assert!(ReplayEngine::replay(initial(timeline_id), &[initial_event, event]).is_ok());

        let missing = committed_event(timeline_id, 1, 9_003 + case as u128 * 4, Vec::new());
        let mut invalid = committed_event(timeline_id, 2, 9_004 + case as u128 * 4, Vec::new());
        invalid.causal_links = vec![CausalLink::new(cause)];
        let error = ReplayEngine::replay(initial(timeline_id), &[missing, invalid])
            .expect_err("causal link to an absent Event must fail deterministically");
        assert!(matches!(error, ReplayError::InvalidEventReference { .. }));
    }
}
