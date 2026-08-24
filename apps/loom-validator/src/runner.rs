//! Extensible validator runner contract.

use crate::{
    BackendContext, ScenarioDescriptor, ScenarioRegistry, ScenarioResult, ValidationReport,
};

/// Execution seam implemented by scenario providers.
///
/// The runner only enumerates descriptors and delegates execution through this
/// contract. Adding a scenario therefore does not require a scenario-specific
/// branch in the runner.
pub trait ScenarioExecutor {
    /// Executes one registered scenario against the supplied backend context.
    fn execute(&self, scenario: &ScenarioDescriptor, backend: &BackendContext) -> ScenarioResult;
}

impl<F> ScenarioExecutor for F
where
    F: Fn(&ScenarioDescriptor, &BackendContext) -> ScenarioResult,
{
    fn execute(&self, scenario: &ScenarioDescriptor, backend: &BackendContext) -> ScenarioResult {
        self(scenario, backend)
    }
}

/// Enumerates and executes validator scenarios without owning Loom execution
/// authority.
#[derive(Clone, Debug)]
pub struct Runner {
    registry: ScenarioRegistry,
}

impl Runner {
    /// Creates a runner over a scenario registry.
    #[must_use]
    pub const fn new(registry: ScenarioRegistry) -> Self {
        Self { registry }
    }

    /// Borrows the registry that this runner will enumerate.
    #[must_use]
    pub const fn registry(&self) -> &ScenarioRegistry {
        &self.registry
    }

    /// Enumerates the registry without an execution context.
    ///
    /// A scenario with no backend/executor context is explicitly unavailable;
    /// it is never silently represented as a pass.
    #[must_use]
    pub fn run(&self) -> ValidationReport {
        let results = self
            .registry
            .iter()
            .map(|scenario| {
                ScenarioResult::skip_unavailable(
                    scenario.id(),
                    "no backend execution context was supplied",
                )
            })
            .collect();
        ValidationReport::from_results(results)
    }

    /// Executes every registered scenario through the extensible executor
    /// contract, preserving deterministic registry order.
    #[must_use]
    pub fn run_with<E>(&self, backend: &BackendContext, executor: &E) -> ValidationReport
    where
        E: ScenarioExecutor + ?Sized,
    {
        let results = self
            .registry
            .iter()
            .map(|scenario| executor.execute(scenario, backend))
            .collect();
        ValidationReport::from_results(results)
    }
}
