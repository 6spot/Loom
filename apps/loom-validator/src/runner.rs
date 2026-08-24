//! Bounded validator runner with deterministic selection.
//!
//! The runner is the execution engine for the validator initiative. It
//! selects scenarios by stable `CV-` identifiers, enforces deterministic
//! ordering, and cleanly separates scenario outcomes from process/runner
//! failures.
//!
//! ## Exit semantics (documented)
//!
//! The runner distinguishes two failure domains:
//!
//! - **Scenario result**: a scenario's `ScenarioOutcome` (`pass`/`fail`/
//!   `skipped`/`unavailable`). In normal development mode the process
//!   continues after a failed scenario, collects remaining results, and
//!   exits **0**. This is the Task Ledger feedback default.
//! - **Runner/config failure**: unknown scenario IDs, malformed selection,
//!   or invalid CLI usage. These are returned as `RunnerError` and the
//!   process should exit **2** (or another non-zero distinct from scenario
//!   failure). They never synthesize a fake `fail` finding.
//!
//! An optional explicit fail-fast mode (`--fail-fast` / `--strict`) exists
//! for CI diagnostics: when enabled the runner stops after the first
//! `fail` and the process exits **1** if any scenario failed. The flag
//! must not be the default for Task Ledger feedback.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt;

use crate::backend::{BackendContext, BackendHarness, BackendStart};
use crate::registry::ScenarioRegistry;
use crate::reports::{ScenarioResult, ValidationReport};
use crate::scenario::ScenarioDescriptor;

/// Error returned when scenario selection or runner configuration fails.
///
/// These errors are **not** synthetic scenario failures; they indicate the
/// runner itself could not proceed. Callers must not map them to a
/// `ScenarioOutcome::Fail` finding.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RunnerError {
    /// One or more requested scenario IDs are unknown to the registry.
    ///
    /// The payload is the sorted, deduplicated list of unknown IDs.
    UnknownScenarioIds(Vec<String>),
    /// The selection string could not be parsed (e.g. empty ID after split).
    InvalidSelection(String),
}

impl fmt::Display for RunnerError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnknownScenarioIds(ids) => {
                write!(f, "unknown scenario id(s): {}", ids.join(", "))
            }
            Self::InvalidSelection(msg) => write!(f, "invalid selection: {msg}"),
        }
    }
}

impl std::error::Error for RunnerError {}

/// Enumerates validator scenarios without owning Loom execution authority.
#[derive(Clone, Debug)]
pub struct Runner {
    registry: ScenarioRegistry,
}

impl Runner {
    /// Creates a runner over a scenario registry.
    #[must_use]
    pub fn new(registry: ScenarioRegistry) -> Self {
        Self { registry }
    }

    /// Borrows the registry that this runner will enumerate.
    #[must_use]
    pub fn registry(&self) -> &ScenarioRegistry {
        &self.registry
    }

    /// Enumerates the registry and returns its bootstrap report.
    #[must_use]
    pub fn run(&self) -> ValidationReport {
        ValidationReport::from_scenario_count(self.registry.len())
    }

    /// Executes each registered scenario via the provided executor.
    ///
    /// The executor is generic over the scenario descriptor and backend
    /// context. Adding a new scenario does not require changes to this
    /// runner—no scenario-specific branching is performed here.
    #[must_use]
    pub fn run_with<F>(&self, backend: &BackendContext, execute: F) -> ValidationReport
    where
        F: Fn(&ScenarioDescriptor, &BackendContext) -> ScenarioResult,
    {
        let results = self
            .registry
            .iter()
            .map(|descriptor| execute(descriptor, backend))
            .collect();
        ValidationReport::from_results(results)
    }

    /// Returns the deterministic list of all registered scenarios.
    ///
    /// The order is sorted by stable `CV-` identifier, matching
    /// `ScenarioRegistry` enumeration order.
    #[must_use]
    pub fn list(&self) -> Vec<&ScenarioDescriptor> {
        self.registry.iter().collect()
    }

    /// Resolves a set of requested scenario IDs to the corresponding descriptors.
    ///
    /// - Empty `ids` means *all available* scenarios (deterministic).
    /// - Each entry may contain comma-separated IDs; whitespace is trimmed.
    /// - IDs are deduplicated and returned in sorted (deterministic) order.
    /// - Unknown IDs return `RunnerError::UnknownScenarioIds` rather than a
    ///   synthetic failure.
    ///
    /// # Errors
    ///
    /// Returns `RunnerError::UnknownScenarioIds` when any requested ID is not
    /// registered.
    pub fn resolve_ids(&self, ids: &[String]) -> Result<Vec<&ScenarioDescriptor>, RunnerError> {
        self.resolve_with_groups(ids, &[], false)
    }

