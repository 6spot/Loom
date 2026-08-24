//! A transport client for the versioned Loom HTTP/JSON and SSE boundary.
//!
//! `loom-client` implements the public [`loom_api`] service contracts over the
//! routes exposed by `loom-boundary`. It is deliberately a consumer-side
//! adapter: it owns HTTP configuration, authentication headers, response
//! decoding and SSE framing, but it contains no Runtime, Storage or Capability
//! implementation and has no semantic authority of its own.
//!
//! Direct Action requests are sent once. Idempotent Ingress submission may use
//! an explicitly configured retry policy. Subscription resume is represented by
//! the durable API cursor and is sent as `Last-Event-ID` on the SSE request;
//! callers may use [`LoomClient::subscribe_with_reconnect`] when they want the
//! transport adapter to follow a server reconnect instruction.

#![forbid(unsafe_code)]

use std::{fmt, str, time::Duration};

use futures_util::StreamExt;
use loom_api::{
    ActionRequest, ActionService, AdminActivateRuntimeRevisionRequest,
    AdminAdvanceWorldTimeRequest, AdminAdvanceWorldTimeResult, AdminEventSessionLookup,
    AdminExecutionSession, AdminExecutionSessionRequest, AdminFuture,
    AdminMissingImplementationBlock, AdminMissingImplementationRequest, AdminRuntimeRevision,
    AdminRuntimeRevisionRequest, AdminRuntimeRevisionSelection, AdminScheduleAgencyWakeRequest,
    AdminScheduleAgencyWakeResult, AdminService, AdminTerminalizeWorkRequest,
    AdminTerminalizeWorkResult, AdminTimelineLogicalStatus, ApiError, ApiErrorCode, ApiFuture,
    ApiResult, CatalogService, CatalogSnapshot, CausalQuery, CausalTraversal, ChangeFeedCursor,
    ChangeFeedPage, CommittedEvent, CreateWorldFromTemplateRequest, CreateWorldFromTemplateResult,
    EventPage, EventQuery, EventRef, ExecutionResult, FacetQuery, FacetSnapshot,
    ForkTimelineRequest, ForkTimelineResult, HistoryService, IngressAcceptance, IngressEnvelope,
    IngressId, IngressService, IngressStatusRecord, QueryService, RelationshipTrajectoryQuery,
    SubscriptionEnd, SubscriptionReconnect, SubscriptionRequest, SubscriptionResult,
    SubscriptionResume, SubscriptionService, TimelineService, TimelineSnapshot, TimelineTarget,
    TrajectoryPage, WorldId, WorldService,
};
use percent_encoding::{NON_ALPHANUMERIC, utf8_percent_encode};
use reqwest::{
    Method, StatusCode, Url,
    header::{CONTENT_TYPE, HeaderMap, HeaderName, HeaderValue},
};
use serde::{Deserialize, Serialize, de::DeserializeOwned};

/// The versioned public API path implemented by `loom-boundary`.
pub const API_PREFIX: &str = "/v1";
/// The isolated Runtime administration path prefix.
pub const ADMIN_API_PREFIX: &str = loom_api::ADMIN_API_PREFIX;

const DEFAULT_REQUEST_TIMEOUT: Duration = Duration::from_secs(30);
const DEFAULT_MAX_RESPONSE_BYTES: usize = 8 * 1024 * 1024;
const DEFAULT_MAX_SSE_BYTES: usize = 4 * 1024 * 1024;

/// Errors found while constructing an HTTP client.
#[derive(Debug)]
pub enum ClientConfigError {
    /// The configured URL is not an absolute HTTP(S) URL with a host.
    InvalidBaseUrl(String),
    /// A configured header value could not be represented as an HTTP header.
    InvalidHeader(String),
    /// An HTTP client could not be constructed from the supplied settings.
    Build(String),
    /// A response or SSE buffer limit was zero.
    ZeroLimit(&'static str),
}

impl fmt::Display for ClientConfigError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidBaseUrl(message) => write!(formatter, "invalid Loom base URL: {message}"),
            Self::InvalidHeader(message) => write!(formatter, "invalid HTTP header: {message}"),
            Self::Build(message) => {
                write!(formatter, "could not build Loom HTTP client: {message}")
            }
            Self::ZeroLimit(name) => write!(formatter, "{name} must be positive"),
        }
    }
}

impl std::error::Error for ClientConfigError {}

/// Explicit retry policy for idempotent Ingress submission.
///
/// A retry is attempted only for an `Unavailable` API error and only when this
/// policy is configured with a non-zero `max_retries`. Direct Action requests
/// never use this policy.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct IngressRetryPolicy {
    max_retries: u32,
    backoff: Duration,
}

