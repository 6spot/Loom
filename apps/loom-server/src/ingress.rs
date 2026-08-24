//! Bounded application-owned durable Ingress processing worker.

use std::time::Duration;

use loom_api::{ApiResult, IngressId};
use loom_runtime::{
    ExecutionSessionStore, IngressStore, PlatformClock, Runtime, RuntimeControlStore,
    RuntimeRevisionStore, SchedulerCommitStore, SemanticProjectionStore, WorkStore,
    WorldRuntimeBindingStore, WorldStore, WorldTimeStore,
};
use tokio::{sync::mpsc, time::timeout};

use crate::{ShutdownSignal, WorkerConfig, add_platform_duration};

const RECOVERY_BATCH_SIZE: usize = 256;

/// Why one bounded Ingress worker run returned.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IngressWorkerStopReason {
    /// The process supervisor requested graceful shutdown.
    ShutdownRequested,
    /// The bounded item limit was reached.
    PollLimitReached,
    /// No item arrived during the bounded wait interval.
    NoWorkAvailable,
    /// The producer side of the queue was closed.
    QueueClosed,
}

/// Summary of one bounded Ingress processing run.
#[derive(Clone, Debug)]
pub struct IngressWorkerReport {
    processed: usize,
    stop_reason: IngressWorkerStopReason,
    last_ingress_id: Option<IngressId>,
}

impl IngressWorkerReport {
    /// Returns the number of durable Ingress records processed.
    #[must_use]
    pub const fn processed(&self) -> usize {
        self.processed
    }

    /// Returns why the bounded run stopped.
    #[must_use]
    pub const fn stop_reason(&self) -> IngressWorkerStopReason {
        self.stop_reason
    }

    /// Returns the most recent record identity, if one was received.
    #[must_use]
    pub const fn last_ingress_id(&self) -> Option<&IngressId> {
        self.last_ingress_id.as_ref()
    }
}

/// One bounded worker that processes queued Ingress identities through
/// `Runtime::process_ingress`.
///
/// Acceptance remains durable Runtime operational state. The queue is only a
/// bounded wake-up path from the public API to this worker; a record can be
/// submitted again after a process restart and Runtime's idempotency/recovery
/// path will reuse the same durable identity rather than rerunning blindly.
pub struct IngressWorker<S, C> {
    runtime: Runtime<S>,
    receiver: mpsc::Receiver<IngressId>,
    clock: C,
    worker_config: WorkerConfig,
    poll_interval: Duration,
    shutdown: ShutdownSignal,
}

impl<S, C> IngressWorker<S, C>
where
    S: WorldStore
        + WorldRuntimeBindingStore
        + WorkStore
        + RuntimeRevisionStore
        + ExecutionSessionStore
        + RuntimeControlStore
        + SchedulerCommitStore
        + WorldTimeStore
        + IngressStore
        + SemanticProjectionStore,
    C: PlatformClock,
{
    /// Creates an Ingress worker over one Runtime authority and bounded queue.
    #[must_use]
    pub fn new(
        runtime: Runtime<S>,
        receiver: mpsc::Receiver<IngressId>,
        clock: C,
        worker_config: WorkerConfig,
        poll_interval: Duration,
        shutdown: ShutdownSignal,
    ) -> Self {
        Self {
            runtime,
            receiver,
            clock,
            worker_config,
            poll_interval,
            shutdown,
        }
    }

    /// Runs at most `poll_limit` queue items, allowing a caller to apply an
    /// explicit bounded validation or test step.
    ///
    /// # Errors
    ///
    /// Returns the Runtime/API error from the semantic Ingress processing
    /// boundary or an operational deadline overflow.
    pub async fn run_bounded(&mut self, poll_limit: usize) -> ApiResult<IngressWorkerReport> {
        let mut processed = 0;
        let mut last_ingress_id = None;
        while processed < poll_limit {
            if self.shutdown.is_requested() {
                return Ok(IngressWorkerReport {
                    processed,
                    stop_reason: IngressWorkerStopReason::ShutdownRequested,
                    last_ingress_id,
                });
            }

            let next = timeout(self.poll_interval, self.receiver.recv()).await;
            let ingress_id = match next {
                Ok(Some(ingress_id)) => ingress_id,
                Ok(None) => {
                    return Ok(IngressWorkerReport {
                        processed,
                        stop_reason: IngressWorkerStopReason::QueueClosed,
                        last_ingress_id,
                    });
                }
                Err(_) => {
                    return Ok(IngressWorkerReport {
                        processed,
                        stop_reason: IngressWorkerStopReason::NoWorkAvailable,
                        last_ingress_id,
                    });
                }
            };
            self.process_ingress_id(ingress_id.clone()).await?;
            processed += 1;
            last_ingress_id = Some(ingress_id);
        }

        Ok(IngressWorkerReport {
            processed,
            stop_reason: IngressWorkerStopReason::PollLimitReached,
            last_ingress_id,
        })
    }

    /// Waits for queue items until graceful shutdown or queue closure.
    ///
    /// # Errors
    ///
    /// Returns the first Runtime/API error surfaced while processing a queued
    /// Ingress identity.
    pub async fn run_until_shutdown(&mut self) -> ApiResult<()> {
        loop {
            if self.shutdown.is_requested() {
                return Ok(());
            }
            let report = self.run_bounded(1).await?;
            if report.stop_reason() == IngressWorkerStopReason::QueueClosed {
                return Ok(());
            }
            if report.stop_reason() == IngressWorkerStopReason::NoWorkAvailable {
                let recovery_ids = self
                    .runtime
                    .list_recoverable_ingress_ids(self.clock.now(), RECOVERY_BATCH_SIZE)
                    .await?;
                for ingress_id in recovery_ids {
                    if self.shutdown.is_requested() {
                        return Ok(());
                    }
                    self.process_ingress_id(ingress_id).await?;
                }
            }
        }
    }

    async fn process_ingress_id(&self, ingress_id: IngressId) -> ApiResult<()> {
        let now = self.clock.now();
        let claimed_until = add_platform_duration(now, self.worker_config.lease_duration())?;
        let retry_available_at = add_platform_duration(now, self.worker_config.retry_backoff())?;
        self.runtime
            .process_ingress(ingress_id, now, claimed_until, retry_available_at)
            .await
            .map(|_| ())
    }
}
