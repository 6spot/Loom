//! Application-owned shell for target-neutral Scheduler supervision.
//!
//! The Supervisor owns the process-local pieces needed by bounded
//! discovery/drive cycles. It deliberately does not own a fixed
//! [`loom_api::TimelineTarget`]: target identities are discovered through the
//! Runtime-owned discovery port for each cycle.

use loom_api::{ApiError, ApiResult, TimelineTarget};
use loom_runtime::{
    ExecutionSessionStore, PinnedWorldReadStore, PlatformClock, Runtime, RuntimeControlStore,
    RuntimeRevisionStore, SchedulerCommitStore, SchedulerDiscoveryCursor, SchedulerDiscoveryError,
    SchedulerDiscoveryRequest, SchedulerDiscoveryStore, SchedulerDiscoveryTarget,
    SemanticProjectionStore, TimelineDriverResult, WorkStore, WorldRuntimeBindingStore, WorldStore,
    WorldTimeStore,
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

/// The outcome of driving one discovered Timeline during a Supervisor cycle.
///
/// This is an application-owned operational report. The `TimelineDriverResult`
/// remains the Runtime-owned semantic outcome; the Supervisor only associates
/// it with the advisory target that it passed back to Runtime.
#[derive(Clone, Debug, PartialEq)]
pub struct SchedulerDriveOutcome {
    target: TimelineTarget,
    result: TimelineDriverResult,
}

impl SchedulerDriveOutcome {
    /// Returns the exact Timeline target passed to Runtime for this drive.
    #[must_use]
    pub const fn target(&self) -> TimelineTarget {
        self.target
    }

    /// Returns the normal Runtime result for this target.
    #[must_use]
    pub const fn result(&self) -> &TimelineDriverResult {
        &self.result
    }
}

/// Small application-owned report for one bounded discovery/drive cycle.
///
/// The report is intentionally limited to advisory targets and their Runtime
/// outcomes. It is not a public API DTO and contains no Work claim, logical
/// head, lease or persistence state.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct SchedulerCycleReport {
    discovered_targets: Vec<TimelineTarget>,
    outcomes: Vec<SchedulerDriveOutcome>,
}

impl SchedulerCycleReport {
    /// Returns the targets returned by the bounded discovery page.
    #[must_use]
    pub fn discovered_targets(&self) -> &[TimelineTarget] {
        &self.discovered_targets
    }

    /// Returns the per-target Runtime outcomes in discovery order.
    #[must_use]
    pub fn outcomes(&self) -> &[SchedulerDriveOutcome] {
        &self.outcomes
    }

    /// Returns how many targets the discovery page contained.
    #[must_use]
    pub const fn discovered_count(&self) -> usize {
        self.discovered_targets.len()
    }

    /// Returns how many Runtime drive calls completed normally.
    #[must_use]
    pub const fn driven_count(&self) -> usize {
        self.outcomes.len()
    }
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

