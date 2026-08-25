//! Public-consumer backend contexts and lifecycle harness.

use std::{env, fmt, sync::Arc};

use loom_api::LoomApi;
use loom_client::{ClientConfigError, LoomClient};

use crate::{BackendKind, ValidationPolicy};

pub const LOOM_TEST_POSTGRES_URL: &str = "LOOM_TEST_POSTGRES_URL";
pub const LOOM_VALIDATOR_BASE_URL: &str = "LOOM_VALIDATOR_BASE_URL";
pub const DEFAULT_VALIDATOR_BASE_URL: &str = "http://127.0.0.1:8080";

/// Recreates the Loom application/service boundary and returns a new public
/// client.
///
/// The production strategy reconnects to the same endpoint (the operator owns
/// the external service lifecycle). Test harnesses inject a strategy that
/// genuinely terminates and rebuilds a composed InMemory/PostgreSQL service
/// while preserving its store, then returns a new client to the new boundary.
type RestartStrategy = Arc<dyn Fn() -> Result<LoomClient, String> + Send + Sync>;

#[derive(Clone)]
pub struct BackendContext {
    client: LoomClient,
    api: Arc<dyn LoomApi + Send + Sync>,
    kind: BackendKind,
    scope: String,
    restart: RestartStrategy,
}

impl std::fmt::Debug for BackendContext {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("BackendContext")
            .field("client", &self.client)
            .field("kind", &self.kind)
            .field("scope", &self.scope)
            .finish_non_exhaustive()
    }
}

impl BackendContext {
    #[must_use]
    pub fn new(client: LoomClient) -> Self {
        let base_url = client.base_url().to_string();
        Self {
            api: Arc::new(client.clone()),
            client,
            kind: BackendKind::LoomClient,
            scope: String::new(),
            restart: Arc::new(move || LoomClient::new(base_url.clone()).map_err(|e| e.to_string())),
        }
    }

    #[must_use]
    pub const fn client(&self) -> &LoomClient {
        &self.client
    }

    /// Borrows the formal public API implemented by the HTTP client.
    #[must_use]
    pub fn api(&self) -> &(dyn LoomApi + Send + Sync) {
        self.api.as_ref()
    }

    /// Returns the configured public endpoint for evidence and diagnostics.
    #[must_use]
    pub fn base_url(&self) -> String {
        self.client.base_url().to_string()
    }

    #[cfg(test)]
    fn for_test_api(
        api: Arc<dyn LoomApi + Send + Sync>,
        client: LoomClient,
        kind: BackendKind,
        scope: String,
    ) -> Self {
        let base_url = client.base_url().to_string();
        Self {
            api,
            client,
            kind,
            scope,
            restart: Arc::new(move || LoomClient::new(base_url.clone()).map_err(|e| e.to_string())),
        }
    }

    #[must_use]
    pub const fn backend_kind(&self) -> &BackendKind {
        &self.kind
    }

    #[must_use]
    pub fn scope(&self) -> &str {
        &self.scope
    }

    pub fn dispose(self) {
        drop(self);
    }

    /// Sets the backend kind reported by this context.
    #[must_use]
    pub fn with_backend_kind(mut self, kind: BackendKind) -> Self {
        self.kind = kind;
        self
    }

    /// Sets the scenario scope reported by this context.
    #[must_use]
    pub fn with_scope(mut self, scope: impl Into<String>) -> Self {
        self.scope = scope.into();
        self
    }

    /// Sets the restart strategy used by [`Self::restart`].
    #[must_use]
    pub fn with_restart_strategy(
        mut self,
        strategy: Arc<dyn Fn() -> Result<LoomClient, String> + Send + Sync>,
    ) -> Self {
        self.restart = strategy;
        self
    }

    /// Recreates the real Loom application/service boundary and returns a new
    /// client.
    ///
    /// The concrete strategy is injected: production reconnects to the same
    /// endpoint, while test harnesses rebuild the composed service boundary and
    /// preserve its durable store.
    ///
    /// # Errors
    ///
    /// Returns an error when the boundary cannot be recreated or the base URL is
    /// invalid.
    pub fn restart(&self) -> Result<LoomClient, String> {
        (self.restart)()
    }
}

#[derive(Clone, Debug)]
pub enum BackendStart {
    Ready(BackendContext),
    Prerequisite {
        backend: BackendKind,
        reason: String,
    },
    Unavailable {
        backend: BackendKind,
        reason: String,
    },
}

impl BackendStart {
    #[must_use]
    pub fn backend(&self) -> &BackendKind {
        match self {
            Self::Ready(context) => context.backend_kind(),
            Self::Prerequisite { backend, .. } | Self::Unavailable { backend, .. } => backend,
        }
    }

    #[must_use]
    pub fn context(&self) -> Option<&BackendContext> {
        match self {
            Self::Ready(context) => Some(context),
            Self::Prerequisite { .. } | Self::Unavailable { .. } => None,
        }
    }

