//! Loom Boundary: transport adapters over the unified Loom API.
//!
//! # Responsibility
//!
//! This crate maps external protocols such as HTTP/JSON, SSE and, where truly
//! required, WebSocket onto the stable application contracts defined by
//! `loom-api`. It also maps committed Loom output back into transport-specific
//! representations.
//!
//! Boundary owns transport concerns such as routing, framing, status codes,
//! reconnect behavior and transport/auth middleware. It does **not** own World
//! semantics, Runtime authority or Capability dispatch.
//!
//! # Cargo dependency boundary
//!
//! Among Loom workspace crates, Boundary depends on `loom-api` rather than
//! `loom-runtime` or `loom-capability`:
//!
//! ```text
//! loom-boundary -> loom-api
//! loom-boundary -X-> loom-runtime
//! loom-boundary -X-> loom-capability
//! ```
//!
//! The Application composition root provides an implementation of the Loom API
//! (normally backed by Runtime) to the Boundary adapter.
//!
//! # Unified exposure rule
//!
//! Boundary is the only place transport may be expressed, but it must expose the
//! **Loom API**, not individual module internals. A Capability Action such as
//! `finance.transfer` is invoked through the common Action API; Boundary must not
//! route directly to a Finance resolver or invent a Finance-specific engine
//! controller that bypasses Loom's public contract.
//!
//! ```text
//! HTTP / SSE / WebSocket
//!          ↓
//!       Loom API
//!          ↓
//!  Runtime implementation
//!          ↓
//! Capability Registry
//! ```
//!
//! # Authority and truth
//!
//! Receiving external data does not make it World Truth. Transport acceptance
//! means only that the request/input crossed the Boundary. Semantic acceptance
//! and World mutation still require the normal API → Runtime → Capability →
//! Resolution → validation → Timeline Commit path.
//!
//! Conversely, authoritative world output must originate from already committed
//! World changes; transport delivery/acknowledgement does not mutate World Truth.
//!
//! # External side effects
//!
//! Loom Core/Runtime do not directly control the real world. A downstream
//! Application may react to committed output and perform an external side effect,
//! but any resulting influence must re-enter through the public Loom boundary
//! before it can affect World Truth again.
//!
//! # Forbidden shortcuts
//!
//! Boundary must not:
//!
//! - mutate World State or append Events directly;
//! - import concrete Capability implementations/resolvers;
//! - import Runtime internals to bypass `loom-api`;
//! - import SQLx/pgvector/object-store repositories;
//! - expose transport success as semantic success.
//!
//! # Documentation contract
//!
//! Every public boundary type must state whether it represents transport input,
//! public API mapping, committed output or transport/runtime metadata, and must
//! document where Loom authority begins and ends. See
//! `docs/architecture/governance.md` and
//! `docs/architecture/runtime-contracts.md`.

#![forbid(unsafe_code)]

use std::{convert::Infallible, fmt::Display, future::Future, str::FromStr, sync::Arc};

use axum::{
    Router,
    body::{Body, to_bytes},
    extract::{Path, Query, Request, State},
    http::{HeaderMap, HeaderValue, StatusCode, header},
    response::{
        IntoResponse, Response, Sse,
        sse::{Event, KeepAlive},
    },
    routing::{get, post},
};
use futures_util::stream;
use loom_api::{
    ActionRequest, AdminActivateRuntimeRevisionRequest, AdminAdvanceWorldTimeRequest,
    AdminExecutionSessionRequest, AdminMissingImplementationRequest, AdminOperation,
    AdminRuntimeRevisionRequest, AdminScheduleAgencyWakeRequest, AdminService,
    AdminTerminalizeWorkRequest, ApiError, ApiResult, CausalQuery, ChangeFeedCursor,
    CreateWorldFromTemplateRequest, EventQuery, EventRef, FacetQuery, IngressId, IngressService,
    LoomApi, RelationshipTrajectoryQuery, SubscriptionRequest, SubscriptionResult,
    SubscriptionService, TimelineTarget, WorldId,
};
use serde::{Deserialize, Serialize, de::DeserializeOwned};
use tower::{ServiceBuilder, limit::ConcurrencyLimitLayer};

/// The versioned path prefix used by the Boundary HTTP adapter.
pub const API_PREFIX: &str = "/v1";

/// Operational bounds enforced before values reach an API service.
///
/// These are transport limits only. Runtime remains responsible for semantic
/// limits and may impose stricter bounds after the request crosses the API
/// boundary.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BoundaryConfig {
    body_bytes: usize,
    header_bytes: usize,
    response_bytes: usize,
    sse_buffer_bytes: usize,
    sse_events: u32,
    concurrent_requests: usize,
}

impl Default for BoundaryConfig {
    fn default() -> Self {
        Self {
            body_bytes: 1024 * 1024,
            header_bytes: 16 * 1024,
            response_bytes: 8 * 1024 * 1024,
            sse_buffer_bytes: 4 * 1024 * 1024,
            sse_events: loom_api::MAX_CHANGE_FEED_PAGE_SIZE,
            concurrent_requests: 128,
        }
    }
}

impl BoundaryConfig {
    /// Creates transport limits, rejecting zero-valued or impossible limits.
    ///
    /// # Errors
    ///
    /// Returns the first configuration error when any transport bound is
    /// zero, because an unbounded transport value is not permitted.
    pub const fn new(
        max_body_bytes: usize,
        max_header_bytes: usize,
        max_response_bytes: usize,
        max_sse_buffer_bytes: usize,
        max_sse_events: u32,
        max_concurrent_requests: usize,
    ) -> Result<Self, BoundaryConfigError> {
        if max_body_bytes == 0 {
            return Err(BoundaryConfigError::ZeroBodyLimit);
        }
        if max_header_bytes == 0 {
            return Err(BoundaryConfigError::ZeroHeaderLimit);
        }
        if max_response_bytes == 0 {
            return Err(BoundaryConfigError::ZeroResponseLimit);
        }
        if max_sse_buffer_bytes == 0 {
            return Err(BoundaryConfigError::ZeroSseBufferLimit);
        }
        if max_sse_events == 0 {
            return Err(BoundaryConfigError::ZeroSseEventLimit);
        }
        if max_concurrent_requests == 0 {
            return Err(BoundaryConfigError::ZeroConcurrencyLimit);
        }
        if max_header_bytes > max_body_bytes {
            return Err(BoundaryConfigError::HeaderLimitExceedsBody);
        }
        if max_response_bytes < max_body_bytes {
            return Err(BoundaryConfigError::ResponseLimitBelowBody);
        }
        if max_sse_buffer_bytes > max_response_bytes {
            return Err(BoundaryConfigError::SseBufferLimitExceedsResponse);
        }
        if max_sse_events > loom_api::MAX_CHANGE_FEED_PAGE_SIZE {
            return Err(BoundaryConfigError::SseEventLimitExceedsPublic);
        }
        Ok(Self {
            body_bytes: max_body_bytes,
            header_bytes: max_header_bytes,
            response_bytes: max_response_bytes,
            sse_buffer_bytes: max_sse_buffer_bytes,
            sse_events: max_sse_events,
            concurrent_requests: max_concurrent_requests,
        })
    }

    /// Returns the maximum request body accepted by the transport.
    #[must_use]
    pub const fn max_body_bytes(self) -> usize {
        self.body_bytes
    }

    /// Returns the maximum encoded request-header bytes accepted by the transport.
    #[must_use]
    pub const fn max_header_bytes(self) -> usize {
        self.header_bytes
    }

    /// Returns the maximum encoded JSON response size.
    #[must_use]
    pub const fn max_response_bytes(self) -> usize {
        self.response_bytes
    }

    /// Returns the maximum buffered SSE event payload for one response.
    #[must_use]
    pub const fn max_sse_buffer_bytes(self) -> usize {
        self.sse_buffer_bytes
    }

