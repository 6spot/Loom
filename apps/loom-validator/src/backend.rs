//! Public-consumer backend contexts and lifecycle harness.
//!
//! The validator deliberately does not assemble `Runtime`, `Storage`, or a
//! database pool. Those are composition-root concerns. A harness connects to
//! the already-composed public Loom service and gives a scenario only a
//! `LoomClient`. This keeps backend selection useful for parity runs without
//! giving scenario code implementation authority.

#![allow(clippy::all, clippy::pedantic, clippy::nursery, clippy::restriction)]
#![allow(unused_imports, dead_code)]

use std::{env, fmt, sync::Arc};

use loom_api::LoomApi;
use loom_client::{ClientConfigError, LoomClient};

use crate::mock::MockApi;
use crate::{BackendKind, ValidationPolicy};

/// The environment variable used by the repository's `PostgreSQL` test path.
pub const LOOM_TEST_POSTGRES_URL: &str = "LOOM_TEST_POSTGRES_URL";

/// Optional public HTTP endpoint override used by the validator harness.
pub const LOOM_VALIDATOR_BASE_URL: &str = "LOOM_VALIDATOR_BASE_URL";

/// The default public endpoint used when no validator endpoint is configured.
pub const DEFAULT_VALIDATOR_BASE_URL: &str = "http://127.0.0.1:8080";

/// A public-client context supplied to one scenario execution.
///
/// The context contains no Runtime, Storage, SQL, pool, transaction, or
/// server handle. Each call to [`BackendHarness::start`] creates a fresh
/// context for the supplied scope, so a scenario cannot accidentally reuse a
/// prior scenario's context.
/// A public API handle used by a scenario — either a `LoomClient` or an
/// in-memory `MockApi` that implements the same `LoomApi` contract. The
/// indirection keeps scenario code on the public/formal surface while
/// allowing `InMemory` to run deterministically without a real HTTP server.
#[derive(Clone)]
pub struct BackendContext {
    api: Arc<dyn LoomApi + Send + Sync>,
    // Keep the original client for base_url evidence when the backend is
    // HTTP; for mock it is None.
    client: Option<LoomClient>,
    kind: BackendKind,
    scope: String,
}

impl std::fmt::Debug for BackendContext {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("BackendContext")
            .field("kind", &self.kind)
            .field("scope", &self.scope)
            .finish_non_exhaustive()
    }
}

impl BackendContext {
    /// Creates a legacy client-only context.
    ///
    /// This constructor remains available for consumers that used the T1/T2
    /// executor seam before backend lifecycle management was added.
    #[must_use]
    pub fn new(client: LoomClient) -> Self {
        let api: Arc<dyn LoomApi + Send + Sync> = Arc::new(client.clone());
        Self {
            api,
            client: Some(client),
            kind: BackendKind::LoomClient,
            scope: String::new(),
        }
    }

    /// Borrows the public API handle for this context.
    #[must_use]
    pub fn api(&self) -> &(dyn LoomApi + Send + Sync) {
        self.api.as_ref()
    }

    /// Borrows the public Loom client when the backend is HTTP.
    ///
    /// For `InMemory` mock backends this is `None`; callers should use
    /// [`Self::api`] for behavior.
    #[must_use]
    pub fn client(&self) -> Option<&LoomClient> {
        self.client.as_ref()
    }

    /// Returns the `LoomClient` base URL when available, otherwise a mock
    /// identifier.
    #[must_use]
    pub fn base_url(&self) -> String {
        self.client
            .as_ref()
            .map(|c| c.base_url().to_string())
            .unwrap_or_else(|| "mock://in-memory".to_string())
    }

    /// Returns the backend realization represented by this context.
    #[must_use]
    pub fn backend_kind(&self) -> &BackendKind {
        &self.kind
    }

    /// Returns the deterministic scenario scope used to create this context.
    #[must_use]
    pub fn scope(&self) -> &str {
        &self.scope
    }

    /// Releases this scenario's public-client context.
    ///
    /// The method intentionally consumes the context. A disposed context
    /// cannot be handed to another scenario, which makes lifecycle ownership
    /// explicit at the harness boundary.
    pub fn dispose(self) {
        drop(self);
    }

    fn for_backend(
        api: Arc<dyn LoomApi + Send + Sync>,
        client: Option<LoomClient>,
        kind: BackendKind,
        scope: String,
    ) -> Self {
        Self {
            api,
            client,
            kind,
            scope,
        }
    }

    fn for_mock(mock: MockApi, kind: BackendKind, scope: String) -> Self {
        let api: Arc<dyn LoomApi + Send + Sync> = Arc::new(mock);
        Self {
            api,
            client: None,
            kind,
            scope,
        }
    }