impl Default for IngressRetryPolicy {
    fn default() -> Self {
        Self {
            max_retries: 0,
            backoff: Duration::ZERO,
        }
    }
}

impl IngressRetryPolicy {
    /// Creates a policy with an explicit retry count and delay between tries.
    #[must_use]
    pub const fn new(max_retries: u32, backoff: Duration) -> Self {
        Self {
            max_retries,
            backoff,
        }
    }

    /// Returns the number of retries after the initial submission.
    #[must_use]
    pub const fn max_retries(self) -> u32 {
        self.max_retries
    }

    /// Returns the delay between retry attempts.
    #[must_use]
    pub const fn backoff(self) -> Duration {
        self.backoff
    }
}

/// Builder for [`LoomClient`].
#[derive(Clone, Debug)]
pub struct ClientBuilder {
    base_url: String,
    headers: HeaderMap,
    timeout: Option<Duration>,
    max_response_bytes: usize,
    max_sse_bytes: usize,
    ingress_retry_policy: IngressRetryPolicy,
}

impl ClientBuilder {
    /// Starts a client builder for an HTTP(S) server URL.
    #[must_use]
    pub fn new(base_url: impl Into<String>) -> Self {
        Self {
            base_url: base_url.into(),
            headers: HeaderMap::new(),
            timeout: Some(DEFAULT_REQUEST_TIMEOUT),
            max_response_bytes: DEFAULT_MAX_RESPONSE_BYTES,
            max_sse_bytes: DEFAULT_MAX_SSE_BYTES,
            ingress_retry_policy: IngressRetryPolicy::default(),
        }
    }

    /// Replaces the base URL. The URL may include an application path prefix.
    #[must_use]
    pub fn base_url(mut self, base_url: impl Into<String>) -> Self {
        self.base_url = base_url.into();
        self
    }

    /// Adds or replaces an authentication or other request header.
    #[must_use]
    pub fn header(mut self, name: HeaderName, value: HeaderValue) -> Self {
        self.headers.insert(name, value);
        self
    }

    /// Replaces the complete set of default request headers.
    #[must_use]
    pub fn default_headers(mut self, headers: HeaderMap) -> Self {
        self.headers = headers;
        self
    }

    /// Adds a bearer token without embedding credentials in the client.
    ///
    /// # Errors
    ///
    /// Returns [`ClientConfigError::InvalidHeader`] when `token` contains a
    /// value that cannot be represented in an HTTP header.
    pub fn bearer_token(mut self, token: impl AsRef<str>) -> Result<Self, ClientConfigError> {
        let value = HeaderValue::try_from(format!("Bearer {}", token.as_ref()))
            .map_err(|error| ClientConfigError::InvalidHeader(error.to_string()))?;
        self.headers.insert("authorization", value);
        Ok(self)
    }

    /// Adds the credential consumed by the isolated Admin authorization hook.
    ///
    /// This header is intentionally distinct from the ordinary API bearer
    /// token. Applications with a different policy should provide their own
    /// Boundary hook and header mapping.
    ///
    /// # Errors
    ///
    /// Returns [`ClientConfigError::InvalidHeader`] when the token cannot be
    /// represented as an HTTP header value.
    pub fn admin_token(mut self, token: impl AsRef<str>) -> Result<Self, ClientConfigError> {
        let value = HeaderValue::try_from(token.as_ref())
            .map_err(|error| ClientConfigError::InvalidHeader(error.to_string()))?;
        self.headers
            .insert(HeaderName::from_static("x-loom-admin-authorization"), value);
        Ok(self)
    }

    /// Sets the request timeout. Dropping a service future also cancels its
    /// in-flight request.
    #[must_use]
    pub fn timeout(mut self, timeout: Duration) -> Self {
        self.timeout = Some(timeout);
        self
    }

    /// Disables the client-side timeout. This is useful only when the caller
    /// supplies cancellation or an external deadline.
    #[must_use]
    pub fn no_timeout(mut self) -> Self {
        self.timeout = None;
        self
    }

    /// Sets the maximum encoded JSON response accepted by the client.
    #[must_use]
    pub fn max_response_bytes(mut self, max_response_bytes: usize) -> Self {
        self.max_response_bytes = max_response_bytes;
        self
    }

    /// Sets the maximum buffered SSE response accepted by the client.
    #[must_use]
    pub fn max_sse_bytes(mut self, max_sse_bytes: usize) -> Self {
        self.max_sse_bytes = max_sse_bytes;
        self
    }

    /// Enables explicit retries for idempotent Ingress submission.
    #[must_use]
    pub fn ingress_retry_policy(mut self, policy: IngressRetryPolicy) -> Self {
        self.ingress_retry_policy = policy;
        self
    }

