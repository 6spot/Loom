//! Axum router: public/Studio namespaces, auth enforcement, proxying, web front.
//!
//! The web front is the C1-T9 React/TypeScript/Vite build (one build serves
//! public Chronicle routes and `/studio/*`; the Studio shell itself is
//! public and every privileged Studio API stays server-auth-enforced).

use std::sync::Arc;

use axum::body::Body;
use axum::extract::{DefaultBodyLimit, OriginalUri, Path, State};
use axum::http::{header, HeaderValue, Method, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::any;
use axum::{Json, Router};
use serde_json::json;

use crate::auth::{credentials_match, parse_basic_credentials};
use crate::config::AdminCredentials;
use crate::error::TypedError;
use crate::static_assets::resolve_web_path;
use crate::upstream::{
    fetch_upstream, forward_upstream, probe_upstream, UpstreamError, UpstreamResponse,
    UpstreamTarget, MAX_PROXY_BODY_BYTES,
};

/// Shared server state (configuration minus bind address).
#[derive(Debug, Clone)]
pub struct AppState {
    /// Single administrator credentials, when Studio auth is configured.
    pub admin: Option<AdminCredentials>,
    /// C0 Python read-model upstream.
    pub upstream: UpstreamTarget,
}

/// Build the full Chronicle router with state provided.
pub fn build_router(state: Arc<AppState>) -> Router {
    let studio = Router::new()
        .route("/status", any(studio_status))
        .route("/documents", any(studio_documents))
        .route("/documents/{*rest}", any(studio_documents))
        .route("/jobs", any(studio_jobs))
        .route("/jobs/{*rest}", any(studio_jobs))
        .fallback(studio_not_found);
    Router::new()
        .route("/healthz", any(health))
        .route("/api/v1/public/timeline", any(public_timeline))
        .route("/api/v1/public/search", any(public_search))
        .route("/api/v1/public/events/{id}", any(public_event))
        .route("/api/v1/public/entities/{id}", any(public_entity))
        .route("/v0/timeline", any(legacy_proxy))
        .route("/v0/search", any(legacy_proxy))
        .route("/v0/events/{id}", any(legacy_proxy))
        .route("/v0/entities/{id}", any(legacy_proxy))
        .nest("/api/v1/studio", studio)
        .fallback(fallback)
        // The 2 MiB default body cap is lifted so Studio uploads can reach
        // the proxy's own explicit limit (typed 413); every other route
        // either ignores bodies or enforces its own bound.
        .layer(DefaultBodyLimit::disable())
        .with_state(state)
}

fn log_request(method: &str, path: &str, status: u16) {
    // Secret-safe access log: method, path without query, status only.
    // No headers, cookies, query values, or credential material.
    let path_only = path.split('?').next().unwrap_or(path);
    println!(
        "{{\"service\":\"chronicle-server\",\"method\":{method:?},\"path\":{path_only:?},\"status\":{status}}}"
    );
}

async fn health(request: axum::http::Request<Body>) -> Response {
    if request.method() != axum::http::Method::GET {
        let response = TypedError::method_not_allowed().into_response();
        log_request("OTHER", "/healthz", 405);
        return response;
    }
    log_request("GET", "/healthz", 200);
    Json(json!({"status": "ok"})).into_response()
}

async fn public_timeline(
    State(state): State<Arc<AppState>>,
    OriginalUri(uri): OriginalUri,
    request: axum::http::Request<Body>,
) -> Response {
    proxy_public(
        &state,
        request.method().clone(),
        "/v0/timeline".to_string(),
        uri.query().map(str::to_string),
    )
    .await
}

async fn public_search(
    State(state): State<Arc<AppState>>,
    OriginalUri(uri): OriginalUri,
    request: axum::http::Request<Body>,
) -> Response {
    proxy_public(
        &state,
        request.method().clone(),
        "/v0/search".to_string(),
        uri.query().map(str::to_string),
    )
    .await
}

async fn public_event(
    State(state): State<Arc<AppState>>,
    OriginalUri(uri): OriginalUri,
    Path(id): Path<String>,
    request: axum::http::Request<Body>,
) -> Response {
    match validated_id(&id) {
        Some(valid) => {
            proxy_public(
                &state,
                request.method().clone(),
                format!("/v0/events/{valid}"),
                uri.query().map(str::to_string),
            )
            .await
        }
        None => TypedError::not_found("route not found").into_response(),
    }
}

async fn public_entity(
    State(state): State<Arc<AppState>>,
    OriginalUri(uri): OriginalUri,
    Path(id): Path<String>,
    request: axum::http::Request<Body>,
) -> Response {
    match validated_id(&id) {
        Some(valid) => {
            proxy_public(
                &state,
                request.method().clone(),
                format!("/v0/entities/{valid}"),
                uri.query().map(str::to_string),
            )
            .await
        }
        None => TypedError::not_found("route not found").into_response(),
    }
}

/// Legacy C0 `/v0/*` compat: same handler, same upstream path.
async fn legacy_proxy(
    State(state): State<Arc<AppState>>,
    OriginalUri(uri): OriginalUri,
    request: axum::http::Request<Body>,
) -> Response {
    let path = uri.path().to_string();
    let query = uri.query().map(str::to_string);
    let method = request.method().clone();
    proxy_public(&state, method, path, query).await
}

fn validated_id(id: &str) -> Option<&str> {
    if id.is_empty() || id.contains('/') || id.contains(char::is_control) {
        return None;
    }
    Some(id)
}

/// Forward one public read to the C0 upstream. Only owned values cross the
/// await boundary (`&Request<Body>` futures are not `Handler`-compatible).
async fn proxy_public(
    state: &AppState,
    method: axum::http::Method,
    upstream_path: String,
    query: Option<String>,
) -> Response {
    if method != axum::http::Method::GET {
        let response = TypedError::method_not_allowed().into_response();
        log_request("OTHER", &upstream_path, 405);
        return response;
    }
    let mut target = upstream_path.clone();
    if let Some(query) = query.as_deref() {
        target.push('?');
        target.push_str(query);
    }
    match fetch_upstream(&state.upstream, &target).await {
        Ok(upstream) => render_proxied(upstream, "GET", &upstream_path),
        Err(err) => render_upstream_error(err, "GET", &upstream_path),
    }
}

/// Render a proxied upstream response byte-for-byte (status, content type,
/// body), preserving C0 read semantics and Studio document payloads.
fn render_proxied(upstream: UpstreamResponse, log_method: &str, log_path: &str) -> Response {
    let status = StatusCode::from_u16(upstream.status).unwrap_or(StatusCode::BAD_GATEWAY);
    let content_type = upstream
        .content_type
        .unwrap_or_else(|| "application/json; charset=utf-8".to_string());
    log_request(log_method, log_path, status.as_u16());
    let content_type_value: HeaderValue = content_type
        .parse()
        .unwrap_or_else(|_| HeaderValue::from_static("application/json; charset=utf-8"));
    Response::builder()
        .status(status)
        .header(header::CONTENT_TYPE, content_type_value)
        .header("x-content-type-options", "nosniff")
        .body(Body::from(upstream.body))
        .expect("proxied response uses validated headers")
}

/// Map an upstream failure onto the typed error contract.
fn render_upstream_error(err: UpstreamError, log_method: &str, log_path: &str) -> Response {
    match err {
        UpstreamError::BadResponse(_) => {
            log_request(log_method, log_path, 502);
            TypedError::upstream_bad_response().into_response()
        }
        UpstreamError::Unreachable(_) | UpstreamError::TimedOut => {
            log_request(log_method, log_path, 503);
            TypedError::upstream_unavailable().into_response()
        }
    }
}

/// Studio authorization outcome. Kept small: callers map it to a response so
/// the `WWW-Authenticate` challenge is attached in exactly one place.
enum AuthDecision {
    /// Request carries valid administrator credentials.
    Authorized(String),
    /// Credentials missing or invalid (401 + challenge).
    Unauthorized,
    /// Studio auth was never configured (fail-closed 503).
    Unconfigured,
}

/// Authenticate one Studio request. Returns the admin username on success.
fn require_admin(state: &AppState, request: &axum::http::Request<Body>) -> AuthDecision {
    let Some(admin) = state.admin.as_ref() else {
        return AuthDecision::Unconfigured;
    };
    let authorized = request
        .headers()
        .get(header::AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
        .and_then(parse_basic_credentials)
        .is_some_and(|(username, password)| credentials_match(admin, &username, &password));
    if authorized {
        AuthDecision::Authorized(admin.username.clone())
    } else {
        AuthDecision::Unauthorized
    }
}

/// Render an [`AuthDecision`] denial as a response.
fn auth_denied(decision: AuthDecision) -> Response {
    match decision {
        AuthDecision::Authorized(_) => TypedError::not_found("route not found").into_response(),
        AuthDecision::Unauthorized => {
            let mut response = TypedError::unauthorized().into_response();
            response.headers_mut().insert(
                header::WWW_AUTHENTICATE,
                HeaderValue::from_static("Basic realm=\"chronicle-studio\""),
            );
            response
        }
        AuthDecision::Unconfigured => TypedError::studio_auth_unconfigured().into_response(),
    }
}

/// Studio document operations (C1-T3): create logical Documents and upload
/// immutable revisions. Authenticated here; persistence lives in the
/// internal Python sidecar, which this handler forwards to byte-for-byte.
async fn studio_documents(
    State(state): State<Arc<AppState>>,
    request: axum::http::Request<Body>,
) -> Response {
    // Authorization first: the Studio namespace never reveals method routing
    // or document existence to unauthenticated callers.
    match require_admin(&state, &request) {
        AuthDecision::Authorized(_) => {}
        denial => return auth_denied(denial),
    }
    let path = request.uri().path().to_string();
    // `nest("/api/v1/studio", ...)` strips the mount prefix before the
    // inner router runs, so this handler sees `/documents...` while the
    // sidecar expects the full Studio path. Re-attach the prefix for the
    // proxied request; anything else here is unreachable routing.
    if path != "/documents" && !path.starts_with("/documents/") {
        log_request("STUDIO", &path, 404);
        return TypedError::not_found("route not found").into_response();
    }
    let upstream_path = format!("/api/v1/studio{path}");
    proxy_studio(&state, request, &upstream_path).await
}

/// Forward one authenticated Studio request (documents or jobs) to the sidecar.
async fn proxy_studio(
    state: &AppState,
    request: axum::http::Request<Body>,
    upstream_path: &str,
) -> Response {
    let method = request.method().clone();
    if method != Method::GET && method != Method::POST {
        return TypedError::studio_method_not_allowed().into_response();
    }
    let query = request.uri().query().map(str::to_string);
    let content_type = request
        .headers()
        .get(header::CONTENT_TYPE)
        .and_then(|value| value.to_str().ok())
        .map(str::to_string);
    let content_type_valid = content_type.as_deref().is_none_or(|value| {
        !value.contains(['\r', '\n'])
            && value
                .bytes()
                .all(|byte| byte.is_ascii_graphic() || byte == b' ')
    });
    if !content_type_valid {
        return TypedError::bad_request("invalid Content-Type").into_response();
    }
    let (_, body) = request.into_parts();
    let body_bytes = match axum::body::to_bytes(body, MAX_PROXY_BODY_BYTES).await {
        Ok(bytes) => bytes.to_vec(),
        Err(_) => return TypedError::payload_too_large().into_response(),
    };
    let mut target = upstream_path.to_string();
    if let Some(query) = query.as_deref() {
        target.push('?');
        target.push_str(query);
    }
    let log_method = method.as_str().to_string();
    match forward_upstream(
        &state.upstream,
        method.as_str(),
        &target,
        content_type.as_deref(),
        &body_bytes,
    )
    .await
    {
        Ok(upstream) => render_proxied(upstream, &log_method, upstream_path),
        Err(err) => render_upstream_error(err, &log_method, upstream_path),
    }
}

/// Studio ingestion-job lifecycle operations (C1-T4): queue, inspect,
/// retry, resume, cancel. Authenticated here; the durable transitions live
/// in the control-plane contract and execute in the internal Python
/// sidecar, which this handler forwards to byte-for-byte. Lifecycle
/// authority stays in this server's authenticated namespace plus the
/// control-plane state machine; the sidecar never invents a transition.
async fn studio_jobs(
    State(state): State<Arc<AppState>>,
    request: axum::http::Request<Body>,
) -> Response {
    // Authorization first: the Studio namespace never reveals method routing
    // or job existence to unauthenticated callers.
    match require_admin(&state, &request) {
        AuthDecision::Authorized(_) => {}
        denial => return auth_denied(denial),
    }
    let path = request.uri().path().to_string();
    // `nest("/api/v1/studio", ...)` strips the mount prefix before the
    // inner router runs, so this handler sees `/jobs...` while the
    // sidecar expects the full Studio path. Re-attach the prefix for the
    // proxied request; anything else here is unreachable routing.
    if path != "/jobs" && !path.starts_with("/jobs/") {
        log_request("STUDIO", &path, 404);
        return TypedError::not_found("route not found").into_response();
    }
    let upstream_path = format!("/api/v1/studio{path}");
    proxy_studio(&state, request, &upstream_path).await
}

async fn studio_status(
    State(state): State<Arc<AppState>>,
    request: axum::http::Request<Body>,
) -> Response {
    // Authorization first: the Studio namespace never reveals method routing
    // to unauthenticated callers.
    let admin_user = match require_admin(&state, &request) {
        AuthDecision::Authorized(username) => username,
        denial => return auth_denied(denial),
    };
    if request.method() != axum::http::Method::GET {
        return TypedError::method_not_allowed().into_response();
    }
    let reachable = probe_upstream(&state.upstream).await;
    log_request("GET", "/api/v1/studio/status", 200);
    Json(json!({
        "schema": "chronicle.studio-status",
        "version": "0.1",
        "admin_user": admin_user,
        "upstream": {"reachable": reachable},
    }))
    .into_response()
}

async fn studio_not_found(
    State(state): State<Arc<AppState>>,
    request: axum::http::Request<Body>,
) -> Response {
    // The Studio namespace is privileged as a whole: unknown Studio paths
    // still require authentication before revealing existence.
    let path = request.uri().path().to_string();
    match require_admin(&state, &request) {
        AuthDecision::Authorized(_) => {
            log_request("STUDIO", &path, 404);
            TypedError::not_found("route not found").into_response()
        }
        denial => auth_denied(denial),
    }
}

async fn fallback(
    State(state): State<Arc<AppState>>,
    request: axum::http::Request<Body>,
) -> Response {
    let path = request.uri().path().to_string();
    if path == "/healthz"
        || path.starts_with("/api/")
        || path.starts_with("/v0/")
        || path.starts_with("/api")
        || path == "/v0"
    {
        // API-shaped paths never fall through to the browser shell.
        if request.method() != axum::http::Method::GET
            && (path == "/healthz"
                || path.starts_with("/v0/")
                || path.starts_with("/api/v1/public/"))
        {
            log_request("OTHER", &path, 405);
            return TypedError::method_not_allowed().into_response();
        }
        // Unknown Studio paths are auth-gated, not anonymously enumerable.
        if path.starts_with("/api/v1/studio") {
            return match require_admin(&state, &request) {
                AuthDecision::Authorized(_) => {
                    log_request("STUDIO", &path, 404);
                    TypedError::not_found("route not found").into_response()
                }
                denial => auth_denied(denial),
            };
        }
        log_request("OTHER", &path, 404);
        return TypedError::not_found("route not found").into_response();
    }
    if request.method() != axum::http::Method::GET {
        return (
            StatusCode::METHOD_NOT_ALLOWED,
            [(
                header::CONTENT_TYPE,
                HeaderValue::from_static("text/plain; charset=utf-8"),
            )],
            "method not allowed\n",
        )
            .into_response();
    }
    match resolve_web_path(&path) {
        Some((content_type, body)) => {
            log_request("GET", &path, 200);
            let content_type_value: HeaderValue = content_type
                .parse()
                .unwrap_or_else(|_| HeaderValue::from_static("text/html; charset=utf-8"));
            Response::builder()
                .status(StatusCode::OK)
                .header(header::CONTENT_TYPE, content_type_value)
                .header("x-content-type-options", "nosniff")
                .body(Body::from(body.to_vec()))
                .expect("static response uses validated headers")
        }
        None => {
            log_request("GET", &path, 404);
            (
                StatusCode::NOT_FOUND,
                [(
                    header::CONTENT_TYPE,
                    HeaderValue::from_static("text/plain; charset=utf-8"),
                )],
                "not found\n",
            )
                .into_response()
        }
    }
}