    /// Discovers and drives one bounded page of Scheduler Timeline targets.
    ///
    /// The existing `WorkerConfig::scheduler_poll_limit` is used as both the
    /// Runtime discovery page size and the maximum number of sequential drive
    /// calls. Platform time is sampled separately for each target, and the
    /// resulting lease/retry deadlines are passed to Runtime unchanged from
    /// the existing worker contract. Runtime remains responsible for logical
    /// head selection, claimability, semantic execution, retries, commits and
    /// World-Time advancement.
    ///
    /// Normal `TimelineDriverResult` values, including Blocked, Idle,
    /// Advanced and chronology-budget outcomes, are recorded per target and
    /// do not stop the cycle. A genuine Runtime or discovery error is returned
    /// to the application owner.
    ///
    /// # Errors
    ///
    /// Returns a boundary-safe API error when discovery cannot be performed or
    /// a Runtime drive step fails. An invalid configured page bound is also
    /// reported before any drive call is attempted.
    pub async fn run_cycle(&mut self) -> ApiResult<SchedulerCycleReport> {
        let request = SchedulerDiscoveryRequest::new(self.worker_config.scheduler_poll_limit())
            .map_err(|error| map_discovery_error(&error))?;
        let request = self
            .discovery_cursor
            .map_or(request, |cursor| request.with_cursor(cursor));
        let page = self
            .runtime
            .discover_scheduler_targets(request)
            .await
            .map_err(|error| map_discovery_error(&error))?;
        // The cursor is only an operational hint. A missing continuation means
        // that this read reached the ordered scan end, including the case where
        // a previously remembered frontier no longer has a successor. Clear it
        // so the next successful cycle wraps to the beginning.
        self.discovery_cursor = if page.targets.is_empty() {
            None
        } else {
            page.continuation()
        };
        let discovered_targets = page
            .targets
            .into_iter()
            .map(SchedulerDiscoveryTarget::timeline_target)
            .collect::<Vec<_>>();
        let mut outcomes = Vec::with_capacity(discovered_targets.len());

        for target in &discovered_targets {
            let now = self.clock.now();
            let claimed_until =
                crate::add_platform_duration(now, self.worker_config.lease_duration())?;
            let retry_available_at =
                crate::add_platform_duration(now, self.worker_config.retry_backoff())?;
            let result = self
                .runtime
                .drive_timeline(*target, now, claimed_until, retry_available_at)
                .await?;
            outcomes.push(SchedulerDriveOutcome {
                target: *target,
                result,
            });
        }

        Ok(SchedulerCycleReport {
            discovered_targets,
            outcomes,
        })
    }
}

fn map_discovery_error(error: &SchedulerDiscoveryError) -> ApiError {
    match error {
        SchedulerDiscoveryError::InvalidPageSize { .. } => {
            ApiError::invalid_request("Scheduler discovery page bound is invalid")
        }
        SchedulerDiscoveryError::StorageUnavailable { .. } => {
            ApiError::unavailable("Scheduler discovery is unavailable")
        }
    }
}

#[cfg(test)]
mod tests {
    use loom_capability::CapabilityRegistry;
    use loom_core::{SchemaRevision, TimelineId, WorkHandlerId, WorkId, WorldId, WorldInstant};
    use loom_runtime::{
        ManualPlatformClock, PlatformClock, PlatformTime, Runtime, RuntimeRevisionDescriptor,
        RuntimeRevisionId, WorkRecord, WorkStatus, WorkTarget, WorkTerminalState,
        WorkTerminalization, WorldRuntimeBinding,
    };
    use loom_storage::InMemoryStore;
    use std::sync::atomic::{AtomicBool, Ordering};

    use super::SchedulerSupervisor;
    use crate::{ShutdownSignal, WorkerConfig};

    fn id<T>(value: u128) -> T
    where
        T: std::str::FromStr,
        T::Err: std::fmt::Debug,
    {
        format!("00000000-0000-0000-0000-{value:012x}")
            .parse()
            .expect("test identity should parse")
    }

    fn pending_work(timeline_id: TimelineId, work_id: WorkId) -> WorkRecord {
        WorkRecord {
            id: work_id,
            timeline_id,
            target: WorkTarget::CapabilityWork {
                owner: None,
                handler: WorkHandlerId::from("missing.scheduler.handler"),
            },
            schema_revision: SchemaRevision::new(1),
            payload: false.into(),
            effective_due_world_time: WorldInstant::default(),
            logical_schedule_order: 1,
            causal_event_id: None,
            origin_work_id: None,
            status: WorkStatus::Pending,
            attempt_count: 0,
            claim_generation: 0,
            available_at: PlatformTime::default(),
            last_error: None,
            lease: None,
        }
    }

    fn worker_config(limit: usize) -> WorkerConfig {
        WorkerConfig::new(10, 1)
            .expect("worker timings should be valid")
            .with_scheduler_poll_limit(limit)
            .expect("scheduler limit should be valid")
    }

