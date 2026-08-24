//! Validator result and report contracts.

use serde::{Deserialize, Serialize};

/// The terminal state of one validator scenario.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum ScenarioStatus {
    /// The scenario ran and its assertions passed.
    Pass,
    /// The scenario ran and produced one or more findings.
    Fail,
    /// The scenario could not run because a prerequisite or environment was
    /// unavailable.
    SkipUnavailable,
}

/// Structured evidence for a failed scenario assertion.
///
/// This payload intentionally contains observations only. It has no
/// remediation or suggested-fix authority field.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct Finding {
    scenario: String,
    expected: String,
    actual: String,
    backend: String,
    context: String,
    evidence: Vec<String>,
}

impl Finding {
    /// Creates a finding with evidence references.
    #[must_use]
    pub fn new(
        scenario: impl Into<String>,
        expected: impl Into<String>,
        actual: impl Into<String>,
        backend: impl Into<String>,
        context: impl Into<String>,
        evidence: impl IntoIterator<Item = impl Into<String>>,
    ) -> Self {
        Self {
            scenario: scenario.into(),
            expected: expected.into(),
            actual: actual.into(),
            backend: backend.into(),
            context: context.into(),
            evidence: evidence.into_iter().map(Into::into).collect(),
        }
    }

    /// Returns the stable scenario ID associated with this finding.
    #[must_use]
    pub fn scenario(&self) -> &str {
        &self.scenario
    }

    /// Returns the expected observation.
    #[must_use]
    pub fn expected(&self) -> &str {
        &self.expected
    }

    /// Returns the actual observation.
    #[must_use]
    pub fn actual(&self) -> &str {
        &self.actual
    }

    /// Returns the backend used by the scenario.
    #[must_use]
    pub fn backend(&self) -> &str {
        &self.backend
    }

    /// Returns the scenario context for the observation.
    #[must_use]
    pub fn context(&self) -> &str {
        &self.context
    }

    /// Returns evidence references associated with the finding.
    #[must_use]
    pub fn evidence(&self) -> &[String] {
        &self.evidence
    }
}

/// The result of executing one scenario.
///
/// The explicit tagged enum keeps an unavailable prerequisite distinct from a
/// pass in serialized or rendered reports.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "kebab-case")]
pub enum ScenarioResult {
    /// The scenario ran successfully.
    Pass { scenario: String },
    /// The scenario ran and found an invariant violation.
    Fail {
        scenario: String,
        findings: Vec<Finding>,
    },
    /// The scenario was not executable in the current prerequisite or
    /// environment state.
    SkipUnavailable { scenario: String, reason: String },
}

impl ScenarioResult {
    /// Creates a passing result.
    #[must_use]
    pub fn pass(scenario: impl Into<String>) -> Self {
        Self::Pass {
            scenario: scenario.into(),
        }
    }

    /// Creates a failing result with structured findings.
    #[must_use]
    pub fn fail<I>(scenario: impl Into<String>, findings: I) -> Self
    where
        I: IntoIterator<Item = Finding>,
    {
        Self::Fail {
            scenario: scenario.into(),
            findings: findings.into_iter().collect(),
        }
    }

    /// Creates an explicit unavailable/prerequisite skip result.
    #[must_use]
    pub fn skip_unavailable(scenario: impl Into<String>, reason: impl Into<String>) -> Self {
        Self::SkipUnavailable {
            scenario: scenario.into(),
            reason: reason.into(),
        }
    }

    /// Converts a prerequisite availability decision into a terminal result.
    ///
    /// This is the safe construction seam for runners that probe an
    /// environment before executing a scenario: an unavailable prerequisite
    /// can never be represented as `pass`.
    #[must_use]
    pub fn from_prerequisite(
        scenario: impl Into<String>,
        available: bool,
        reason: impl Into<String>,
    ) -> Self {
        let scenario = scenario.into();
        if available {
            Self::pass(scenario)
        } else {
            Self::skip_unavailable(scenario, reason)
        }
    }

    /// Returns the terminal status.
    #[must_use]
    pub const fn status(&self) -> ScenarioStatus {
        match self {
            Self::Pass { .. } => ScenarioStatus::Pass,
            Self::Fail { .. } => ScenarioStatus::Fail,
            Self::SkipUnavailable { .. } => ScenarioStatus::SkipUnavailable,
        }
    }

    /// Returns the stable scenario ID associated with this result.
    #[must_use]
    pub fn scenario(&self) -> &str {
        match self {
            Self::Pass { scenario }
            | Self::Fail { scenario, .. }
            | Self::SkipUnavailable { scenario, .. } => scenario,
        }
    }

    /// Returns findings for a failure, or an empty slice for other states.
    #[must_use]
    pub fn findings(&self) -> &[Finding] {
        match self {
            Self::Fail { findings, .. } => findings,
            Self::Pass { .. } | Self::SkipUnavailable { .. } => &[],
        }
    }

    /// Returns the unavailable reason when this result is skipped.
    #[must_use]
    pub fn unavailable_reason(&self) -> Option<&str> {
        match self {
            Self::SkipUnavailable { reason, .. } => Some(reason),
            Self::Pass { .. } | Self::Fail { .. } => None,
        }
    }
}

/// Report produced by one validator run.
#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub struct ValidationReport {
    results: Vec<ScenarioResult>,
}

impl ValidationReport {
    pub(crate) fn from_results(results: Vec<ScenarioResult>) -> Self {
        Self { results }
    }

    /// Returns the number of scenarios represented by the run.
    #[must_use]
    pub const fn scenario_count(&self) -> usize {
        self.results.len()
    }

    /// Reports whether no scenarios were available for execution.
    #[must_use]
    pub const fn is_empty(&self) -> bool {
        self.results.is_empty()
    }

    /// Returns all scenario results in registry order.
    #[must_use]
    pub fn results(&self) -> &[ScenarioResult] {
        &self.results
    }

    /// Returns the scenario results in registry order.
    pub fn iter(&self) -> impl Iterator<Item = &ScenarioResult> {
        self.results.iter()
    }
}
