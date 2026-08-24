//! Public-consumer validator skeleton for Loom.
//!
//! The validator is intentionally an upper-layer consumer. Scenario code must
//! use the formal [`loom_client`] surface and must not construct or inspect
//! Runtime, Storage, or transport implementation authority directly.

#![forbid(unsafe_code)]

mod backend;
mod feedback;
mod registry;
mod reports;
mod runner;

pub use backend::BackendContext;
pub use feedback::TaskLedgerFeedback;
pub use registry::{RegistryError, ScenarioDescriptor, ScenarioRegistry};
pub use reports::{Finding, ScenarioResult, ScenarioStatus, ValidationReport};
pub use runner::{Runner, ScenarioExecutor};

#[cfg(test)]
mod tests {
    use super::{
        BackendContext, Finding, RegistryError, Runner, ScenarioDescriptor, ScenarioRegistry,
        ScenarioResult, ScenarioStatus,
    };

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
    fn registry_rejects_duplicates_and_enumerates_by_stable_id() {
        let mut registry = ScenarioRegistry::new();
        registry
            .register(ScenarioDescriptor::new("CV-002", "second"))
            .expect("first scenario registration");
        registry
            .register(ScenarioDescriptor::new("CV-001", "first"))
            .expect("second scenario registration");

        let ids: Vec<_> = registry.iter().map(ScenarioDescriptor::id).collect();
        assert_eq!(ids, ["CV-001", "CV-002"]);
        assert_eq!(
            registry.lookup("CV-001").map(ScenarioDescriptor::name),
            Some("first")
        );

        let duplicate = registry.register(ScenarioDescriptor::new("CV-001", "duplicate"));
        assert_eq!(
            duplicate,
            Err(RegistryError::DuplicateScenarioId("CV-001".to_owned()))
        );
        assert_eq!(
            registry.lookup("CV-001").map(ScenarioDescriptor::name),
            Some("first")
        );
    }

    #[test]
    fn metadata_is_stable_and_deduplicated() {
        let descriptor = ScenarioDescriptor::new("CV-001", "catalog reads")
            .with_capability_area("catalog")
            .with_supported_backends(["http", "memory", "http"])
            .with_prerequisite("a running public Loom server")
            .with_related_tasks(["ME-251", "ME-251"])
            .with_architecture_references(["runtime-contracts.md", "runtime-contracts.md"]);

        assert_eq!(descriptor.name(), "catalog reads");
        assert_eq!(descriptor.capability_area(), "catalog");
        assert_eq!(descriptor.supported_backends(), ["http", "memory"]);
        assert_eq!(
            descriptor.prerequisite_description(),
            "a running public Loom server"
        );
        assert_eq!(descriptor.related_tasks(), ["ME-251"]);
        assert_eq!(
            descriptor.architecture_references(),
            Some(["runtime-contracts.md".to_owned()].as_slice())
        );
    }

    #[test]
    fn unavailable_prerequisites_keep_results_out_of_pass_state() {
        let result = ScenarioResult::from_prerequisite("CV-001", false, "server unavailable");
        assert_eq!(result.status(), ScenarioStatus::SkipUnavailable);
        assert_eq!(result.unavailable_reason(), Some("server unavailable"));

        let json = serde_json::to_string(&result).expect("result JSON");
        assert!(json.contains("skip-unavailable"));
        assert!(!json.contains("\"pass\""));

        let mut registry = ScenarioRegistry::new();
        registry
            .register(ScenarioDescriptor::new("CV-001", "unavailable"))
            .expect("scenario registration");
        let report = Runner::new(registry).run();
        assert_eq!(
            report.results()[0].status(),
            ScenarioStatus::SkipUnavailable
        );
    }

    #[test]
    fn runner_delegates_each_scenario_through_the_executor_contract() {
        let mut registry = ScenarioRegistry::new();
        registry
            .register(ScenarioDescriptor::new("CV-001", "first"))
            .expect("scenario registration");
        let client = loom_client::LoomClient::new("http://localhost:8080").expect("client");
        let backend = BackendContext::new(client);
        let report = Runner::new(registry).run_with(
            &backend,
            &|scenario: &ScenarioDescriptor, _backend: &BackendContext| {
                ScenarioResult::pass(scenario.id())
            },
        );

        assert_eq!(report.scenario_count(), 1);
        assert_eq!(report.results()[0].status(), ScenarioStatus::Pass);
        assert_eq!(report.results()[0].scenario(), "CV-001");
    }

    #[test]
    fn finding_payload_is_observational_and_has_required_fields() {
        let finding = Finding::new(
            "CV-001",
            "catalog contains the declared action",
            "catalog did not contain the action",
            "http",
            "world=example, action=inspect",
            ["response:42", "trace:7"],
        );
        let result = ScenarioResult::fail("CV-001", [finding.clone()]);
        let json = serde_json::to_string(&result).expect("finding JSON");

        assert_eq!(finding.scenario(), "CV-001");
        assert_eq!(finding.expected(), "catalog contains the declared action");
        assert_eq!(finding.actual(), "catalog did not contain the action");
        assert_eq!(finding.backend(), "http");
        assert_eq!(finding.context(), "world=example, action=inspect");
        assert_eq!(finding.evidence(), ["response:42", "trace:7"]);
        assert!(json.contains("expected"));
        assert!(json.contains("actual"));
        assert!(json.contains("backend"));
        assert!(json.contains("context"));
        assert!(json.contains("evidence"));
        assert!(!json.contains("remediation"));
        assert!(!json.contains("suggested-fix"));
    }
}
