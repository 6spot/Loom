//! Non-secret configuration for the `loom-server` composition root.

use std::{net::SocketAddr, path::PathBuf, str::FromStr, time::Duration};

use loom_boundary::BoundaryConfig;
use loom_runtime::{ChronologyBudgetPolicy, FailurePolicy, HistoryBudget, ResolutionBudget};

use crate::WorkerConfig;

/// Application configuration accepted by native and container startup.
///
/// The database URL is retained only for adapter initialization and is never
/// included in `Debug` output or structured logs. Filesystem-backed durable
/// paths are derived from one root, keeping the `PostgreSQL` child inaccessible
/// to the server process in the Compose topology.
#[derive(Clone)]
pub struct ServerConfig {
    pub(crate) database_url: String,
    pub(crate) bind_addr: SocketAddr,
    pub(crate) data_dir: PathBuf,
    pub(crate) revision_id: String,
    pub(crate) core_build_ref: String,
    pub(crate) worker_config: WorkerConfig,
    pub(crate) worker_poll_interval: Duration,
    pub(crate) ingress_queue_capacity: usize,
    pub(crate) boundary_config: BoundaryConfig,
    pub(crate) resolution_budget: ResolutionBudget,
    pub(crate) history_budget: HistoryBudget,
    pub(crate) failure_policy: FailurePolicy,
    pub(crate) chronology_budget: ChronologyBudgetPolicy,
}