    /// Builds the configured client.
    ///
    /// # Errors
    ///
    /// Returns a [`ClientConfigError`] when the base URL, limits or HTTP
    /// transport configuration is invalid.
    pub fn build(self) -> Result<LoomClient, ClientConfigError> {
        LoomClient::from_builder(&self)
    }
}

/// A reusable HTTP/JSON/SSE client implementing every v0 [`loom_api`] service.
///
/// The client is cloneable; clones share the underlying connection pools and
/// retain the same base URL, headers, limits and retry policy.
#[derive(Clone)]
pub struct LoomClient {
    base_url: Url,
    http: reqwest::Client,
    max_response_bytes: usize,
    max_sse_bytes: usize,
    ingress_retry_policy: IngressRetryPolicy,
}

impl fmt::Debug for LoomClient {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("LoomClient")
            .field("base_url", &self.base_url)
            .field("max_response_bytes", &self.max_response_bytes)
            .field("max_sse_bytes", &self.max_sse_bytes)
            .field("ingress_retry_policy", &self.ingress_retry_policy)
            .finish_non_exhaustive()
    }
}

impl LoomClient {
    /// Starts a builder for a Loom server URL.
    #[must_use]
    pub fn builder(base_url: impl Into<String>) -> ClientBuilder {
        ClientBuilder::new(base_url)
    }

    /// Builds a client with default headers, timeout and response limits.
    ///
    /// # Errors
    ///
    /// Returns a [`ClientConfigError`] when `base_url` is not an absolute
    /// HTTP(S) URL or the underlying HTTP client cannot be constructed.
    pub fn new(base_url: impl Into<String>) -> Result<Self, ClientConfigError> {
        Self::builder(base_url).build()
    }

    fn from_builder(builder: &ClientBuilder) -> Result<Self, ClientConfigError> {
        if builder.max_response_bytes == 0 {
            return Err(ClientConfigError::ZeroLimit("max response bytes"));
        }
        if builder.max_sse_bytes == 0 {
            return Err(ClientConfigError::ZeroLimit("max SSE bytes"));
        }

        let mut base_url = Url::parse(&builder.base_url)
            .map_err(|error| ClientConfigError::InvalidBaseUrl(error.to_string()))?;
        if !matches!(base_url.scheme(), "http" | "https") || base_url.host_str().is_none() {
            return Err(ClientConfigError::InvalidBaseUrl(
                "base URL must be an absolute HTTP(S) URL".to_owned(),
            ));
        }
        if !base_url.path().ends_with('/') {
            base_url.set_path(&format!("{}/", base_url.path()));
        }

        let mut async_builder = reqwest::Client::builder().default_headers(builder.headers.clone());
        if let Some(timeout) = builder.timeout {
            async_builder = async_builder.timeout(timeout);
        }
        let http = async_builder
            .build()
            .map_err(|error| ClientConfigError::Build(error.to_string()))?;

        Ok(Self {
            base_url,
            http,
            max_response_bytes: builder.max_response_bytes,
            max_sse_bytes: builder.max_sse_bytes,
            ingress_retry_policy: builder.ingress_retry_policy,
        })
    }

    /// Returns the configured server URL, before the versioned API path.
    #[must_use]
    pub fn base_url(&self) -> &Url {
        &self.base_url
    }

    /// Sends one subscription request and follows reconnect instructions up to
    /// `max_reconnects` times. A returned `Reconnect` after that bound remains
    /// visible to the caller and can be resumed manually with its cursor.
    ///
    /// # Errors
    ///
    /// Returns the typed API error reported by the server or an unavailable
    /// error when the HTTP/SSE exchange cannot be completed.
    pub async fn subscribe_with_reconnect(
        &self,
        mut request: SubscriptionRequest,
        max_reconnects: u32,
    ) -> ApiResult<SubscriptionResult> {
        let mut reconnects = 0;
        loop {
            let result = SubscriptionService::subscribe(self, request).await?;
            let SubscriptionResult::Reconnect(instruction) = &result else {
                return Ok(result);
            };
            if reconnects >= max_reconnects {
                return Ok(result);
            }
            reconnects += 1;
            request = match instruction.resume_from {
                Some(cursor) => SubscriptionRequest::resume(request.target, cursor, request.limit),
                None => SubscriptionRequest::new(request.target, request.limit),
            };
        }
    }

    async fn send_ingress(&self, request: &IngressEnvelope) -> ApiResult<IngressAcceptance> {
        let mut retries = 0;
        loop {
            let result = self
                .execute_async_raw(
                    Method::POST,
                    &format!("{API_PREFIX}/ingress"),
                    Some(request),
                )
                .await
                .and_then(|(status, bytes)| {
                    if status == StatusCode::CONFLICT {
                        decode_ingress_response(&bytes)
                    } else {
                        decode_http_response(status, &bytes)
                    }
                });
            let retry_policy = self.ingress_retry_policy;
            if !is_retryable_ingress_error(&result) || retries >= retry_policy.max_retries {
                return result;
            }
            retries += 1;
            if !retry_policy.backoff.is_zero() {
                tokio::time::sleep(retry_policy.backoff).await;
            }
        }
    }

