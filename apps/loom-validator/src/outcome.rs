//! Scenario result states.
//!
//! The contract distinguishes `pass`, `fail`, and explicit
//! prerequisite/environment skip/unavailable. Missing prerequisites
//! must never serialize as `pass`.

use std::fmt;

/// The outcome of a single scenario execution.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ScenarioOutcome {
    /// The scenario passed.
    Pass,
    /// The scenario failed.
    Fail,
    /// The scenario was skipped due to missing prerequisites.
    Skipped {
        /// Human-readable reason for the skip.
        reason: String,
    },
    /// The scenario could not run due to environment unavailability.
    Unavailable {
        /// Human-readable reason for the unavailability.
        reason: String,
    },
}

impl ScenarioOutcome {
    /// Returns true if the outcome is `Pass`.
    #[must_use]
    pub fn is_pass(&self) -> bool {
        matches!(self, Self::Pass)
    }

    /// Returns true if the outcome is `Fail`.
    #[must_use]
    pub fn is_fail(&self) -> bool {
        matches!(self, Self::Fail)
    }

    /// Returns true if the outcome is `Skipped`.
    #[must_use]
    pub fn is_skipped(&self) -> bool {
        matches!(self, Self::Skipped { .. })
    }

    /// Returns true if the outcome is `Unavailable`.
    #[must_use]
    pub fn is_unavailable(&self) -> bool {
        matches!(self, Self::Unavailable { .. })
    }

    /// Returns the stable string label for this outcome.
    ///
    /// This label is used for serialization/rendering and is
    /// guaranteed to differ between `Pass` and `Skipped`/`Unavailable`.
    #[must_use]
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Pass => "pass",
            Self::Fail => "fail",
            Self::Skipped { .. } => "skipped",
            Self::Unavailable { .. } => "unavailable",
        }
    }

    /// Returns the reason for `Skipped` or `Unavailable`, if present.
    #[must_use]
    pub fn reason(&self) -> Option<&str> {
        match self {
            Self::Skipped { reason } | Self::Unavailable { reason } => Some(reason.as_str()),
            _ => None,
        }
    }

    /// Serializes the outcome to its stable label.
    ///
    /// This is the canonical render path used by reports. It guarantees
    /// that missing prerequisites never serialize as `pass`.
    #[must_use]
    pub fn serialize(&self) -> String {
        self.as_str().to_string()
    }

    /// Renders the outcome as a display string.
    #[must_use]
    pub fn render(&self) -> String {
        self.serialize()
    }
}

impl fmt::Display for ScenarioOutcome {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

#[cfg(test)]
mod tests {
    use super::ScenarioOutcome;

    #[test]
    fn pass_is_pass() {
        assert!(ScenarioOutcome::Pass.is_pass());
        assert_eq!(ScenarioOutcome::Pass.as_str(), "pass");
    }

    #[test]
    fn skipped_is_not_pass() {
        let outcome = ScenarioOutcome::Skipped {
            reason: "missing prerequisite: test db".to_string(),
        };
        assert!(!outcome.is_pass());
        assert_eq!(outcome.as_str(), "skipped");
        assert_eq!(outcome.serialize(), "skipped");
        assert_ne!(outcome.serialize(), "pass");
        assert_eq!(outcome.reason(), Some("missing prerequisite: test db"));
    }

    #[test]
    fn unavailable_is_not_pass() {
        let outcome = ScenarioOutcome::Unavailable {
            reason: "environment unavailable".to_string(),
        };
        assert!(!outcome.is_pass());
        assert_eq!(outcome.as_str(), "unavailable");
        assert_ne!(outcome.serialize(), "pass");
    }

    #[test]
    fn fail_is_not_pass() {
        assert!(!ScenarioOutcome::Fail.is_pass());
        assert_eq!(ScenarioOutcome::Fail.as_str(), "fail");
    }
}