impl ServerConfig {
    /// Loads and validates configuration from the process environment.
    ///
    /// `LOOM_DATABASE_URL` is required because silently choosing a local or
    /// in-memory authority would make native and container startup diverge.
    /// All other values have bounded, non-secret development defaults.
    ///
    /// # Errors
    ///
    /// Returns a variable-specific error when a required value is absent or a
    /// bounded value cannot be parsed.
    #[expect(
        clippy::too_many_lines,
        reason = "the composition root keeps all startup policy validation together"
    )]
    pub fn from_env() -> Result<Self, ServerConfigError> {
        let database_url = required_env("LOOM_DATABASE_URL")?;
        let bind_addr =
            parse_env::<SocketAddr>("LOOM_BIND_ADDR", &SocketAddr::from(([0, 0, 0, 0], 8080)))?;
        let data_dir = PathBuf::from(env_or("LOOM_DATA_DIR", "./loom"));
        if data_dir.as_os_str().is_empty() {
            return Err(ServerConfigError::InvalidValue {
                name: "LOOM_DATA_DIR",
                message: "must not be empty".to_owned(),
            });
        }

        let lease_duration = parse_env("LOOM_WORKER_LEASE_MS", &30_000_i64)?;
        let retry_backoff = parse_env("LOOM_WORKER_RETRY_BACKOFF_MS", &1_000_i64)?;
        let scheduler_poll_limit = parse_positive_env("LOOM_WORKER_SCHEDULER_POLL_LIMIT", &1)?;
        let recovery_batch_size = parse_positive_env("LOOM_WORKER_RECOVERY_BATCH_SIZE", &256)?;
        let worker_config = WorkerConfig::new(lease_duration, retry_backoff)
            .and_then(|config| config.with_scheduler_poll_limit(scheduler_poll_limit))
            .and_then(|config| config.with_recovery_batch_size(recovery_batch_size))
            .map_err(|error| ServerConfigError::InvalidValue {
                name: "LOOM_WORKER_*",
                message: error.to_string(),
            })?;
        let poll_millis = parse_env("LOOM_WORKER_POLL_MS", &100_u64)?;
        if poll_millis == 0 {
            return Err(ServerConfigError::InvalidValue {
                name: "LOOM_WORKER_POLL_MS",
                message: "must be positive".to_owned(),
            });
        }
        let ingress_queue_capacity = parse_positive_env("LOOM_INGRESS_QUEUE_CAPACITY", &256)?;

        let max_semantic_results =
            parse_positive_env("LOOM_RUNTIME_MAX_SEMANTIC_RESULTS", &1_024_usize)?;
        if max_semantic_results > loom_runtime::MAX_SEMANTIC_QUERY_RESULTS as usize {
            return Err(ServerConfigError::InvalidValue {
                name: "LOOM_RUNTIME_MAX_SEMANTIC_RESULTS",
                message: format!(
                    "must not exceed the public semantic result bound {}",
                    loom_runtime::MAX_SEMANTIC_QUERY_RESULTS
                ),
            });
        }
        let max_semantic_result_bytes =
            parse_positive_env("LOOM_RUNTIME_MAX_SEMANTIC_RESULT_BYTES", &1_048_576_usize)?;
        if max_semantic_result_bytes > loom_runtime::MAX_SEMANTIC_QUERY_RESULT_BYTES as usize {
            return Err(ServerConfigError::InvalidValue {
                name: "LOOM_RUNTIME_MAX_SEMANTIC_RESULT_BYTES",
                message: format!(
                    "must not exceed the public semantic result-byte bound {}",
                    loom_runtime::MAX_SEMANTIC_QUERY_RESULT_BYTES
                ),
            });
        }
        let max_semantic_depth = parse_positive_env("LOOM_RUNTIME_MAX_SEMANTIC_DEPTH", &32_usize)?;
        if max_semantic_depth > loom_runtime::MAX_SEMANTIC_QUERY_DEPTH as usize {
            return Err(ServerConfigError::InvalidValue {
                name: "LOOM_RUNTIME_MAX_SEMANTIC_DEPTH",
                message: format!(
                    "must not exceed the public semantic depth bound {}",
                    loom_runtime::MAX_SEMANTIC_QUERY_DEPTH
                ),
            });
        }
        let max_semantic_filters =
            parse_positive_env("LOOM_RUNTIME_MAX_SEMANTIC_FILTERS", &1_usize)?;
        if max_semantic_filters > loom_runtime::MAX_SEMANTIC_QUERY_FILTERS as usize {
            return Err(ServerConfigError::InvalidValue {
                name: "LOOM_RUNTIME_MAX_SEMANTIC_FILTERS",
                message: format!(
                    "must not exceed the public semantic filter bound {}",
                    loom_runtime::MAX_SEMANTIC_QUERY_FILTERS
                ),
            });
        }

        let resolution_budget = ResolutionBudget::default()
            .with_max_action_payload_bytes(parse_positive_env(
                "LOOM_RUNTIME_MAX_ACTION_PAYLOAD_BYTES",
                &262_144_usize,
            )?)
            .with_max_ingress_payload_bytes(parse_positive_env(
                "LOOM_INGRESS_MAX_PAYLOAD_BYTES",
                &524_288_usize,
            )?)
            .with_max_session_provenance_bytes(parse_positive_env(
                "LOOM_RUNTIME_MAX_SESSION_PROVENANCE_BYTES",
                &4_194_304_usize,
            )?)
            .with_max_session_provenance_entries(parse_positive_env(
                "LOOM_RUNTIME_MAX_SESSION_PROVENANCE_ENTRIES",
                &4_096_usize,
            )?)
            .with_max_event_payload_bytes(parse_positive_env(
                "LOOM_RUNTIME_MAX_EVENT_PAYLOAD_BYTES",
                &262_144_usize,
            )?)
            .with_max_work_payload_bytes(parse_positive_env(
                "LOOM_RUNTIME_MAX_WORK_PAYLOAD_BYTES",
                &262_144_usize,
            )?)
            .with_max_events(parse_positive_env("LOOM_RUNTIME_MAX_EVENTS", &256_usize)?)
            .with_max_effects(parse_positive_env(
                "LOOM_RUNTIME_MAX_EFFECTS",
                &1_024_usize,
            )?)
            .with_max_work_mutations(parse_positive_env(
                "LOOM_RUNTIME_MAX_WORK_MUTATIONS",
                &256_usize,
            )?)
            .with_max_reaction_schedules(parse_positive_env(
                "LOOM_RUNTIME_MAX_REACTION_SCHEDULES",
                &256_usize,
            )?)
            .with_max_subresolution_depth(parse_positive_env(
                "LOOM_RUNTIME_MAX_SUBRESOLUTION_DEPTH",
                &8_usize,
            )?)
            .with_max_subresolution_count(parse_positive_env(
                "LOOM_RUNTIME_MAX_SUBRESOLUTION_COUNT",
                &64_usize,
            )?)
            .with_max_semantic_queries(parse_positive_env(
                "LOOM_RUNTIME_MAX_SEMANTIC_QUERIES",
                &64_usize,
            )?)
            .with_max_semantic_results(max_semantic_results)
            .with_max_semantic_result_bytes(max_semantic_result_bytes)
            .with_max_semantic_depth(max_semantic_depth)
            .with_max_semantic_filters(max_semantic_filters);
        let max_change_feed_page_size =
            parse_positive_env("LOOM_RUNTIME_MAX_CHANGE_FEED_PAGE_SIZE", &256_u32)?;
        if max_change_feed_page_size > loom_api::MAX_CHANGE_FEED_PAGE_SIZE {
            return Err(ServerConfigError::InvalidValue {
                name: "LOOM_RUNTIME_MAX_CHANGE_FEED_PAGE_SIZE",
                message: format!(
                    "must not exceed the public Change Feed bound {}",
                    loom_api::MAX_CHANGE_FEED_PAGE_SIZE
                ),
            });
        }
        let history_budget = HistoryBudget::new(
            parse_positive_env("LOOM_RUNTIME_MAX_HISTORY_PAGE_SIZE", &1_024_u32)?,
            parse_positive_env("LOOM_RUNTIME_MAX_CAUSAL_DEPTH", &64_u32)?,
            parse_positive_env("LOOM_RUNTIME_MAX_CAUSAL_RESULTS", &1_024_u32)?,
        )
        .with_max_change_feed_page_size(max_change_feed_page_size);
        let failure_policy = FailurePolicy::new(
            parse_env("LOOM_INGRESS_MAX_RETRY_ATTEMPTS", &3_u32)?,
            retry_backoff,
        )
        .map_err(|error| ServerConfigError::InvalidValue {
            name: "LOOM_INGRESS_MAX_RETRY_ATTEMPTS/LOOM_WORKER_RETRY_BACKOFF_MS",
            message: error.to_string(),
        })?;
        let chronology_budget = ChronologyBudgetPolicy::new(parse_positive_env(
            "LOOM_RUNTIME_MAX_CHRONOLOGY_COMPLETIONS",
            &1_024_u64,
        )?);

        let max_body_bytes = parse_positive_env("LOOM_HTTP_MAX_BODY_BYTES", &(1024 * 1024))?;
        let max_header_bytes = parse_positive_env("LOOM_HTTP_MAX_HEADER_BYTES", &(16 * 1024))?;
        let max_response_bytes =
            parse_positive_env("LOOM_HTTP_MAX_RESPONSE_BYTES", &(8 * 1024 * 1024))?;
        let max_sse_buffer_bytes =
            parse_positive_env("LOOM_HTTP_MAX_SSE_BUFFER_BYTES", &(4 * 1024 * 1024))?;
        let max_sse_events = parse_positive_env("LOOM_HTTP_MAX_SSE_EVENTS", &1_000_u32)?;
        let max_concurrent_requests =
            parse_positive_env("LOOM_HTTP_MAX_CONCURRENT_REQUESTS", &128_usize)?;
        let boundary_config = BoundaryConfig::new(
            max_body_bytes,
            max_header_bytes,
            max_response_bytes,
            max_sse_buffer_bytes,
            max_sse_events,
            max_concurrent_requests,
        )
        .map_err(|error| ServerConfigError::InvalidValue {
            name: "LOOM_HTTP_*",
            message: error.to_string(),
        })?;

        Ok(Self {
            database_url,
            bind_addr,
            data_dir,
            revision_id: env_or("LOOM_RUNTIME_REVISION_ID", "loom-server"),
            core_build_ref: env_or(
                "LOOM_CORE_BUILD_REF",
                concat!("loom-server-", env!("CARGO_PKG_VERSION")),
            ),
            worker_config,
            worker_poll_interval: Duration::from_millis(poll_millis),
            ingress_queue_capacity,
            boundary_config,
            resolution_budget,
            history_budget,
            failure_policy,
            chronology_budget,
        })
    }

    /// Returns the one configured child directory used by the local `BlobStore`.
    #[must_use]
    pub fn blob_dir(&self) -> PathBuf {
        self.data_dir.join("blobs")
    }

    /// Returns the configured persistence root without exposing any database
    /// child path to application code that owns the server runtime.
    #[must_use]
    pub fn data_dir(&self) -> &std::path::Path {
        &self.data_dir
    }

    /// Returns the HTTP bind address.
    #[must_use]
    pub const fn bind_addr(&self) -> SocketAddr {
        self.bind_addr
    }
}