    fn seed_pending_targets(
        store: &InMemoryStore,
        world_id: WorldId,
        timeline_start: u128,
        work_start: u128,
        count: usize,
    ) -> Vec<(loom_api::TimelineTarget, WorkId)> {
        (0..count)
            .map(|offset| {
                let offset = offset as u128;
                let timeline_id: TimelineId = id(timeline_start + offset);
                let work_id: WorkId = id(work_start + offset);
                store
                    .create_timeline(world_id, timeline_id)
                    .expect("test Timeline should be created");
                store
                    .seed_work(pending_work(timeline_id, work_id))
                    .expect("Pending Work should be seeded");
                (
                    loom_api::TimelineTarget::new(world_id, timeline_id),
                    work_id,
                )
            })
            .collect()
    }

    fn blocked_runtime(store: &InMemoryStore, world_id: WorldId) -> Runtime<&InMemoryStore> {
        let registry = CapabilityRegistry::new();
        store
            .persist_binding(
                world_id,
                WorldRuntimeBinding::new(Vec::new(), false.into(), 1, None),
            )
            .expect("test Runtime binding should be persisted");
        let revision = RuntimeRevisionDescriptor::new(
            RuntimeRevisionId::from("scheduler-supervisor-test"),
            PlatformTime::default(),
            "scheduler-supervisor-test-build",
            registry.loom_version().clone(),
            Vec::new(),
        )
        .expect("empty test Runtime Revision should be valid");
        store
            .confirm_revision(revision.clone())
            .expect("test Runtime Revision should be confirmed");
        store
            .activate_revision(revision.id().clone(), None, PlatformTime::default())
            .expect("test Runtime Revision should be activated");
        Runtime::new(store, registry).expect("test Runtime should assemble")
    }