    /// Resolves IDs and optional capability-area groups to descriptors.
    ///
    /// Group selection filters by `ScenarioDescriptor::capability_area`. Each
    /// group entry may be comma-separated; groups are exact matches.
    ///
    /// Selection union: explicit IDs ∪ group-matched scenarios, deduplicated
    /// and sorted. Empty IDs and empty groups (and `all == false`) means
    /// *all available* scenarios. When `all == true`, selection is always
    /// all regardless of other filters.
    ///
    /// # Errors
    ///
    /// Unknown explicit IDs return `RunnerError`. Unknown groups do not error;
    /// they simply match no scenarios (result may be empty if no other IDs
    /// were requested, but empty selection is not itself an error except
    /// when the caller treats it as such).
    pub fn resolve_with_groups(
        &self,
        ids: &[String],
        groups: &[String],
        all: bool,
    ) -> Result<Vec<&ScenarioDescriptor>, RunnerError> {
        if all {
            return Ok(self.registry.iter().collect());
        }

        let expanded_ids = expand_csv(ids);
        let expanded_groups = expand_csv(groups);

        if expanded_ids.is_empty() && expanded_groups.is_empty() {
            return Ok(self.registry.iter().collect());
        }

        // Validate explicit IDs.
        let mut unknown = Vec::new();
        let mut selected_ids = BTreeSet::new();

        for id in &expanded_ids {
            if id.is_empty() {
                return Err(RunnerError::InvalidSelection(
                    "empty scenario id".to_string(),
                ));
            }
            if self.registry.get(id).is_none() {
                unknown.push(id.clone());
            } else {
                selected_ids.insert(id.clone());
            }
        }

        if !unknown.is_empty() {
            unknown.sort();
            unknown.dedup();
            return Err(RunnerError::UnknownScenarioIds(unknown));
        }

        // Group matching: exact capability area equality.
        if !expanded_groups.is_empty() {
            // Build a set of group strings for fast lookup.
            let group_set: BTreeSet<String> = expanded_groups.into_iter().collect();
            for descriptor in self.registry.iter() {
                if group_set.contains(descriptor.capability_area().as_str()) {
                    selected_ids.insert(descriptor.id_str().to_string());
                }
            }
        }

        // If after processing we have an empty set but groups were requested,
        // it means no scenario matched the groups. Return empty selection
        // (caller may decide to treat empty as success with 0 scenarios).
        if selected_ids.is_empty() {
            // If groups were requested but matched nothing, return empty vec.
            // If only unknown handling prevented this, we already errored.
            return Ok(Vec::new());
        }

        // Preserve deterministic order: sort IDs and then emit in sorted order.
        // Because registry.iter() is already sorted, we can filter it, but
        // we also need to respect sorted deduplicated requested order.
        // The canonical deterministic order is sorted by CV- ID.
        let mut sorted_ids: Vec<String> = selected_ids.into_iter().collect();
        sorted_ids.sort();

        // Build lookup map for efficiency.
        let lookup: BTreeMap<&str, &ScenarioDescriptor> =
            self.registry.iter().map(|d| (d.id_str(), d)).collect();

        let mut out = Vec::with_capacity(sorted_ids.len());
        for id in sorted_ids {
            if let Some(desc) = lookup.get(id.as_str()) {
                out.push(*desc);
            }
        }
        Ok(out)
    }

    /// Convenience wrapper that treats a slice of IDs without groups.
    ///
    /// Equivalent to `resolve_with_groups(ids, &[], all)`.
    ///
    /// # Errors
    ///
    /// Returns `RunnerError::UnknownScenarioIds` when any requested ID is unknown.
    pub fn resolve_selection(
        &self,
        ids: &[String],
        all: bool,
    ) -> Result<Vec<&ScenarioDescriptor>, RunnerError> {
        self.resolve_with_groups(ids, &[], all)
    }