    /// Returns the maximum number of events one SSE response may contain.
    #[must_use]
    pub const fn max_sse_events(self) -> u32 {
        self.sse_events
    }

    /// Returns the maximum number of in-flight transport requests.
    #[must_use]
    pub const fn max_concurrent_requests(self) -> usize {
        self.concurrent_requests
    }
}

/// Invalid transport limit configuration.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BoundaryConfigError {
    /// The request body bound was zero.
    ZeroBodyLimit,
    /// The request header bound was zero.
    ZeroHeaderLimit,
    /// The JSON response bound was zero.
    ZeroResponseLimit,
    /// The SSE buffer bound was zero.
    ZeroSseBufferLimit,
    /// The SSE event-count bound was zero.
    ZeroSseEventLimit,
    /// The request concurrency bound was zero.
    ZeroConcurrencyLimit,
    /// Header bytes cannot exceed the request body budget.
    HeaderLimitExceedsBody,
    /// A response must be able to carry a bounded request response envelope.
    ResponseLimitBelowBody,
    /// An SSE buffer cannot exceed the encoded response budget.
    SseBufferLimitExceedsResponse,
    /// Public Change Feed pagination is smaller than the configured SSE page.
    SseEventLimitExceedsPublic,
}

impl Display for BoundaryConfigError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let message = match self {
            Self::ZeroBodyLimit => "request body limit must be positive",
            Self::ZeroHeaderLimit => "request header limit must be positive",
            Self::ZeroResponseLimit => "response limit must be positive",
            Self::ZeroSseBufferLimit => "SSE buffer limit must be positive",
            Self::ZeroSseEventLimit => "SSE event limit must be positive",
            Self::ZeroConcurrencyLimit => "request concurrency limit must be positive",
            Self::HeaderLimitExceedsBody => {
                "request header limit must not exceed request body limit"
            }
            Self::ResponseLimitBelowBody => "response limit must not be below request body limit",
            Self::SseBufferLimitExceedsResponse => {
                "SSE buffer limit must not exceed response limit"
            }
            Self::SseEventLimitExceedsPublic => {
                "SSE event limit must not exceed the public Change Feed bound"
            }
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for BoundaryConfigError {}

/// The API capabilities required by the HTTP/SSE adapter.
pub trait BoundaryApi:
    LoomApi + IngressService + SubscriptionService + Send + Sync + 'static
{
}

impl<T> BoundaryApi for T where
    T: LoomApi + IngressService + SubscriptionService + Send + Sync + 'static
{
}

/// API capabilities required by the isolated Runtime admin router.
pub trait AdminBoundaryApi: BoundaryApi + AdminService {}

impl<T> AdminBoundaryApi for T where T: BoundaryApi + AdminService {}

/// Authorization hook for the Admin/Runtime Control namespace.
///
/// The hook is deliberately owned by the Boundary composition root rather
/// than inferred from ordinary World API access. It receives the stable
/// operation identity and transport headers, and must return a typed failure
/// before any Admin service method is called.
pub trait AdminAuthorizationHook: Send + Sync + 'static {
    /// Authorizes one isolated Admin operation.
    ///
    /// # Errors
    ///
    /// Returns a typed `Unauthorized` or `Forbidden` error when the request
    /// does not satisfy the composition root's Admin policy.
    fn authorize(&self, operation: AdminOperation, headers: &HeaderMap) -> ApiResult<()>;
}

/// Minimal composition-root hook requiring a distinct Admin credential.
///
/// Applications with a real identity/policy provider should replace this hook.
/// It intentionally does not interpret ordinary bearer tokens or grant World
/// API authority; it only demonstrates the independent Admin boundary gate.
#[derive(Clone, Copy, Debug, Default)]
pub struct RequireAdminAuthorization;

impl AdminAuthorizationHook for RequireAdminAuthorization {
    fn authorize(&self, _operation: AdminOperation, headers: &HeaderMap) -> ApiResult<()> {
        if headers
            .get("x-loom-admin-authorization")
            .is_some_and(|value| !value.as_bytes().is_empty())
        {
            Ok(())
        } else {
            Err(ApiError::unauthorized("Admin authorization is required"))
        }
    }
}

struct AppState<S> {
    api: Arc<S>,
    config: BoundaryConfig,
}

struct AdminAppState<S, A> {
    api: Arc<S>,
    authorizer: Arc<A>,
    config: BoundaryConfig,
}

impl<S, A> Clone for AdminAppState<S, A> {
    fn clone(&self) -> Self {
        Self {
            api: Arc::clone(&self.api),
            authorizer: Arc::clone(&self.authorizer),
            config: self.config,
        }
    }
}

impl<S> Clone for AppState<S> {
    fn clone(&self) -> Self {
        Self {
            api: Arc::clone(&self.api),
            config: self.config,
        }
    }
}

/// Builds the versioned HTTP/JSON and SSE router over a unified Loom API.
///
/// The router owns no Runtime, Storage or Capability value. The application
/// composition root supplies an implementation of the focused loom-api
/// service traits, normally by putting a Runtime-backed value in the Arc.
pub fn router<S>(api: Arc<S>, config: BoundaryConfig) -> Router
where
    S: BoundaryApi,
{
    let state = AppState { api, config };
    Router::new()
        .route("/v1/worlds", post(create_world::<S>))
        .route("/v1/worlds/from-template", post(create_world::<S>))
        .route("/v1/actions", post(invoke_action::<S>))
        .route("/v1/timelines/inspect", post(inspect_timeline::<S>))
        .route("/v1/timelines/fork", post(fork_timeline::<S>))
        .route(
            "/v1/timelines/{world_id}/{timeline_id}",
            get(inspect_timeline_path::<S>),
        )
        .route(
            "/v1/timelines/{world_id}/{timeline_id}/changes",
            get(change_feed::<S>),
        )
        .route("/v1/query/facet", post(get_facet::<S>))
        .route("/v1/history/events", post(list_events::<S>))
        .route("/v1/history/event", post(get_event::<S>))
        .route("/v1/history/causes", post(direct_causes::<S>))
        .route("/v1/history/effects", post(direct_effects::<S>))
        .route("/v1/history/causal-walk", post(causal_walk::<S>))
        .route(
            "/v1/history/entity-trajectory",
            post(entity_trajectory::<S>),
        )
        .route(
            "/v1/history/relationship-trajectory",
            post(relationship_trajectory::<S>),
        )
        .route("/v1/catalog", get(catalog::<S>))
        .route("/v1/catalog/worlds/{world_id}", get(catalog_for_world::<S>))
        .route("/v1/ingress", post(submit_ingress::<S>))
        .route("/v1/ingress/{ingress_id}", get(ingress_status::<S>))
        .with_state(state)
        .layer(ServiceBuilder::new().layer(ConcurrencyLimitLayer::new(config.concurrent_requests)))
}

/// Alias for the router function, useful when the application calls its HTTP value app.
pub fn app<S>(api: Arc<S>, config: BoundaryConfig) -> Router
where
    S: BoundaryApi,
{
    router(api, config)
}

