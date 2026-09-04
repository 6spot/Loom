//! Typed Chronicle API errors.
//!
//! Every JSON error uses the C0 envelope so public clients and Studio share
//! one shape: `{"schema":"chronicle.error","version":"0.1",
//! "error":{"code":...,"message":...}}`. Messages never include credentials,
//! connection strings, or internal I/O detail.

use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use serde_json::{json, Value};

/// C0-compatible error schema marker.
pub const ERROR_SCHEMA: &str = "chronicle.error";

/// C0-compatible error schema version.
pub const ERROR_VERSION: &str = "0.1";

/// Build one typed error payload.
#[must_use]
pub fn error_body(code: &str, message: &str) -> Value {
    json!({
        "schema": ERROR_SCHEMA,
        "version": ERROR_VERSION,
        "error": {"code": code, "message": message},
    })
}

/// Status + typed-code error responder.
pub struct TypedError {
    status: StatusCode,
    code: &'static str,
    message: String,
}

impl TypedError {
    /// Create an error with a static code and a dynamic message.
    pub fn new(status: StatusCode, code: &'static str, message: impl Into<String>) -> Self {
        Self {
            status,
            code,
            message: message.into(),
        }
    }

    /// 400 for malformed input.
    pub fn bad_request(message: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, "bad_request", message)
    }

    /// 401 for missing/invalid Studio credentials.
    pub fn unauthorized() -> Self {
        Self::new(
            StatusCode::UNAUTHORIZED,
            "unauthorized",
            "valid Studio administrator credentials are required",
        )
    }

    /// 404 for unknown routes/objects.
    pub fn not_found(message: impl Into<String>) -> Self {
        Self::new(StatusCode::NOT_FOUND, "not_found", message)
    }

    /// 405 for non-GET methods on read routes.
    pub fn method_not_allowed() -> Self {
        Self::new(
            StatusCode::METHOD_NOT_ALLOWED,
            "method_not_allowed",
            "only GET is supported",
        )
    }

    /// 405 for unsupported methods on Studio document routes.
    pub fn studio_method_not_allowed() -> Self {
        Self::new(
            StatusCode::METHOD_NOT_ALLOWED,
            "method_not_allowed",
            "only GET and POST are supported",
        )
    }

    /// 413 for Studio upload bodies over the proxy ceiling.
    pub fn payload_too_large() -> Self {
        Self::new(
            StatusCode::PAYLOAD_TOO_LARGE,
            "payload_too_large",
            "Studio upload exceeds the proxy body limit",
        )
    }

    /// 502 when the upstream answered with an unusable response.
    pub fn upstream_bad_response() -> Self {
        Self::new(
            StatusCode::BAD_GATEWAY,
            "upstream_bad_response",
            "Chronicle read service returned an unusable response",
        )
    }

    /// 503 when the upstream cannot be reached in time.
    pub fn upstream_unavailable() -> Self {
        Self::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "upstream_unavailable",
            "Chronicle read service is unavailable",
        )
    }

    /// 503 when Studio auth was never configured. Fail-closed by design.
    pub fn studio_auth_unconfigured() -> Self {
        Self::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "studio_auth_unconfigured",
            "Studio authentication is not configured on this server",
        )
    }
}

impl IntoResponse for TypedError {
    fn into_response(self) -> Response {
        let mut response = (
            self.status,
            [(
                axum::http::header::CONTENT_TYPE,
                "application/json; charset=utf-8",
            )],
            axum::Json(error_body(self.code, &self.message)),
        )
            .into_response();
        response.headers_mut().insert(
            "x-content-type-options",
            axum::http::HeaderValue::from_static("nosniff"),
        );
        response
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn envelope_matches_c0_shape() {
        let body = error_body("not_found", "route not found");
        assert_eq!(body["schema"], "chronicle.error");
        assert_eq!(body["version"], "0.1");
        assert_eq!(body["error"]["code"], "not_found");
        assert_eq!(body["error"]["message"], "route not found");
    }
}
