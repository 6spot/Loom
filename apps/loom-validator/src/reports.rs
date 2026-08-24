//! Validator run reports.

use crate::finding::Finding;
use crate::outcome::ScenarioOutcome;
use crate::scenario::ScenarioId;

/// The result of a single scenario execution, combining outcome and finding.
///
/// The finding payload contains scenario, expected, actual, backend/context,
/// and evidence references.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ScenarioResult {
    scenario_id: ScenarioId,
    outcome: ScenarioOutcome,
    finding: Finding,
}

impl ScenarioResult {
    /// Creates a new scenario result.
    #[must_use]
    pub fn new(scenario_id: ScenarioId, outcome: ScenarioOutcome, finding: Finding) -> Self {
        Self {
            scenario_id,
            outcome,
            finding,
        }
    }

    /// Returns the scenario identifier.
    #[must_use]
    pub fn scenario_id(&self) -> &ScenarioId {
        &self.scenario_id
    }

    /// Returns the scenario outcome.
    #[must_use]
    pub fn outcome(&self) -> &ScenarioOutcome {
        &self.outcome
    }

    /// Returns the structured finding payload.
    #[must_use]
    pub fn finding(&self) -> &Finding {
        &self.finding
    }

    /// Serializes the result to a stable string.
    ///
    /// Missing prerequisites never serialize as `pass`.
    #[must_use]
    pub fn serialize(&self) -> String {
        format!(
            "result: scenario={} outcome={} finding={}",
            self.scenario_id,
            self.outcome.as_str(),
            self.finding.serialize()
        )
    }

    /// Renders the result for reporting.
    #[must_use]
    pub fn render(&self) -> String {
        self.serialize()
    }
}

/// Report produced by enumerating one scenario registry.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ValidationReport {
    scenario_count: usize,
    results: Vec<ScenarioResult>,
}

impl ValidationReport {
    pub(crate) fn from_scenario_count(scenario_count: usize) -> Self {
        Self {
            scenario_count,
            results: Vec::new(),
        }
    }

    /// Creates a report from explicit scenario results.
    #[must_use]
    pub fn from_results(results: Vec<ScenarioResult>) -> Self {
        let count = results.len();
        Self {
            scenario_count: count,
            results,
        }
    }

    /// Returns the number of scenario entries enumerated by the run.
    #[must_use]
    pub fn scenario_count(&self) -> usize {
        self.scenario_count
    }

    /// Reports whether no scenarios were available for execution.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.scenario_count == 0
    }

    /// Returns the scenario results, if any.
    #[must_use]
    pub fn results(&self) -> &[ScenarioResult] {
        &self.results
    }

    /// Counts results with `pass` outcome.
    #[must_use]
    pub fn passed_count(&self) -> usize {
        self.results
            .iter()
            .filter(|r| r.outcome().is_pass())
            .count()
    }

    /// Counts results with `fail` outcome.
    #[must_use]
    pub fn failed_count(&self) -> usize {
        self.results
            .iter()
            .filter(|r| r.outcome().is_fail())
            .count()
    }

    /// Counts results with `skipped` outcome.
    #[must_use]
    pub fn skipped_count(&self) -> usize {
        self.results
            .iter()
            .filter(|r| r.outcome().is_skipped())
            .count()
    }

    /// Counts results with `unavailable` outcome.
    #[must_use]
    pub fn unavailable_count(&self) -> usize {
        self.results
            .iter()
            .filter(|r| r.outcome().is_unavailable())
            .count()
    }

    /// Reports whether any scenario failed.
    #[must_use]
    pub fn has_failures(&self) -> bool {
        self.failed_count() > 0
    }

    /// Returns a concise human-readable summary line for terminal output.
    ///
    /// The summary is deterministic and does not duplicate raw logs or
    /// remediation guidance. It is suitable for the CLI concise summary
    /// required by the runner task.
    #[must_use]
    pub fn summary_line(&self) -> String {
        format!(
            "scenarios: {} total, {} pass, {} fail, {} skipped, {} unavailable",
            self.scenario_count(),
            self.passed_count(),
            self.failed_count(),
            self.skipped_count(),
            self.unavailable_count()
        )
    }
}

#[cfg(test)]
mod tests {
    use super::{ScenarioResult, ValidationReport};
    use crate::finding::Finding;
    use crate::outcome::ScenarioOutcome;
    use crate::scenario::{BackendKind, ScenarioId};

    #[test]
    fn report_from_count() {
        let report = ValidationReport::from_scenario_count(2);
        assert_eq!(report.scenario_count(), 2);
        assert!(!report.is_empty());
        assert!(report.results().is_empty());
    }

    #[test]
    fn skipped_result_does_not_serialize_as_pass() {
        let finding = Finding::new(
            ScenarioId::new("CV-002"),
            "needs db",
            "db present",
            "db missing",
            BackendKind::LoomClient,
            "env:test",
            vec![],
            ScenarioOutcome::Skipped {
                reason: "missing prerequisite: db".to_string(),
            },
        );
        let result = ScenarioResult::new(
            ScenarioId::new("CV-002"),
            ScenarioOutcome::Skipped {
                reason: "missing prerequisite: db".to_string(),
            },
            finding,
        );
        let serialized = result.serialize();
        assert!(serialized.contains("skipped"));
        assert!(!serialized.contains("outcome=pass"));
    }
}
