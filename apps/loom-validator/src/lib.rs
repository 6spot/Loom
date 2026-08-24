//! Public-consumer validator skeleton for Loom.
//!
//! The validator is intentionally an upper-layer consumer. Scenario code must
//! use the formal [`loom_client`] surface and must not construct or inspect
//! Runtime, Storage, or transport implementation authority directly.

#![forbid(unsafe_code)]

mod backend;
mod feedback;
mod finding;
mod outcome;
mod registry;
mod reports;
mod runner;
mod scenario;

pub use backend::BackendContext;
pub use feedback::TaskLedgerFeedback;
pub use finding::{EvidenceReference, Finding};
pub use outcome::ScenarioOutcome;
pub use registry::{RegistryError, ScenarioRegistry};
pub use reports::{ScenarioResult, ValidationReport};
pub use runner::Runner;
pub use scenario::{BackendKind, CapabilityArea, ScenarioDescriptor, ScenarioId};

#[cfg(test)]
mod tests {
    use super::{Runner, ScenarioRegistry};

    #[test]
    fn bootstrap_registry_is_empty() {
        let registry = ScenarioRegistry::bootstrap();

        assert!(registry.is_empty());
        assert_eq!(registry.len(), 0);
        assert_eq!(registry.iter().count(), 0);
    }

    #[test]
    fn runner_enumerates_bootstrap_registry() {
        let report = Runner::new(ScenarioRegistry::bootstrap()).run();

        assert_eq!(report.scenario_count(), 0);
        assert!(report.is_empty());
    }
}
