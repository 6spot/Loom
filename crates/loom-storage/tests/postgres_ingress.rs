mod support;

use std::str::FromStr;

use loom_api::{
    IngressAuthorizationContext, IngressEnvelope, IngressId, IngressProvenance,
    IngressTimeMetadata, TimelineTarget,
};
use loom_core::{ActionTypeId, TimelineId, WorldId};
use loom_protocol::ActionInvocation;
use loom_runtime::{
    IngressAcceptance, IngressError, IngressStatus, IngressStore, IngressSubmission,
    IngressTechnicalFailure, PlatformTime, WorldStore,
};
use loom_storage::PgStorage;
use serde_json::json;
use support::TestDatabase;

fn id<T>(value: u128) -> T
where
    T: FromStr,
    T::Err: std::fmt::Debug,
{
    format!("00000000-0000-0000-0000-{value:012x}")
        .parse()
        .expect("test identity should parse")
}

fn submission(
    world_id: WorldId,
    timeline_id: TimelineId,
    ingress_id: &str,
    key: &str,
    fingerprint: &str,
) -> IngressSubmission {
    IngressSubmission::new(
        "tenant-a",
        IngressEnvelope::new(
            IngressId::from(ingress_id),
            key,
            IngressProvenance::new("postgres-test"),
            TimelineTarget::new(world_id, timeline_id),
            IngressAuthorizationContext::new(json!({"opaque": true})),
            IngressTimeMetadata::none(),
            ActionInvocation::new(ActionTypeId::from("test.action"), json!({"value": 1})),
        ),
        fingerprint,
        PlatformTime::new(10),
    )
}

async fn seed_target(pool: &sqlx::PgPool, world_id: WorldId, timeline_id: TimelineId) {
    sqlx::query("INSERT INTO loom_world (world_id) VALUES ($1::uuid)")
        .bind(world_id.to_string())
        .execute(pool)
        .await
        .expect("test World should insert");
    sqlx::query("INSERT INTO loom_timeline (timeline_id, world_id) VALUES ($1::uuid, $2::uuid)")
        .bind(timeline_id.to_string())
        .bind(world_id.to_string())
        .execute(pool)
        .await
        .expect("test Timeline should insert");
}

