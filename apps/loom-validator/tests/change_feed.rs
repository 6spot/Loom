//! Change Feed suite integration tests (T18) — CV-038..CV-040 via formal client.
//!
//! Validates committed change-feed/SSE behavior through formal Loom client surface,
//! including resume/cursor semantics and disconnect recovery, without polling
//! internal event tables. Uses real `InMemory` and `PostgreSQL` service boundaries
//! with controlled restart where durability is required.

mod common;

use std::{
    fmt::Write as _,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
};

use loom_api::{
    ActionInvocation, ActionRequest, ActionService, ApiErrorCode, ChangeFeedCursor, EventId,
    EventQuery, HistoryService, SubscriptionRequest, SubscriptionResult, SubscriptionService,
    TimelineTarget, WorldInstant, WorldService, WorldTemplateDescriptor,
};
use loom_client::LoomClient;
use loom_validator::{BackendContext, BackendKind, change_feed, validator_registry};
use serde_json::json;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use uuid::Uuid;

use common::{InMemoryServer, PgServer};

#[test]
fn change_feed_suite_scaffold_is_non_registering_and_disjoint() {
    assert_eq!(change_feed::SUITE, "change_feed");
    assert_eq!(change_feed::CV_RANGE, "CV-038..CV-040");
    assert_eq!(change_feed::CAPABILITY_AREA, "change-feed");
    assert_eq!(change_feed::suite_name(), "change_feed");
    assert!(change_feed::owns_cv("CV-038"));
    assert!(change_feed::owns_cv("CV-039"));
    assert!(change_feed::owns_cv("CV-040"));
    assert!(!change_feed::owns_cv("CV-037"));
    assert!(!change_feed::owns_cv("CV-012"));

    let registry = validator_registry();
    assert_eq!(registry.len(), 32);
    assert!(registry.get("CV-038").is_some());
    assert!(registry.get("CV-040").is_some());

    // Local suite registry should contain CV-038..040 without polluting central registry
    let suite_registry = change_feed::change_feed_registry();
    assert_eq!(suite_registry.len(), 3);
    assert!(suite_registry.get("CV-038").is_some());
    assert!(suite_registry.get("CV-040").is_some());
}

fn in_memory_context(scope: &str) -> (BackendContext, InMemoryServer) {
    let (server, client) = InMemoryServer::start().expect("in-memory service should start");
    let server_for_restart = server.clone();
    let strategy: Arc<dyn Fn() -> Result<LoomClient, String> + Send + Sync> =
        Arc::new(move || server_for_restart.restart());
    let ctx = BackendContext::new(client)
        .with_backend_kind(BackendKind::InMemory)
        .with_restart_strategy(strategy)
        .with_controlled_boundary_restart()
        .with_scope(scope.to_string());
    (ctx, server)
}

fn pg_context(scope: &str) -> (BackendContext, PgServer) {
    let (server, client) = PgServer::start().expect("pg service should start");
    let server_for_restart = server.clone();
    let strategy: Arc<dyn Fn() -> Result<LoomClient, String> + Send + Sync> =
        Arc::new(move || server_for_restart.restart());
    let ctx = BackendContext::new(client)
        .with_backend_kind(BackendKind::PostgreSQL)
        .with_restart_strategy(strategy)
        .with_controlled_boundary_restart()
        .with_scope(scope.to_string());
    (ctx, server)
}

fn assert_pass(result: &loom_validator::ScenarioResult, id: &str) {
    assert!(
        result.outcome().is_pass(),
        "{id} should pass via formal client: {result:?} finding={:?}",
        result.finding()
    );
    // Ensure evidence mentions formal surfaces and not internal storage
    let evidence = result
        .finding()
        .evidence()
        .iter()
        .map(loom_validator::EvidenceReference::as_str)
        .collect::<Vec<_>>()
        .join(",");
    assert!(
        evidence.contains("public-surface:loom-client::SubscriptionService::subscribe"),
        "{id} evidence should contain subscription surface: {evidence}"
    );
    assert!(
        evidence.contains("public-surface:loom-client::HistoryService::list_events"),
        "{id} evidence should contain history surface: {evidence}"
    );
    assert!(
        !evidence.to_lowercase().contains("loom_storage")
            && !evidence.to_lowercase().contains("pgstorage")
            && !evidence.to_lowercase().contains("sqlx"),
        "{id} must not assert against storage internals: {evidence}"
    );
}