    struct ClearingClock<'a> {
        store: &'a InMemoryStore,
        timeline_id: TimelineId,
        work_id: WorkId,
        cleared: AtomicBool,
    }

    impl PlatformClock for ClearingClock<'_> {
        fn now(&self) -> PlatformTime {
            if !self.cleared.swap(true, Ordering::AcqRel) {
                let version = self
                    .store
                    .snapshot(self.timeline_id)
                    .expect("stale-discovery Timeline should exist")
                    .version();
                let terminalization = WorkTerminalization::new(
                    self.timeline_id,
                    version,
                    self.work_id,
                    WorkTerminalState::Cancelled,
                    PlatformTime::new(7),
                );
                self.store
                    .terminalize_work(&terminalization)
                    .expect("stale-discovery Work should be terminalized");
            }
            PlatformTime::new(7)
        }
    }

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

    #[tokio::test(flavor = "current_thread")]
    async fn empty_discovery_performs_zero_drive_calls() {
        let store = InMemoryStore::new();
        let runtime = Runtime::new(&store, CapabilityRegistry::new())
            .expect("empty registry should assemble");
        let mut supervisor = SchedulerSupervisor::new(
            runtime,
            ManualPlatformClock::new(PlatformTime::new(7)),
            WorkerConfig::new(10, 1)
                .expect("worker timings should be valid")
                .with_scheduler_poll_limit(4)
                .expect("scheduler limit should be valid"),
            ShutdownSignal::new(),
        );

        let report = supervisor
            .run_cycle()
            .await
            .expect("empty discovery should be a successful cycle");

        assert_eq!(report.discovered_count(), 0);
        assert_eq!(report.driven_count(), 0);
        assert!(report.discovered_targets().is_empty());
        assert!(report.outcomes().is_empty());
    }

    #[tokio::test(flavor = "current_thread")]
    async fn one_discovered_target_performs_exactly_one_drive_step() {
        let store = InMemoryStore::new();
        let world_id: WorldId = id(0x100);
        let timeline_id: TimelineId = id(0x101);
        store
            .create_timeline(world_id, timeline_id)
            .expect("test Timeline should be created");
        store
            .seed_work(pending_work(timeline_id, id(0x102)))
            .expect("Pending Work should be seeded");
        let runtime = blocked_runtime(&store, world_id);
        let target = loom_api::TimelineTarget::new(world_id, timeline_id);
        let mut supervisor = SchedulerSupervisor::new(
            runtime,
            ManualPlatformClock::new(PlatformTime::new(7)),
            WorkerConfig::new(10, 1)
                .expect("worker timings should be valid")
                .with_scheduler_poll_limit(4)
                .expect("scheduler limit should be valid"),
            ShutdownSignal::new(),
        );

        let report = supervisor
            .run_cycle()
            .await
            .expect("one discovered target should be driven");

        assert_eq!(report.discovered_targets(), &[target]);
        assert_eq!(report.driven_count(), 1);
        assert_eq!(report.outcomes()[0].target(), target);
    }

    #[tokio::test(flavor = "current_thread")]
    async fn discovered_targets_are_driven_at_most_to_the_configured_bound() {
        let store = InMemoryStore::new();
        let world_id: WorldId = id(0x200);
        let all_targets: Vec<_> = (0..4)
            .map(|offset| {
                let timeline_id: TimelineId = id(0x210 + offset);
                store
                    .create_timeline(world_id, timeline_id)
                    .expect("test Timeline should be created");
                store
                    .seed_work(pending_work(timeline_id, id(0x220 + offset)))
                    .expect("Pending Work should be seeded");
                loom_api::TimelineTarget::new(world_id, timeline_id)
            })
            .collect();
        let runtime = blocked_runtime(&store, world_id);
        let limit = 2;
        let mut supervisor = SchedulerSupervisor::new(
            runtime,
            ManualPlatformClock::new(PlatformTime::new(7)),
            WorkerConfig::new(10, 1)
                .expect("worker timings should be valid")
                .with_scheduler_poll_limit(limit)
                .expect("scheduler limit should be valid"),
            ShutdownSignal::new(),
        );

        let report = supervisor
            .run_cycle()
            .await
            .expect("bounded discovery should be a successful cycle");

        assert_eq!(report.discovered_count(), limit);
        assert_eq!(report.driven_count(), limit);
        assert_eq!(report.discovered_targets(), &all_targets[..limit]);
    }

    #[tokio::test(flavor = "current_thread")]
    async fn bounded_cycles_visit_every_target_and_wrap_after_the_scan_end() {
        let store = InMemoryStore::new();
        let world_id: WorldId = id(0x500);
        let seeded = seed_pending_targets(&store, world_id, 0x510, 0x520, 4);
        let expected = seeded.iter().map(|(target, _)| *target).collect::<Vec<_>>();
        let runtime = blocked_runtime(&store, world_id);
        let mut supervisor = SchedulerSupervisor::new(
            runtime,
            ManualPlatformClock::new(PlatformTime::new(7)),
            worker_config(2),
            ShutdownSignal::new(),
        );

        let first = supervisor
            .run_cycle()
            .await
            .expect("first bounded cycle should succeed");
        let second = supervisor
            .run_cycle()
            .await
            .expect("second bounded cycle should succeed");
        let third = supervisor
            .run_cycle()
            .await
            .expect("wrapped bounded cycle should succeed");

        assert_eq!(first.discovered_targets(), &expected[..2]);
        assert_eq!(second.discovered_targets(), &expected[2..4]);
        assert_eq!(third.discovered_targets(), &expected[..2]);
        assert!(first.outcomes().iter().all(|outcome| matches!(
            outcome.result(),
            loom_runtime::TimelineDriverResult::Blocked { .. }
        )));
    }

    #[tokio::test(flavor = "current_thread")]
    async fn permanently_blocked_first_target_does_not_starve_later_targets() {
        let store = InMemoryStore::new();
        let world_id: WorldId = id(0x550);
        let seeded = seed_pending_targets(&store, world_id, 0x560, 0x570, 3);
        let expected = seeded.iter().map(|(target, _)| *target).collect::<Vec<_>>();
        let runtime = blocked_runtime(&store, world_id);
        let mut supervisor = SchedulerSupervisor::new(
            runtime,
            ManualPlatformClock::new(PlatformTime::new(7)),
            worker_config(1),
            ShutdownSignal::new(),
        );

        for expected_target in expected {
            let report = supervisor
                .run_cycle()
                .await
                .expect("a normal Blocked result should not fail the cycle");

            assert_eq!(report.discovered_targets(), &[expected_target]);
            assert!(matches!(
                report.outcomes()[0].result(),
                loom_runtime::TimelineDriverResult::Blocked { .. }
            ));
        }
    }

    #[tokio::test(flavor = "current_thread")]
    async fn terminalizing_the_cursor_adjacent_target_does_not_wedge_discovery() {
        let store = InMemoryStore::new();
        let world_id: WorldId = id(0x580);
        let seeded = seed_pending_targets(&store, world_id, 0x590, 0x5a0, 3);
        let expected = seeded.iter().map(|(target, _)| *target).collect::<Vec<_>>();
        let runtime = blocked_runtime(&store, world_id);
        let mut supervisor = SchedulerSupervisor::new(
            runtime,
            ManualPlatformClock::new(PlatformTime::new(7)),
            worker_config(2),
            ShutdownSignal::new(),
        );

        let first = supervisor
            .run_cycle()
            .await
            .expect("first bounded cycle should succeed");
        assert_eq!(first.discovered_targets(), &expected[..2]);

        let cursor_adjacent = &seeded[1];
        let version = store
            .snapshot(cursor_adjacent.0.timeline_id)
            .expect("cursor-adjacent Timeline should exist")
            .version();
        store
            .terminalize_work(&WorkTerminalization::new(
                cursor_adjacent.0.timeline_id,
                version,
                cursor_adjacent.1,
                WorkTerminalState::Cancelled,
                PlatformTime::new(7),
            ))
            .expect("cursor-adjacent Work should be terminalized");

        let second = supervisor
            .run_cycle()
            .await
            .expect("discovery should recover after target removal");

        assert_eq!(second.discovered_targets(), &[expected[2]]);
    }

    #[tokio::test(flavor = "current_thread")]
    async fn an_empty_page_after_the_cursor_resets_the_next_cycle_to_the_beginning() {
        let store = InMemoryStore::new();
        let world_id: WorldId = id(0x5a0);
        let seeded = seed_pending_targets(&store, world_id, 0x5b0, 0x5c0, 2);
        let first_target = seeded[0].0;
        let removed_target = &seeded[1];
        let runtime = blocked_runtime(&store, world_id);
        let mut supervisor = SchedulerSupervisor::new(
            runtime,
            ManualPlatformClock::new(PlatformTime::new(7)),
            worker_config(1),
            ShutdownSignal::new(),
        );

        let first = supervisor
            .run_cycle()
            .await
            .expect("first bounded cycle should succeed");
        assert_eq!(first.discovered_targets(), &[first_target]);

        let version = store
            .snapshot(removed_target.0.timeline_id)
            .expect("removed Timeline should exist")
            .version();
        store
            .terminalize_work(&WorkTerminalization::new(
                removed_target.0.timeline_id,
                version,
                removed_target.1,
                WorkTerminalState::Cancelled,
                PlatformTime::new(7),
            ))
            .expect("removed Work should be terminalized");

        let empty = supervisor
            .run_cycle()
            .await
            .expect("an empty post-cursor page should be successful");
        assert!(empty.discovered_targets().is_empty());

        let wrapped = supervisor
            .run_cycle()
            .await
            .expect("the cursor should recover after an empty page");
        assert_eq!(wrapped.discovered_targets(), &[first_target]);
    }

    #[tokio::test(flavor = "current_thread")]
    async fn newly_added_later_target_becomes_reachable_without_restarting_supervisor() {
        let store = InMemoryStore::new();
        let world_id: WorldId = id(0x5b0);
        let seeded = seed_pending_targets(&store, world_id, 0x5c0, 0x5d0, 3);
        let expected = seeded.iter().map(|(target, _)| *target).collect::<Vec<_>>();
        let runtime = blocked_runtime(&store, world_id);
        let mut supervisor = SchedulerSupervisor::new(
            runtime,
            ManualPlatformClock::new(PlatformTime::new(7)),
            worker_config(2),
            ShutdownSignal::new(),
        );

        let first = supervisor
            .run_cycle()
            .await
            .expect("first bounded cycle should succeed");
        assert_eq!(first.discovered_targets(), &expected[..2]);

        let later_timeline_id: TimelineId = id(0x5c3);
        let later_work_id: WorkId = id(0x5d3);
        store
            .create_timeline(world_id, later_timeline_id)
            .expect("new later Timeline should be created");
        store
            .seed_work(pending_work(later_timeline_id, later_work_id))
            .expect("new later Pending Work should be seeded");
        let later_target = loom_api::TimelineTarget::new(world_id, later_timeline_id);

        let second = supervisor
            .run_cycle()
            .await
            .expect("new later target should be discovered");

        assert_eq!(second.discovered_targets(), &[expected[2], later_target]);
    }

    #[tokio::test(flavor = "current_thread")]
    async fn normal_blocked_result_is_a_per_target_outcome_not_a_cycle_error() {
        let store = InMemoryStore::new();
        let world_id: WorldId = id(0x300);
        let timeline_id: TimelineId = id(0x301);
        store
            .create_timeline(world_id, timeline_id)
            .expect("test Timeline should be created");
        store
            .seed_work(pending_work(timeline_id, id(0x302)))
            .expect("Pending Work should be seeded");
        let runtime = blocked_runtime(&store, world_id);
        let mut supervisor = SchedulerSupervisor::new(
            runtime,
            ManualPlatformClock::new(PlatformTime::new(7)),
            WorkerConfig::new(10, 1).expect("worker timings should be valid"),
            ShutdownSignal::new(),
        );

        let report = supervisor
            .run_cycle()
            .await
            .expect("a normal Blocked result must not fail the cycle");

        assert!(matches!(
            report.outcomes()[0].result(),
            loom_runtime::TimelineDriverResult::Blocked { .. }
        ));
    }

    #[tokio::test(flavor = "current_thread")]
    async fn normal_idle_result_from_a_stale_discovery_is_not_a_cycle_error() {
        let store = InMemoryStore::new();
        let world_id: WorldId = id(0x350);
        let timeline_id: TimelineId = id(0x351);
        let work_id: WorkId = id(0x352);
        store
            .create_timeline(world_id, timeline_id)
            .expect("test Timeline should be created");
        store
            .seed_work(pending_work(timeline_id, work_id))
            .expect("Pending Work should be seeded");
        let runtime = Runtime::new(&store, CapabilityRegistry::new())
            .expect("empty registry should assemble");
        let mut supervisor = SchedulerSupervisor::new(
            runtime,
            ClearingClock {
                store: &store,
                timeline_id,
                work_id,
                cleared: AtomicBool::new(false),
            },
            WorkerConfig::new(10, 1).expect("worker timings should be valid"),
            ShutdownSignal::new(),
        );

        let report = supervisor
            .run_cycle()
            .await
            .expect("a normal Idle result must not fail the cycle");

        assert_eq!(report.driven_count(), 1);
        assert!(matches!(
            report.outcomes()[0].result(),
            loom_runtime::TimelineDriverResult::Idle { .. }
        ));
    }

    #[tokio::test(flavor = "current_thread")]
    async fn each_drive_outcome_keeps_the_exact_discovered_target() {
        let store = InMemoryStore::new();
        let world_id: WorldId = id(0x400);
        let targets: Vec<_> = (0..2)
            .map(|offset| {
                let timeline_id: TimelineId = id(0x410 + offset);
                store
                    .create_timeline(world_id, timeline_id)
                    .expect("test Timeline should be created");
                store
                    .seed_work(pending_work(timeline_id, id(0x420 + offset)))
                    .expect("Pending Work should be seeded");
                loom_api::TimelineTarget::new(world_id, timeline_id)
            })
            .collect();
        let runtime = blocked_runtime(&store, world_id);
        let mut supervisor = SchedulerSupervisor::new(
            runtime,
            ManualPlatformClock::new(PlatformTime::new(7)),
            WorkerConfig::new(10, 1)
                .expect("worker timings should be valid")
                .with_scheduler_poll_limit(2)
                .expect("scheduler limit should be valid"),
            ShutdownSignal::new(),
        );

        let report = supervisor
            .run_cycle()
            .await
            .expect("discovered targets should be driven");

        let driven_targets = report
            .outcomes()
            .iter()
            .map(super::SchedulerDriveOutcome::target)
            .collect::<Vec<_>>();
        assert_eq!(driven_targets, targets);
    }
}
