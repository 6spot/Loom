//! Structured finding payload for validator scenarios.
//!
//! The payload contains scenario, expected, actual, backend/context,
//! and evidence references. It intentionally contains no
//! remediation authority field.

use crate::outcome::ScenarioOutcome;
use crate::scenario::{BackendKind, ScenarioId};

/// Evidence reference for a finding (e.g. log line, artifact path, or trace id).
#[derive(Clone, Debug, Eq, PartialEq, PartialOrd, Ord, Hash)]
pub struct EvidenceReference(String);

impl EvidenceReference {
    /// Creates a new evidence reference.
    #[must_use]
    pub fn new(evidence: impl Into<String>) -> Self {
        Self(evidence.into())
    }

    /// Creates a Task Ledger reference to the command that produced evidence.
    #[must_use]
    pub fn command(command: impl Into<String>) -> Self {
        Self::new(format!("command:{}", command.into()))
    }

    /// Creates a Task Ledger reference to a validator run identifier.
    #[must_use]
    pub fn run(run_id: impl Into<String>) -> Self {
        Self::new(format!("run:{}", run_id.into()))
    }

    /// Creates a Task Ledger reference to a report or diagnostic artifact.
    #[must_use]
    pub fn path(path: impl Into<String>) -> Self {
        Self::new(format!("path:{}", path.into()))
    }

    /// Creates a Task Ledger reference to a CI run or check.
    #[must_use]
    pub fn ci(reference: impl Into<String>) -> Self {
        Self::new(format!("ci:{}", reference.into()))
    }

    /// Borrows the evidence as a string.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl AsRef<str> for EvidenceReference {
    fn as_ref(&self) -> &str {
        &self.0
    }
}

/// Structured finding payload produced by a scenario execution.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Finding {
    scenario_id: ScenarioId,
    scenario_name: String,
    expected: String,
    actual: String,
    backend: BackendKind,
    context: String,
    evidence: Vec<EvidenceReference>,
    outcome: ScenarioOutcome,
}

impl Finding {
    /// Creates a new finding payload.
    #[must_use]
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        scenario_id: ScenarioId,
        scenario_name: impl Into<String>,
        expected: impl Into<String>,
        actual: impl Into<String>,
        backend: BackendKind,
        context: impl Into<String>,
        evidence: Vec<EvidenceReference>,
        outcome: ScenarioOutcome,
    ) -> Self {
        Self {
            scenario_id,
            scenario_name: scenario_name.into(),
            expected: expected.into(),
            actual: actual.into(),
            backend,
            context: context.into(),
            evidence,
            outcome,
        }
    }

    /// Returns the scenario identifier.
    #[must_use]
    pub fn scenario_id(&self) -> &ScenarioId {
        &self.scenario_id
    }

    /// Returns the scenario name.
    #[must_use]
    pub fn scenario_name(&self) -> &str {
        &self.scenario_name
    }

    /// Returns the expected value/description.
    #[must_use]
    pub fn expected(&self) -> &str {
        &self.expected
    }

    /// Returns the actual value/description.
    #[must_use]
    pub fn actual(&self) -> &str {
        &self.actual
    }

    /// Returns the backend under test.
    #[must_use]
    pub fn backend(&self) -> &BackendKind {
        &self.backend
    }

    /// Returns the backend context description.
    #[must_use]
    pub fn context(&self) -> &str {
        &self.context
    }

    /// Returns the evidence references.
    #[must_use]
    pub fn evidence(&self) -> &[EvidenceReference] {
        &self.evidence
    }

    /// Returns the scenario outcome.
    #[must_use]
    pub fn outcome(&self) -> &ScenarioOutcome {
        &self.outcome
    }

    /// Renders the finding as a deterministic string for reports.
    ///
    /// The render includes scenario, expected, actual, backend, context,
    /// evidence, and outcome, but never serializes a skipped finding as `pass`.
    #[must_use]
    pub fn render(&self) -> String {
        let mut evidence = self
            .evidence
            .iter()
            .map(EvidenceReference::as_str)
            .collect::<Vec<_>>();
        evidence.sort_unstable();
        let evidence = evidence.join(", ");
        format!(
            "finding: scenario={} name={} expected={} actual={} backend={} context={} evidence=[{}] outcome={}",
            self.scenario_id,
            self.scenario_name,
            self.expected,
            self.actual,
            self.backend,
            self.context,
            evidence,
            self.outcome.as_str()
        )
    }

    /// Serializes the finding to a stable string representation.
    #[must_use]
    pub fn serialize(&self) -> String {
        self.render()
    }
}

#[cfg(test)]
mod tests {
    use super::{EvidenceReference, Finding};
    use crate::outcome::ScenarioOutcome;
    use crate::scenario::{BackendKind, ScenarioId};

    #[test]
    fn finding_contains_required_fields() {
        let finding = Finding::new(
            ScenarioId::new("CV-001"),
            "world birth",
            "world exists",
            "world missing",
            BackendKind::LoomClient,
            "client v1",
            vec![EvidenceReference::new("log:123")],
            ScenarioOutcome::Fail,
        );
        assert_eq!(finding.scenario_id().as_str(), "CV-001");
        assert_eq!(finding.scenario_name(), "world birth");
        assert_eq!(finding.expected(), "world exists");
        assert_eq!(finding.actual(), "world missing");
        assert_eq!(finding.backend().as_str(), "loom-client");
        assert_eq!(finding.context(), "client v1");
        assert_eq!(finding.evidence().len(), 1);
    }

    #[test]
    fn skipped_finding_does_not_render_as_pass() {
        let finding = Finding::new(
            ScenarioId::new("CV-002"),
            "needs db",
            "db present",
            "db missing",
            BackendKind::LoomClient,
            "env: test",
            vec![],
            ScenarioOutcome::Skipped {
                reason: "missing prerequisite: db".to_string(),
            },
        );
        let rendered = finding.render();
        assert!(rendered.contains("skipped"));
        assert!(!rendered.contains("outcome=pass"));
        assert_eq!(finding.outcome().as_str(), "skipped");
    }

    #[test]
    fn finding_has_no_remediation_field() {
        // This test ensures the finding payload does not expose remediation authority.
        // We check via debug string that no remediation field exists.
        let finding = Finding::new(
            ScenarioId::new("CV-003"),
            "sample",
            "expected",
            "actual",
            BackendKind::InMemory,
            "ctx",
            vec![],
            ScenarioOutcome::Pass,
        );
        let debug = format!("{finding:?}");
        assert!(!debug.contains("remediation"));
        // Also ensure serialized form does not contain remediation.
        assert!(!finding.serialize().contains("remediation"));
    }
}