fn assert_actual_contains(result: &loom_validator::ScenarioResult, id: &str, expected: &str) {
    assert!(
        result
            .finding()
            .actual()
            .to_ascii_lowercase()
            .contains(&expected.to_ascii_lowercase()),
        "{id} actual should contain {expected:?}: {}",
        result.finding().actual()
    );
}

#[derive(Clone)]
struct MidPageDisconnectState {
    target: TimelineTarget,
    cursor: ChangeFeedCursor,
    remaining: Arc<Vec<loom_api::CommittedEvent>>,
    fail_once: Arc<AtomicBool>,
}

struct MidPageDisconnectFixture {
    base_url: String,
    task: tokio::task::JoinHandle<()>,
}

impl MidPageDisconnectFixture {
    fn start(
        target: TimelineTarget,
        cursor: ChangeFeedCursor,
        remaining: Vec<loom_api::CommittedEvent>,
    ) -> Self {
        let state = MidPageDisconnectState {
            target,
            cursor,
            remaining: Arc::new(remaining),
            fail_once: Arc::new(AtomicBool::new(true)),
        };
        let (addr, task) = common::leaked_runtime().block_on(async move {
            let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
                .await
                .expect("mid-page fixture listener should bind");
            let addr = listener
                .local_addr()
                .expect("mid-page fixture listener should have an address");
            let task = tokio::spawn(async move {
                loop {
                    let Ok((stream, _)) = listener.accept().await else {
                        break;
                    };
                    let state = state.clone();
                    tokio::spawn(async move {
                        mid_page_disconnect_connection(stream, state).await;
                    });
                }
            });
            (addr, task)
        });
        Self {
            base_url: format!("http://{addr}"),
            task,
        }
    }

    fn client(&self) -> LoomClient {
        LoomClient::new(&self.base_url).expect("mid-page fixture client should build")
    }

    fn stop(self) {
        self.task.abort();
    }
}

async fn mid_page_disconnect_connection(
    mut stream: tokio::net::TcpStream,
    state: MidPageDisconnectState,
) {
    let mut request = Vec::new();
    let mut chunk = [0_u8; 1024];
    while !request.windows(4).any(|window| window == b"\r\n\r\n") {
        let Ok(read) = stream.read(&mut chunk).await else {
            return;
        };
        if read == 0 {
            return;
        }
        request.extend_from_slice(&chunk[..read]);
        if request.len() > 16 * 1024 {
            return;
        }
    }
    let requested_cursor = String::from_utf8_lossy(&request)
        .lines()
        .find_map(|line| line.strip_prefix("last-event-id:"))
        .and_then(|value| value.trim().parse::<u64>().ok());
    if requested_cursor != Some(state.cursor.after.value()) {
        let body = b"fixture requires the pre-disconnect cursor";
        let response = format!(
            "HTTP/1.1 400 Bad Request\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            body.len()
        );
        let _ = stream.write_all(response.as_bytes()).await;
        let _ = stream.write_all(body).await;
        let _ = stream.shutdown().await;
        return;
    }

    let mut body = String::new();
    let first_attempt = state.fail_once.swap(false, Ordering::SeqCst);
    let events = if first_attempt {
        // The response terminates after a complete change frame but before
        // page metadata. This is the in-flight SSE disconnect observed by
        // LoomClient as ApiError::Unavailable.
        &state.remaining[..1]
    } else {
        &state.remaining[..]
    };
    for event in events {
        let _ = write!(
            body,
            "event: change\nid: {}\ndata: {}\n\n",
            event.sequence.value(),
            serde_json::to_string(event).expect("event should serialize")
        );
    }
    if !first_attempt {
        let next_cursor = state
            .remaining
            .last()
            .map(|event| ChangeFeedCursor::after(state.target, event.sequence));
        let metadata = serde_json::json!({
            "next_cursor": next_cursor,
            "has_more": false,
        });
        let _ = write!(
            body,
            "event: page\ndata: {}\n\n",
            serde_json::to_string(&metadata).expect("page metadata should serialize")
        );
    }
    let advertised_length = if first_attempt {
        // Advertise one byte more than was sent, then close the socket. This
        // terminates the HTTP body in-flight after a complete change frame but
        // before page metadata; the formal client must surface ApiError.
        body.len() + 1
    } else {
        body.len()
    };
    let response = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: {advertised_length}\r\nConnection: close\r\n\r\n"
    );
    let _ = stream.write_all(response.as_bytes()).await;
    let _ = stream.write_all(body.as_bytes()).await;
    let _ = stream.shutdown().await;
}