impl std::fmt::Debug for ServerConfig {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("ServerConfig")
            .field("database_url", &"<redacted>")
            .field("bind_addr", &self.bind_addr)
            .field("data_dir", &self.data_dir)
            .field("revision_id", &self.revision_id)
            .field("core_build_ref", &self.core_build_ref)
            .field("worker_config", &self.worker_config)
            .field("worker_poll_interval", &self.worker_poll_interval)
            .field("ingress_queue_capacity", &self.ingress_queue_capacity)
            .field("boundary_config", &self.boundary_config)
            .field("resolution_budget", &self.resolution_budget)
            .field("history_budget", &self.history_budget)
            .field("failure_policy", &self.failure_policy)
            .field("chronology_budget", &self.chronology_budget)
            .finish()
    }
}

/// Configuration parsing failure with the offending variable identified but
/// no secret value copied into the error.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ServerConfigError {
    /// A required variable was not present.
    Missing { name: &'static str },
    /// A variable was present but failed validation.
    InvalidValue {
        /// Variable name or bounded group of related variables.
        name: &'static str,
        /// Safe validation explanation, never the variable value.
        message: String,
    },
}

impl std::fmt::Display for ServerConfigError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Missing { name } => write!(formatter, "required configuration {name} is missing"),
            Self::InvalidValue { name, message } => {
                write!(formatter, "invalid configuration {name}: {message}")
            }
        }
    }
}