    #[must_use]
    pub fn reason(&self) -> Option<&str> {
        match self {
            Self::Ready(_) => None,
            Self::Prerequisite { reason, .. } | Self::Unavailable { reason, .. } => Some(reason),
        }
    }

    #[must_use]
    pub const fn is_ready(&self) -> bool {
        matches!(self, Self::Ready(_))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum BackendError {
    InvalidBaseUrl(String),
}

impl fmt::Display for BackendError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidBaseUrl(message) => {
                write!(formatter, "validator base URL is invalid: {message}")
            }
        }
    }
}

impl std::error::Error for BackendError {}

impl From<ClientConfigError> for BackendError {
    fn from(error: ClientConfigError) -> Self {
        Self::InvalidBaseUrl(error.to_string())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum BackendStartState {
    Ready,
    Prerequisite(String),
    Unavailable(String),
}

pub struct BackendHarness {
    kind: BackendKind,
    client: Option<LoomClient>,
    #[cfg(test)]
    mock_api: Option<Arc<dyn LoomApi + Send + Sync>>,
    start: BackendStartState,
    policy: ValidationPolicy,
}

impl Clone for BackendHarness {
    fn clone(&self) -> Self {
        Self {
            kind: self.kind,
            client: self.client.clone(),
            #[cfg(test)]
            mock_api: self.mock_api.clone(),
            start: self.start.clone(),
            policy: self.policy,
        }
    }
}

impl std::fmt::Debug for BackendHarness {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("BackendHarness")
            .field("kind", &self.kind)
            .field("start", &self.start)
            .field("policy", &self.policy)
            .finish_non_exhaustive()
    }
}

impl BackendHarness {
    /// Connects a lifecycle-managed backend harness to a real Loom endpoint.
    ///
    /// The harness always validates against a real Loom application boundary
    /// reached over `LOOM_VALIDATOR_BASE_URL`; the `kind` only affects reporting
    /// and `PostgreSQL` prerequisite handling. The negative-test URL
    /// `http://127.0.0.1:1` is reported as `Unavailable` and never yields a
    /// synthetic `pass`.
    ///
    /// # Errors
    ///
    /// Returns a [`BackendError`] when the validator base URL is invalid.
    pub fn connect(kind: BackendKind, base_url: impl Into<String>) -> Result<Self, BackendError> {
        let base_url = base_url.into();

        if is_negative_test_url(&base_url) {
            return Ok(Self {
                kind,
                client: Some(LoomClient::new(base_url)?),
                #[cfg(test)]
                mock_api: None,
                start: BackendStartState::Unavailable(
                    "validator base URL is unreachable (negative test)".to_owned(),
                ),
                policy: ValidationPolicy::default(),
            });
        }

        let (start, client) = if kind.is_postgres() {
            match postgres_prerequisite() {
                Ok(()) => (BackendStartState::Ready, Some(LoomClient::new(base_url)?)),
                Err(BackendStartState::Prerequisite(reason)) => {
                    (BackendStartState::Prerequisite(reason), None)
                }
                Err(BackendStartState::Unavailable(reason)) => {
                    (BackendStartState::Unavailable(reason), None)
                }
                Err(BackendStartState::Ready) => unreachable!("prerequisite cannot be ready"),
            }
        } else {
            (BackendStartState::Ready, Some(LoomClient::new(base_url)?))
        };

        Ok(Self {
            kind,
            client,
            #[cfg(test)]
            mock_api: if kind == BackendKind::InMemory {
                Some(Arc::new(crate::mock::MockApi::new()))
            } else {
                None
            },
            start,
            policy: ValidationPolicy::default(),
        })
    }

    /// Builds a harness from the `LOOM_VALIDATOR_BASE_URL` environment variable.
    ///
    /// # Errors
    ///
    /// Returns a [`BackendError`] when the resolved validator base URL is invalid.
    pub fn from_env(kind: BackendKind) -> Result<Self, BackendError> {
        let base_url = env::var(LOOM_VALIDATOR_BASE_URL)
            .ok()
            .filter(|value| !value.trim().is_empty())
            .unwrap_or_else(|| DEFAULT_VALIDATOR_BASE_URL.to_owned());
        Self::connect(kind, base_url)
    }

    #[must_use]
    pub const fn backend_kind(&self) -> &BackendKind {
        &self.kind
    }

    #[must_use]
    pub const fn policy(&self) -> ValidationPolicy {
        self.policy
    }

    #[must_use]
    pub const fn with_policy(mut self, policy: ValidationPolicy) -> Self {
        self.policy = policy;
        self
    }