fn seed_cv040_history(client: &LoomClient) -> (TimelineTarget, Vec<loom_api::CommittedEvent>) {
    common::leaked_runtime().block_on(async {
        let template = WorldTemplateDescriptor::new(
            "validator.change-feed.t18.fixture",
            1,
            WorldInstant::new(42),
        )
        .requires_capability("neutral.counter", "^0.1.0")
        .with_configuration(json!({"profile": "counter"}));
        let target = client
            .create_world_from_template(loom_api::CreateWorldFromTemplateRequest::new(template))
            .await
            .expect("fixture world should be created")
            .target;
        for index in 1..=3_u128 {
            let event_id = EventId::from_uuid(Uuid::from_u128(0x4010 + index));
            let entity_id = loom_api::EntityId::from_uuid(Uuid::from_u128(0x4001 + index));
            let result = client
                .invoke(ActionRequest::new(
                    target,
                    ActionInvocation::new(
                        "neutral.counter.seed".into(),
                        json!({
                            "event_id": event_id.to_string(),
                            "entity_id": entity_id.to_string(),
                            "value": 10 + i64::try_from(index).expect("small fixture index"),
                        }),
                    ),
                ))
                .await
                .expect("fixture event should be committed");
            assert!(
                result.is_committed(),
                "fixture event should commit: {result:?}"
            );
        }
        let history = client
            .list_events(EventQuery::all(target))
            .await
            .expect("fixture history should be readable");
        assert_eq!(history.len(), 3);
        (target, history)
    })
}

#[test]
fn cv040_formal_client_observes_mid_page_disconnect_and_resumes() {
    let (_server, client) = InMemoryServer::start().expect("in-memory service should start");
    let (target, history_before) = seed_cv040_history(&client);
    let initial_page = common::leaked_runtime().block_on(async {
        match client
            .subscribe(SubscriptionRequest::new(target, 1))
            .await
            .expect("initial bounded page should succeed")
        {
            SubscriptionResult::Events(page) => page,
            other => panic!("expected initial bounded Events page, got {other:?}"),
        }
    });
    assert_eq!(initial_page.events, history_before[..1]);
    assert!(initial_page.has_more);
    let observed_cursor = initial_page
        .next_cursor
        .expect("initial page should expose next_cursor");
    assert_eq!(
        observed_cursor,
        ChangeFeedCursor::after(target, history_before[0].sequence)
    );

    let fixture =
        MidPageDisconnectFixture::start(target, observed_cursor, history_before[1..].to_vec());
    let fixture_client = fixture.client();
    let interrupted = common::leaked_runtime().block_on(async {
        fixture_client
            .subscribe(SubscriptionRequest::resume(target, observed_cursor, 2))
            .await
    });
    let error = interrupted.expect_err("partial SSE exchange must return ApiError");
    assert_eq!(error.code, ApiErrorCode::Unavailable);
    assert!(
        error.message.contains("response could not be read")
            || error.message.contains("omitted change-feed page metadata"),
        "client should report the incomplete SSE exchange: {error}"
    );

    let resumed_page = common::leaked_runtime().block_on(async {
        fixture_client
            .subscribe(SubscriptionRequest::resume(target, observed_cursor, 2))
            .await
            .expect("resume from pre-disconnect cursor should succeed")
    });
    let SubscriptionResult::Events(resumed_page) = resumed_page else {
        panic!("expected resumed Events page after client-observed disconnect");
    };
    assert_eq!(resumed_page.events, history_before[1..]);
    assert!(!resumed_page.has_more);
    assert_eq!(
        resumed_page.next_cursor,
        Some(ChangeFeedCursor::after(target, history_before[2].sequence))
    );

    let history_after = common::leaked_runtime().block_on(async {
        client
            .list_events(EventQuery::all(target))
            .await
            .expect("authoritative history should remain readable")
    });
    assert_eq!(history_after, history_before);
    fixture.stop();
}

