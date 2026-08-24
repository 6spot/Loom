//! Validator run reports.

use crate::finding::Finding;
use crate::outcome::ScenarioOutcome;
use crate::scenario::{BackendKind, ScenarioId};

/// Gate policy for a validator report.
///
/// Best-effort mode keeps optional live backends observable without turning an
/// unavailable prerequisite into a synthetic scenario failure. Strict mode
/// requires every selected scenario to pass. Required-live mode additionally
/// requires at least one passing `PostgreSQL` result, so a missing or
/// unavailable `PostgreSQL` prerequisite cannot satisfy the gate.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ValidationPolicy {
    strict: bool,
    required_live: bool,
}

impl ValidationPolicy {
    /// Creates the default best-effort policy.
    #[must_use]
    pub const fn best_effort() -> Self {
        Self {
            strict: false,
            required_live: false,
        }
    }

    /// Creates a strict policy in which skipped/unavailable results fail the
    /// runner gate.
    #[must_use]
    pub const fn strict() -> Self {
        Self {
            strict: true,
            required_live: false,
        }
    }

    /// Creates a policy that requires passing `PostgreSQL` evidence.
    #[must_use]
    pub const fn required_live() -> Self {
        Self {
            strict: true,
            required_live: true,
        }
    }

    /// Sets whether all selected results must be `pass`.
    #[must_use]
    pub const fn with_strict(mut self, strict: bool) -> Self {
        self.strict = strict;
        self
    }

    /// Sets whether at least one `PostgreSQL` result must pass.
    #[must_use]
    pub const fn with_required_live(mut self, required_live: bool) -> Self {
        self.required_live = required_live;
        if required_live {
            self.strict = true;
        }
        self
    }

    /// Reports whether strict result evaluation is enabled.
    #[must_use]
    pub const fn is_strict(self) -> bool {
        self.strict
    }

    /// Reports whether live `PostgreSQL` evidence is required.
    #[must_use]
    pub const fn requires_live(self) -> bool {
        self.required_live
    }
}

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

    /// Creates an explicit prerequisite result without executing scenario
    /// code. The result is never a pass.
    #[must_use]
    pub fn prerequisite(
        scenario_id: ScenarioId,
        scenario_name: impl Into<String>,
        backend: BackendKind,
        reason: impl Into<String>,
    ) -> Self {
        let reason = reason.into();
        let outcome = ScenarioOutcome::Skipped {
            reason: reason.clone(),
        };
        let finding = Finding::new(
            scenario_id.clone(),
            scenario_name,
            "backend prerequisite is available",
            reason,
            backend,
            "backend-harness",
            vec![],
            outcome.clone(),
        );
        Self::new(scenario_id, outcome, finding)
    }

    /// Creates an explicit unavailable result without executing scenario code.
    /// The result is never a pass.
    #[must_use]
    pub fn unavailable(
        scenario_id: ScenarioId,
        scenario_name: impl Into<String>,
        backend: BackendKind,
        reason: impl Into<String>,
    ) -> Self {
        let reason = reason.into();
        let outcome = ScenarioOutcome::Unavailable {
            reason: reason.clone(),
        };
        let finding = Finding::new(
            scenario_id.clone(),
            scenario_name,
            "public backend is available",
            reason,
            backend,
            "backend-harness",
            vec![],
            outcome.clone(),
        );
        Self::new(scenario_id, outcome, finding)
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
    policy: ValidationPolicy,
}

impl ValidationReport {
    pub(crate) fn from_scenario_count(scenario_count: usize) -> Self {
        Self {
            scenario_count,
            results: Vec::new(),
            policy: ValidationPolicy::default(),
        }
    }

    /// Creates a report from explicit scenario results.
    #[must_use]
    pub fn from_results(results: Vec<ScenarioResult>) -> Self {
        Self::from_results_with_policy(results, ValidationPolicy::default())
    }

    /// Creates a report from explicit results and a gate policy.
    #[must_use]
    pub fn from_results_with_policy(
        results: Vec<ScenarioResult>,
        policy: ValidationPolicy,
    ) -> Self {
        let count = results.len();
        Self {
            scenario_count: count,
            results,
            policy,
        }
    }

    /// Returns the policy used to evaluate this report.
    #[must_use]
    pub const fn policy(&self) -> ValidationPolicy {
        self.policy
    }

    /// Reports whether this report satisfies its configured runner gate.
    #[must_use]
    pub fn gate_passes(&self) -> bool {
        if self.results.is_empty() {
            return false;
        }

        // Prerequisite/unavailable results are deliberately non-pass in every
        // mode. Best-effort mode may continue executing later scenarios, but
        // it must not turn an incomplete report into a passing gate.
        if self
            .results
            .iter()
            .any(|result| !result.outcome().is_pass())
        {
            return false;
        }

        if self.policy.required_live {
            return self.results.iter().any(|result| {
                result.finding().backend() == &BackendKind::PostgreSQL && result.outcome().is_pass()
            });
        }

        !self.results.iter().any(|result| result.outcome().is_fail())
    }

    /// Reports whether the configured runner gate passes.
    #[must_use]
    pub fn is_pass(&self) -> bool {
        self.gate_passes()
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
    use super::{ScenarioResult, ValidationPolicy, ValidationReport};
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
    fn unavailable_result_never_passes_any_gate() {
        let result = ScenarioResult::unavailable(
            ScenarioId::new("CV-003"),
            "live backend",
            BackendKind::PostgreSQL,
            "missing LOOM_TEST_POSTGRES_URL",
        );
        assert!(!ValidationReport::from_results(vec![result.clone()]).gate_passes());
        assert!(
            !ValidationReport::from_results_with_policy(
                vec![result],
                ValidationPolicy::required_live(),
            )
            .gate_passes()
        );
    }

    #[test]
    fn required_live_needs_a_passing_postgres_result() {
        let finding = Finding::new(
            ScenarioId::new("CV-004"),
            "live backend",
            "service responds",
            "service responded",
            BackendKind::PostgreSQL,
            "backend-harness",
            vec![],
            ScenarioOutcome::Pass,
        );
        let result = ScenarioResult::new(ScenarioId::new("CV-004"), ScenarioOutcome::Pass, finding);
        let report = ValidationReport::from_results_with_policy(
            vec![result],
            ValidationPolicy::required_live(),
        );
        assert!(report.gate_passes());
    }
}
