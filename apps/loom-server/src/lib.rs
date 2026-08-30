//! Application-owned v0 server composition.
//!
//! The target-neutral [`SchedulerSupervisor`] owns one
//! [`loom_runtime::Runtime`] instance and drives discovered Timelines on the
//! executor selected by the application process. It deliberately supplies
//! polling, lease and retry platform times to Runtime's semantic
//! [`loom_runtime::Runtime::drive_timeline`] step; it does not select a Work,
//! claim a successor, advance World Time or perform a persistence operation
//! itself.
//!
//! v0 applications should run the Supervisor on a single-thread Tokio runtime
//! per application process. Independent Supervisor instances may discover and
//! drive Timelines against the same `PostgreSQL` authority. A process restart
//! constructs a fresh Runtime and Supervisor; `PostgreSQL` lease expiry and
//! claim fencing make an interrupted Work reclaimable without an in-process
//! Runtime mutex.

#![forbid(unsafe_code)]

mod application;
mod config;
mod ingress;
mod scheduler_supervisor;

pub use application::{
    ApplicationApi, LoomServer, ServerError, SystemClock, SystemEntropySource, run_from_env,
};
pub use config::{ServerConfig, ServerConfigError};
pub use ingress::{IngressWorker, IngressWorkerReport, IngressWorkerStopReason};
pub use scheduler_supervisor::{SchedulerCycleReport, SchedulerDriveOutcome, SchedulerSupervisor};

use std::sync::{
    Arc,
    atomic::{AtomicBool, Ordering},
};

use loom_api::{ApiError, ApiResult};
use loom_runtime::PlatformTime;
use tokio::sync::Notify;

/// Bounded operational timing supplied by the application composition root.
///
/// These values are platform metadata only. They do not define semantic due
/// time or Timeline ordering. `lease_duration` must be positive so a claim can
/// be established; `retry_backoff` may be zero for an application that wants
/// Runtime `FailurePolicy` to control retry availability.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct WorkerConfig {
    lease_duration: i64,
    retry_backoff: i64,
    scheduler_poll_limit: usize,
    recovery_batch_size: usize,
}

impl WorkerConfig {
    /// Creates bounded lease and retry timing for one worker instance.
    ///
    /// # Errors
    ///
    /// Returns an error when a lease is not positive or a retry backoff is
    /// negative. The values are deliberately validated before a worker starts
    /// so a polling step cannot create an invalid claim deadline.
    pub const fn new(lease_duration: i64, retry_backoff: i64) -> Result<Self, WorkerConfigError> {
        if lease_duration <= 0 {
            return Err(WorkerConfigError::NonPositiveLease);
        }
        if retry_backoff < 0 {
            return Err(WorkerConfigError::NegativeRetryBackoff);
        }
        Ok(Self {
            lease_duration,
            retry_backoff,
            scheduler_poll_limit: 1,
            recovery_batch_size: 256,
        })
    }

    /// Sets the maximum number of scheduler items processed per poll.
    ///
    /// # Errors
    ///
    /// Returns an error when the limit is zero.
    pub const fn with_scheduler_poll_limit(
        mut self,
        limit: usize,
    ) -> Result<Self, WorkerConfigError> {
        if limit == 0 {
            return Err(WorkerConfigError::NonPositiveSchedulerPollLimit);
        }
        self.scheduler_poll_limit = limit;
        Ok(self)
    }

    /// Sets the maximum number of recoverable Ingress records scanned per
    /// idle recovery pass.
    ///
    /// # Errors
    ///
    /// Returns an error when the limit is zero.
    pub const fn with_recovery_batch_size(
        mut self,
        limit: usize,
    ) -> Result<Self, WorkerConfigError> {
        if limit == 0 {
            return Err(WorkerConfigError::NonPositiveRecoveryBatchSize);
        }
        self.recovery_batch_size = limit;
        Ok(self)
    }

    /// Returns the platform duration reserved for one active claim.
    #[must_use]
    pub const fn lease_duration(self) -> i64 {
        self.lease_duration
    }