#[tokio::test]
#[expect(
    clippy::too_many_lines,
    reason = "the integration test keeps the concurrent acceptance and fence handoff evidence together"
)]
async fn postgres_ingress_is_atomic_across_workers_and_survives_reopen() {
    let database = TestDatabase::provision("ingress").await;
    let pool = database.pool().await;
    let world_id = id::<WorldId>(0xb101);
    let timeline_id = id::<TimelineId>(0xb102);
    seed_target(&pool, world_id, timeline_id).await;
    let first = database.storage().await;
    let second = first.clone();
    let before = WorldStore::snapshot(&first, timeline_id)
        .await
        .expect("test Timeline should be readable before acceptance");

    let (left, right) = tokio::join!(
        IngressStore::accept(
            &first,
            submission(world_id, timeline_id, "ingress-a", "key-a", "fp-a")
        ),
        IngressStore::accept(
            &second,
            submission(world_id, timeline_id, "ingress-b", "key-a", "fp-a")
        )
    );
    let outcomes = [
        left.expect("first worker acceptance should succeed"),
        right.expect("second worker acceptance should succeed"),
    ];
    assert_eq!(
        outcomes
            .iter()
            .filter(|outcome| matches!(outcome, IngressAcceptance::Accepted(_)))
            .count(),
        1
    );
    let accepted_id = outcomes
        .iter()
        .find_map(|outcome| match outcome {
            IngressAcceptance::Accepted(receipt) => Some(receipt.ingress_id.clone()),
            IngressAcceptance::Deduplicated(_) | IngressAcceptance::IdempotencyConflict(_) => None,
        })
        .expect("one concurrent worker should own the accepted identity");
    let pending = IngressStore::list_recoverable(&first, PlatformTime::new(10), 10)
        .await
        .expect("accepted durable records should be enumerable for recovery");
    assert_eq!(pending, vec![accepted_id.clone()]);
    assert_eq!(
        outcomes
            .iter()
            .filter(|outcome| matches!(outcome, IngressAcceptance::Deduplicated(_)))
            .count(),
        1
    );

    let conflict = IngressStore::accept(
        &first,
        submission(world_id, timeline_id, "ingress-c", "key-a", "different-fp"),
    )
    .await
    .expect("fingerprint conflict is a normal platform result");
    assert!(matches!(
        conflict,
        IngressAcceptance::IdempotencyConflict(_)
    ));
    let after = WorldStore::snapshot(&first, timeline_id)
        .await
        .expect("test Timeline should be readable after acceptance");
    assert_eq!(after.version(), before.version());
    assert!(after.events.is_empty());

    let claim = IngressStore::claim(
        &first,
        accepted_id.clone(),
        PlatformTime::new(10),
        PlatformTime::new(20),
    )
    .await
    .expect("one worker should claim the accepted record");
    assert_eq!(claim.fence(), 1);
    assert_eq!(claim.attempt_count(), 1);
    assert!(
        IngressStore::list_recoverable(&first, PlatformTime::new(11), 10)
            .await
            .expect("active lease enumeration should succeed")
            .is_empty()
    );
    assert!(matches!(
        IngressStore::claim(
            &second,
            accepted_id.clone(),
            PlatformTime::new(11),
            PlatformTime::new(21),
        )
        .await,
        Err(IngressError::AlreadyClaimed { .. })
    ));

    let recovered = IngressStore::claim(
        &second,
        accepted_id.clone(),
        PlatformTime::new(20),
        PlatformTime::new(30),
    )
    .await
    .expect("expired lease should be reclaimable after reopen-equivalent worker handoff");
    assert_eq!(recovered.fence(), 2);
    assert!(matches!(
        IngressStore::retry(
            &first,
            &claim,
            PlatformTime::new(21),
            PlatformTime::new(25),
            IngressTechnicalFailure::new("stale", "old worker"),
        )
        .await,
        Err(IngressError::StaleClaim { .. })
    ));
    let retried = IngressStore::retry(
        &second,
        &recovered,
        PlatformTime::new(21),
        PlatformTime::new(25),
        IngressTechnicalFailure::new("temporary", "retry me"),
    )
    .await
    .expect("current fence should record retry");
    assert!(matches!(retried.status, IngressStatus::Retryable(_)));

    first.close().await;
    second.close().await;
    let reopened: PgStorage = database.storage().await;
    let persisted = IngressStore::ingress(&reopened, accepted_id)
        .await
        .expect("Ingress operational state should survive adapter reopen");
    assert!(matches!(persisted.status, IngressStatus::Retryable(_)));
    assert_eq!(persisted.claim_fence, 2);
    assert_eq!(persisted.attempt_count, 2);
    let retryable = IngressStore::list_recoverable(&reopened, PlatformTime::new(25), 10)
        .await
        .expect("retryable durable records should be enumerable after restart");
    assert_eq!(retryable.len(), 1);
    reopened.close().await;
    pool.close().await;
    database.cleanup().await;
}

#[tokio::test]
async fn postgres_started_provenance_update_keeps_ended_at_null() {
    let database = TestDatabase::provision("session-provenance").await;
    let pool = database.pool().await;
    let session_id = id::<loom_core::ExecutionSessionId>(0xb201);
    sqlx::query(
        "INSERT INTO loom_execution_session \
         (session_id, world_id, timeline_id, origin, status, started_at, ended_at, record) \
         VALUES ($1::uuid, $2::uuid, $3::uuid, 'Ingress', 'Started', 10, NULL, $4::jsonb)",
    )
    .bind(session_id.to_string())
    .bind(id::<WorldId>(0xb202).to_string())
    .bind(id::<TimelineId>(0xb203).to_string())
    .bind(json!({"status": "Started"}))
    .execute(&pool)
    .await
    .expect("Started Session should insert");
    let result = sqlx::query(include_str!("../sql/session/prepare_provenance.sql"))
        .bind(session_id.to_string())
        .bind(json!({"status": "Started", "prepared": true}))
        .execute(&pool)
        .await
        .expect("prepared provenance should update the non-terminal record");
    assert_eq!(result.rows_affected(), 1);
    let ended_at: Option<i64> = sqlx::query_scalar(
        "SELECT ended_at FROM loom_execution_session WHERE session_id = $1::uuid",
    )
    .bind(session_id.to_string())
    .fetch_one(&pool)
    .await
    .expect("Started Session should remain readable");
    assert_eq!(ended_at, None);
    pool.close().await;
    database.cleanup().await;
}