/// Builds the isolated `/v1/admin` Runtime Control router.
pub fn admin_router<S, A>(api: Arc<S>, authorizer: Arc<A>, config: BoundaryConfig) -> Router
where
    S: AdminBoundaryApi,
    A: AdminAuthorizationHook,
{
    let state = AdminAppState {
        api,
        authorizer,
        config,
    };
    Router::new()
        .route(
            "/v1/admin/runtime-revisions/active",
            get(admin_active_runtime_revision::<S, A>),
        )
        .route(
            "/v1/admin/runtime-revisions",
            get(admin_list_runtime_revisions::<S, A>),
        )
        .route(
            "/v1/admin/runtime-revisions/get",
            post(admin_get_runtime_revision::<S, A>),
        )
        .route(
            "/v1/admin/runtime-revisions/activate",
            post(admin_activate_runtime_revision::<S, A>),
        )
        .route("/v1/admin/sessions", get(admin_list_sessions::<S, A>))
        .route("/v1/admin/sessions/get", post(admin_get_session::<S, A>))
        .route(
            "/v1/admin/sessions/event",
            post(admin_session_for_event::<S, A>),
        )
        .route(
            "/v1/admin/timelines/status",
            post(admin_timeline_status::<S, A>),
        )
        .route(
            "/v1/admin/timelines/missing-implementation",
            post(admin_missing_implementation::<S, A>),
        )
        .route(
            "/v1/admin/work/terminalize",
            post(admin_terminalize_work::<S, A>),
        )
        .route(
            "/v1/admin/work/agency-wake/schedule",
            post(admin_schedule_agency_wake::<S, A>),
        )
        .route(
            "/v1/admin/world-time/advance",
            post(admin_advance_world_time::<S, A>),
        )
        .with_state(state)
        .layer(ServiceBuilder::new().layer(ConcurrencyLimitLayer::new(config.concurrent_requests)))
}

/// Builds the ordinary World router plus the isolated Admin router.
pub fn router_with_admin<S, A>(api: Arc<S>, authorizer: Arc<A>, config: BoundaryConfig) -> Router
where
    S: AdminBoundaryApi,
    A: AdminAuthorizationHook,
{
    router(Arc::clone(&api), config).merge(admin_router(api, authorizer, config))
}

/// Alias for [`router_with_admin`] for composition roots that call their HTTP
/// value an application.
pub fn app_with_admin<S, A>(api: Arc<S>, authorizer: Arc<A>, config: BoundaryConfig) -> Router
where
    S: AdminBoundaryApi,
    A: AdminAuthorizationHook,
{
    router_with_admin(api, authorizer, config)
}

fn authorize_admin<S, A>(
    state: &AdminAppState<S, A>,
    request: &Request,
    operation: AdminOperation,
) -> ApiResult<()>
where
    A: AdminAuthorizationHook,
{
    validate_headers(request, state.config)?;
    state.authorizer.authorize(operation, request.headers())
}

async fn admin_active_runtime_revision<S, A>(
    State(state): State<AdminAppState<S, A>>,
    request: Request,
) -> Response
where
    S: AdminBoundaryApi,
    A: AdminAuthorizationHook,
{
    if let Err(error) = authorize_admin(&state, &request, AdminOperation::ReadActiveRevision) {
        return error_response(error, state.config);
    }
    match block_on_api(state.api.active_runtime_revision()) {
        Ok(selection) => json_response(StatusCode::OK, &selection, state.config),
        Err(error) => error_response(error, state.config),
    }
}

async fn admin_list_runtime_revisions<S, A>(
    State(state): State<AdminAppState<S, A>>,
    request: Request,
) -> Response
where
    S: AdminBoundaryApi,
    A: AdminAuthorizationHook,
{
    if let Err(error) = authorize_admin(&state, &request, AdminOperation::ListRevisions) {
        return error_response(error, state.config);
    }
    match block_on_api(state.api.list_runtime_revisions()) {
        Ok(revisions) => json_response(StatusCode::OK, &revisions, state.config),
        Err(error) => error_response(error, state.config),
    }
}

async fn admin_get_runtime_revision<S, A>(
    State(state): State<AdminAppState<S, A>>,
    request: Request,
) -> Response
where
    S: AdminBoundaryApi,
    A: AdminAuthorizationHook,
{
    if let Err(error) = authorize_admin(&state, &request, AdminOperation::ReadRevision) {
        return error_response(error, state.config);
    }
    let body = match json_body::<AdminRuntimeRevisionRequest>(request, state.config).await {
        Ok(body) => body,
        Err(error) => return error_response(error, state.config),
    };
    match block_on_api(state.api.get_runtime_revision(body)) {
        Ok(revision) => json_response(StatusCode::OK, &revision, state.config),
        Err(error) => error_response(error, state.config),
    }
}

async fn admin_activate_runtime_revision<S, A>(
    State(state): State<AdminAppState<S, A>>,
    request: Request,
) -> Response
where
    S: AdminBoundaryApi,
    A: AdminAuthorizationHook,
{
    if let Err(error) = authorize_admin(&state, &request, AdminOperation::ActivateRevision) {
        return error_response(error, state.config);
    }
    let body = match json_body::<AdminActivateRuntimeRevisionRequest>(request, state.config).await {
        Ok(body) => body,
        Err(error) => return error_response(error, state.config),
    };
    match block_on_api(state.api.activate_runtime_revision(body)) {
        Ok(selection) => json_response(StatusCode::OK, &selection, state.config),
        Err(error) => error_response(error, state.config),
    }
}

async fn admin_list_sessions<S, A>(
    State(state): State<AdminAppState<S, A>>,
    request: Request,
) -> Response
where
    S: AdminBoundaryApi,
    A: AdminAuthorizationHook,
{
    if let Err(error) = authorize_admin(&state, &request, AdminOperation::ListSessions) {
        return error_response(error, state.config);
    }
    match block_on_api(state.api.list_execution_sessions()) {
        Ok(sessions) => json_response(StatusCode::OK, &sessions, state.config),
        Err(error) => error_response(error, state.config),
    }
}

async fn admin_get_session<S, A>(
    State(state): State<AdminAppState<S, A>>,
    request: Request,
) -> Response
where
    S: AdminBoundaryApi,
    A: AdminAuthorizationHook,
{
    if let Err(error) = authorize_admin(&state, &request, AdminOperation::ReadSession) {
        return error_response(error, state.config);
    }
    let body = match json_body::<AdminExecutionSessionRequest>(request, state.config).await {
        Ok(body) => body,
        Err(error) => return error_response(error, state.config),
    };
    match block_on_api(state.api.get_execution_session(body)) {
        Ok(session) => json_response(StatusCode::OK, &session, state.config),
        Err(error) => error_response(error, state.config),
    }
}

async fn admin_session_for_event<S, A>(
    State(state): State<AdminAppState<S, A>>,
    request: Request,
) -> Response
where
    S: AdminBoundaryApi,
    A: AdminAuthorizationHook,
{
    if let Err(error) = authorize_admin(&state, &request, AdminOperation::SessionForEvent) {
        return error_response(error, state.config);
    }
    let body = match json_body::<EventRef>(request, state.config).await {
        Ok(body) => body,
        Err(error) => return error_response(error, state.config),
    };
    match block_on_api(state.api.session_for_event(body)) {
        Ok(lookup) => json_response(StatusCode::OK, &lookup, state.config),
        Err(error) => error_response(error, state.config),
    }
}

async fn admin_timeline_status<S, A>(
    State(state): State<AdminAppState<S, A>>,
    request: Request,
) -> Response
where
    S: AdminBoundaryApi,
    A: AdminAuthorizationHook,
{
    if let Err(error) = authorize_admin(&state, &request, AdminOperation::ReadTimelineLogicalStatus)
    {
        return error_response(error, state.config);
    }
    let body = match json_body::<TimelineTarget>(request, state.config).await {
        Ok(body) => body,
        Err(error) => return error_response(error, state.config),
    };
    match block_on_api(state.api.timeline_logical_status(body)) {
        Ok(status) => json_response(StatusCode::OK, &status, state.config),
        Err(error) => error_response(error, state.config),
    }
}

async fn admin_missing_implementation<S, A>(
    State(state): State<AdminAppState<S, A>>,
    request: Request,
) -> Response
where
    S: AdminBoundaryApi,
    A: AdminAuthorizationHook,
{
    if let Err(error) = authorize_admin(&state, &request, AdminOperation::ReadMissingImplementation)
    {
        return error_response(error, state.config);
    }
    let body = match json_body::<AdminMissingImplementationRequest>(request, state.config).await {
        Ok(body) => body,
        Err(error) => return error_response(error, state.config),
    };
    match block_on_api(state.api.missing_implementation(body)) {
        Ok(block) => json_response(StatusCode::OK, &block, state.config),
        Err(error) => error_response(error, state.config),
    }
}