    async fn send_json_once<B, T>(&self, method: Method, path: String, body: &B) -> ApiResult<T>
    where
        B: Serialize + ?Sized,
        T: DeserializeOwned,
    {
        self.execute_async(method, &path, Some(body)).await
    }

    async fn send_empty<T>(&self, method: Method, path: String) -> ApiResult<T>
    where
        T: DeserializeOwned,
    {
        self.execute_async::<(), T>(method, &path, None).await
    }

    async fn execute_async<B, T>(
        &self,
        method: Method,
        path: &str,
        body: Option<&B>,
    ) -> ApiResult<T>
    where
        B: Serialize + ?Sized,
        T: DeserializeOwned,
    {
        let (status, bytes) = self.execute_async_raw(method, path, body).await?;
        decode_http_response(status, &bytes)
    }

    async fn execute_async_raw<B>(
        &self,
        method: Method,
        path: &str,
        body: Option<&B>,
    ) -> ApiResult<(StatusCode, Vec<u8>)>
    where
        B: Serialize + ?Sized,
    {
        let url = self.endpoint(path)?;
        let mut request = self.http.request(method, url);
        if let Some(body) = body {
            request = request.json(body);
        }
        let response = request
            .send()
            .await
            .map_err(|_| ApiError::unavailable("Loom HTTP request was unavailable"))?;
        let status = response.status();
        let bytes = read_async_body(response, self.max_response_bytes).await?;
        Ok((status, bytes))
    }

    async fn subscribe_http(&self, request: SubscriptionRequest) -> ApiResult<SubscriptionResult> {
        request.validate()?;
        let path = format!(
            "{API_PREFIX}/timelines/{}/{}/changes?limit={}",
            path_segment(&request.target.world_id.to_string()),
            path_segment(&request.target.timeline_id.to_string()),
            request.limit
        );
        let url = self.endpoint(&path)?;
        let mut http_request = self.http.get(url);
        if let Some(cursor) = request.resume_from {
            let value = HeaderValue::from_str(&cursor.after.value().to_string())
                .map_err(|_| ApiError::invalid_request("subscription cursor is invalid"))?;
            http_request = http_request.header(HeaderName::from_static("last-event-id"), value);
        }
        let response = http_request
            .header(CONTENT_TYPE, "text/event-stream")
            .send()
            .await
            .map_err(|_| ApiError::unavailable("Loom SSE request was unavailable"))?;
        let status = response.status();
        let bytes = read_async_body(response, self.max_sse_bytes).await?;
        if status == StatusCode::TOO_MANY_REQUESTS {
            return decode_body(&bytes).map(SubscriptionResult::Backpressure);
        }
        if !status.is_success() {
            return Err(decode_http_error(status, &bytes));
        }
        decode_sse_subscription(&bytes)
    }

    fn endpoint(&self, path: &str) -> ApiResult<Url> {
        self.base_url
            .join(path.trim_start_matches('/'))
            .map_err(|_| ApiError::internal("Loom API endpoint could not be constructed"))
    }
}

/// Compatibility alias for consumers that call the adapter an HTTP client.
pub type HttpClient = LoomClient;

impl WorldService for LoomClient {
    fn create_world_from_template(
        &self,
        request: CreateWorldFromTemplateRequest,
    ) -> ApiFuture<'_, CreateWorldFromTemplateResult> {
        Box::pin(async move {
            self.send_json_once(
                Method::POST,
                format!("{API_PREFIX}/worlds/from-template"),
                &request,
            )
            .await
        })
    }
}

impl ActionService for LoomClient {
    fn invoke(&self, request: ActionRequest) -> ApiFuture<'_, ExecutionResult> {
        Box::pin(async move {
            self.send_json_once(Method::POST, format!("{API_PREFIX}/actions"), &request)
                .await
        })
    }
}

impl IngressService for LoomClient {
    fn submit_ingress(&self, request: IngressEnvelope) -> ApiFuture<'_, IngressAcceptance> {
        Box::pin(async move { self.send_ingress(&request).await })
    }

    fn ingress_status(&self, ingress_id: IngressId) -> ApiFuture<'_, IngressStatusRecord> {
        Box::pin(self.send_empty(
            Method::GET,
            format!("{API_PREFIX}/ingress/{}", path_segment(ingress_id.as_str())),
        ))
    }
}

