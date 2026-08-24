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

    /// Returns the number of scenarios that passed.
    #[must_use]
    pub fn passed_count(&self) -> usize {
        self.results
            .iter()
            .filter(|result| result.outcome().is_pass())
            .count()
    }

    /// Returns the number of scenarios that failed.
    #[must_use]
    pub fn failed_count(&self) -> usize {
        self.results
            .iter()
            .filter(|result| result.outcome().is_fail())
            .count()
    }

    /// Returns the number of scenarios skipped for a missing prerequisite.
    #[must_use]
    pub fn skipped_count(&self) -> usize {
        self.results
            .iter()
            .filter(|result| result.outcome().is_skipped())
            .count()
    }

    /// Returns the number of scenarios unavailable in the current environment.
    #[must_use]
    pub fn unavailable_count(&self) -> usize {
        self.results
            .iter()
            .filter(|result| result.outcome().is_unavailable())
            .count()
    }

    /// Reports whether any executed scenario returned `Fail`.
    #[must_use]
    pub fn has_failures(&self) -> bool {
        self.failed_count() > 0
    }

    /// Renders a concise, deterministic human-readable summary.
    #[must_use]
    pub fn render_summary(&self) -> String {
        let mut lines = self
            .results
            .iter()
            .map(|result| {
                let reason = result
                    .outcome()
                    .reason()
                    .map_or_else(String::new, |reason| format!(" ({reason})"));
                format!("{} {}{}", result.scenario_id(), result.outcome(), reason)
            })
            .collect::<Vec<_>>();
        lines.push(format!(
            "summary: {} selected, {} passed, {} failed, {} skipped, {} unavailable",
            self.scenario_count(),
            self.passed_count(),
            self.failed_count(),
            self.skipped_count(),
            self.unavailable_count()
        ));
        lines.join("\n")
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

    #[test]
    fn summary_counts_each_outcome_without_collapsing_skips() {
        let pass = result("CV-001", ScenarioOutcome::Pass);
        let fail = result("CV-002", ScenarioOutcome::Fail);
        let skipped = result(
            "CV-003",
            ScenarioOutcome::Skipped {
                reason: "missing prerequisite".to_string(),
            },
        );
        let unavailable = result(
            "CV-004",
            ScenarioOutcome::Unavailable {
                reason: "backend unavailable".to_string(),
            },
        );
        let report = ValidationReport::from_results(vec![pass, fail, skipped, unavailable]);

        assert_eq!(report.passed_count(), 1);
        assert_eq!(report.failed_count(), 1);
        assert_eq!(report.skipped_count(), 1);
        assert_eq!(report.unavailable_count(), 1);
        assert!(report.has_failures());
        assert_eq!(
            report.render_summary(),
            "CV-001 pass\nCV-002 fail\nCV-003 skipped (missing prerequisite)\nCV-004 unavailable (backend unavailable)\nsummary: 4 selected, 1 passed, 1 failed, 1 skipped, 1 unavailable"
        );
    }

    fn result(id: &str, outcome: ScenarioOutcome) -> ScenarioResult {
        let finding = Finding::new(
            ScenarioId::new(id),
            "scenario",
            "expected",
            "actual",
            BackendKind::LoomClient,
            "test",
            vec![],
            outcome.clone(),
        );
        ScenarioResult::new(ScenarioId::new(id), outcome, finding)
    }
}
