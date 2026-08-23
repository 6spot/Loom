use std::str::FromStr;

use loom_api::{
    IngressAuthorizationContext, IngressCompletion, IngressEnvelope, IngressId, IngressProvenance,
    IngressStatus, IngressTimeMetadata, TimelineTarget,
};
use loom_core::{ActionTypeId, EventSeq, ExecutionSessionId, StateRevision, TimelineVersion};
use loom_protocol::ActionInvocation;
use loom_runtime::{
    IngressAcceptance, IngressClaim, IngressError, IngressSubmission, IngressTechnicalFailure,
    PlatformTime,
};
use loom_storage::InMemoryStore;
use serde_json::json;

fn id<T>(value: u128) -> T
where
    T: FromStr,
    T::Err: std::fmt::Debug,
{
    format!("00000000-0000-0000-0000-{value:012x}")
        .parse()
        .expect("test identity should parse")
}

fn submission(ingress_id: &str, key: &str, input: serde_json::Value) -> IngressSubmission {
    IngressSubmission::new(
        "tenant-a",
        IngressEnvelope::new(
            IngressId::from(ingress_id),
            key,
            IngressProvenance::new("test-source").with_external_id("source-item-1"),
            TimelineTarget::new(id(1), id(2)),
            IngressAuthorizationContext::new(json!({"policy": "opaque"})),
            IngressTimeMetadata::from_source("source-time").with_platform_time("boundary-time"),
            ActionInvocation::new(ActionTypeId::from("test.action"), input),
        ),
        "canonical-fingerprint-v1",
        PlatformTime::new(10),
    )
}

#[test]
fn in_memory_ingress_acceptance_is_idempotent_and_does_not_touch_timeline() {
    let store = InMemoryStore::new();
    store
        .create_timeline(id(1), id(2))
        .expect("test Timeline should be created");
    let before = store
        .snapshot(id(2))
        .expect("test Timeline should be readable");

    let first = store
        .accept_ingress(submission("ingress-1", "key-1", json!({"value": 1})))
        .expect("first Ingress should be accepted");
    assert!(matches!(first, IngressAcceptance::Accepted(_)));
    let mut mismatch = submission("ingress-2", "key-1", json!({"value": 2}));
    mismatch.request_fingerprint = "different-fingerprint".to_owned();
    let duplicate = store
        .accept_ingress(mismatch)
        .expect("same key should return a platform outcome");
    assert!(matches!(
        duplicate,
        IngressAcceptance::IdempotencyConflict(_)
    ));

    let equivalent = store
        .accept_ingress(submission("ingress-3", "key-1", json!({"value": 3})))
        .expect("same canonical request should deduplicate");
    assert!(matches!(equivalent, IngressAcceptance::Deduplicated(_)));
    let after = store
        .snapshot(id(2))
        .expect("test Timeline should remain readable");
    assert_eq!(after.version(), before.version());
    assert_eq!(after.world_time(), before.world_time());
    assert!(after.events.is_empty());

    let record = store
        .ingress("ingress-1".into())
        .expect("accepted Ingress should be durable");
    assert!(matches!(record.status, IngressStatus::Accepted));
    assert_eq!(record.submission.envelope.provenance.source, "test-source");
    assert_eq!(record.submission.envelope.target.timeline_id, id(2));
    assert_eq!(record.submission.received_at, PlatformTime::new(10));
}

#[test]
fn in_memory_ingress_claim_reclaim_and_stale_fence_are_operational_only() {
    let store = InMemoryStore::new();
    store
        .create_timeline(id(1), id(2))
        .expect("test Timeline should be created");
    store
        .accept_ingress(submission("ingress-1", "key-1", json!({"value": 1})))
        .expect("first Ingress should be accepted");

    let first = store
        .claim_ingress(
            "ingress-1".into(),
            PlatformTime::new(10),
            PlatformTime::new(20),
        )
        .expect("first worker should claim");
    assert_eq!(first.fence(), 1);
    assert_eq!(first.attempt_count(), 1);
    assert_eq!(
        store.claim_ingress(
            "ingress-1".into(),
            PlatformTime::new(11),
            PlatformTime::new(21)
        ),
        Err(IngressError::AlreadyClaimed {
            ingress_id: "ingress-1".into(),
            claimed_until: PlatformTime::new(20),
        })
    );

    let recovered = store
        .claim_ingress(
            "ingress-1".into(),
            PlatformTime::new(20),
            PlatformTime::new(30),
        )
        .expect("expired worker lease should be reclaimable");
    assert_eq!(recovered.fence(), 2);
    assert_eq!(recovered.attempt_count(), 2);
    let stale_failure = IngressTechnicalFailure::new("stale", "old worker");
    assert!(matches!(
        store.retry_ingress(
            &first,
            PlatformTime::new(21),
            PlatformTime::new(25),
            stale_failure,
        ),
        Err(IngressError::StaleClaim { .. })
    ));

    let retried = store
        .retry_ingress(
            &recovered,
            PlatformTime::new(21),
            PlatformTime::new(25),
            IngressTechnicalFailure::new("temporary", "retry me"),
        )
        .expect("current worker should release a retryable record");
    assert!(matches!(retried.status, IngressStatus::Retryable(_)));
    let final_claim = store
        .claim_ingress(
            "ingress-1".into(),
            PlatformTime::new(25),
            PlatformTime::new(35),
        )
        .expect("retry should be claimable at its platform deadline");
    let completed = store
        .complete_ingress(
            &final_claim,
            id::<ExecutionSessionId>(3),
            IngressCompletion::NoChange,
            PlatformTime::new(26),
        )
        .expect("current worker should complete the operational record");
    assert!(matches!(
        completed.status,
        IngressStatus::Completed(IngressCompletion::NoChange)
    ));
    assert_eq!(completed.completed_session_id, Some(id(3)));
    assert_eq!(completed.completed_event_refs, Vec::new());

    let snapshot = store
        .snapshot(id(2))
        .expect("test Timeline should remain readable");
    assert_eq!(
        snapshot.version(),
        TimelineVersion::new(EventSeq::new(0), StateRevision::new(0))
    );
    assert!(snapshot.events.is_empty());
}

#[test]
fn in_memory_stale_claim_constructor_cannot_mutate_current_record() {
    let store = InMemoryStore::new();
    store
        .accept_ingress(submission("ingress-1", "key-1", json!({"value": 1})))
        .expect("first Ingress should be accepted");
    let claim = store
        .claim_ingress(
            "ingress-1".into(),
            PlatformTime::new(10),
            PlatformTime::new(20),
        )
        .expect("worker should claim");
    let forged = IngressClaim::new("ingress-1", PlatformTime::new(20), claim.fence() - 1, 1);
    assert!(matches!(
        store.fail_ingress(
            &forged,
            PlatformTime::new(11),
            IngressTechnicalFailure::new("forged", "must reject"),
        ),
        Err(IngressError::StaleClaim { .. })
    ));
}