impl TimelineService for LoomClient {
    fn inspect_timeline(&self, target: TimelineTarget) -> ApiFuture<'_, TimelineSnapshot> {
        Box::pin(async move {
            self.send_json_once(
                Method::POST,
                format!("{API_PREFIX}/timelines/inspect"),
                &target,
            )
            .await
        })
    }

    fn fork(&self, request: ForkTimelineRequest) -> ApiFuture<'_, ForkTimelineResult> {
        Box::pin(async move {
            self.send_json_once(
                Method::POST,
                format!("{API_PREFIX}/timelines/fork"),
                &request,
            )
            .await
        })
    }
}

impl QueryService for LoomClient {
    fn get_facet(&self, query: FacetQuery) -> ApiFuture<'_, Option<FacetSnapshot>> {
        Box::pin(async move {
            self.send_json_once(Method::POST, format!("{API_PREFIX}/query/facet"), &query)
                .await
        })
    }
}

impl HistoryService for LoomClient {
    fn list_events(&self, query: EventQuery) -> ApiFuture<'_, Vec<CommittedEvent>> {
        Box::pin(async move { Ok(self.list_events_page(query).await?.events) })
    }

    fn list_events_page(&self, query: EventQuery) -> ApiFuture<'_, EventPage> {
        Box::pin(async move {
            self.send_json_once(Method::POST, format!("{API_PREFIX}/history/events"), &query)
                .await
        })
    }

    fn get_event(&self, event_ref: EventRef) -> ApiFuture<'_, Option<CommittedEvent>> {
        Box::pin(async move {
            self.send_json_once(
                Method::POST,
                format!("{API_PREFIX}/history/event"),
                &event_ref,
            )
            .await
        })
    }

    fn direct_causes(&self, event_ref: EventRef) -> ApiFuture<'_, Vec<EventRef>> {
        Box::pin(async move {
            self.send_json_once(
                Method::POST,
                format!("{API_PREFIX}/history/causes"),
                &event_ref,
            )
            .await
        })
    }

    fn direct_effects(&self, event_ref: EventRef) -> ApiFuture<'_, Vec<EventRef>> {
        Box::pin(async move {
            self.send_json_once(
                Method::POST,
                format!("{API_PREFIX}/history/effects"),
                &event_ref,
            )
            .await
        })
    }

    fn causal_walk(&self, query: CausalQuery) -> ApiFuture<'_, CausalTraversal> {
        Box::pin(async move {
            self.send_json_once(
                Method::POST,
                format!("{API_PREFIX}/history/causal-walk"),
                &query,
            )
            .await
        })
    }

    fn entity_trajectory(
        &self,
        query: loom_api::EntityTrajectoryQuery,
    ) -> ApiFuture<'_, TrajectoryPage> {
        Box::pin(async move {
            self.send_json_once(
                Method::POST,
                format!("{API_PREFIX}/history/entity-trajectory"),
                &query,
            )
            .await
        })
    }

    fn relationship_trajectory(
        &self,
        query: RelationshipTrajectoryQuery,
    ) -> ApiFuture<'_, TrajectoryPage> {
        Box::pin(async move {
            self.send_json_once(
                Method::POST,
                format!("{API_PREFIX}/history/relationship-trajectory"),
                &query,
            )
            .await
        })
    }
}

impl SubscriptionService for LoomClient {
    fn subscribe(&self, request: SubscriptionRequest) -> ApiFuture<'_, SubscriptionResult> {
        Box::pin(self.subscribe_http(request))
    }
}