#[test]
fn cv038_passes_on_real_in_memory_via_formal_subscription() {
    let (ctx, _server) = in_memory_context("CV-038-inmemory");
    let descriptor = change_feed::descriptors()
        .into_iter()
        .find(|d| d.id_str() == "CV-038")
        .expect("CV-038 descriptor");
    let result = change_feed::execute(&descriptor, &ctx);
    assert_pass(&result, "CV-038");
    assert_actual_contains(&result, "CV-038", "EventId");
    assert_actual_contains(&result, "CV-038", "content");
}

#[test]
fn cv039_resume_passes_on_real_in_memory() {
    let (ctx, _server) = in_memory_context("CV-039-inmemory");
    let descriptor = change_feed::descriptors()
        .into_iter()
        .find(|d| d.id_str() == "CV-039")
        .expect("CV-039 descriptor");
    let result = change_feed::execute(&descriptor, &ctx);
    assert_pass(&result, "CV-039");
    assert_actual_contains(&result, "CV-039", "authoritative");
    assert_actual_contains(&result, "CV-039", "content");
}

#[test]
fn cv040_disconnect_reconnect_preserves_history_on_real_in_memory() {
    let (ctx, _server) = in_memory_context("CV-040-inmemory");
    let descriptor = change_feed::descriptors()
        .into_iter()
        .find(|d| d.id_str() == "CV-040")
        .expect("CV-040 descriptor");
    let result = change_feed::execute(&descriptor, &ctx);
    assert_pass(&result, "CV-040");
    assert_actual_contains(&result, "CV-040", "bounded-page disconnect");
    assert_actual_contains(&result, "CV-040", "remaining EventSeq");
    assert_actual_contains(&result, "CV-040", "retry");
}

#[test]
fn cv038_to_cv040_pass_on_live_postgres_with_controlled_restart() {
    for id in ["CV-038", "CV-039", "CV-040"] {
        let (ctx, _server) = pg_context(&format!("pg-{id}"));
        let descriptor = change_feed::descriptors()
            .into_iter()
            .find(|d| d.id_str() == id)
            .unwrap_or_else(|| panic!("missing {id}"));
        let result = change_feed::execute(&descriptor, &ctx);
        assert_pass(&result, id);
        // For CV-039/040, ensure durable evidence when postgres with controlled restart
        if id == "CV-039" || id == "CV-040" {
            let actual = result.finding().actual().to_ascii_lowercase();
            // Should mention restart or durable for PG path
            assert!(
                actual.contains("restart")
                    || actual.contains("durable")
                    || actual.contains("resume"),
                "{id} PG actual should mention restart/durable/resume: {}",
                result.finding().actual()
            );
        }
    }
}

#[test]
fn change_feed_scenarios_use_formal_client_not_event_table_polling() {
    // Negative check: ensure implementation does not contain forbidden internal polling patterns
    // by inspecting that the change_feed module source uses SubscriptionService and not loom_storage
    let source = include_str!("../src/change_feed.rs");
    assert!(
        source.contains("SubscriptionService::subscribe") || source.contains("SubscriptionRequest"),
        "change_feed should use formal SubscriptionService"
    );
    assert!(
        source.contains("ChangeFeedCursor::after"),
        "change_feed should use documented cursor semantics"
    );
    assert!(
        !source.contains("loom_storage")
            && !source.contains("PgStorage")
            && !source.contains("InMemoryStore"),
        "change_feed must not import storage internals for polling"
    );
    assert!(
        !source.contains("validator_registry") || source.contains("change_feed_registry"),
        "change_feed should not mutate central validator_registry"
    );
}
