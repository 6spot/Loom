//! Bounded validator runner skeleton.

use crate::{ScenarioRegistry, ValidationReport};

/// Enumerates validator scenarios without owning Loom execution authority.
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

    /// Enumerates the registry and returns its bootstrap report.
    #[must_use]
    pub fn run(&self) -> ValidationReport {
        ValidationReport::from_scenario_count(self.registry.len())
    }
}