impl AdminService for LoomClient {
    fn active_runtime_revision(&self) -> AdminFuture<'_, Option<AdminRuntimeRevisionSelection>> {
        Box::pin(self.send_empty(
            Method::GET,
            format!("{ADMIN_API_PREFIX}/runtime-revisions/active"),
        ))
    }

    fn list_runtime_revisions(&self) -> AdminFuture<'_, Vec<AdminRuntimeRevision>> {
        Box::pin(self.send_empty(Method::GET, format!("{ADMIN_API_PREFIX}/runtime-revisions")))
    }

    fn get_runtime_revision(
        &self,
        request: AdminRuntimeRevisionRequest,
    ) -> AdminFuture<'_, AdminRuntimeRevision> {
        Box::pin(async move {
            self.send_json_once(
                Method::POST,
                format!("{ADMIN_API_PREFIX}/runtime-revisions/get"),
                &request,
            )
            .await
        })
    }

    fn activate_runtime_revision(
        &self,
        request: AdminActivateRuntimeRevisionRequest,
    ) -> AdminFuture<'_, AdminRuntimeRevisionSelection> {
        Box::pin(async move {
            self.send_json_once(
                Method::POST,
                format!("{ADMIN_API_PREFIX}/runtime-revisions/activate"),
                &request,
            )
            .await
        })
    }

    fn list_execution_sessions(&self) -> AdminFuture<'_, Vec<AdminExecutionSession>> {
        Box::pin(self.send_empty(Method::GET, format!("{ADMIN_API_PREFIX}/sessions")))
    }

    fn get_execution_session(
        &self,
        request: AdminExecutionSessionRequest,
    ) -> AdminFuture<'_, AdminExecutionSession> {
        Box::pin(async move {
            self.send_json_once(
                Method::POST,
                format!("{ADMIN_API_PREFIX}/sessions/get"),
                &request,
            )
            .await
        })
    }

    fn session_for_event(&self, event_ref: EventRef) -> AdminFuture<'_, AdminEventSessionLookup> {
        Box::pin(async move {
            self.send_json_once(
                Method::POST,
                format!("{ADMIN_API_PREFIX}/sessions/event"),
                &event_ref,
            )
            .await
        })
    }

    fn timeline_logical_status(
        &self,
        target: TimelineTarget,
    ) -> AdminFuture<'_, AdminTimelineLogicalStatus> {
        Box::pin(async move {
            self.send_json_once(
                Method::POST,
                format!("{ADMIN_API_PREFIX}/timelines/status"),
                &target,
            )
            .await
        })
    }

    fn missing_implementation(
        &self,
        request: AdminMissingImplementationRequest,
    ) -> AdminFuture<'_, Option<AdminMissingImplementationBlock>> {
        Box::pin(async move {
            self.send_json_once(
                Method::POST,
                format!("{ADMIN_API_PREFIX}/timelines/missing-implementation"),
                &request,
            )
            .await
        })
    }

    fn terminalize_work(
        &self,
        request: AdminTerminalizeWorkRequest,
    ) -> AdminFuture<'_, AdminTerminalizeWorkResult> {
        Box::pin(async move {
            self.send_json_once(
                Method::POST,
                format!("{ADMIN_API_PREFIX}/work/terminalize"),
                &request,
            )
            .await
        })
    }

    fn schedule_agency_wake(
        &self,
        request: AdminScheduleAgencyWakeRequest,
    ) -> AdminFuture<'_, AdminScheduleAgencyWakeResult> {
        Box::pin(async move {
            self.send_json_once(
                Method::POST,
                format!("{ADMIN_API_PREFIX}/work/agency-wake/schedule"),
                &request,
            )
            .await
        })
    }

    fn advance_world_time(
        &self,
        request: AdminAdvanceWorldTimeRequest,
    ) -> AdminFuture<'_, AdminAdvanceWorldTimeResult> {
        Box::pin(async move {
            self.send_json_once(
                Method::POST,
                format!("{ADMIN_API_PREFIX}/world-time/advance"),
                &request,
            )
            .await
        })
    }
}

impl CatalogService for LoomClient {
    fn catalog(&self) -> ApiResult<CatalogSnapshot> {
        let client = self.clone();
        std::thread::Builder::new()
            .name("loom-client-catalog".to_owned())
            .spawn(move || {
                let runtime = tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .map_err(|_| ApiError::unavailable("Loom catalog runtime was unavailable"))?;
                runtime.block_on(
                    client.send_empty::<CatalogSnapshot>(
                        Method::GET,
                        format!("{API_PREFIX}/catalog"),
                    ),
                )
            })
            .map_err(|_| ApiError::unavailable("Loom catalog worker was unavailable"))?
            .join()
            .map_err(|_| ApiError::unavailable("Loom catalog worker was unavailable"))?
    }

    fn catalog_for_world(&self, world_id: WorldId) -> ApiFuture<'_, CatalogSnapshot> {
        Box::pin(self.send_empty(
            Method::GET,
            format!(
                "{API_PREFIX}/catalog/worlds/{}",
                path_segment(&world_id.to_string())
            ),
        ))
    }
}

fn is_retryable_ingress_error<T>(result: &ApiResult<T>) -> bool {
    matches!(
        result,
        Err(ApiError {
            code: ApiErrorCode::Unavailable,
            ..
        })
    )
}

fn path_segment(value: &str) -> String {
    utf8_percent_encode(value, NON_ALPHANUMERIC).to_string()
}

#[derive(Debug, Deserialize)]
struct WireError {
    code: String,
    message: String,
}

fn decode_http_response<T>(status: StatusCode, bytes: &[u8]) -> ApiResult<T>
where
    T: DeserializeOwned,
{
    if !status.is_success() {
        return Err(decode_http_error(status, bytes));
    }
    decode_body(bytes)
}

fn decode_ingress_response(bytes: &[u8]) -> ApiResult<IngressAcceptance> {
    match serde_json::from_slice(bytes) {
        Ok(acceptance) => Ok(acceptance),
        Err(_) => Err(decode_http_error(StatusCode::CONFLICT, bytes)),
    }
}