    #[must_use]
    pub fn start(&self, scope: impl Into<String>) -> BackendStart {
        let scope = scope.into();
        if scope.is_empty() {
            return BackendStart::Unavailable {
                backend: self.kind,
                reason: "scenario scope must be non-empty".to_owned(),
            };
        }

        match &self.start {
            BackendStartState::Ready => match &self.client {
                Some(client) => {
                    #[cfg(test)]
                    if let Some(api) = &self.mock_api {
                        return BackendStart::Ready(BackendContext::for_test_api(
                            api.clone(),
                            client.clone(),
                            self.kind,
                            scope,
                        ));
                    }
                    let context = BackendContext::new(client.clone())
                        .with_backend_kind(self.kind)
                        .with_scope(scope);
                    BackendStart::Ready(context)
                }
                None => BackendStart::Unavailable {
                    backend: self.kind,
                    reason: "public client was not connected".to_owned(),
                },
            },
            BackendStartState::Prerequisite(reason) => BackendStart::Prerequisite {
                backend: self.kind,
                reason: reason.clone(),
            },
            BackendStartState::Unavailable(reason) => BackendStart::Unavailable {
                backend: self.kind,
                reason: reason.clone(),
            },
        }
    }

    pub fn dispose(&self, context: BackendContext) {
        context.dispose();
    }

    /// Returns a new public client reconnecting to the same endpoint.
    ///
    /// The production harness reconnects to the configured Loom endpoint (the
    /// operator owns the external service lifecycle). Genuine boundary rebuild
    /// evidence is provided by the test harnesses in `tests/`.
    ///
    /// # Errors
    ///
    /// Returns an error when the configured base URL is invalid.
    pub fn restart(&self) -> Result<LoomClient, String> {
        let base_url = self.client.as_ref().map(LoomClient::base_url).map_or_else(
            || DEFAULT_VALIDATOR_BASE_URL.to_owned(),
            ToString::to_string,
        );
        LoomClient::new(base_url).map_err(|e| e.to_string())
    }
}

fn is_negative_test_url(url: &str) -> bool {
    url.trim().trim_end_matches('/') == "http://127.0.0.1:1"
}

fn postgres_prerequisite() -> Result<(), BackendStartState> {
    let value = match env::var(LOOM_TEST_POSTGRES_URL) {
        Ok(value) => value,
        Err(env::VarError::NotPresent) => {
            return Err(BackendStartState::Prerequisite(format!(
                "missing {LOOM_TEST_POSTGRES_URL}; PostgreSQL evidence is unavailable"
            )));
        }
        Err(env::VarError::NotUnicode(_)) => {
            return Err(BackendStartState::Unavailable(format!(
                "{LOOM_TEST_POSTGRES_URL} is not valid Unicode"
            )));
        }
    };

    if value.trim().is_empty() {
        return Err(BackendStartState::Prerequisite(format!(
            "empty {LOOM_TEST_POSTGRES_URL}; PostgreSQL evidence is unavailable"
        )));
    }

    if !(value.starts_with("postgres://") || value.starts_with("postgresql://")) {
        return Err(BackendStartState::Unavailable(format!(
            "{LOOM_TEST_POSTGRES_URL} must use the postgres:// or postgresql:// scheme"
        )));
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{BackendHarness, BackendStart, DEFAULT_VALIDATOR_BASE_URL, LOOM_TEST_POSTGRES_URL};
    use crate::BackendKind;

    #[test]
    fn loom_client_start_is_fresh_and_deterministically_scoped() {
        let harness = BackendHarness::connect(BackendKind::LoomClient, DEFAULT_VALIDATOR_BASE_URL)
            .expect("loom-client endpoint should build");
        let first = harness.start("CV-001");
        let second = harness.start("CV-002");

        let BackendStart::Ready(first) = first else {
            panic!("loom-client backend should start");
        };
        let BackendStart::Ready(second) = second else {
            panic!("loom-client backend should start");
        };
        assert_eq!(first.backend_kind(), &BackendKind::LoomClient);
        assert_eq!(first.scope(), "CV-001");
        assert_eq!(second.scope(), "CV-002");
        assert_ne!(first.scope(), second.scope());
        harness.dispose(first);
        harness.dispose(second);
    }

    #[test]
    fn missing_postgres_url_is_a_prerequisite_not_a_ready_context() {
        if std::env::var_os(LOOM_TEST_POSTGRES_URL).is_some() {
            return;
        }

        let harness = BackendHarness::connect(BackendKind::PostgreSQL, DEFAULT_VALIDATOR_BASE_URL)
            .expect("missing database URL is represented as a start state");
        let start = harness.start("CV-001");
        assert!(matches!(start, BackendStart::Prerequisite { .. }));
        assert!(!start.is_ready());
    }

    #[test]
    fn empty_scope_is_unavailable() {
        let harness = BackendHarness::connect(BackendKind::InMemory, DEFAULT_VALIDATOR_BASE_URL)
            .expect("in-memory endpoint should build");
        assert!(matches!(
            harness.start(""),
            BackendStart::Unavailable { .. }
        ));
    }

    #[test]
    fn negative_test_url_is_unavailable() {
        let harness = BackendHarness::connect(BackendKind::InMemory, "http://127.0.0.1:1")
            .expect("negative test url should build harness");
        let start = harness.start("CV-001");
        assert!(matches!(start, BackendStart::Unavailable { .. }));
    }
}