async fn admin_terminalize_work<S, A>(
    State(state): State<AdminAppState<S, A>>,
    request: Request,
) -> Response
where
    S: AdminBoundaryApi,
    A: AdminAuthorizationHook,
{
    if let Err(error) = authorize_admin(&state, &request, AdminOperation::TerminalizeWork) {
        return error_response(error, state.config);
    }
    let body = match json_body::<AdminTerminalizeWorkRequest>(request, state.config).await {
        Ok(body) => body,
        Err(error) => return error_response(error, state.config),
    };
    match block_on_api(state.api.terminalize_work(body)) {
        Ok(result) => json_response(StatusCode::OK, &result, state.config),
        Err(error) => error_response(error, state.config),
    }
}

async fn admin_schedule_agency_wake<S, A>(
    State(state): State<AdminAppState<S, A>>,
    request: Request,
) -> Response
where
    S: AdminBoundaryApi,
    A: AdminAuthorizationHook,
{
    if let Err(error) = authorize_admin(&state, &request, AdminOperation::ScheduleAgencyWake) {
        return error_response(error, state.config);
    }
    let body = match json_body::<AdminScheduleAgencyWakeRequest>(request, state.config).await {
        Ok(body) => body,
        Err(error) => return error_response(error, state.config),
    };
    match block_on_api(state.api.schedule_agency_wake(body)) {
        Ok(result) => json_response(StatusCode::OK, &result, state.config),
        Err(error) => error_response(error, state.config),
    }
}

async fn admin_advance_world_time<S, A>(
    State(state): State<AdminAppState<S, A>>,
    request: Request,
) -> Response
where
    S: AdminBoundaryApi,
    A: AdminAuthorizationHook,
{
    if let Err(error) = authorize_admin(&state, &request, AdminOperation::AdvanceWorldTime) {
        return error_response(error, state.config);
    }
    let body = match json_body::<AdminAdvanceWorldTimeRequest>(request, state.config).await {
        Ok(body) => body,
        Err(error) => return error_response(error, state.config),
    };
    match block_on_api(state.api.advance_world_time(body)) {
        Ok(result) => json_response(StatusCode::OK, &result, state.config),
        Err(error) => error_response(error, state.config),
    }
}

async fn create_world<S>(State(state): State<AppState<S>>, request: Request) -> Response
where
    S: BoundaryApi,
{
    if let Err(error) = validate_headers(&request, state.config) {
        return error_response(error, state.config);
    }
    let body = match json_body::<CreateWorldFromTemplateRequest>(request, state.config).await {
        Ok(body) => body,
        Err(error) => return error_response(error, state.config),
    };
    match block_on_api(state.api.create_world_from_template(body)) {
        Ok(snapshot) => json_response(StatusCode::OK, &snapshot, state.config),
        Err(error) => error_response(error, state.config),
    }
}

async fn invoke_action<S>(State(state): State<AppState<S>>, request: Request) -> Response
where
    S: BoundaryApi,
{
    if let Err(error) = validate_headers(&request, state.config) {
        return error_response(error, state.config);
    }
    let body = match json_body::<ActionRequest>(request, state.config).await {
        Ok(body) => body,
        Err(error) => return error_response(error, state.config),
    };
    match block_on_api(state.api.invoke(body)) {
        Ok(result) => json_response(StatusCode::OK, &result, state.config),
        Err(error) => error_response(error, state.config),
    }
}

async fn inspect_timeline<S>(State(state): State<AppState<S>>, request: Request) -> Response
where
    S: BoundaryApi,
{
    if let Err(error) = validate_headers(&request, state.config) {
        return error_response(error, state.config);
    }
    let body = match json_body::<TimelineTarget>(request, state.config).await {
        Ok(body) => body,
        Err(error) => return error_response(error, state.config),
    };
    match block_on_api(state.api.inspect_timeline(body)) {
        Ok(snapshot) => json_response(StatusCode::OK, &snapshot, state.config),
        Err(error) => error_response(error, state.config),
    }
}

async fn inspect_timeline_path<S>(
    State(state): State<AppState<S>>,
    Path(path): Path<TimelinePath>,
    request: Request,
) -> Response
where
    S: BoundaryApi,
{
    if let Err(error) = validate_headers(&request, state.config) {
        return error_response(error, state.config);
    }
    let target = match path.target() {
        Ok(target) => target,
        Err(error) => return error_response(error, state.config),
    };
    match block_on_api(state.api.inspect_timeline(target)) {
        Ok(snapshot) => json_response(StatusCode::OK, &snapshot, state.config),
        Err(error) => error_response(error, state.config),
    }
}

async fn fork_timeline<S>(State(state): State<AppState<S>>, request: Request) -> Response
where
    S: BoundaryApi,
{
    if let Err(error) = validate_headers(&request, state.config) {
        return error_response(error, state.config);
    }
    let body = match json_body::<loom_api::ForkTimelineRequest>(request, state.config).await {
        Ok(body) => body,
        Err(error) => return error_response(error, state.config),
    };
    match block_on_api(state.api.fork(body)) {
        Ok(snapshot) => json_response(StatusCode::OK, &snapshot, state.config),
        Err(error) => error_response(error, state.config),
    }
}

async fn get_facet<S>(State(state): State<AppState<S>>, request: Request) -> Response
where
    S: BoundaryApi,
{
    if let Err(error) = validate_headers(&request, state.config) {
        return error_response(error, state.config);
    }
    let body = match json_body::<FacetQuery>(request, state.config).await {
        Ok(body) => body,
        Err(error) => return error_response(error, state.config),
    };
    match block_on_api(state.api.get_facet(body)) {
        Ok(snapshot) => json_response(StatusCode::OK, &snapshot, state.config),
        Err(error) => error_response(error, state.config),
    }
}

async fn list_events<S>(State(state): State<AppState<S>>, request: Request) -> Response
where
    S: BoundaryApi,
{
    if let Err(error) = validate_headers(&request, state.config) {
        return error_response(error, state.config);
    }
    let body = match json_body::<EventQuery>(request, state.config).await {
        Ok(body) => body,
        Err(error) => return error_response(error, state.config),
    };
    match block_on_api(state.api.list_events_page(body)) {
        Ok(page) => json_response(StatusCode::OK, &page, state.config),
        Err(error) => error_response(error, state.config),
    }
}

async fn get_event<S>(State(state): State<AppState<S>>, request: Request) -> Response
where
    S: BoundaryApi,
{
    if let Err(error) = validate_headers(&request, state.config) {
        return error_response(error, state.config);
    }
    let body = match json_body::<EventRef>(request, state.config).await {
        Ok(body) => body,
        Err(error) => return error_response(error, state.config),
    };
    match block_on_api(state.api.get_event(body)) {
        Ok(event) => json_response(StatusCode::OK, &event, state.config),
        Err(error) => error_response(error, state.config),
    }
}

async fn direct_causes<S>(State(state): State<AppState<S>>, request: Request) -> Response
where
    S: BoundaryApi,
{
    history_event_refs(state, request, |api, event_ref| {
        api.direct_causes(event_ref)
    })
    .await
}

async fn direct_effects<S>(State(state): State<AppState<S>>, request: Request) -> Response
where
    S: BoundaryApi,
{
    history_event_refs(state, request, |api, event_ref| {
        api.direct_effects(event_ref)
    })
    .await
}

async fn history_event_refs<S, F>(state: AppState<S>, request: Request, operation: F) -> Response
where
    S: BoundaryApi,
    F: FnOnce(&S, EventRef) -> loom_api::ApiFuture<'_, Vec<EventRef>> + Send,
{
    if let Err(error) = validate_headers(&request, state.config) {
        return error_response(error, state.config);
    }
    let body = match json_body::<EventRef>(request, state.config).await {
        Ok(body) => body,
        Err(error) => return error_response(error, state.config),
    };
    match block_on_api(operation(&state.api, body)) {
        Ok(events) => json_response(StatusCode::OK, &events, state.config),
        Err(error) => error_response(error, state.config),
    }
}