fn decode_http_error(status: StatusCode, bytes: &[u8]) -> ApiError {
    if let Ok(error) = serde_json::from_slice::<WireError>(bytes) {
        return ApiError::new(parse_error_code(&error.code), error.message);
    }
    match status {
        StatusCode::BAD_REQUEST => ApiError::invalid_request("Loom rejected the HTTP request"),
        StatusCode::NOT_FOUND => ApiError::not_found("Loom resource was not found"),
        StatusCode::CONFLICT => ApiError::conflict("Loom request conflicted with current state"),
        StatusCode::TOO_MANY_REQUESTS | StatusCode::SERVICE_UNAVAILABLE => {
            ApiError::unavailable("Loom service is temporarily unavailable")
        }
        _ => ApiError::internal("Loom HTTP request failed"),
    }
}

fn parse_error_code(code: &str) -> ApiErrorCode {
    match code {
        "invalid_request" | "InvalidRequest" => ApiErrorCode::InvalidRequest,
        "not_found" | "NotFound" => ApiErrorCode::NotFound,
        "conflict" | "Conflict" => ApiErrorCode::Conflict,
        "unavailable" | "Unavailable" => ApiErrorCode::Unavailable,
        "unauthorized" | "Unauthorized" => ApiErrorCode::Unauthorized,
        "forbidden" | "Forbidden" => ApiErrorCode::Forbidden,
        _ => ApiErrorCode::Internal,
    }
}

fn decode_body<T>(bytes: &[u8]) -> ApiResult<T>
where
    T: DeserializeOwned,
{
    serde_json::from_slice(bytes)
        .map_err(|_| ApiError::unavailable("Loom response was not valid API JSON"))
}

async fn read_async_body(response: reqwest::Response, max_bytes: usize) -> ApiResult<Vec<u8>> {
    if response
        .content_length()
        .is_some_and(|length| length > max_bytes as u64)
    {
        return Err(ApiError::unavailable(
            "Loom response exceeds the client byte limit",
        ));
    }
    let mut bytes = Vec::new();
    let mut stream = response.bytes_stream();
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|_| ApiError::unavailable("Loom response could not be read"))?;
        if bytes.len().saturating_add(chunk.len()) > max_bytes {
            return Err(ApiError::unavailable(
                "Loom response exceeds the client byte limit",
            ));
        }
        bytes.extend_from_slice(&chunk);
    }
    Ok(bytes)
}

#[derive(Debug)]
struct SseFrame {
    event: String,
    id: Option<String>,
    data: String,
}

#[derive(Debug, Deserialize)]
struct SsePageMetadata {
    next_cursor: Option<ChangeFeedCursor>,
    has_more: bool,
}

fn decode_sse_subscription(bytes: &[u8]) -> ApiResult<SubscriptionResult> {
    let text = str::from_utf8(bytes)
        .map_err(|_| ApiError::unavailable("Loom SSE response was not valid UTF-8"))?;
    let frames = parse_sse_frames(text)?;
    let mut events = Vec::new();
    let mut control = None;
    let mut page_metadata = None;
    for frame in frames {
        match frame.event.as_str() {
            "change" => {
                let event = decode_body::<CommittedEvent>(frame.data.as_bytes())?;
                if let Some(id) = frame.id {
                    let sequence = id.parse::<u64>().map_err(|_| {
                        ApiError::unavailable("Loom SSE change ID was not an EventSeq")
                    })?;
                    if sequence != event.sequence.value() {
                        return Err(ApiError::unavailable(
                            "Loom SSE change ID did not match the committed Event",
                        ));
                    }
                }
                events.push(event);
            }
            "page" => {
                page_metadata = Some(decode_body::<SsePageMetadata>(frame.data.as_bytes())?);
            }
            "resume" => {
                control = Some(SubscriptionResult::Resumed(decode_body::<
                    SubscriptionResume,
                >(
                    frame.data.as_bytes()
                )?));
            }
            "reconnect" => {
                control = Some(SubscriptionResult::Reconnect(decode_body::<
                    SubscriptionReconnect,
                >(
                    frame.data.as_bytes()
                )?));
            }
            "end" => {
                control = Some(SubscriptionResult::Ended(decode_body::<SubscriptionEnd>(
                    frame.data.as_bytes(),
                )?));
            }
            other => {
                return Err(ApiError::unavailable(format!(
                    "unknown Loom SSE event: {other}"
                )));
            }
        }
    }
    if !events.is_empty() || page_metadata.is_some() {
        let metadata = page_metadata.ok_or_else(|| {
            ApiError::unavailable("Loom SSE response omitted change-feed page metadata")
        })?;
        return Ok(SubscriptionResult::Events(ChangeFeedPage {
            events,
            next_cursor: metadata.next_cursor,
            has_more: metadata.has_more,
        }));
    }
    control
        .ok_or_else(|| ApiError::unavailable("Loom SSE response contained no subscription result"))
}

