//! Validator run reports.

/// Report produced by enumerating one scenario registry.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ValidationReport {
    scenario_count: usize,
}

impl ValidationReport {
    pub(crate) const fn from_scenario_count(scenario_count: usize) -> Self {
        Self { scenario_count }
    }

    /// Returns the number of scenario entries enumerated by the run.
    #[must_use]
    pub const fn scenario_count(self) -> usize {
        self.scenario_count
    }

    /// Reports whether no scenarios were available for execution.
    #[must_use]
    pub const fn is_empty(self) -> bool {
        self.scenario_count == 0
    }
}
