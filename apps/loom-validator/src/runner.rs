//! Deterministic validator scenario selection and execution.

use std::collections::BTreeSet;
use std::fmt;

use crate::backend::BackendContext;
use crate::reports::{ScenarioResult, ValidationReport};
use crate::scenario::{ScenarioDescriptor, ScenarioId};

/// The scenarios selected for a run.
///
/// IDs are resolved against the registry before execution. An ID may be
/// supplied more than once; repeated IDs are treated as one selection. The
/// registry's deterministic ID order, rather than command-line order, is the
/// execution order.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ScenarioSelection {
    /// Select every scenario in the registry.
    All,
    /// Select the listed stable IDs.
    Ids(Vec<String>),
}

impl ScenarioSelection {
    /// Select every registered scenario.
    #[must_use]
    pub const fn all() -> Self {
        Self::All
    }

    /// Select one or more stable IDs.
    #[must_use]
    pub fn ids<I, S>(ids: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        Self::Ids(ids.into_iter().map(Into::into).collect())
    }
}

/// Runner/configuration failures.
///
/// These errors are intentionally separate from [`crate::ScenarioOutcome`]: an
/// unknown ID means the requested run was not configured successfully, while
/// a scenario `Fail` is a valid execution result.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RunnerError {
    /// The requested ID does not exist in the registry.
    UnknownScenario(String),
    /// The requested ID does not satisfy the stable scenario ID contract.
    InvalidScenarioId { id: String, reason: String },
}

impl fmt::Display for RunnerError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnknownScenario(id) => write!(f, "unknown scenario id: {id}"),
            Self::InvalidScenarioId { id, reason } => {
                write!(f, "invalid scenario id {id:?}: {reason}")
            }
        }
    }
}

impl std::error::Error for RunnerError {}

/// Execution controls for a selected scenario set.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExecutionOptions {
    selection: ScenarioSelection,
    fail_fast: bool,
}

impl ExecutionOptions {
    /// Creates default development-mode options for all scenarios.
    #[must_use]
    pub const fn all() -> Self {
        Self {
            selection: ScenarioSelection::All,
            fail_fast: false,
        }
    }

    /// Creates default development-mode options for a selection.
    #[must_use]
    pub const fn new(selection: ScenarioSelection) -> Self {
        Self {
            selection,
            fail_fast: false,
        }
    }

    /// Returns the selection used by this run.
    #[must_use]
    pub const fn selection(&self) -> &ScenarioSelection {
        &self.selection
    }

    /// Enables or disables stopping after the first scenario failure.
    #[must_use]
    pub const fn with_fail_fast(mut self, fail_fast: bool) -> Self {
        self.fail_fast = fail_fast;
        self
    }

    /// Reports whether the run stops after the first `Fail` outcome.
    #[must_use]
    pub const fn fail_fast(&self) -> bool {
        self.fail_fast
    }
}

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

    /// Resolves a selection into descriptors in deterministic registry order.
    ///
    /// Repeated requested IDs are de-duplicated. Every requested ID must be
    /// known before any descriptor is returned, so a configuration error
    /// cannot produce a partial scenario run.
    ///
    /// # Errors
    ///
    /// Returns [`RunnerError::InvalidScenarioId`] for malformed IDs and
    /// [`RunnerError::UnknownScenario`] for valid IDs absent from the registry.
    pub fn select(
        &self,
        selection: &ScenarioSelection,
    ) -> Result<Vec<&ScenarioDescriptor>, RunnerError> {
        match selection {
            ScenarioSelection::All => Ok(self.registry.iter().collect()),
            ScenarioSelection::Ids(ids) => {
                let mut requested = BTreeSet::new();
                for id in ids {
                    let parsed = ScenarioId::try_new(id.clone()).map_err(|reason| {
                        RunnerError::InvalidScenarioId {
                            id: id.clone(),
                            reason,
                        }
                    })?;
                    requested.insert(parsed);
                }

                for id in &requested {
                    if self.registry.get_by_id(id).is_none() {
                        return Err(RunnerError::UnknownScenario(id.to_string()));
                    }
                }

                Ok(self
                    .registry
                    .iter()
                    .filter(|descriptor| requested.contains(descriptor.id()))
                    .collect())
            }
        }
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

    /// Executes a selected set of scenarios in deterministic order.
    ///
    /// Normal mode (`fail_fast == false`) always invokes the executor for all
    /// selected scenarios, including after a `Fail` result. Fail-fast mode is
    /// explicit and stops only after a scenario returns `ScenarioOutcome::Fail`.
    /// Configuration errors are returned before the first scenario executes.
    ///
    /// # Errors
    ///
    /// Returns a [`RunnerError`] when selection cannot be resolved.
    pub fn run_with_options<F>(
        &self,
        options: &ExecutionOptions,
        backend: &BackendContext,
        mut execute: F,
    ) -> Result<ValidationReport, RunnerError>
    where
        F: FnMut(&ScenarioDescriptor, &BackendContext) -> ScenarioResult,
    {
        let descriptors = self.select(options.selection())?;
        let mut results = Vec::with_capacity(descriptors.len());

        for descriptor in descriptors {
            let result = execute(descriptor, backend);
            let stop = options.fail_fast() && result.outcome().is_fail();
            results.push(result);
            if stop {
                break;
            }
        }

        Ok(ValidationReport::from_results(results))
    }

    /// Executes a selection in the default continue-after-failure mode.
    ///
    /// This is a convenience wrapper around [`Self::run_with_options`].
    ///
    /// # Errors
    ///
    /// Returns a [`RunnerError`] when selection cannot be resolved.
    pub fn run_selected<F>(
        &self,
        selection: ScenarioSelection,
        backend: &BackendContext,
        execute: F,
    ) -> Result<ValidationReport, RunnerError>
    where
        F: FnMut(&ScenarioDescriptor, &BackendContext) -> ScenarioResult,
    {
        self.run_with_options(&ExecutionOptions::new(selection), backend, execute)
    }
}

