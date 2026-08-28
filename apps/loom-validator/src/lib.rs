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
mod lifecycle;
#[cfg(test)]
mod mock;
mod outcome;
mod registry;
mod reports;
mod runner;
mod runtime_authority;
mod scenario;
pub mod scenarios;

// Stage-2 suite modules (T10-T18). Each leaf owns exactly one production
// module + one integration-test module; T19 is the sole central composition
// point for their registered descriptors.
pub mod action_ingress;
pub mod agency;
pub mod change_feed;
pub mod provenance;
pub mod query_catalog;
pub mod scheduler;
pub mod semantic_blob;
pub mod world_binding;
pub mod world_time;

pub use backend::{
    BackendContext, BackendError, BackendHarness, BackendStart, DEFAULT_VALIDATOR_BASE_URL,
    LOOM_TEST_POSTGRES_URL, LOOM_VALIDATOR_BASE_URL, RestartCapability,
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
pub use lifecycle::{
    execute as execute_lifecycle, lifecycle_registry, register as register_lifecycle,
};
pub use outcome::ScenarioOutcome;
pub use registry::{RegistryError, ScenarioRegistry};
pub use reports::{
    MachineReport, PrerequisiteDetail, PrerequisiteState, REPORT_KIND, REPORT_SCHEMA_VERSION,
    ReportResultState, RunMetadata, ScenarioResult, TaskRecordReference, ValidationPolicy,
    ValidationReport,
};
pub use runner::{Runner, RunnerError};
pub use runtime_authority::{
    CV_010, CV_011, descriptors as runtime_authority_descriptors, execute_runtime_authority,
    register_runtime_authority,
};
pub use scenario::{BackendEvidence, BackendKind, CapabilityArea, ScenarioDescriptor, ScenarioId};
pub use scenarios::{
    CV_005, CV_006, CV_007, CV_008, CV_009, execute_replay_fork, register_replay_fork,
    replay_fork_descriptors,
};

/// Builds the complete validator registry for all currently registered
/// capability scenarios. Registration is deterministic and duplicate IDs are
/// programming errors.
///
/// # Panics
///
/// Panics if a registered scenario set contains duplicate stable IDs.
#[must_use]
pub fn validator_registry() -> ScenarioRegistry {
    let mut registry = ScenarioRegistry::bootstrap();
    lifecycle::register(&mut registry).expect("lifecycle scenario IDs should be unique");
    register_replay_fork(&mut registry).expect("replay/fork scenario IDs should be unique");
    register_runtime_authority(&mut registry)
        .expect("runtime-authority scenario IDs should be unique");
    register_stage2(&mut registry).expect("Stage-2 scenario IDs should be unique");
    registry
}

/// Composes the completed Stage-2 suites into the one global registry.
///
/// Blocked T08 rows deliberately remain absent: they have no public/controlled
/// authority surface and their owning suites do not provide executable
/// descriptors. The registry is the only central composition point; suite
/// modules retain their own descriptors and execution semantics.
fn register_stage2(registry: &mut ScenarioRegistry) -> Result<(), RegistryError> {
    world_binding::register_world_binding(registry)?;

    register_descriptors(registry, action_ingress::descriptors())?;
    scheduler::register_scheduler(registry)?;
    world_time::register_world_time(registry)?;
    query_catalog::register_query_catalog(registry)?;
    semantic_blob::register(registry)?;
    register_descriptors(registry, provenance::descriptors())?;
    change_feed::register(registry)?;
    Ok(())
}

fn register_descriptors(
    registry: &mut ScenarioRegistry,
    descriptors: impl IntoIterator<Item = ScenarioDescriptor>,
) -> Result<(), RegistryError> {
    for descriptor in descriptors {
        registry.register(descriptor)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{Runner, ScenarioRegistry, validator_registry};

    const EXPECTED_IDS: [&str; 32] = [
        "CV-001", "CV-002", "CV-003", "CV-004", "CV-005", "CV-006", "CV-007", "CV-008", "CV-009",
        "CV-010", "CV-011", "CV-012", "CV-013", "CV-014", "CV-015", "CV-016", "CV-017", "CV-020",
        "CV-021", "CV-022", "CV-023", "CV-024", "CV-025", "CV-026", "CV-027", "CV-030", "CV-031",
        "CV-032", "CV-033", "CV-038", "CV-039", "CV-040",
    ];

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

    #[test]
    fn stage2_registry_is_exact_deterministic_and_duplicate_free() {
        let first = validator_registry();
        let second = validator_registry();
        let first_ids: Vec<_> = first
            .ids()
            .map(crate::scenario::ScenarioId::as_str)
            .collect();
        let second_ids: Vec<_> = second
            .ids()
            .map(crate::scenario::ScenarioId::as_str)
            .collect();
        assert_eq!(first_ids, EXPECTED_IDS);
        assert_eq!(first_ids, second_ids);
        assert_eq!(first.len(), EXPECTED_IDS.len());
        assert_eq!(
            first_ids
                .iter()
                .collect::<std::collections::BTreeSet<_>>()
                .len(),
            first.len()
        );
        for blocked in [
            "CV-018", "CV-019", "CV-028", "CV-029", "CV-034", "CV-035", "CV-036", "CV-037",
        ] {
            assert!(
                first.get(blocked).is_none(),
                "blocked {blocked} must not be registered"
            );
        }
    }

    #[test]
    fn stage2_groups_resolve_exactly_and_unknown_groups_remain_errors() {
        let runner = Runner::new(validator_registry());
        let expected = [
            ("lifecycle", vec!["CV-001", "CV-002", "CV-003", "CV-004"]),
            (
                "replay-fork",
                vec!["CV-005", "CV-006", "CV-007", "CV-008", "CV-009"],
            ),
            ("runtime-authority", vec!["CV-010", "CV-011"]),
            ("world-binding", vec!["CV-012", "CV-013", "CV-014"]),
            ("action-ingress", vec!["CV-015", "CV-016", "CV-017"]),
            ("scheduler", vec!["CV-020"]),
            ("world-time", vec!["CV-021", "CV-022", "CV-023", "CV-024"]),
            ("query-catalog", vec!["CV-025", "CV-026", "CV-027"]),
            ("semantic-blob", vec!["CV-030"]),
            ("provenance", vec!["CV-031", "CV-032", "CV-033"]),
            ("change-feed", vec!["CV-038", "CV-039", "CV-040"]),
        ];
        for (group, ids) in expected {
            let selected = runner
                .resolve_with_groups(&[], &[group.to_string()], false)
                .expect("known group resolves");
            assert_eq!(
                selected
                    .iter()
                    .map(|descriptor| descriptor.id_str())
                    .collect::<Vec<_>>(),
                ids
            );
        }
        assert!(matches!(
            runner.resolve_with_groups(&[], &["unknown-group".to_string()], false),
            Err(crate::runner::RunnerError::UnknownGroups(groups)) if groups == vec!["unknown-group"]
        ));
    }

    #[test]
    fn all_selection_is_complete_and_uses_registered_executor_paths() {
        let runner = Runner::new(validator_registry());
        let selected = runner
            .resolve_with_groups(&[], &[], true)
            .expect("--all resolves");
        assert_eq!(selected.len(), EXPECTED_IDS.len());
        let report = runner.run_selected(
            &selected,
            &crate::backend::BackendContext::new(
                loom_client::LoomClient::new("http://127.0.0.1:1").expect("client"),
            ),
            crate::cli::execute_registered_scenario,
            false,
        );
        assert_eq!(report.results().len(), EXPECTED_IDS.len());
        assert_eq!(
            report.selected_scenario_ids(),
            &EXPECTED_IDS.map(str::to_owned)
        );
        assert_eq!(
            report
                .results()
                .iter()
                .map(|result| result.scenario_id().as_str())
                .collect::<Vec<_>>(),
            EXPECTED_IDS
        );
    }
}
