//! Chronicle C1-T2 application server library.
//!
//! The server owns the Chronicle HTTP boundary for C1: distinct public and
//! Studio API namespaces, single-administrator Studio authentication from
//! environment configuration, health/error behavior, and the same-origin web
//! front. Historical reads stay on the proven C0 Python read model behind
//! `CHRONICLE_UPSTREAM_URL`, so this crate introduces no second historical
//! read authority and takes no Loom Runtime/Storage authority.
//!
//! Governance: no `loom-*` dependency, no SQLx/PostgreSQL driver dependency,
//! no inline SQL. Persistence lives in the registered Chronicle product
//! persistence root (`apps/chronicle/persistence/`) behind
//! `CHRONICLE_DATABASE_URL` (Architecture Amendment 0006).

#![forbid(unsafe_code)]

use std::sync::Arc;

use axum::body::Body;
use axum::extract::OriginalUri;
use axum::http::{header, HeaderValue, Method, Request, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::any;
use axum::Router;

pub mod app;
pub mod auth;
pub mod config;
pub mod error;
pub mod static_assets;
pub mod upstream;

pub use app::AppState;
pub use auth::{credentials_match, parse_basic_credentials};
pub use config::{AdminCredentials, ChronicleConfig};
pub use error::{error_body, TypedError};
pub use upstream::{fetch_upstream, forward_upstream, UpstreamTarget, MAX_PROXY_BODY_BYTES};

/// Build the Chronicle router and add C1-T14's read-only Coverage aliases.
///
/// `app::build_router` remains the stable C1-T2/T9 composition root. Coverage
/// is deliberately a thin forwarding surface over the same Python read-model
/// upstream, so the Rust server still owns auth/namespace policy without
/// acquiring PostgreSQL or historical-data authority.
pub fn build_router(state: Arc<AppState>) -> Router {
    let public_state = state.clone();
    let legacy_state = state.clone();
    let studio_state = state.clone();

    app::build_router(state)
        .route(
            "/api/v1/public/coverage",
            any(move |OriginalUri(uri): OriginalUri, request: Request<Body>| {
                let state = public_state.clone();
                async move { coverage_proxy(&state, request.method(), uri.query()).await }
            }),
        )
        .route(
            "/v0/coverage",
            any(move |OriginalUri(uri): OriginalUri, request: Request<Body>| {
                let state = legacy_state.clone();
                async move { coverage_proxy(&state, request.method(), uri.query()).await }
            }),
        )
        .route(
            "/api/v1/studio/coverage",
            any(move |OriginalUri(uri): OriginalUri, request: Request<Body>| {
                let state = studio_state.clone();
                async move {
                    if let Some(response) = coverage_admin_rejection(&state, &request) {
                        response
                    } else {
                        coverage_proxy(&state, request.method(), uri.query()).await
                    }
                }
            }),
        )
}

fn coverage_admin_rejection(state: &AppState, request: &Request<Body>) -> Option<Response> {
    let Some(admin) = state.admin.as_ref() else {
        return Some(TypedError::studio_auth_unconfigured().into_response());
    };
    let authorized = request
        .headers()
        .get(header::AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
        .and_then(parse_basic_credentials)
        .is_some_and(|(username, password)| credentials_match(admin, &username, &password));
    if authorized {
        None
    } else {
        let mut response = TypedError::unauthorized().into_response();
        response.headers_mut().insert(
            header::WWW_AUTHENTICATE,
            HeaderValue::from_static("Basic realm=\"chronicle-studio\""),
        );
        Some(response)
    }
}

async fn coverage_proxy(state: &AppState, method: &Method, query: Option<&str>) -> Response {
    if method != Method::GET {
        return TypedError::method_not_allowed().into_response();
    }
    let mut target = "/v0/coverage".to_string();
    if let Some(query) = query {
        target.push('?');
        target.push_str(query);
    }
    match fetch_upstream(&state.upstream, &target).await {
        Ok(upstream) => {
            let status = StatusCode::from_u16(upstream.status).unwrap_or(StatusCode::BAD_GATEWAY);
            let content_type = upstream
                .content_type
                .unwrap_or_else(|| "application/json; charset=utf-8".to_string());
            let content_type_value: HeaderValue = content_type
                .parse()
                .unwrap_or_else(|_| HeaderValue::from_static("application/json; charset=utf-8"));
            Response::builder()
                .status(status)
                .header(header::CONTENT_TYPE, content_type_value)
                .header("x-content-type-options", "nosniff")
                .body(Body::from(upstream.body))
                .expect("coverage proxy response uses validated headers")
        }
        Err(upstream::UpstreamError::BadResponse(_)) => {
            TypedError::upstream_bad_response().into_response()
        }
        Err(upstream::UpstreamError::Unreachable(_) | upstream::UpstreamError::TimedOut) => {
            TypedError::upstream_unavailable().into_response()
        }
    }
}
