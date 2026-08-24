//! Task Ledger feedback collected by validator runs.

/// Facts a validator run can append to its Task Ledger handoff.
///
/// This is deliberately a small reporting seam. It does not duplicate Loom's
/// public API or claim authority over task status transitions.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct TaskLedgerFeedback {
    facts: Vec<String>,
}

impl TaskLedgerFeedback {
    /// Creates an empty feedback collection.
    #[must_use]
    pub const fn new() -> Self {
        Self { facts: Vec::new() }
    }

    /// Appends one factual observation for the Task Ledger handoff.
    pub fn record_fact(&mut self, fact: impl Into<String>) {
        self.facts.push(fact.into());
    }

    /// Returns the recorded factual observations in insertion order.
    #[must_use]
    pub fn facts(&self) -> &[String] {
        &self.facts
    }
}
