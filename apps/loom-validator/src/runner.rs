//! Bounded validator runner skeleton.

use crate::backend::BackendContext;
use crate::reports::{ScenarioResult, ValidationReport};
use crate::scenario::ScenarioDescriptor;

/// Enumerates validator scenarios without owning Loom execution authority.
#[derive(Clone, Debug)]
pub struct Runner {
    registry: ScenarioRegistry,
}

use crate::registry::ScenarioRegistry;

impl Runner {
    /// Creates a runner over a scenario registry.
    #[must_use]
    pub fn new(registry: ScenarioRegistry) -> Self {
        Self { registry }
    }

    /// Borrows the registry that this runner will enumerate.
    #[must_use]
    pub fn registry(&self) -> &ScenarioRegistry {
        &self.registry
    }

    /// Enumerates the registry and returns its bootstrap report.
    #[must_use]
    pub fn run(&self) -> ValidationReport {
        ValidationReport::from_scenario_count(self.registry.len())
    }

    /// Executes each registered scenario via the provided executor.
    ///
    /// The executor is generic over the scenario descriptor and backend
    /// context. Adding a new scenario does not require changes to this
    /// runner—no scenario-specific branching is performed here.
    #[must_use]
    pub fn run_with<F>(&self, backend: &BackendContext, execute: F) -> ValidationReport
    where
        F: Fn(&ScenarioDescriptor, &BackendContext) -> ScenarioResult,
    {
        let results = self
            .registry
            .iter()
            .map(|descriptor| execute(descriptor, backend))
            .collect();
        ValidationReport::from_results(results)
    }
}

#[cfg(test)]
mod tests {
    use super::{Runner, ScenarioRegistry};
    use crate::backend::BackendContext;
    use crate::finding::{EvidenceReference, Finding};
    use crate::outcome::ScenarioOutcome;
    use crate::reports::ScenarioResult;
    use crate::scenario::{BackendKind, ScenarioDescriptor};
    use loom_client::LoomClient;

    fn descriptor(id: &str) -> ScenarioDescriptor {
        ScenarioDescriptor::new(
            id,
            format!("scenario {id}"),
            "world",
            vec![BackendKind::LoomClient],
            "none",
            vec![],
            vec![],
        )
    }

    #[test]
    fn runner_is_extensible_without_branching() {
        // The runner must not contain scenario-specific branching. This test
        // demonstrates extensibility by adding two new scenarios without
        // modifying the runner and executing them via a generic closure.
        let mut registry = ScenarioRegistry::bootstrap();
        registry.register(descriptor("CV-001")).unwrap();
        registry.register(descriptor("CV-002")).unwrap();

        let runner = Runner::new(registry);
        // Construct a minimal client for the backend context. The URL is not
        // used because the executor in this test does not perform network calls.
        let client = LoomClient::builder("http://localhost:8080".to_string())
            .build()
            .expect("client builder should succeed for test");
        let backend = BackendContext::new(client);

        let report = runner.run_with(&backend, |desc, ctx| {
            // Generic execution: no match on id, just uses descriptor metadata and backend.
            let _ = ctx.client();
            let finding = Finding::new(
                desc.id().clone(),
                desc.name(),
                "expected",
                "actual",
                desc.supported_backends()[0].clone(),
                "test-context",
                vec![EvidenceReference::new("evidence:test")],
                ScenarioOutcome::Pass,
            );
            ScenarioResult::new(desc.id().clone(), ScenarioOutcome::Pass, finding)
        });

        assert_eq!(report.scenario_count(), 2);
        assert_eq!(report.results().len(), 2);
        let ids: Vec<_> = report
            .results()
            .iter()
            .map(|r| r.scenario_id().as_str().to_string())
            .collect();
        assert_eq!(ids, vec!["CV-001", "CV-002"]);
    }
}
