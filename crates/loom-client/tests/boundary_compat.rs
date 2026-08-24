use std::{future::IntoFuture, str::FromStr, sync::Arc};

use axum::serve;
use loom_api::{
    ActionInvocation, ActionRequest, ActionService, ActionTypeId, ApiError, ApiFuture,
    CatalogService, CatalogSnapshot, ChangeFeedCursor, ChangeFeedPage, EventQuery, EventSeq,
    ExecutionResult, HistoryService, IngressAcceptance, IngressEnvelope, IngressId, IngressService,
    IngressStatusRecord, QueryService, StateRevision, SubscriptionRequest, SubscriptionResult,
    SubscriptionResume, SubscriptionService, TimelineId, TimelineService, TimelineSnapshot,
    TimelineTarget, TimelineVersion, WorldId, WorldInstant, WorldService,
};
use loom_boundary::{BoundaryConfig, router};
use loom_client::LoomClient;
use serde_json::json;

#[derive(Clone, Default)]
struct FakeApi;

impl WorldService for FakeApi {}

impl ActionService for FakeApi {
    fn invoke(&self, _request: ActionRequest) -> ApiFuture<'_, ExecutionResult> {
        Box::pin(async { Ok(ExecutionResult::NoChange) })
    }
}

impl TimelineService for FakeApi {
    fn inspect_timeline(&self, target: TimelineTarget) -> ApiFuture<'_, TimelineSnapshot> {
        Box::pin(async move {
            Ok(TimelineSnapshot::new(
                target,
                TimelineVersion::new(EventSeq::new(0), StateRevision::new(0)),
                WorldInstant::new(0),
            ))
        })
    }
}

impl QueryService for FakeApi {
    fn get_facet(
        &self,
        _query: loom_api::FacetQuery,
    ) -> ApiFuture<'_, Option<loom_api::FacetSnapshot>> {
        Box::pin(async { Ok(None) })
    }
}

impl HistoryService for FakeApi {
    fn list_events(&self, _query: EventQuery) -> ApiFuture<'_, Vec<loom_api::CommittedEvent>> {
        Box::pin(async { Ok(Vec::new()) })
    }
}

impl loom_api::CatalogService for FakeApi {
    fn catalog(&self) -> Result<CatalogSnapshot, ApiError> {
        Ok(CatalogSnapshot::default())
    }
}

impl IngressService for FakeApi {
    fn submit_ingress(&self, _request: IngressEnvelope) -> ApiFuture<'_, IngressAcceptance> {
        Box::pin(async {
            Ok(IngressAcceptance::conflict(
                loom_api::IdempotencyConflict::new(
                    "same-key".into(),
                    "existing-ingress".into(),
                    "old-fingerprint",
                    "new-fingerprint",
                ),
            ))
        })
    }

    fn ingress_status(&self, _ingress_id: IngressId) -> ApiFuture<'_, IngressStatusRecord> {
        Box::pin(async { Err(ApiError::not_found("test status is not configured")) })
    }
}

impl SubscriptionService for FakeApi {
    fn subscribe(&self, request: SubscriptionRequest) -> ApiFuture<'_, SubscriptionResult> {
        Box::pin(async move {
            match request.resume_from {
                Some(cursor) => Ok(SubscriptionResult::Resumed(SubscriptionResume { cursor })),
                None => Ok(SubscriptionResult::Events(ChangeFeedPage {
                    events: Vec::new(),
                    next_cursor: None,
                    has_more: true,
                })),
            }
        })
    }
}

fn target() -> TimelineTarget {
    TimelineTarget::new(
        WorldId::from_str("00000000-0000-0000-0000-000000000001").expect("World ID"),
        TimelineId::from_str("00000000-0000-0000-0000-000000000002").expect("Timeline ID"),
    )
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn client_round_trips_boundary_json_and_typed_ingress_conflict() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("test listener");
    let address = listener.local_addr().expect("test address");
    let server = tokio::spawn(
        serve(
            listener,
            router(Arc::new(FakeApi), BoundaryConfig::default()),
        )
        .into_future(),
    );

    let client = LoomClient::new(format!("http://{address}")).expect("client");
    let action = ActionService::invoke(
        &client,
        ActionRequest::new(
            target(),
            ActionInvocation::new(ActionTypeId::new("example.noop"), json!({})),
        ),
    )
    .await
    .expect("action response");
    assert!(matches!(action, ExecutionResult::NoChange));

    // CatalogService is synchronous in loom-api. Boundary runs it on its
    // blocking pool so the client's synchronous API compatibility method can
    // perform its own short-lived async request runtime off the request task.
    let catalog = CatalogService::catalog(&client).expect("catalog response");
    assert_eq!(catalog, CatalogSnapshot::default());

    let ingress = IngressService::submit_ingress(
        &client,
        IngressEnvelope::new(
            "ingress-1",
            "same-key",
            loom_api::IngressProvenance::new("test"),
            target(),
            loom_api::IngressAuthorizationContext::new(json!({})),
            loom_api::IngressTimeMetadata::none(),
            ActionInvocation::new(ActionTypeId::new("example.noop"), json!({})),
        ),
    )
    .await
    .expect("typed ingress conflict response");
    assert!(ingress.is_conflict());

    let page = SubscriptionService::subscribe(&client, SubscriptionRequest::new(target(), 1))
        .await
        .expect("SSE page response");
    let SubscriptionResult::Events(page) = page else {
        panic!("expected SSE page result");
    };
    assert!(page.has_more);

    let subscription = SubscriptionService::subscribe(
        &client,
        SubscriptionRequest::resume(
            target(),
            ChangeFeedCursor::after(target(), EventSeq::new(7)),
            1,
        ),
    )
    .await
    .expect("SSE resume response");
    let SubscriptionResult::Resumed(resume) = subscription else {
        panic!("expected SSE resume result");
    };
    assert_eq!(resume.cursor.after, EventSeq::new(7));

    server.abort();
}