impl std::error::Error for ServerConfigError {}

fn env_or(name: &str, default: &str) -> String {
    std::env::var(name).unwrap_or_else(|_| default.to_owned())
}

fn required_env(name: &'static str) -> Result<String, ServerConfigError> {
    match std::env::var(name) {
        Ok(value) if !value.trim().is_empty() => Ok(value),
        Ok(_) | Err(std::env::VarError::NotPresent) => Err(ServerConfigError::Missing { name }),
        Err(std::env::VarError::NotUnicode(_)) => Err(ServerConfigError::InvalidValue {
            name,
            message: "must be valid UTF-8".to_owned(),
        }),
    }
}

fn parse_env<T>(name: &'static str, default: &T) -> Result<T, ServerConfigError>
where
    T: FromStr + ToString,
    T::Err: std::fmt::Display,
{
    let raw = env_or(name, &default.to_string());
    raw.parse::<T>()
        .map_err(|error| ServerConfigError::InvalidValue {
            name,
            message: error.to_string(),
        })
}

fn parse_positive_env<T>(name: &'static str, default: &T) -> Result<T, ServerConfigError>
where
    T: FromStr + PartialEq + Default + ToString,
    T::Err: std::fmt::Display,
{
    let value = parse_env(name, default)?;
    if value == T::default() {
        return Err(ServerConfigError::InvalidValue {
            name,
            message: "must be positive".to_owned(),
        });
    }
    Ok(value)
}
