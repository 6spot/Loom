//! Public-consumer backend contexts and lifecycle harness.
//!
//! The validator deliberately does not assemble `Runtime`, `Storage`, or a
//! database pool. Those are composition-root concerns. A harness connects to
//! the already-composed public Loom service and gives a scenario only a
//! `LoomClient`. This keeps backend selection useful for parity runs without
//! giving scenario code implementation authority.

use std::{env, fmt};

use loom_client::{ClientConfigError, LoomClient};

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
#[derive(Clone, Debug)]
pub struct BackendContext {
    client: LoomClient,
    kind: BackendKind,
    scope: String,
}

impl BackendContext {
    /// Creates a legacy client-only context.
    ///
    /// This constructor remains available for consumers that used the T1/T2
    /// executor seam before backend lifecycle management was added.
    #[must_use]
    pub const fn new(client: LoomClient) -> Self {
        Self {
            client,
            kind: BackendKind::LoomClient,
            scope: String::new(),
        }
    }

    /// Borrows the public Loom client used by this context.
    #[must_use]
    pub const fn client(&self) -> &LoomClient {
        &self.client
    }

    /// Returns the backend realization represented by this context.
    #[must_use]
    pub const fn backend_kind(&self) -> &BackendKind {
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

    fn for_backend(client: LoomClient, kind: BackendKind, scope: String) -> Self {
        Self {
            client,
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
#[derive(Clone, Debug)]
pub struct BackendHarness {
    kind: BackendKind,
    client: Option<LoomClient>,
    start: BackendStartState,
    policy: ValidationPolicy,
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
            start,
            policy: ValidationPolicy::default(),
        })
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

        match &self.start {
            BackendStartState::Ready => match self.client.as_ref() {
                Some(client) => BackendStart::Ready(BackendContext::for_backend(
                    client.clone(),
                    self.kind,
                    scope,
                )),
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