    /// Test-only helper to construct a context with an explicit backend kind.
    ///
    /// The harness normally constructs these via [`BackendHarness::start`]. This
    /// helper is provided for unit tests that need to simulate a `PostgreSQL`
    /// context without re-entering the harness prerequisite path.
    #[cfg(test)]
    #[must_use]
    pub fn for_test_with_kind(client: LoomClient, kind: BackendKind, scope: String) -> Self {
        let api: Arc<dyn LoomApi + Send + Sync> = Arc::new(client.clone());
        Self {
            api,
            client: Some(client),
            kind,
            scope,
        }
    }

    #[cfg(test)]
    #[must_use]
    pub fn for_test_with_api(
        api: Arc<dyn LoomApi + Send + Sync>,
        kind: BackendKind,
        scope: String,
    ) -> Self {
        Self {
            api,
            client: None,
            kind,
            scope,
        }
    }
}

/// Why a backend could not be started for a scenario.
#[derive(Clone, Debug)]
pub enum BackendStart {
    /// The public client context is ready for scenario execution.
    Ready(BackendContext),
    /// A declared prerequisite is absent. This is not a passing result.
    Prerequisite {
        /// Backend that requested the prerequisite.
        backend: BackendKind,
        /// Human-readable prerequisite explanation.
        reason: String,
    },
    /// The prerequisite was present, but the public service is unavailable or
    /// the configuration is invalid. This is not a passing result.
    Unavailable {
        /// Backend that was unavailable.
        backend: BackendKind,
        /// Human-readable unavailability explanation.
        reason: String,
    },
}

impl BackendStart {
    /// Returns the backend associated with this start attempt.
    #[must_use]
    pub fn backend(&self) -> &BackendKind {
        match self {
            Self::Ready(context) => context.backend_kind(),
            Self::Prerequisite { backend, .. } | Self::Unavailable { backend, .. } => backend,
        }
    }

    /// Returns the ready context, if startup succeeded.
    #[must_use]
    pub fn context(&self) -> Option<&BackendContext> {
        match self {
            Self::Ready(context) => Some(context),
            Self::Prerequisite { .. } | Self::Unavailable { .. } => None,
        }
    }

    /// Returns the explicit prerequisite/unavailable reason, if any.
    #[must_use]
    pub fn reason(&self) -> Option<&str> {
        match self {
            Self::Ready(_) => None,
            Self::Prerequisite { reason, .. } | Self::Unavailable { reason, .. } => Some(reason),
        }
    }

    /// Reports whether this start produced a usable public context.
    #[must_use]
    pub const fn is_ready(&self) -> bool {
        matches!(self, Self::Ready(_))
    }
}

/// Errors found while constructing the public endpoint for a backend.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum BackendError {
    /// The public endpoint could not be represented as a Loom client.
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

/// A connected, public-consumer backend harness.
///
/// `connect` performs configuration checks only. The repository's supported
/// `PostgreSQL` composition path owns database process startup and migration
/// policy; the validator observes it through the public HTTP endpoint. A
/// `PostgreSQL` URL therefore proves a prerequisite is configured, not that a
/// scenario has passed. Scenario execution remains responsible for producing
/// the evidence that the runner gate evaluates.
#[derive(Clone)]
pub struct BackendHarness {
    kind: BackendKind,
    api: Option<Arc<dyn LoomApi + Send + Sync>>,
    client: Option<LoomClient>,
    start: BackendStartState,
    policy: ValidationPolicy,
}

