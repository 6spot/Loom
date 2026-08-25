//! Public-consumer validator skeleton for Loom.
//!
//! The validator is intentionally an upper-layer consumer. Scenario code must
//! use the formal [`loom_client`] surface and must not construct or inspect
//! Runtime, Storage, or transport implementation authority directly.

#![forbid(unsafe_code)]

mod backend;
mod cli;
mod feedback;
mod finding;
mod mock;
mod outcome;
mod registry;
mod reports;
mod runner;
mod scenario;
pub mod scenarios;

pub use backend::{
    BackendContext, BackendError, BackendHarness, BackendStart, DEFAULT_VALIDATOR_BASE_URL,
    LOOM_TEST_POSTGRES_URL, LOOM_VALIDATOR_BASE_URL,
};
pub use cli::{
    CliAction, CliArgs, EXIT_RUNNER_ERROR, EXIT_SCENARIO_FAILURE, EXIT_SUCCESS, decide_action,
    execute_cli, help_text, parse_args, run_from_args,
};
pub use feedback::{
    FeedbackAppendSummary, TaskLedgerFeedback, TaskLedgerFeedbackError,
    append_report_to_task_ledger, feedback_exit_code,
};
pub use finding::{EvidenceReference, Finding};
pub use outcome::ScenarioOutcome;
pub use registry::{RegistryError, ScenarioRegistry};
pub use reports::{
    MachineReport, PrerequisiteDetail, PrerequisiteState, REPORT_KIND, REPORT_SCHEMA_VERSION,
    ReportResultState, RunMetadata, ScenarioResult, TaskRecordReference, ValidationPolicy,
    ValidationReport,
};
pub use runner::{Runner, RunnerError};
pub use scenario::{BackendKind, CapabilityArea, ScenarioDescriptor, ScenarioId};
pub use scenarios::{
    CV_005, CV_006, CV_007, CV_008, CV_009, execute_replay_fork, register_replay_fork,
    replay_fork_descriptors,
};

/// Builds the current validator registry containing all stable scenario IDs.
///
/// The bootstrap registry remains empty for unit-test determinism. This
/// function returns the registry that the CLI and harness use in production.
/// It currently includes the replay/fork branch-isolation scenarios (`CV-005`
/// through `CV-009`). Future leaves extend this function without changing
/// `bootstrap` semantics.
///
/// # Panics
///
/// Panics if the replay/fork scenario registration fails due to a duplicate
/// stable ID. This indicates a programming error in the scenario descriptors.
#[must_use]
pub fn validator_registry() -> ScenarioRegistry {
    let mut registry = ScenarioRegistry::bootstrap();
    // Replay/fork scenarios are stable and deterministic; registration must not
    // silently ignore duplicates, so we expect success.
    register_replay_fork(&mut registry).expect("replay/fork scenario registration should succeed");
    registry
}

#[cfg(test)]
mod tests {
    use super::{Runner, ScenarioRegistry};

    #[test]
    fn bootstrap_registry_is_empty() {
        let registry = ScenarioRegistry::bootstrap();

        assert!(registry.is_empty());
        assert_eq!(registry.len(), 0);
        assert_eq!(registry.iter().count(), 0);
    }

    #[test]
    fn runner_enumerates_bootstrap_registry() {
        let report = Runner::new(ScenarioRegistry::bootstrap()).run();

        assert_eq!(report.scenario_count(), 0);
        assert!(report.is_empty());
    }
}