#[cfg(test)]
mod tests {
    use super::{ExecutionOptions, Runner, RunnerError, ScenarioRegistry, ScenarioSelection};
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

    #[test]
    fn selection_deduplicates_ids_and_uses_registry_order() {
        let mut registry = ScenarioRegistry::bootstrap();
        registry.register(descriptor("CV-003")).unwrap();
        registry.register(descriptor("CV-001")).unwrap();
        registry.register(descriptor("CV-002")).unwrap();

        let runner = Runner::new(registry);
        let selected = runner
            .select(&ScenarioSelection::ids(["CV-003", "CV-001", "CV-003"]))
            .unwrap();
        let ids: Vec<_> = selected.iter().map(|scenario| scenario.id_str()).collect();

        assert_eq!(ids, vec!["CV-001", "CV-003"]);
    }

    #[test]
    fn unknown_selection_is_a_runner_error_before_execution() {
        use std::cell::Cell;

        let mut registry = ScenarioRegistry::bootstrap();
        registry.register(descriptor("CV-001")).unwrap();
        let runner = Runner::new(registry);
        let client = LoomClient::builder("http://localhost:8080".to_string())
            .build()
            .expect("client builder should succeed for test");
        let backend = BackendContext::new(client);
        let executed = Cell::new(false);

        let error = runner
            .run_selected(ScenarioSelection::ids(["CV-999"]), &backend, |_, _| {
                executed.set(true);
                unreachable!("configuration errors must happen before execution")
            })
            .unwrap_err();

        assert_eq!(error, RunnerError::UnknownScenario("CV-999".to_string()));
        assert!(!executed.get());
    }

    #[test]
    fn default_execution_continues_after_a_failure() {
        let mut registry = ScenarioRegistry::bootstrap();
        registry.register(descriptor("CV-001")).unwrap();
        registry.register(descriptor("CV-002")).unwrap();
        registry.register(descriptor("CV-003")).unwrap();
        let runner = Runner::new(registry);
        let client = LoomClient::builder("http://localhost:8080".to_string())
            .build()
            .expect("client builder should succeed for test");
        let backend = BackendContext::new(client);

        let report = runner
            .run_with_options(&ExecutionOptions::all(), &backend, |desc, _| {
                let outcome = if desc.id_str() == "CV-001" {
                    ScenarioOutcome::Fail
                } else {
                    ScenarioOutcome::Pass
                };
                let finding = Finding::new(
                    desc.id().clone(),
                    desc.name(),
                    "expected",
                    "actual",
                    desc.supported_backends()[0].clone(),
                    "test-context",
                    vec![EvidenceReference::new("evidence:test")],
                    outcome.clone(),
                );
                ScenarioResult::new(desc.id().clone(), outcome, finding)
            })
            .unwrap();

        assert_eq!(report.results().len(), 3);
        assert_eq!(report.failed_count(), 1);
    }

    #[test]
    fn fail_fast_is_explicit() {
        let mut registry = ScenarioRegistry::bootstrap();
        registry.register(descriptor("CV-001")).unwrap();
        registry.register(descriptor("CV-002")).unwrap();
        let runner = Runner::new(registry);
        let client = LoomClient::builder("http://localhost:8080".to_string())
            .build()
            .expect("client builder should succeed for test");
        let backend = BackendContext::new(client);

        let report = runner
            .run_with_options(
                &ExecutionOptions::all().with_fail_fast(true),
                &backend,
                |desc, _| {
                    let finding = Finding::new(
                        desc.id().clone(),
                        desc.name(),
                        "expected",
                        "actual",
                        desc.supported_backends()[0].clone(),
                        "test-context",
                        vec![],
                        ScenarioOutcome::Fail,
                    );
                    ScenarioResult::new(desc.id().clone(), ScenarioOutcome::Fail, finding)
                },
            )
            .unwrap();

        assert_eq!(report.results().len(), 1);
        assert_eq!(report.failed_count(), 1);
    }
}