fn parse_sse_frames(text: &str) -> ApiResult<Vec<SseFrame>> {
    let mut frames = Vec::new();
    let mut event = None;
    let mut id = None;
    let mut data = String::new();
    for line in text.lines() {
        let line = line.strip_suffix('\r').unwrap_or(line);
        if line.is_empty() {
            if event.is_some() || !data.is_empty() {
                frames.push(SseFrame {
                    event: event.take().unwrap_or_else(|| "message".to_owned()),
                    id: id.take(),
                    data: data.strip_suffix('\n').unwrap_or(&data).to_owned(),
                });
                data.clear();
            }
            continue;
        }
        if line.starts_with(':') {
            continue;
        }
        let (field, value) = line.split_once(':').map_or((line, ""), |(field, value)| {
            (field, value.strip_prefix(' ').unwrap_or(value))
        });
        match field {
            "event" => event = Some(value.to_owned()),
            "id" => id = Some(value.to_owned()),
            "data" => {
                data.push_str(value);
                data.push('\n');
            }
            _ => {}
        }
    }
    if event.is_some() || !data.is_empty() {
        frames.push(SseFrame {
            event: event.unwrap_or_else(|| "message".to_owned()),
            id,
            data: data.strip_suffix('\n').unwrap_or(&data).to_owned(),
        });
    }
    if frames.is_empty() {
        return Err(ApiError::unavailable(
            "Loom SSE response contained no frames",
        ));
    }
    Ok(frames)
}

#[cfg(test)]
mod tests {
    use std::str::FromStr;

    use loom_api::{
        ApiErrorCode, ChangeFeedCursor, EventId, EventSeq, EventTypeId, SubscriptionResult,
        TimelineId, TimelineTarget, WorldId,
    };
    use serde_json::json;

    use super::{
        decode_http_error, decode_ingress_response, decode_sse_subscription, parse_sse_frames,
    };

    fn target() -> TimelineTarget {
        TimelineTarget::new(
            WorldId::from_str("00000000-0000-0000-0000-000000000001").expect("World ID"),
            TimelineId::from_str("00000000-0000-0000-0000-000000000002").expect("Timeline ID"),
        )
    }

    #[test]
    fn typed_boundary_errors_preserve_public_category() {
        let error = decode_http_error(
            reqwest::StatusCode::CONFLICT,
            br#"{"code":"conflict","message":"stale timeline"}"#,
        );
        assert_eq!(error.code, ApiErrorCode::Conflict);
        assert_eq!(error.message, "stale timeline");
    }

    #[test]
    fn generic_conflict_errors_do_not_decode_as_unavailable_ingress_results() {
        let error = decode_ingress_response(br#"{"code":"conflict","message":"stale"}"#)
            .expect_err("generic conflict is not an Ingress acceptance");
        assert_eq!(error.code, ApiErrorCode::Conflict);
        assert_eq!(error.message, "stale");
    }

    #[test]
    fn sse_change_frames_round_trip_as_a_resumable_page() {
        let event = json!({
            "id": EventId::from_str("00000000-0000-0000-0000-000000000003").expect("Event ID"),
            "timeline_id": target().timeline_id,
            "sequence": EventSeq::new(7),
            "event_type": EventTypeId::new("example.created"),
            "schema_revision": 1,
            "occurred_at": 0,
            "participants": [],
            "relationship_refs": [],
            "causal_links": [],
            "payload": {},
            "effects": []
        });
        let payload = serde_json::to_string(&event).expect("event JSON");
        let metadata = serde_json::json!({
            "next_cursor": ChangeFeedCursor::after(target(), EventSeq::new(7)),
            "has_more": true
        });
        let wire = format!("event: change\nid: 7\ndata: {payload}\n\n")
            + &format!("event: page\ndata: {metadata}\n\n");
        let result = decode_sse_subscription(wire.as_bytes()).expect("subscription");
        let SubscriptionResult::Events(page) = result else {
            panic!("expected change page");
        };
        assert_eq!(page.events.len(), 1);
        assert_eq!(
            page.next_cursor,
            Some(ChangeFeedCursor::after(target(), EventSeq::new(7)))
        );
        assert!(page.has_more);
    }

    #[test]
    fn keep_alive_comments_do_not_become_subscription_frames() {
        let frames = parse_sse_frames(": keep-alive\n\n").expect_err("only comments are empty");
        assert_eq!(frames.code, ApiErrorCode::Unavailable);
    }
}
