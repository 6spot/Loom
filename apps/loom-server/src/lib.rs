//! Application-owned v0 Scheduler worker composition.
//!
//! A worker owns exactly one [`loom_runtime::Runtime`] instance and drives one
//! Timeline at a time on the executor selected by the Linux worker process.
//! The worker deliberately supplies polling, lease and retry platform times to
//! Runtime's semantic [`loom_runtime::Runtime::drive_timeline`] step; it does
//! not select a Work, claim a successor, advance World Time or perform a
//! persistence operation itself.
//!
//! v0 applications should run one of these workers on a single-thread Tokio
//! runtime per Linux worker process. Independent Timelines are made concurrent
//! by starting independent worker processes/instances against the same
//! `PostgreSQL` authority. A process restart constructs a fresh Runtime and
//! worker; `PostgreSQL` lease expiry and claim fencing make an interrupted Work
//! reclaimable without an in-process Runtime mutex.

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

use loom_api::{ApiError, ApiResult, TimelineTarget};
use loom_runtime::{
    ExecutionSessionStore, PinnedWorldReadStore, PlatformClock, PlatformTime, Runtime,
    RuntimeControlStore, RuntimeRevisionStore, SchedulerCommitStore, SemanticProjectionStore,
    TimelineDriverResult, WorkStore, WorldRuntimeBindingStore, WorldStore, WorldTimeStore,
};
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
/// Setting the signal does not revoke an active claim. The worker observes it
/// before each Runtime step, so graceful shutdown stops new claims while the
/// current semantic drive/claim/execute/complete operation is allowed to
/// finish. A supervisor can discard the worker and construct a new one after a
/// process restart; no restart state is kept in Runtime.
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

/// Why a bounded worker run returned.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum WorkerStopReason {
    /// The external process/application signal stopped new Runtime steps.
    ShutdownRequested,
    /// The caller's polling bound was reached.
    PollLimitReached,
}

/// Summary of one bounded application polling run.
#[derive(Clone, Debug)]
pub struct WorkerReport {
    polls: usize,
    stop_reason: WorkerStopReason,
    last_result: Option<TimelineDriverResult>,
}

impl WorkerReport {
    /// Returns the number of Runtime semantic steps completed by the run.
    #[must_use]
    pub const fn polls(&self) -> usize {
        self.polls
    }

    /// Returns why the bounded run stopped.
    #[must_use]
    pub const fn stop_reason(&self) -> WorkerStopReason {
        self.stop_reason
    }

    /// Returns the most recent Runtime driver result, if a step ran.
    #[must_use]
    pub fn last_result(&self) -> Option<&TimelineDriverResult> {
        self.last_result.as_ref()
    }
}

/// One application-owned worker instance for one Timeline target.
///
/// The type intentionally has no `Send`/`Sync` bounds on Runtime, storage
/// futures, resolver objects or Capability SPI. The application chooses a
/// single-thread executor for the process containing this value. Independent
/// worker instances/processes may still drive independent Timelines against
/// shared `PostgreSQL` authority.
pub struct SchedulerWorker<S, C> {
    runtime: Runtime<S>,
    target: TimelineTarget,
    clock: C,
    config: WorkerConfig,
    shutdown: ShutdownSignal,
}