    /// Executes the given selection deterministically.
    ///
    /// `selection` should be the result of `resolve_*`; it is executed in
    /// the order provided (which the resolver guarantees is sorted). When
    /// `fail_fast` is `false` (default), all selected scenarios run and
    /// failures are collected. When `true`, execution stops after the first
    /// `ScenarioOutcome::Fail` and the partial report is returned.
    #[must_use]
    pub fn run_selected<F>(
        &self,
        selection: &[&ScenarioDescriptor],
        backend: &BackendContext,
        execute: F,
        fail_fast: bool,
    ) -> ValidationReport
    where
        F: Fn(&ScenarioDescriptor, &BackendContext) -> ScenarioResult,
    {
        let mut results = Vec::with_capacity(selection.len());
        for descriptor in selection {
            let result = execute(descriptor, backend);
            let is_fail = result.outcome().is_fail();
            results.push(result);
            if fail_fast && is_fail {
                break;
            }
        }
        ValidationReport::from_results(results)
    }

    /// Executes a selection derived from raw ID and group strings.
    ///
    /// This is the high-level helper used by the CLI: it resolves the
    /// selection (returning `Err` for unknown IDs) and then executes with
    /// the provided executor in deterministic order, respecting `fail_fast`.
    ///
    /// # Errors
    ///
    /// Propagates `RunnerError` for unknown IDs or invalid selection;
    /// scenario failures are collected inside `Ok(ValidationReport)`.
    pub fn run_with_selection<F>(
        &self,
        ids: &[String],
        groups: &[String],
        all: bool,
        backend: &BackendContext,
        execute: F,
        fail_fast: bool,
    ) -> Result<ValidationReport, RunnerError>
    where
        F: Fn(&ScenarioDescriptor, &BackendContext) -> ScenarioResult,
    {
        let selection = self.resolve_with_groups(ids, groups, all)?;
        Ok(self.run_selected(&selection, backend, execute, fail_fast))
    }
}

    /// Executes the registry against one lifecycle-managed backend harness.
    ///
    /// A fresh public context is started and disposed for every supported
    /// scenario. Backend prerequisite/unavailable states become explicit
    /// scenario results and never invoke scenario code or become `pass`.
    #[must_use]
    pub fn run_with_harness<F>(&self, harness: &BackendHarness, execute: F) -> ValidationReport
    where
        F: Fn(&ScenarioDescriptor, &BackendContext) -> ScenarioResult,
    {
        let results = self
            .registry
            .iter()
            .map(|descriptor| {
                let backend = harness.backend_kind();
                if !descriptor.supported_backends().contains(backend) {
                    return ScenarioResult::prerequisite(
                        descriptor.id().clone(),
                        descriptor.name(),
                        *backend,
                        format!(
                            "scenario does not declare backend {} as supported",
                            backend.as_str()
                        ),
                    );
                }

                match harness.start(descriptor.id_str()) {
                    BackendStart::Ready(context) => {
                        let result = execute(descriptor, &context);
                        harness.dispose(context);
                        result
                    }
                    BackendStart::Prerequisite { backend, reason } => ScenarioResult::prerequisite(
                        descriptor.id().clone(),
                        descriptor.name(),
                        backend,
                        reason,
                    ),
                    BackendStart::Unavailable { backend, reason } => ScenarioResult::unavailable(
                        descriptor.id().clone(),
                        descriptor.name(),
                        backend,
                        reason,
                    ),
                }
            })
            .collect();
        ValidationReport::from_results_with_policy(results, harness.policy())
    }