async fn causal_walk<S>(State(state): State<AppState<S>>, request: Request) -> Response
where
    S: BoundaryApi,
{
    if let Err(error) = validate_headers(&request, state.config) {
        return error_response(error, state.config);
    }
    let body = match json_body::<CausalQuery>(request, state.config).await {
        Ok(body) => body,
        Err(error) => return error_response(error, state.config),
    };
    match block_on_api(state.api.causal_walk(body)) {
        Ok(traversal) => json_response(StatusCode::OK, &traversal, state.config),
        Err(error) => error_response(error, state.config),
    }
}

async fn entity_trajectory<S>(State(state): State<AppState<S>>, request: Request) -> Response
where
    S: BoundaryApi,
{
    if let Err(error) = validate_headers(&request, state.config) {
        return error_response(error, state.config);
    }
    let body = match json_body::<loom_api::EntityTrajectoryQuery>(request, state.config).await {
        Ok(body) => body,
        Err(error) => return error_response(error, state.config),
    };
    match block_on_api(state.api.entity_trajectory(body)) {
        Ok(page) => json_response(StatusCode::OK, &page, state.config),
        Err(error) => error_response(error, state.config),
    }
}

async fn relationship_trajectory<S>(State(state): State<AppState<S>>, request: Request) -> Response
where
    S: BoundaryApi,
{
    if let Err(error) = validate_headers(&request, state.config) {
        return error_response(error, state.config);
    }
    let body = match json_body::<RelationshipTrajectoryQuery>(request, state.config).await {
        Ok(body) => body,
        Err(error) => return error_response(error, state.config),
    };
    match block_on_api(state.api.relationship_trajectory(body)) {
        Ok(page) => json_response(StatusCode::OK, &page, state.config),
        Err(error) => error_response(error, state.config),
    }
}

async fn catalog<S>(State(state): State<AppState<S>>, request: Request) -> Response
where
    S: BoundaryApi,
{
    if let Err(error) = validate_headers(&request, state.config) {
        return error_response(error, state.config);
    }
    // `CatalogService::catalog` is intentionally synchronous in the public
    // contract. Run it on Tokio's blocking pool so a network-backed API client
    // can perform its synchronous compatibility implementation without
    // entering a blocking HTTP runtime from an async request task.
    let api = Arc::clone(&state.api);
    let config = state.config;
    match tokio::task::spawn_blocking(move || api.catalog()).await {
        Ok(Ok(catalog)) => json_response(StatusCode::OK, &catalog, config),
        Ok(Err(error)) => error_response(error, config),
        Err(_) => error_response(
            ApiError::unavailable("catalog request worker was unavailable"),
            config,
        ),
    }
}

async fn catalog_for_world<S>(
    State(state): State<AppState<S>>,
    Path(world_id): Path<String>,
    request: Request,
) -> Response
where
    S: BoundaryApi,
{
    if let Err(error) = validate_headers(&request, state.config) {
        return error_response(error, state.config);
    }
    let world_id = match parse_path_value::<WorldId>(&world_id, "World ID") {
        Ok(world_id) => world_id,
        Err(error) => return error_response(error, state.config),
    };
    match block_on_api(state.api.catalog_for_world(world_id)) {
        Ok(catalog) => json_response(StatusCode::OK, &catalog, state.config),
        Err(error) => error_response(error, state.config),
    }
}

async fn submit_ingress<S>(State(state): State<AppState<S>>, request: Request) -> Response
where
    S: BoundaryApi,
{
    if let Err(error) = validate_headers(&request, state.config) {
        return error_response(error, state.config);
    }
    let body = match json_body::<loom_api::IngressEnvelope>(request, state.config).await {
        Ok(body) => body,
        Err(error) => return error_response(error, state.config),
    };
    match block_on_api(state.api.submit_ingress(body)) {
        Ok(acceptance) => {
            let status = if acceptance.is_conflict() {
                StatusCode::CONFLICT
            } else {
                StatusCode::ACCEPTED
            };
            json_response(status, &acceptance, state.config)
        }
        Err(error) => error_response(error, state.config),
    }
}

async fn ingress_status<S>(
    State(state): State<AppState<S>>,
    Path(ingress_id): Path<String>,
    request: Request,
) -> Response
where
    S: BoundaryApi,
{
    if let Err(error) = validate_headers(&request, state.config) {
        return error_response(error, state.config);
    }
    let ingress_id = IngressId::from(ingress_id);
    match block_on_api(state.api.ingress_status(ingress_id)) {
        Ok(status) => json_response(StatusCode::OK, &status, state.config),
        Err(error) => error_response(error, state.config),
    }
}

async fn change_feed<S>(
    State(state): State<AppState<S>>,
    Path(path): Path<TimelinePath>,
    Query(query): Query<FeedQuery>,
    request: Request,
) -> Response
where
    S: BoundaryApi,
{
    if let Err(error) = validate_headers(&request, state.config) {
        return error_response(error, state.config);
    }
    let target = match path.target() {
        Ok(target) => target,
        Err(error) => return error_response(error, state.config),
    };
    let after = match feed_cursor(request.headers(), &query) {
        Ok(after) => after,
        Err(error) => return error_response(error, state.config),
    };
    let limit = match query.limit.as_deref() {
        Some(value) => match value.parse::<u32>() {
            Ok(limit) => limit,
            Err(_) => {
                return error_response(
                    ApiError::invalid_request("SSE limit must be an unsigned integer"),
                    state.config,
                );
            }
        },
        None => state.config.sse_events,
    };
    if limit == 0 || limit > state.config.sse_events {
        return error_response(
            ApiError::invalid_request("SSE limit exceeds the transport bound"),
            state.config,
        );
    }
    let subscription = match after {
        Some(after) => {
            SubscriptionRequest::resume(target, ChangeFeedCursor::after(target, after), limit)
        }
        None => SubscriptionRequest::new(target, limit),
    };
    let result = match block_on_api(state.api.subscribe(subscription)) {
        Ok(result) => result,
        Err(error) => return error_response(error, state.config),
    };
    subscription_response(result, state.config)
}

#[derive(Clone, Debug, Deserialize)]
struct TimelinePath {
    world_id: String,
    timeline_id: String,
}

impl TimelinePath {
    fn target(&self) -> ApiResult<TimelineTarget> {
        Ok(TimelineTarget::new(
            parse_path_value(&self.world_id, "World ID")?,
            parse_path_value(&self.timeline_id, "Timeline ID")?,
        ))
    }
}

#[derive(Clone, Debug, Deserialize)]
struct FeedQuery {
    limit: Option<String>,
    after: Option<String>,
}

fn feed_cursor(headers: &HeaderMap, query: &FeedQuery) -> ApiResult<Option<loom_api::EventSeq>> {
    if let Some(value) = headers.get("last-event-id") {
        let value = value
            .to_str()
            .map_err(|_| ApiError::invalid_request("Last-Event-ID is not valid UTF-8"))?;
        return value
            .parse::<u64>()
            .map(loom_api::EventSeq::new)
            .map(Some)
            .map_err(|_| ApiError::invalid_request("Last-Event-ID must be an unsigned integer"));
    }
    query
        .after
        .as_deref()
        .map(|value| {
            value
                .parse::<u64>()
                .map(loom_api::EventSeq::new)
                .map_err(|_| ApiError::invalid_request("SSE cursor must be an unsigned integer"))
        })
        .transpose()
}