impl<S, C> SchedulerWorker<S, C>
where
    S: WorldStore
        + WorldRuntimeBindingStore
        + WorkStore
        + RuntimeRevisionStore
        + ExecutionSessionStore
        + RuntimeControlStore
        + SchedulerCommitStore
        + WorldTimeStore
        + SemanticProjectionStore
        + PinnedWorldReadStore,
    C: PlatformClock,
{
    /// Creates one worker bound to one Timeline and one application clock.
    #[must_use]
    pub const fn new(
        runtime: Runtime<S>,
        target: TimelineTarget,
        clock: C,
        config: WorkerConfig,
        shutdown: ShutdownSignal,
    ) -> Self {
        Self {
            runtime,
            target,
            clock,
            config,
            shutdown,
        }
    }

    /// Returns the external shutdown signal shared with the process supervisor.
    #[must_use]
    pub fn shutdown_signal(&self) -> ShutdownSignal {
        self.shutdown.clone()
    }

    /// Runs at most `poll_limit` semantic Runtime steps.
    ///
    /// Polling cadence, process restart and any sleep/backoff between calls are
    /// intentionally left to the application. Each step samples platform time
    /// once, computes only operational lease/retry deadlines, and delegates
    /// head selection, claim/fence, semantic execution, completion/retry and
    /// World-Time CAS to Runtime.
    ///
    /// A shutdown request is checked before a step, so no new claim starts
    /// after the signal is observed. If a Runtime step returns an error, the
    /// error is returned to the application supervisor, which decides whether
    /// and how to rebuild the process-owned Runtime.
    ///
    /// # Errors
    ///
    /// Returns the Runtime/API error from the semantic step, including an
    /// operational deadline overflow or an authority failure. The caller owns
    /// the restart decision after an error.
    pub async fn run_bounded(&mut self, poll_limit: usize) -> ApiResult<WorkerReport> {
        let mut last_result = None;
        for polls in 0..poll_limit {
            if self.shutdown.is_requested() {
                return Ok(WorkerReport {
                    polls,
                    stop_reason: WorkerStopReason::ShutdownRequested,
                    last_result,
                });
            }

            let now = self.clock.now();
            let claimed_until = add_platform_duration(now, self.config.lease_duration())?;
            let retry_available_at = add_platform_duration(now, self.config.retry_backoff())?;
            last_result = Some(
                self.runtime
                    .drive_timeline(self.target, now, claimed_until, retry_available_at)
                    .await?,
            );
        }

        Ok(WorkerReport {
            polls: poll_limit,
            stop_reason: WorkerStopReason::PollLimitReached,
            last_result,
        })
    }

    /// Consumes the worker so an application supervisor can rebuild a Runtime
    /// after a fatal process-owned error without adding restart state to
    /// Runtime or persistence.
    #[must_use]
    pub fn into_runtime(self) -> Runtime<S> {
        self.runtime
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
    use loom_api::TimelineTarget;
    use loom_capability::CapabilityRegistry;
    use loom_core::{TimelineId, WorldId};
    use loom_runtime::{ManualPlatformClock, PlatformTime, Runtime};
    use loom_storage::InMemoryStore;

    use super::{
        ApplicationApi, SchedulerWorker, ShutdownSignal, SystemClock, SystemEntropySource,
        WorkerConfig, WorkerStopReason,
    };

    fn assert_send_sync<T: Send + Sync>() {}

    #[test]
    fn transport_owned_state_has_the_only_cross_thread_send_sync_boundary() {
        // The HTTP/SSE composition requires Send + Sync for its shared API
        // object. Runtime worker values intentionally remain on a
        // current-thread executor and are not asserted here.
        assert_send_sync::<ApplicationApi>();
        assert_send_sync::<SystemClock>();
        assert_send_sync::<SystemEntropySource>();
        assert_send_sync::<ShutdownSignal>();
    }

    fn id<T>(value: u128) -> T
    where
        T: std::str::FromStr,
        T::Err: std::fmt::Debug,
    {
        format!("00000000-0000-0000-0000-{value:012x}")
            .parse()
            .expect("test identity should parse")
    }

    #[tokio::test(flavor = "current_thread")]
    async fn worker_is_bounded_and_uses_single_thread_runtime_boundary() {
        let store = InMemoryStore::new();
        let world_id: WorldId = id(0x100);
        let timeline_id: TimelineId = id(0x101);
        store
            .create_timeline(world_id, timeline_id)
            .expect("Timeline fixture should be created");
        let runtime =
            Runtime::new(store, CapabilityRegistry::new()).expect("empty registry should assemble");
        let config = WorkerConfig::new(10, 1).expect("worker timings should be valid");
        let mut worker = SchedulerWorker::new(
            runtime,
            TimelineTarget::new(world_id, timeline_id),
            ManualPlatformClock::new(PlatformTime::new(7)),
            config,
            ShutdownSignal::new(),
        );

        let report = worker
            .run_bounded(2)
            .await
            .expect("bounded worker run should succeed");
        assert_eq!(report.polls(), 2);
        assert_eq!(report.stop_reason(), WorkerStopReason::PollLimitReached);
        assert!(matches!(
            report.last_result(),
            Some(loom_runtime::TimelineDriverResult::Idle { .. })
        ));
    }

    #[tokio::test(flavor = "current_thread")]
    async fn shutdown_stops_before_a_new_claim() {
        let store = InMemoryStore::new();
        let world_id: WorldId = id(0x200);
        let timeline_id: TimelineId = id(0x201);
        store
            .create_timeline(world_id, timeline_id)
            .expect("Timeline fixture should be created");
        let runtime =
            Runtime::new(store, CapabilityRegistry::new()).expect("empty registry should assemble");
        let shutdown = ShutdownSignal::new();
        shutdown.request();
        let mut worker = SchedulerWorker::new(
            runtime,
            TimelineTarget::new(world_id, timeline_id),
            ManualPlatformClock::new(PlatformTime::new(7)),
            WorkerConfig::new(10, 1).expect("worker timings should be valid"),
            shutdown,
        );

        let report = worker
            .run_bounded(10)
            .await
            .expect("shutdown should be a normal worker result");
        assert_eq!(report.polls(), 0);
        assert_eq!(report.stop_reason(), WorkerStopReason::ShutdownRequested);
        assert!(report.last_result().is_none());
    }
}