/// Expands a slice of strings that may each contain comma-separated values
/// into a flat list of trimmed non-empty entries.
fn expand_csv(input: &[String]) -> Vec<String> {
    let mut out = Vec::new();
    for entry in input {
        for part in entry.split(',') {
            let trimmed = part.trim();
            if !trimmed.is_empty() {
                out.push(trimmed.to_string());
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::{Runner, RunnerError, ScenarioRegistry};
    use crate::backend::{BackendContext, BackendHarness, BackendStart};
    use crate::finding::{EvidenceReference, Finding};
    use crate::outcome::ScenarioOutcome;
    use crate::reports::ScenarioResult;
    use crate::scenario::{BackendKind, ScenarioDescriptor};
    use loom_client::LoomClient;

    fn descriptor(id: &str) -> ScenarioDescriptor {
        ScenarioDescriptor::new(
            id,
            format!("scenario {id}"),
            "world",
            vec![BackendKind::LoomClient],
            "none",
            vec![],
            vec![],
        )
    }

    fn descriptor_with_area(id: &str, area: &str) -> ScenarioDescriptor {
        ScenarioDescriptor::new(
            id,
            format!("scenario {id}"),
            area,
            vec![BackendKind::LoomClient],
            "none",
            vec![],
            vec![],
        )
    }

    #[test]
    fn runner_is_extensible_without_branching() {
        // The runner must not contain scenario-specific branching. This test
        // demonstrates extensibility by adding two new scenarios without
        // modifying the runner and executing them via a generic closure.
        let mut registry = ScenarioRegistry::bootstrap();
        registry.register(descriptor("CV-001")).unwrap();
        registry.register(descriptor("CV-002")).unwrap();

        let runner = Runner::new(registry);
        // Construct a minimal client for the backend context. The URL is not
        // used because the executor in this test does not perform network calls.
        let client = LoomClient::builder("http://localhost:8080".to_string())
            .build()
            .expect("client builder should succeed for test");
        let backend = BackendContext::new(client);

        let report = runner.run_with(&backend, |desc, ctx| {
            // Generic execution: no match on id, just uses descriptor metadata and backend.
            let _ = ctx.client();
            let finding = Finding::new(
                desc.id().clone(),
                desc.name(),
                "expected",
                "actual",
                desc.supported_backends()[0].clone(),
                "test-context",
                vec![EvidenceReference::new("evidence:test")],
                ScenarioOutcome::Pass,
            );
            ScenarioResult::new(desc.id().clone(), ScenarioOutcome::Pass, finding)
        });

        assert_eq!(report.scenario_count(), 2);
        assert_eq!(report.results().len(), 2);
        let ids: Vec<_> = report
            .results()
            .iter()
            .map(|r| r.scenario_id().as_str().to_string())
            .collect();
        assert_eq!(ids, vec!["CV-001", "CV-002"]);
    }

    #[test]
    fn list_is_deterministic() {
        let mut registry = ScenarioRegistry::bootstrap();
        registry.register(descriptor("CV-003")).unwrap();
        registry.register(descriptor("CV-001")).unwrap();
        registry.register(descriptor("CV-002")).unwrap();
        let runner = Runner::new(registry);
        let ids: Vec<_> = runner
            .list()
            .iter()
            .map(|d| d.id_str().to_string())
            .collect();
        assert_eq!(ids, vec!["CV-001", "CV-002", "CV-003"]);
    }

    #[test]
    fn single_selection_works() {
        let mut registry = ScenarioRegistry::bootstrap();
        registry.register(descriptor("CV-001")).unwrap();
        registry.register(descriptor("CV-002")).unwrap();
        let runner = Runner::new(registry);
        let sel = runner.resolve_ids(&["CV-001".to_string()]).unwrap();
        assert_eq!(sel.len(), 1);
        assert_eq!(sel[0].id_str(), "CV-001");
    }

    #[test]
    fn multi_selection_is_sorted_and_deduped() {
        let mut registry = ScenarioRegistry::bootstrap();
        registry.register(descriptor("CV-001")).unwrap();
        registry.register(descriptor("CV-002")).unwrap();
        registry.register(descriptor("CV-003")).unwrap();
        let runner = Runner::new(registry);
        // Intentionally out of order and duplicated, with comma.
        let sel = runner
            .resolve_ids(&[
                "CV-003,CV-001".to_string(),
                "CV-002".to_string(),
                "CV-001".to_string(),
            ])
            .unwrap();
        let ids: Vec<_> = sel.iter().map(|d| d.id_str().to_string()).collect();
        assert_eq!(ids, vec!["CV-001", "CV-002", "CV-003"]);
    }

    #[test]
    fn all_selection_when_empty() {
        let mut registry = ScenarioRegistry::bootstrap();
        registry.register(descriptor("CV-001")).unwrap();
        registry.register(descriptor("CV-002")).unwrap();
        let runner = Runner::new(registry);
        let sel = runner.resolve_ids(&[]).unwrap();
        let ids: Vec<_> = sel.iter().map(|d| d.id_str().to_string()).collect();
        assert_eq!(ids, vec!["CV-001", "CV-002"]);
    }

    #[test]
    fn unknown_ids_return_runner_error() {
        let mut registry = ScenarioRegistry::bootstrap();
        registry.register(descriptor("CV-001")).unwrap();
        let runner = Runner::new(registry);
        let err = runner.resolve_ids(&["CV-999".to_string()]).unwrap_err();
        assert_eq!(
            err,
            RunnerError::UnknownScenarioIds(vec!["CV-999".to_string()])
        );
        // Ensure the error displays as runner error, not fake failure.
        let msg = format!("{err}");
        assert!(msg.contains("unknown scenario"));
        assert!(!msg.contains("fail"));
    }

    #[test]
    fn unknown_ids_are_not_fake_failures() {
        let mut registry = ScenarioRegistry::bootstrap();
        registry.register(descriptor("CV-001")).unwrap();
        let runner = Runner::new(registry);
        let client = LoomClient::builder("http://localhost:8080".to_string())
            .build()
            .unwrap();
        let backend = BackendContext::new(client);
        let err = runner
            .run_with_selection(
                &["CV-999".to_string()],
                &[],
                false,
                &backend,
                |desc, ctx| {
                    let _ = ctx.client();
                    let finding = Finding::new(
                        desc.id().clone(),
                        desc.name(),
                        "expected",
                        "actual",
                        BackendKind::LoomClient,
                        "ctx",
                        vec![],
                        ScenarioOutcome::Pass,
                    );
                    ScenarioResult::new(desc.id().clone(), ScenarioOutcome::Pass, finding)
                },
                false,
            )
            .unwrap_err();
        assert!(matches!(err, RunnerError::UnknownScenarioIds(_)));
    }

    #[test]
    fn failing_scenario_does_not_prevent_later() {
        let mut registry = ScenarioRegistry::bootstrap();
        registry.register(descriptor("CV-001")).unwrap();
        registry.register(descriptor("CV-002")).unwrap();
        registry.register(descriptor("CV-003")).unwrap();
        let runner = Runner::new(registry);
        let client = LoomClient::builder("http://localhost:8080".to_string())
            .build()
            .unwrap();
        let backend = BackendContext::new(client);
        let selection = runner
            .resolve_ids(&[
                "CV-001".to_string(),
                "CV-002".to_string(),
                "CV-003".to_string(),
            ])
            .unwrap();
        let report = runner.run_selected(
            &selection,
            &backend,
            |desc, _| {
                let outcome = if desc.id_str() == "CV-002" {
                    ScenarioOutcome::Fail
                } else {
                    ScenarioOutcome::Pass
                };
                let finding = Finding::new(
                    desc.id().clone(),
                    desc.name(),
                    "expected",
                    "actual",
                    BackendKind::LoomClient,
                    "ctx",
                    vec![],
                    outcome.clone(),
                );
                ScenarioResult::new(desc.id().clone(), outcome, finding)
            },
            false, // normal mode: continue
        );
        assert_eq!(report.scenario_count(), 3);
        assert_eq!(report.passed_count(), 2);
        assert_eq!(report.failed_count(), 1);
        // Verify deterministic ordering still holds even after failure.
        let ids: Vec<_> = report
            .results()
            .iter()
            .map(|r| r.scenario_id().as_str().to_string())
            .collect();
        assert_eq!(ids, vec!["CV-001", "CV-002", "CV-003"]);
        // Ensure scenario after failure still ran.
        assert_eq!(report.results()[2].outcome(), &ScenarioOutcome::Pass);
    }

    #[test]
    fn fail_fast_stops_after_first_failure() {
        let mut registry = ScenarioRegistry::bootstrap();
        registry.register(descriptor("CV-001")).unwrap();
        registry.register(descriptor("CV-002")).unwrap();
        registry.register(descriptor("CV-003")).unwrap();
        let runner = Runner::new(registry);
        let client = LoomClient::builder("http://localhost:8080".to_string())
            .build()
            .unwrap();
        let backend = BackendContext::new(client);
        let selection = runner
            .resolve_ids(&[
                "CV-001".to_string(),
                "CV-002".to_string(),
                "CV-003".to_string(),
            ])
            .unwrap();
        let report = runner.run_selected(
            &selection,
            &backend,
            |desc, _| {
                let outcome = if desc.id_str() == "CV-001" {
                    ScenarioOutcome::Fail
                } else {
                    ScenarioOutcome::Pass
                };
                let finding = Finding::new(
                    desc.id().clone(),
                    desc.name(),
                    "expected",
                    "actual",
                    BackendKind::LoomClient,
                    "ctx",
                    vec![],
                    outcome.clone(),
                );
                ScenarioResult::new(desc.id().clone(), outcome, finding)
            },
            true, // fail-fast
        );
        // Should stop after CV-001.
        assert_eq!(report.scenario_count(), 1);
        assert_eq!(report.failed_count(), 1);
        assert_eq!(report.results()[0].scenario_id().as_str(), "CV-001");
    }

    #[test]
    fn deterministic_execution_ordering() {
        let mut registry = ScenarioRegistry::bootstrap();
        registry.register(descriptor("CV-003")).unwrap();
        registry.register(descriptor("CV-001")).unwrap();
        registry.register(descriptor("CV-002")).unwrap();
        let runner = Runner::new(registry);
        // Request in reverse order.
        let sel = runner
            .resolve_ids(&[
                "CV-003".to_string(),
                "CV-002".to_string(),
                "CV-001".to_string(),
            ])
            .unwrap();
        let ids: Vec<_> = sel.iter().map(|d| d.id_str().to_string()).collect();
        assert_eq!(ids, vec!["CV-001", "CV-002", "CV-003"]);
        // Execution should follow that sorted order regardless of input order.
        let client = LoomClient::builder("http://localhost:8080".to_string())
            .build()
            .unwrap();
        let backend = BackendContext::new(client);
        let report = runner.run_selected(
            &sel,
            &backend,
            |desc, _| {
                let finding = Finding::new(
                    desc.id().clone(),
                    desc.name(),
                    "expected",
                    "actual",
                    BackendKind::LoomClient,
                    "ctx",
                    vec![],
                    ScenarioOutcome::Pass,
                );
                ScenarioResult::new(desc.id().clone(), ScenarioOutcome::Pass, finding)
            },
            false,
        );
        let exec_ids: Vec<_> = report
            .results()
            .iter()
            .map(|r| r.scenario_id().as_str().to_string())
            .collect();
        assert_eq!(exec_ids, vec!["CV-001", "CV-002", "CV-003"]);
    }

    #[test]
    fn group_selection_works() {
        let mut registry = ScenarioRegistry::bootstrap();
        registry
            .register(descriptor_with_area("CV-001", "world"))
            .unwrap();
        registry
            .register(descriptor_with_area("CV-002", "agency"))
            .unwrap();
        registry
            .register(descriptor_with_area("CV-003", "world"))
            .unwrap();
        let runner = Runner::new(registry);
        let sel = runner
            .resolve_with_groups(&[], &["world".to_string()], false)
            .unwrap();
        let ids: Vec<_> = sel.iter().map(|d| d.id_str().to_string()).collect();
        assert_eq!(ids, vec!["CV-001", "CV-003"]);
        // Mixed IDs + groups.
        let sel2 = runner
            .resolve_with_groups(&["CV-002".to_string()], &["world".to_string()], false)
            .unwrap();
        let ids2: Vec<_> = sel2.iter().map(|d| d.id_str().to_string()).collect();
        assert_eq!(ids2, vec!["CV-001", "CV-002", "CV-003"]);
    }

    #[test]
    fn all_flag_overrides_selection() {
        let mut registry = ScenarioRegistry::bootstrap();
        registry.register(descriptor("CV-001")).unwrap();
        registry.register(descriptor("CV-002")).unwrap();
        let runner = Runner::new(registry);
        let sel = runner
            .resolve_with_groups(&["CV-001".to_string()], &["world".to_string()], true)
            .unwrap();
        let ids: Vec<_> = sel.iter().map(|d| d.id_str().to_string()).collect();
        assert_eq!(ids, vec!["CV-001", "CV-002"]);
    }

    #[test]
    fn repeated_ids_are_deduped() {
        let mut registry = ScenarioRegistry::bootstrap();
        registry.register(descriptor("CV-001")).unwrap();
        registry.register(descriptor("CV-002")).unwrap();
        let runner = Runner::new(registry);
        let sel = runner
            .resolve_ids(&[
                "CV-001".to_string(),
                "CV-001".to_string(),
                "CV-002,CV-001".to_string(),
            ])
            .unwrap();
        let ids: Vec<_> = sel.iter().map(|d| d.id_str().to_string()).collect();
        assert_eq!(ids, vec!["CV-001", "CV-002"]);
    }
    #[test]
    fn harness_starts_and_disposes_a_fresh_context_per_scenario() {
        use std::cell::RefCell;

        let mut registry = ScenarioRegistry::bootstrap();
        registry.register(descriptor("CV-001")).unwrap();
        registry.register(descriptor("CV-002")).unwrap();
        let runner = Runner::new(registry);
        let harness = BackendHarness::connect(BackendKind::LoomClient, "http://localhost:8080")
            .expect("public client should build");

        let scopes = RefCell::new(Vec::new());
        let report = runner.run_with_harness(&harness, |descriptor, context| {
            scopes.borrow_mut().push(context.scope().to_owned());
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "context is fresh",
                context.scope(),
                BackendKind::LoomClient,
                "harness",
                vec![],
                ScenarioOutcome::Pass,
            );
            ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Pass, finding)
        });

        assert!(report.gate_passes());
        assert_eq!(*scopes.borrow(), vec!["CV-001", "CV-002"]);
    }

}