fn subscription_response(result: SubscriptionResult, config: BoundaryConfig) -> Response {
    match result {
        SubscriptionResult::Events(page) => sse_page(page, config),
        SubscriptionResult::Resumed(resume) => sse_event_response(
            "resume",
            resume.cursor.after.value().to_string(),
            &resume,
            config,
        ),
        SubscriptionResult::Reconnect(reconnect) => {
            let id = reconnect
                .resume_from
                .map(|cursor| cursor.after.value().to_string());
            sse_optional_id_response("reconnect", id, &reconnect, config)
        }
        SubscriptionResult::Ended(end) => {
            let id = end.cursor.map(|cursor| cursor.after.value().to_string());
            sse_optional_id_response("end", id, &end, config)
        }
        SubscriptionResult::Backpressure(backpressure) => {
            let mut response = json_response(StatusCode::TOO_MANY_REQUESTS, &backpressure, config);
            if let Some(retry_after_ms) = backpressure.retry_after_ms
                && let Ok(value) = HeaderValue::try_from(retry_after_ms.to_string())
            {
                response.headers_mut().insert("retry-after-ms", value);
            }
            response
        }
    }
}

fn sse_page(page: loom_api::ChangeFeedPage, config: BoundaryConfig) -> Response {
    if page.events.len() > config.sse_events as usize {
        return error_response(
            ApiError::unavailable("SSE page exceeds the transport event bound"),
            config,
        );
    }
    let mut events = Vec::with_capacity(page.events.len() + 1);
    let mut buffered_bytes = 0_usize;
    for event in page.events {
        let Ok(data) = serde_json::to_string(&event) else {
            return error_response(
                ApiError::internal("committed Event could not be encoded as SSE"),
                config,
            );
        };
        let id = event.sequence.value().to_string();
        buffered_bytes = match buffered_bytes.checked_add(sse_frame_size("change", &id, data.len()))
        {
            Some(size) => size,
            None => {
                return error_response(
                    ApiError::unavailable("SSE response buffer limit was exceeded"),
                    config,
                );
            }
        };
        if buffered_bytes > config.sse_buffer_bytes {
            return error_response(
                ApiError::unavailable("SSE response buffer limit was exceeded"),
                config,
            );
        }
        events.push(Event::default().event("change").id(id).data(data));
    }
    let metadata = SsePageMetadata {
        next_cursor: page.next_cursor,
        has_more: page.has_more,
    };
    let Ok(data) = serde_json::to_string(&metadata) else {
        return error_response(
            ApiError::internal("Change Feed metadata could not be encoded as SSE"),
            config,
        );
    };
    buffered_bytes = match buffered_bytes.checked_add(sse_frame_size("page", "", data.len())) {
        Some(size) => size,
        None => {
            return error_response(
                ApiError::unavailable("SSE response buffer limit was exceeded"),
                config,
            );
        }
    };
    if buffered_bytes > config.sse_buffer_bytes {
        return error_response(
            ApiError::unavailable("SSE response buffer limit was exceeded"),
            config,
        );
    }
    events.push(Event::default().event("page").data(data));
    sse_response(events)
}

#[derive(Serialize)]
struct SsePageMetadata {
    next_cursor: Option<loom_api::ChangeFeedCursor>,
    has_more: bool,
}

fn sse_event_response<T>(
    event_name: &str,
    id: String,
    value: &T,
    config: BoundaryConfig,
) -> Response
where
    T: Serialize,
{
    sse_optional_id_response(event_name, Some(id), value, config)
}

fn sse_optional_id_response<T>(
    event_name: &str,
    id: Option<String>,
    value: &T,
    config: BoundaryConfig,
) -> Response
where
    T: Serialize,
{
    let Ok(data) = serde_json::to_string(value) else {
        return error_response(
            ApiError::internal("subscription result could not be encoded as SSE"),
            config,
        );
    };
    let frame_size = sse_frame_size(event_name, id.as_deref().unwrap_or_default(), data.len());
    if frame_size > config.sse_buffer_bytes {
        return error_response(
            ApiError::unavailable("SSE response buffer limit was exceeded"),
            config,
        );
    }
    let mut event = Event::default().event(event_name).data(data);
    if let Some(id) = id {
        event = event.id(id);
    }
    sse_response(vec![event])
}

fn sse_frame_size(event_name: &str, id: &str, data_bytes: usize) -> usize {
    const FRAME_OVERHEAD: usize = "event:\nid:\ndata:\n\n".len();
    FRAME_OVERHEAD
        .saturating_add(event_name.len())
        .saturating_add(id.len())
        .saturating_add(data_bytes)
}

fn sse_response(events: Vec<Event>) -> Response {
    let stream = stream::iter(events.into_iter().map(Ok::<Event, Infallible>));
    let mut response = Sse::new(stream)
        .keep_alive(KeepAlive::default())
        .into_response();
    response.headers_mut().insert(
        header::CACHE_CONTROL,
        HeaderValue::from_static("no-cache, no-transform"),
    );
    response.headers_mut().insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("text/event-stream"),
    );
    response
        .headers_mut()
        .insert("x-accel-buffering", HeaderValue::from_static("no"));
    response
}

fn parse_path_value<T>(value: &str, name: &str) -> ApiResult<T>
where
    T: FromStr,
{
    value
        .parse()
        .map_err(|_| ApiError::invalid_request(format!("{name} is invalid")))
}

fn block_on_api<T, F>(future: F) -> ApiResult<T>
where
    F: Future<Output = ApiResult<T>>,
{
    // `loom-api` deliberately keeps its future executor-neutral and therefore
    // non-Send. Boundary is the transport/application seam, so it adapts that
    // contract here rather than leaking Runtime or Storage constraints into
    // the public API. A multithread Tokio server yields the worker while this
    // one API operation runs; current-thread tests remain executor-neutral.
    let Ok(handle) = tokio::runtime::Handle::try_current() else {
        return futures_executor::block_on(future);
    };
    if matches!(
        handle.runtime_flavor(),
        tokio::runtime::RuntimeFlavor::MultiThread
    ) {
        tokio::task::block_in_place(|| handle.block_on(future))
    } else {
        futures_executor::block_on(future)
    }
}

fn validate_headers(request: &Request, config: BoundaryConfig) -> ApiResult<()> {
    let size = request
        .headers()
        .iter()
        .try_fold(0_usize, |size, (name, value)| {
            size.checked_add(name.as_str().len())
                .and_then(|size| size.checked_add(value.as_bytes().len()))
                .ok_or(())
        })
        .unwrap_or(usize::MAX);
    if size > config.header_bytes {
        Err(ApiError::invalid_request(
            "request headers exceed the transport limit",
        ))
    } else {
        Ok(())
    }
}

async fn json_body<T>(request: Request, config: BoundaryConfig) -> ApiResult<T>
where
    T: DeserializeOwned,
{
    let bytes = to_bytes(request.into_body(), config.body_bytes)
        .await
        .map_err(|_| ApiError::invalid_request("request body exceeds the transport limit"))?;
    serde_json::from_slice(&bytes)
        .map_err(|_| ApiError::invalid_request("request body is not valid API JSON"))
}

fn json_response<T>(status: StatusCode, value: &T, config: BoundaryConfig) -> Response
where
    T: Serialize,
{
    let Ok(bytes) = serde_json::to_vec(value) else {
        return error_response(
            ApiError::internal("API response could not be encoded as JSON"),
            config,
        );
    };
    if bytes.len() > config.response_bytes {
        return error_response(
            ApiError::unavailable("API response exceeds the transport limit"),
            config,
        );
    }
    response_with_bytes(status, "application/json", bytes, config.response_bytes)
}

