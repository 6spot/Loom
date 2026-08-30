//! Application-owned shell for target-neutral Scheduler supervision.
//!
//! The Supervisor owns the process-local pieces needed by the later bounded
//! discovery/drive cycles. It deliberately does not own a fixed
//! [`loom_api::TimelineTarget`]: target identities are discovered through the
//! Runtime-owned discovery port when the cycle is implemented.

use loom_runtime::{
    ExecutionSessionStore, PinnedWorldReadStore, PlatformClock, Runtime, RuntimeControlStore,
    RuntimeRevisionStore, SchedulerCommitStore, SchedulerDiscoveryCursor, SchedulerDiscoveryStore,
    SemanticProjectionStore, WorkStore, WorldRuntimeBindingStore, WorldStore, WorldTimeStore,
};

use crate::{ShutdownSignal, WorkerConfig};

/// Application-owned, target-neutral Scheduler Supervisor state.
///
/// This is only the lifecycle shell for the automatic discovery path. It owns
/// one Runtime and one application clock, while discovery remains an
/// operational observation and all Timeline semantic authority remains in
/// Runtime. The cursor is an in-memory enumeration frontier; it is not
/// persisted Timeline state and does not select a logical Work head.
///
/// The generic bounds are the union of the Runtime discovery and existing
/// Timeline-drive ports. They keep this application helper independent of a
/// concrete persistence adapter such as `PgStorage`.
#[allow(dead_code)]
pub struct SchedulerSupervisor<S, C> {
    runtime: Runtime<S>,
    clock: C,
    worker_config: WorkerConfig,
    shutdown: ShutdownSignal,
    discovery_cursor: Option<SchedulerDiscoveryCursor>,
}

impl<S, C> SchedulerSupervisor<S, C>
where
    S: SchedulerDiscoveryStore
        + WorldStore
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
    /// Creates a target-neutral Supervisor over one Runtime authority.
    ///
    /// No World or Timeline identity is required. Later discovery cycles use
    /// the Runtime-owned `SchedulerDiscoveryStore` port to obtain advisory
    /// Timeline identities before delegating each drive to Runtime.
    #[must_use]
    pub const fn new(
        runtime: Runtime<S>,
        clock: C,
        worker_config: WorkerConfig,
        shutdown: ShutdownSignal,
    ) -> Self {
        Self {
            runtime,
            clock,
            worker_config,
            shutdown,
            discovery_cursor: None,
        }
    }

    /// Returns the external shutdown signal shared with the process
    /// supervisor and other application workers.
    #[must_use]
    pub fn shutdown_signal(&self) -> ShutdownSignal {
        self.shutdown.clone()
    }
}

#[cfg(test)]
mod tests {
    use loom_capability::CapabilityRegistry;
    use loom_runtime::{ManualPlatformClock, PlatformTime, Runtime};
    use loom_storage::InMemoryStore;

    use super::SchedulerSupervisor;
    use crate::{ShutdownSignal, WorkerConfig};

    fn runtime() -> Runtime<InMemoryStore> {
        Runtime::new(InMemoryStore::new(), CapabilityRegistry::new())
            .expect("empty registry should assemble")
    }

    #[test]
    fn supervisor_is_constructible_without_a_fixed_timeline_target() {
        let supervisor = SchedulerSupervisor::new(
            runtime(),
            ManualPlatformClock::new(PlatformTime::new(7)),
            WorkerConfig::new(10, 1).expect("worker timings should be valid"),
            ShutdownSignal::new(),
        );

        assert!(!supervisor.shutdown_signal().is_requested());
    }

    #[test]
    fn supervisor_shares_shutdown_signal_with_its_owner() {
        let shutdown = ShutdownSignal::new();
        let supervisor = SchedulerSupervisor::new(
            runtime(),
            ManualPlatformClock::new(PlatformTime::new(7)),
            WorkerConfig::new(10, 1).expect("worker timings should be valid"),
            shutdown.clone(),
        );

        let owned_signal = supervisor.shutdown_signal();
        owned_signal.request();

        assert!(shutdown.is_requested());
        assert!(supervisor.shutdown_signal().is_requested());
    }
}