    /// Returns the platform retry backoff supplied to Runtime failure policy.
    #[must_use]
    pub const fn retry_backoff(self) -> i64 {
        self.retry_backoff
    }

    /// Returns the scheduler poll item bound.
    #[must_use]
    pub const fn scheduler_poll_limit(self) -> usize {
        self.scheduler_poll_limit
    }

    /// Returns the idle recovery batch bound.
    #[must_use]
    pub const fn recovery_batch_size(self) -> usize {
        self.recovery_batch_size
    }
}

/// Invalid application-owned worker timing.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum WorkerConfigError {
    /// A claim must expire after the platform time at which it was created.
    NonPositiveLease,
    /// Retry availability cannot move backwards from the sampled platform time.
    NegativeRetryBackoff,
    /// A scheduler poll must process at least one item when enabled.
    NonPositiveSchedulerPollLimit,
    /// An idle recovery pass must scan at least one item when enabled.
    NonPositiveRecoveryBatchSize,
}

impl std::fmt::Display for WorkerConfigError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NonPositiveLease => formatter.write_str("worker lease duration must be positive"),
            Self::NegativeRetryBackoff => {
                formatter.write_str("worker retry backoff must not be negative")
            }
            Self::NonPositiveSchedulerPollLimit => {
                formatter.write_str("worker scheduler poll limit must be positive")
            }
            Self::NonPositiveRecoveryBatchSize => {
                formatter.write_str("worker recovery batch size must be positive")
            }
        }
    }
}

impl std::error::Error for WorkerConfigError {}

/// External lifecycle signal owned by the application/process supervisor.
///
/// Setting the signal does not revoke an active claim. The application loop
/// observes it before each Runtime step, so graceful shutdown stops new claims
/// while the current semantic drive/claim/execute/complete operation is
/// allowed to finish. A process supervisor can discard the active loop and
/// construct a new one after a restart; no restart state is kept in Runtime.
#[derive(Clone, Debug)]
pub struct ShutdownSignal {
    requested: Arc<AtomicBool>,
    notify: Arc<Notify>,
}

impl ShutdownSignal {
    /// Creates a clear shutdown signal.
    #[must_use]
    pub fn new() -> Self {
        Self {
            requested: Arc::new(AtomicBool::new(false)),
            notify: Arc::new(Notify::new()),
        }
    }

    /// Requests graceful shutdown before the next Runtime step.
    pub fn request(&self) {
        self.requested.store(true, Ordering::Release);
        self.notify.notify_waiters();
    }

    /// Returns whether the application has requested graceful shutdown.
    #[must_use]
    pub fn is_requested(&self) -> bool {
        self.requested.load(Ordering::Acquire)
    }

    /// Waits until the process supervisor requests shutdown.
    pub async fn wait(&self) {
        if self.is_requested() {
            return;
        }
        self.notify.notified().await;
    }
}

impl Default for ShutdownSignal {
    fn default() -> Self {
        Self::new()
    }
}

pub(crate) fn add_platform_duration(now: PlatformTime, duration: i64) -> ApiResult<PlatformTime> {
    now.value()
        .checked_add(duration)
        .map(PlatformTime::new)
        .ok_or_else(|| ApiError::invalid_request("worker platform deadline overflowed"))
}

#[cfg(test)]
mod tests {
    use super::{ApplicationApi, ShutdownSignal, SystemClock, SystemEntropySource};

    fn assert_send_sync<T: Send + Sync>() {}

    #[test]
    fn transport_owned_state_has_the_only_cross_thread_send_sync_boundary() {
        // The HTTP/SSE composition requires Send + Sync for its shared API
        // object. Scheduler state intentionally remains on a current-thread
        // executor and is not asserted here.
        assert_send_sync::<ApplicationApi>();
        assert_send_sync::<SystemClock>();
        assert_send_sync::<SystemEntropySource>();
        assert_send_sync::<ShutdownSignal>();
    }
}