fn error_response(error: ApiError, config: BoundaryConfig) -> Response {
    let body = TransportErrorBody {
        code: error.code.to_string(),
        message: error.message,
    };
    let status = match body.code.as_str() {
        "invalid_request" => StatusCode::BAD_REQUEST,
        "not_found" => StatusCode::NOT_FOUND,
        "conflict" => StatusCode::CONFLICT,
        "unavailable" => StatusCode::SERVICE_UNAVAILABLE,
        "unauthorized" => StatusCode::UNAUTHORIZED,
        "forbidden" => StatusCode::FORBIDDEN,
        _ => StatusCode::INTERNAL_SERVER_ERROR,
    };
    let bytes = serde_json::to_vec(&body)
        .unwrap_or_else(|_| br#"{"code":"internal","message":"API boundary error"}"#.to_vec());
    let bytes = if bytes.len() <= config.response_bytes {
        bytes
    } else {
        br#"{"code":"internal","message":"API boundary error"}"#.to_vec()
    };
    response_with_bytes(status, "application/json", bytes, config.response_bytes)
}

fn response_with_bytes(
    status: StatusCode,
    content_type: &'static str,
    mut bytes: Vec<u8>,
    max_bytes: usize,
) -> Response {
    if bytes.len() > max_bytes {
        bytes.truncate(max_bytes);
    }
    Response::builder()
        .status(status)
        .header(header::CONTENT_TYPE, content_type)
        .header(header::CONTENT_LENGTH, bytes.len())
        .body(Body::from(bytes))
        .expect("static response headers are valid")
}

#[derive(Serialize)]
struct TransportErrorBody {
    code: String,
    message: String,
}

#[cfg(test)]
mod tests {
    use std::str::FromStr;
    use std::sync::{Arc, Mutex};

    use axum::{
        body::Body,
        http::{Request, StatusCode},
        response::Response,
    };
    use loom_api::{
        ActionInvocation, ActionRequest, ActionService, ApiError, ApiFuture, CatalogService,
        CatalogSnapshot, ChangeFeedCursor, ChangeFeedPage, EventId, EventSeq, EventTypeId,
        ExecutionResult, FacetQuery, ForkTimelineRequest, HistoryService, IngressAcceptance,
        IngressEnvelope, IngressId, IngressService, IngressStatusRecord, QueryService,
        SchemaRevision, SubscriptionBackpressure, SubscriptionReconnect,
        SubscriptionReconnectReason, SubscriptionRequest, SubscriptionResult, SubscriptionService,
        TimelineService, TimelineSnapshot, TimelineTarget, WorldInstant, WorldService,
    };
    use loom_api::{CommittedEvent, TimelineId, TimelineVersion, WorldId};
    use serde::{Serialize, Serializer};
    use serde_json::json;
    use tower::ServiceExt;

    use super::{BoundaryConfig, BoundaryConfigError, router};

    #[derive(Default)]
    struct FakeApi {
        calls: Arc<Mutex<Vec<&'static str>>>,
    }

    impl FakeApi {
        fn record(&self, call: &'static str) {
            self.calls.lock().expect("fake call log lock").push(call);
        }

        fn target() -> TimelineTarget {
            TimelineTarget::new(
                WorldId::from_str("00000000-0000-0000-0000-000000000001").expect("World ID"),
                TimelineId::from_str("00000000-0000-0000-0000-000000000002").expect("Timeline ID"),
            )
        }
    }

    impl WorldService for FakeApi {
        fn create_world_from_template(
            &self,
            _request: loom_api::CreateWorldFromTemplateRequest,
        ) -> ApiFuture<'_, TimelineSnapshot> {
            self.record("world");
            Box::pin(async { Ok(snapshot()) })
        }
    }

    impl ActionService for FakeApi {
        fn invoke(&self, _request: ActionRequest) -> ApiFuture<'_, ExecutionResult> {
            self.record("action");
            Box::pin(async { Ok(ExecutionResult::no_change()) })
        }
    }

    impl TimelineService for FakeApi {
        fn inspect_timeline(&self, _target: TimelineTarget) -> ApiFuture<'_, TimelineSnapshot> {
            self.record("timeline");
            Box::pin(async { Ok(snapshot()) })
        }

        fn fork(&self, _request: ForkTimelineRequest) -> ApiFuture<'_, TimelineSnapshot> {
            self.record("fork");
            Box::pin(async { Ok(snapshot()) })
        }
    }

    impl QueryService for FakeApi {
        fn get_facet(&self, _query: FacetQuery) -> ApiFuture<'_, Option<loom_api::FacetSnapshot>> {
            self.record("query");
            Box::pin(async { Ok(None) })
        }
    }

    impl HistoryService for FakeApi {
        fn list_events(
            &self,
            _query: loom_api::EventQuery,
        ) -> ApiFuture<'_, Vec<loom_api::CommittedEvent>> {
            self.record("history");
            Box::pin(async { Ok(Vec::new()) })
        }
    }

    impl CatalogService for FakeApi {
        fn catalog(&self) -> loom_api::ApiResult<CatalogSnapshot> {
            self.record("catalog");
            Ok(CatalogSnapshot::default())
        }
    }

    impl IngressService for FakeApi {
        fn submit_ingress(&self, request: IngressEnvelope) -> ApiFuture<'_, IngressAcceptance> {
            self.record("ingress");
            Box::pin(async {
                Ok(IngressAcceptance::accepted(loom_api::IngressReceipt::new(
                    request.ingress_id,
                    request.idempotency_key,
                )))
            })
        }

        fn ingress_status(&self, _ingress_id: IngressId) -> ApiFuture<'_, IngressStatusRecord> {
            self.record("ingress-status");
            Box::pin(async { Err(ApiError::not_found("missing ingress")) })
        }
    }

    impl SubscriptionService for FakeApi {
        fn subscribe(&self, request: SubscriptionRequest) -> ApiFuture<'_, SubscriptionResult> {
            self.record("subscription");
            let cursor = request
                .resume_from
                .unwrap_or_else(|| ChangeFeedCursor::beginning(request.target));
            Box::pin(async move {
                Ok(SubscriptionResult::Resumed(loom_api::SubscriptionResume {
                    cursor,
                }))
            })
        }
    }

    fn snapshot() -> TimelineSnapshot {
        TimelineSnapshot::new(
            FakeApi::target(),
            TimelineVersion::new(EventSeq::new(0), 0.into()),
            WorldInstant::new(0),
        )
    }

    fn request(method: &'static str, uri: &'static str, body: Option<String>) -> Request<Body> {
        let mut builder = Request::builder().method(method).uri(uri);
        if body.is_some() {
            builder = builder.header("content-type", "application/json");
        }
        builder
            .body(Body::from(body.unwrap_or_default()))
            .expect("test request is valid")
    }

    async fn body_bytes(response: Response) -> Vec<u8> {
        axum::body::to_bytes(response.into_body(), 1024 * 1024)
            .await
            .expect("test response body can be read")
            .to_vec()
    }

    async fn body(response: Response) -> String {
        let bytes = body_bytes(response).await;
        String::from_utf8(bytes).expect("test response is UTF-8")
    }

    #[tokio::test]
    async fn generic_json_routes_call_only_the_unified_api() {
        let api = Arc::new(FakeApi::default());
        let target = FakeApi::target();
        let action = ActionRequest::for_timeline(
            target.world_id,
            target.timeline_id,
            ActionInvocation::new("counter.increment".into(), json!({"amount": 1})),
        );
        let app = router(api.clone(), BoundaryConfig::default());
        let response = app
            .oneshot(request(
                "POST",
                "/v1/actions",
                Some(serde_json::to_string(&action).expect("action JSON")),
            ))
            .await
            .expect("router response");
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(body(response).await, r#""NoChange""#);
        assert_eq!(
            api.calls.lock().expect("call log lock").as_slice(),
            &["action"]
        );
    }

    #[tokio::test]
    async fn typed_api_errors_map_without_internal_details() {
        let app = router(Arc::new(FakeApi::default()), BoundaryConfig::default());
        let response = app
            .oneshot(request("GET", "/v1/ingress/missing", None))
            .await
            .expect("router response");
        assert_eq!(response.status(), StatusCode::NOT_FOUND);
        assert_eq!(
            body(response).await,
            r#"{"code":"not_found","message":"missing ingress"}"#
        );
    }

    #[tokio::test]
    async fn error_response_is_capped_when_config_is_smaller_than_fallback() {
        let config = BoundaryConfig::new(8, 8, 8, 8, 10, 1).expect("valid limits");
        let response = super::error_response(ApiError::internal("internal details"), config);
        let declared_length = response
            .headers()
            .get("content-length")
            .expect("content length")
            .to_str()
            .expect("content length is ASCII")
            .parse::<usize>()
            .expect("content length is numeric");
        let bytes = body_bytes(response).await;

        assert!(bytes.len() <= config.max_response_bytes());
        assert_eq!(declared_length, bytes.len());
    }

    #[tokio::test]
    async fn oversized_json_response_is_capped_and_preserves_typed_error() {
        let config = BoundaryConfig::new(8, 8, 256, 256, 10, 1).expect("valid limits");
        let value = json!({ "payload": "x".repeat(1024) });
        let response = super::json_response(StatusCode::OK, &value, config);
        assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
        let declared_length = response
            .headers()
            .get("content-length")
            .expect("content length")
            .to_str()
            .expect("content length is ASCII")
            .parse::<usize>()
            .expect("content length is numeric");
        let bytes = body_bytes(response).await;
        let error: serde_json::Value = serde_json::from_slice(&bytes).expect("typed error JSON");

        assert!(bytes.len() <= config.max_response_bytes());
        assert_eq!(declared_length, bytes.len());
        assert_eq!(error["code"], "unavailable");
    }

    struct FailingSerialize;

    impl Serialize for FailingSerialize {
        fn serialize<S>(&self, _serializer: S) -> Result<S::Ok, S::Error>
        where
            S: Serializer,
        {
            Err(serde::ser::Error::custom("forced serialization failure"))
        }
    }

    #[tokio::test]
    async fn serialization_failure_response_is_capped() {
        let config = BoundaryConfig::new(8, 8, 8, 8, 10, 1).expect("valid limits");
        let response = super::json_response(StatusCode::OK, &FailingSerialize, config);
        let declared_length = response
            .headers()
            .get("content-length")
            .expect("content length")
            .to_str()
            .expect("content length is ASCII")
            .parse::<usize>()
            .expect("content length is numeric");
        let bytes = body_bytes(response).await;

        assert!(bytes.len() <= config.max_response_bytes());
        assert_eq!(declared_length, bytes.len());
    }

    #[tokio::test]
    async fn last_event_id_is_mapped_to_a_resumable_subscription_cursor() {
        let api = Arc::new(FakeApi::default());
        let target = FakeApi::target();
        let app = router(api.clone(), BoundaryConfig::default());
        let response = app
            .clone()
            .oneshot(
                Request::builder()
                    .method("GET")
                    .uri(format!(
                        "/v1/timelines/{}/{}",
                        target.world_id, target.timeline_id
                    ))
                    .header("last-event-id", "7")
                    .body(Body::empty())
                    .expect("test request is valid"),
            )
            .await
            .expect("router response");
        assert_eq!(response.status(), StatusCode::OK);

        let response = app
            .oneshot(
                Request::builder()
                    .method("GET")
                    .uri(format!(
                        "/v1/timelines/{}/{}/changes?limit=1",
                        target.world_id, target.timeline_id
                    ))
                    .header("last-event-id", "7")
                    .body(Body::empty())
                    .expect("test request is valid"),
            )
            .await
            .expect("router response");
        assert_eq!(response.status(), StatusCode::OK);
        assert!(body(response).await.contains("\"after\":7"));
    }

    #[tokio::test]
    async fn sse_maps_event_ids_reconnects_and_backpressure() {
        let target = FakeApi::target();
        let event = CommittedEvent {
            id: EventId::from_str("00000000-0000-0000-0000-000000000003").expect("Event ID"),
            timeline_id: target.timeline_id,
            sequence: EventSeq::new(3),
            event_type: EventTypeId::from("counter.changed"),
            schema_revision: SchemaRevision::new(1),
            occurred_at: WorldInstant::new(0),
            participants: Vec::new(),
            relationship_refs: Vec::new(),
            causal_links: Vec::new(),
            payload: json!({"amount": 1}),
            effects: Vec::new(),
        };
        let page = ChangeFeedPage {
            events: vec![event],
            next_cursor: Some(ChangeFeedCursor::after(target, EventSeq::new(3))),
            has_more: true,
        };
        let response = super::subscription_response(
            SubscriptionResult::Events(page),
            BoundaryConfig::default(),
        );
        assert_eq!(response.status(), StatusCode::OK);
        let events = body(response).await;
        assert!(events.contains("event: change"));
        assert!(events.contains("id: 3"));
        assert!(events.contains("event: page"));
        assert!(events.contains("\"has_more\":true"));

        let response = super::subscription_response(
            SubscriptionResult::Reconnect(SubscriptionReconnect {
                resume_from: Some(ChangeFeedCursor::after(target, EventSeq::new(3))),
                reason: SubscriptionReconnectReason::TemporaryFailure,
            }),
            BoundaryConfig::default(),
        );
        assert_eq!(response.status(), StatusCode::OK);
        assert!(body(response).await.contains("event: reconnect"));

        let response = super::subscription_response(
            SubscriptionResult::Backpressure(SubscriptionBackpressure {
                resume_from: Some(ChangeFeedCursor::after(target, EventSeq::new(3))),
                retry_after_ms: Some(25),
                max_events: 1,
            }),
            BoundaryConfig::default(),
        );
        assert_eq!(response.status(), StatusCode::TOO_MANY_REQUESTS);
        assert_eq!(
            response
                .headers()
                .get("retry-after-ms")
                .expect("retry header"),
            "25"
        );
    }

    #[tokio::test]
    async fn oversized_body_is_rejected_before_api_dispatch() {
        let api = Arc::new(FakeApi::default());
        let config = BoundaryConfig::new(64, 64, 1024, 1024, 10, 1).expect("valid limits");
        let app = router(api.clone(), config);
        let response = app
            .oneshot(request("POST", "/v1/actions", Some("x".repeat(65))))
            .await
            .expect("router response");
        assert_eq!(response.status(), StatusCode::BAD_REQUEST);
        assert!(body(response).await.contains("request body exceeds"));
        assert!(api.calls.lock().expect("call log lock").is_empty());
    }

    #[tokio::test]
    async fn json_body_accepts_under_and_exact_limits_and_rejects_over() {
        let config = BoundaryConfig::new(4, 4, 4, 4, 1, 1).expect("valid limits");
        let under: serde_json::Value =
            super::json_body(request("POST", "/", Some("0".to_owned())), config)
                .await
                .expect("under-limit JSON should pass");
        assert_eq!(under, json!(0));
        let exact: serde_json::Value =
            super::json_body(request("POST", "/", Some("null".to_owned())), config)
                .await
                .expect("exact-limit JSON should pass");
        assert_eq!(exact, serde_json::Value::Null);
        let over = super::json_body::<serde_json::Value>(
            request("POST", "/", Some("{}xxx".to_owned())),
            config,
        )
        .await
        .expect_err("over-limit JSON should fail before parsing");
        assert_eq!(over.message, "request body exceeds the transport limit");
    }

    #[test]
    fn impossible_transport_limit_combinations_fail_at_startup() {
        assert_eq!(
            BoundaryConfig::new(8, 9, 9, 9, 1, 1),
            Err(BoundaryConfigError::HeaderLimitExceedsBody)
        );
        assert_eq!(
            BoundaryConfig::new(8, 8, 7, 7, 1, 1),
            Err(BoundaryConfigError::ResponseLimitBelowBody)
        );
        assert_eq!(
            BoundaryConfig::new(8, 8, 8, 9, 1, 1),
            Err(BoundaryConfigError::SseBufferLimitExceedsResponse)
        );
        assert_eq!(
            BoundaryConfig::new(8, 8, 8, 8, loom_api::MAX_CHANGE_FEED_PAGE_SIZE + 1, 1),
            Err(BoundaryConfigError::SseEventLimitExceedsPublic)
        );
    }
}