impl std::fmt::Debug for BackendHarness {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("BackendHarness")
            .field("kind", &self.kind)
            .field("start", &self.start)
            .field("policy", &self.policy)
            .finish_non_exhaustive()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum BackendStartState {
    Ready,
    Prerequisite(String),
    Unavailable(String),
}

impl BackendHarness {
    /// Connects to one public backend realization.
    ///
    /// For `PostgreSQL`, `LOOM_TEST_POSTGRES_URL` is checked before the public
    /// endpoint is built. An absent or empty value is retained as an explicit
    /// prerequisite state so a caller can report it as `skipped` rather than
    /// accidentally treating a missing live backend as a pass.
    ///
    /// # Errors
    ///
    /// Returns [`BackendError::InvalidBaseUrl`] when a configured endpoint is
    /// not a valid public Loom URL. `PostgreSQL` prerequisite failures are
    /// represented by [`BackendStart::Prerequisite`] from [`Self::start`].
    pub fn connect(kind: BackendKind, base_url: impl Into<String>) -> Result<Self, BackendError> {
        let base_url = base_url.into();
        if kind.is_postgres() {
            let (start, api, client) = match postgres_prerequisite() {
                Ok(()) => {
                    let client = LoomClient::new(base_url.clone())?;
                    // Verify the live endpoint is actually reachable when the
                    // prerequisite is present; otherwise mark as unavailable
                    // rather than silently producing a pass.
                    let api: Arc<dyn LoomApi + Send + Sync> = Arc::new(client.clone());
                    match api.catalog() {
                        Ok(_) => (BackendStartState::Ready, Some(api), Some(client)),
                        Err(err) => (
                            BackendStartState::Unavailable(format!(
                                "PostgreSQL live backend at {base_url} unavailable: {:?} - {}",
                                err.code, err.message
                            )),
                            None,
                            None,
                        ),
                    }
                }
                Err(BackendStartState::Prerequisite(reason)) => {
                    (BackendStartState::Prerequisite(reason), None, None)
                }
                Err(BackendStartState::Unavailable(reason)) => {
                    (BackendStartState::Unavailable(reason), None, None)
                }
                Err(BackendStartState::Ready) => unreachable!("prerequisite cannot be ready"),
            };
            Ok(Self {
                kind,
                api,
                client,
                start,
                policy: ValidationPolicy::default(),
            })
        } else if kind == BackendKind::InMemory {
            // InMemory uses the in-process mock that implements the same
            // public Loom API contract. It provides deterministic behavior
            // without requiring an external HTTP server and without importing
            // Runtime/Storage in the validator crate.
            let mock_api = MockApi::new();
            let api: Arc<dyn LoomApi + Send + Sync> = Arc::new(mock_api);
            // Keep a dummy client for base_url evidence; it is not used for
            // InMemory behavior but preserves the public client surface.
            let client = LoomClient::new(base_url).ok();
            Ok(Self {
                kind,
                api: Some(api),
                client,
                start: BackendStartState::Ready,
                policy: ValidationPolicy::default(),
            })
        } else {
            let client = LoomClient::new(base_url.clone())?;
            let api: Arc<dyn LoomApi + Send + Sync> = Arc::new(client.clone());
            Ok(Self {
                kind,
                api: Some(api),
                client: Some(client),
                start: BackendStartState::Ready,
                policy: ValidationPolicy::default(),
            })
        }
    }

    /// Connects using the optional validator endpoint environment override.
    ///
    /// The database prerequisite remains `LOOM_TEST_POSTGRES_URL`; the
    /// endpoint override only selects where the public consumer sends calls.
    ///
    /// # Errors
    ///
    /// Returns [`BackendError::InvalidBaseUrl`] for an invalid endpoint.
    pub fn from_env(kind: BackendKind) -> Result<Self, BackendError> {
        let base_url = env::var(LOOM_VALIDATOR_BASE_URL)
            .ok()
            .filter(|value| !value.trim().is_empty())
            .unwrap_or_else(|| DEFAULT_VALIDATOR_BASE_URL.to_owned());
        Self::connect(kind, base_url)
    }

    /// Returns the backend realization selected by this harness.
    #[must_use]
    pub const fn backend_kind(&self) -> &BackendKind {
        &self.kind
    }

    /// Returns the gate policy used by reports created from this harness.
    #[must_use]
    pub const fn policy(&self) -> ValidationPolicy {
        self.policy
    }

    /// Replaces the gate policy used by this harness.
    #[must_use]
    pub const fn with_policy(mut self, policy: ValidationPolicy) -> Self {
        self.policy = policy;
        self
    }

    /// Starts a fresh public context for one deterministic scenario scope.
    ///
    /// The scope is metadata only; it does not expose backend state. A fresh
    /// client context is created for every call, and callers must dispose it
    /// before starting another scenario on the same harness.
    #[must_use]
    pub fn start(&self, scope: impl Into<String>) -> BackendStart {
        let scope = scope.into();
        if scope.is_empty() {
            return BackendStart::Unavailable {
                backend: self.kind,
                reason: "scenario scope must be non-empty".to_owned(),
            };
        }

        match (&self.start, self.api.as_ref()) {
            (BackendStartState::Ready, Some(api)) => BackendStart::Ready(
                BackendContext::for_backend(api.clone(), self.client.clone(), self.kind, scope),
            ),
            (BackendStartState::Ready, None) => BackendStart::Unavailable {
                backend: self.kind,
                reason: "public API was not connected".to_owned(),
            },
            (BackendStartState::Prerequisite(reason), _) => BackendStart::Prerequisite {
                backend: self.kind,
                reason: reason.clone(),
            },
            (BackendStartState::Unavailable(reason), _) => BackendStart::Unavailable {
                backend: self.kind,
                reason: reason.clone(),
            },
        }
    }

    /// Disposes a started scenario context.
    pub fn dispose(&self, context: BackendContext) {
        context.dispose();
    }
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
    fn in_memory_start_is_fresh_and_deterministically_scoped() {
        let harness = BackendHarness::connect(BackendKind::InMemory, DEFAULT_VALIDATOR_BASE_URL)
            .expect("in-memory endpoint should build");
        let first = harness.start("CV-001");
        let second = harness.start("CV-002");

        let BackendStart::Ready(first) = first else {
            panic!("in-memory backend should start");
        };
        let BackendStart::Ready(second) = second else {
            panic!("in-memory backend should start");
        };
        assert_eq!(first.backend_kind(), &BackendKind::InMemory);
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
}
