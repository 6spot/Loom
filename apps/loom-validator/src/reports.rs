//! Validator run reports.

use std::collections::BTreeSet;
use std::path::Path;

use serde_json::{Map, Value, json};

use crate::finding::{EvidenceReference, Finding};
use crate::outcome::ScenarioOutcome;
use crate::scenario::{BackendEvidence, BackendKind, ScenarioId};

/// Version of the machine-readable validator report schema.
pub const REPORT_SCHEMA_VERSION: u64 = 1;

/// Stable report kind used by CI and Task Ledger consumers.
pub const REPORT_KIND: &str = "loom-validator";

/// An explicit Task Ledger record selected for a scenario.
///
/// The validator never derives a task path from a scenario name or from a
/// directory scan. Callers must provide this reference in run metadata.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TaskRecordReference {
    scenario_id: String,
    path: String,
}

impl TaskRecordReference {
    /// Creates an explicit scenario-to-task-record mapping.
    #[must_use]
    pub fn new(scenario_id: impl Into<String>, path: impl Into<String>) -> Self {
        Self {
            scenario_id: scenario_id.into(),
            path: path.into(),
        }
    }

    /// Returns the scenario covered by this mapping.
    #[must_use]
    pub fn scenario_id(&self) -> &str {
        &self.scenario_id
    }

    /// Returns the explicitly supplied task-record path.
    #[must_use]
    pub fn path(&self) -> &str {
        &self.path
    }
}

/// Metadata identifying the run that produced a report.
///
/// Values are supplied by the caller instead of being generated implicitly so
/// serializing equivalent results remains deterministic. Empty values mean
/// that the caller did not have the corresponding run metadata.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct RunMetadata {
    run_id: String,
    command: String,
    evidence: Vec<EvidenceReference>,
    observation_date: Option<String>,
    task_record: Option<String>,
    task_records: Vec<TaskRecordReference>,
}

impl RunMetadata {
    /// Creates metadata for a validator run.
    #[must_use]
    pub fn new(run_id: impl Into<String>) -> Self {
        Self {
            run_id: run_id.into(),
            ..Self::default()
        }
    }

    /// Sets the command that produced this report.
    #[must_use]
    pub fn with_command(mut self, command: impl Into<String>) -> Self {
        self.command = command.into();
        self
    }

    /// Adds one durable evidence reference to this run.
    #[must_use]
    pub fn with_evidence(mut self, evidence: EvidenceReference) -> Self {
        self.evidence.push(evidence);
        self
    }

    /// Sets the observation date used by Task Ledger feedback.
    ///
    /// The date is intentionally caller-supplied so report serialization and
    /// task-file feedback do not acquire an implicit wall-clock dependency.
    #[must_use]
    pub fn with_observation_date(mut self, observation_date: impl Into<String>) -> Self {
        self.observation_date = Some(observation_date.into());
        self
    }

    /// Sets one explicit task record for every scenario in this run.
    #[must_use]
    pub fn with_task_record(mut self, path: impl Into<String>) -> Self {
        self.task_record = Some(path.into());
        self
    }

    /// Adds an explicit task-record mapping for one scenario.
    #[must_use]
    pub fn with_task_record_for_scenario(
        mut self,
        scenario_id: impl Into<String>,
        path: impl Into<String>,
    ) -> Self {
        self.task_records
            .push(TaskRecordReference::new(scenario_id, path));
        self
    }

    /// Adds an explicit task-record mapping for one scenario.
    #[must_use]
    pub fn with_task_record_reference(mut self, reference: TaskRecordReference) -> Self {
        self.task_records.push(reference);
        self
    }

    /// Sets the run identifier used as the feedback run reference.
    #[must_use]
    pub fn with_run_id(mut self, run_id: impl Into<String>) -> Self {
        self.run_id = run_id.into();
        self
    }

    /// Returns the run identifier.
    #[must_use]
    pub fn run_id(&self) -> &str {
        &self.run_id
    }

    /// Returns the producing command.
    #[must_use]
    pub fn command(&self) -> &str {
        &self.command
    }

    /// Returns durable evidence references for this run.
    #[must_use]
    pub fn evidence(&self) -> &[EvidenceReference] {
        &self.evidence
    }

    /// Returns the supplied observation date, if any.
    #[must_use]
    pub fn observation_date(&self) -> Option<&str> {
        self.observation_date.as_deref()
    }

    /// Returns the global task-record path, if any.
    #[must_use]
    pub fn task_record(&self) -> Option<&str> {
        self.task_record.as_deref()
    }

    /// Returns explicit per-scenario task-record mappings.
    #[must_use]
    pub fn task_records(&self) -> &[TaskRecordReference] {
        &self.task_records
    }
}

/// The aggregate state of a validator report.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ReportResultState {
    /// Every executed scenario passed.
    Pass,
    /// At least one executed scenario returned a failure.
    ScenarioFailure,
    /// A required backend prerequisite was missing or unavailable.
    PrerequisiteUnavailable,
    /// Selection or runner configuration prevented execution.
    RunnerConfigFailure,
    /// No scenario was selected or executed.
    NoScenarios,
}

impl ReportResultState {
    /// Returns the stable machine-readable state label.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Pass => "pass",
            Self::ScenarioFailure => "scenario_failure",
            Self::PrerequisiteUnavailable => "prerequisite_unavailable",
            Self::RunnerConfigFailure => "runner_config_failure",
            Self::NoScenarios => "no_scenarios",
        }
    }
}

impl std::fmt::Display for ReportResultState {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(self.as_str())
    }
}

/// Classification of a prerequisite detail in a machine-readable report.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PrerequisiteState {
    /// The declared prerequisite was not configured.
    Missing,
    /// The prerequisite was configured but could not be used.
    Unavailable,
}

impl PrerequisiteState {
    /// Returns the stable machine-readable prerequisite state.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Missing => "missing",
            Self::Unavailable => "unavailable",
        }
    }
}

impl std::fmt::Display for PrerequisiteState {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(self.as_str())
    }
}

/// Gate policy for a validator report.
///
/// Best-effort mode keeps optional live backends observable without turning an
/// unavailable prerequisite into a synthetic scenario failure. Strict mode
/// requires every selected scenario to pass. Required-live mode additionally
/// requires passing trusted `PostgreSQL` evidence, so a generic endpoint or an
/// ambient `LOOM_TEST_POSTGRES_URL` cannot satisfy the gate.
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
    capability_area: Option<String>,
}

impl ScenarioResult {
    /// Creates a new scenario result.
    #[must_use]
    pub fn new(scenario_id: ScenarioId, outcome: ScenarioOutcome, finding: Finding) -> Self {
        Self {
            scenario_id,
            outcome,
            finding,
            capability_area: None,
        }
    }

    /// Attaches the stable capability area from the selected scenario
    /// descriptor.
    #[must_use]
    pub fn with_capability_area(mut self, capability_area: impl Into<String>) -> Self {
        self.capability_area = Some(capability_area.into());
        self
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

    /// Returns the selected scenario's capability area, when the runner had
    /// descriptor metadata available.
    #[must_use]
    pub fn capability_area(&self) -> Option<&str> {
        self.capability_area.as_deref()
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
    selected_scenario_ids: Vec<String>,
    backend: Option<BackendKind>,
    backend_evidence: Option<BackendEvidence>,
    run_metadata: RunMetadata,
    runner_error: Option<String>,
}

/// Public name for the canonical machine-readable validator report.
pub type MachineReport = ValidationReport;

impl ValidationReport {
    pub(crate) fn from_scenario_count(scenario_count: usize) -> Self {
        Self {
            scenario_count,
            results: Vec::new(),
            policy: ValidationPolicy::default(),
            selected_scenario_ids: Vec::new(),
            backend: None,
            backend_evidence: None,
            run_metadata: RunMetadata::default(),
            runner_error: None,
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
        mut results: Vec<ScenarioResult>,
        policy: ValidationPolicy,
    ) -> Self {
        // Canonical ordering is part of the report contract. A caller may
        // collect results concurrently or pass an equivalent set in another
        // order; both inputs must serialize identically.
        results.sort_by(|left, right| {
            left.scenario_id()
                .cmp(right.scenario_id())
                .then_with(|| left.serialize().cmp(&right.serialize()))
        });
        let count = results.len();
        let selected_scenario_ids = results
            .iter()
            .map(|result| result.scenario_id().as_str().to_owned())
            .collect();
        let backend = results.first().map(|result| *result.finding().backend());
        let backend_evidence = backend.map(BackendKind::evidence);
        Self {
            scenario_count: count,
            results,
            policy,
            selected_scenario_ids,
            backend,
            backend_evidence,
            run_metadata: RunMetadata::default(),
            runner_error: None,
        }
    }

    /// Creates a report representing a runner/configuration failure.
    ///
    /// This keeps configuration errors machine-readable without inventing a
    /// synthetic scenario finding.
    #[must_use]
    pub fn runner_config_failure(
        selected_scenario_ids: Vec<String>,
        error: impl Into<String>,
    ) -> Self {
        Self {
            scenario_count: 0,
            results: Vec::new(),
            policy: ValidationPolicy::default(),
            selected_scenario_ids: canonical_ids(selected_scenario_ids),
            backend: None,
            backend_evidence: None,
            run_metadata: RunMetadata::default(),
            runner_error: Some(error.into()),
        }
    }

    /// Replaces the selected IDs represented by this report.
    #[must_use]
    pub fn with_selected_scenario_ids(mut self, ids: Vec<String>) -> Self {
        self.selected_scenario_ids = canonical_ids(ids);
        self
    }

    /// Records the backend selected for this run.
    #[must_use]
    pub const fn with_backend(mut self, backend: BackendKind) -> Self {
        self.backend = Some(backend);
        self.backend_evidence = Some(backend.evidence());
        self
    }

    /// Records the explicit storage evidence selected for this report.
    #[must_use]
    pub const fn with_backend_evidence(mut self, evidence: BackendEvidence) -> Self {
        self.backend_evidence = Some(evidence);
        self.backend = Some(evidence.backend_kind());
        self
    }

    /// Records run metadata for this report.
    #[must_use]
    pub fn with_run_metadata(mut self, metadata: RunMetadata) -> Self {
        self.run_metadata = metadata;
        self
    }

    /// Returns the selected scenario IDs in canonical order.
    #[must_use]
    pub fn selected_scenario_ids(&self) -> &[String] {
        &self.selected_scenario_ids
    }

    /// Returns the backend selected for this report, if one was provided or
    /// inferred from a scenario finding.
    #[must_use]
    pub const fn backend(&self) -> Option<BackendKind> {
        self.backend
    }

    /// Returns the storage evidence selected for this report, if known.
    #[must_use]
    pub const fn backend_evidence(&self) -> Option<BackendEvidence> {
        self.backend_evidence
    }

    /// Returns the run metadata attached to this report.
    #[must_use]
    pub const fn run_metadata(&self) -> &RunMetadata {
        &self.run_metadata
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
            return self.backend_evidence == Some(BackendEvidence::PostgreSQL)
                && self.results.iter().any(|result| {
                    result.finding().backend().evidence() == BackendEvidence::PostgreSQL
                        && result.outcome().is_pass()
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

    /// Returns the aggregate machine-readable result state.
    #[must_use]
    pub fn result_state(&self) -> ReportResultState {
        if self.runner_error.is_some() {
            return ReportResultState::RunnerConfigFailure;
        }
        if self.results.is_empty() {
            return ReportResultState::NoScenarios;
        }
        if self.has_failures() {
            return ReportResultState::ScenarioFailure;
        }
        if self
            .results
            .iter()
            .any(|result| result.outcome().is_skipped() || result.outcome().is_unavailable())
        {
            return ReportResultState::PrerequisiteUnavailable;
        }
        ReportResultState::Pass
    }

    /// Returns prerequisite details derived from explicit non-pass backend
    /// start results. Scenario failures are deliberately not included here.
    #[must_use]
    pub fn prerequisite_details(&self) -> Vec<PrerequisiteDetail> {
        self.results
            .iter()
            .filter_map(PrerequisiteDetail::from_result)
            .collect()
    }

    /// Serializes the complete report as canonical compact JSON.
    ///
    /// Object keys use a `BTreeMap` and all report arrays are canonicalized, so
    /// equivalent scenario results have byte-identical output.
    ///
    /// # Panics
    ///
    /// Panics only if the local `serde_json` serializer cannot serialize a
    /// `serde_json::Value`, which is not expected for this report schema.
    #[must_use]
    pub fn serialize_json(&self) -> String {
        serde_json::to_string(&self.json_value()).expect("validator report JSON is serializable")
    }

    /// Alias for [`Self::serialize_json`].
    #[must_use]
    pub fn to_json(&self) -> String {
        self.serialize_json()
    }

    /// Serializes the report using the canonical deterministic machine format.
    #[must_use]
    pub fn to_json_deterministic(&self) -> String {
        self.serialize_json()
    }

    /// Serializes this report using the canonical machine-readable format.
    #[must_use]
    pub fn serialize(&self) -> String {
        self.serialize_json()
    }

    /// Renders this report using the canonical machine-readable format.
    #[must_use]
    pub fn render(&self) -> String {
        self.serialize_json()
    }

    /// Returns the report as a JSON value for embedding in another artifact.
    #[must_use]
    pub fn json_value(&self) -> Value {
        let mut report = Map::new();
        report.insert(
            "backend".to_owned(),
            self.backend
                .map_or(Value::Null, |backend| json!(backend.as_str())),
        );
        report.insert(
            "backend_evidence".to_owned(),
            self.backend_evidence
                .map_or(Value::Null, |evidence| json!(evidence.as_str())),
        );
        report.insert(
            "backend_evidence_trusted".to_owned(),
            json!(
                self.backend_evidence
                    .is_some_and(BackendEvidence::is_trusted)
            ),
        );
        report.insert("counts".to_owned(), self.json_counts());
        report.insert("findings".to_owned(), Value::Array(self.json_findings()));
        report.insert(
            "prerequisites".to_owned(),
            Value::Array(self.json_prerequisites()),
        );
        report.insert(
            "result_state".to_owned(),
            json!(self.result_state().as_str()),
        );
        report.insert("results".to_owned(), Value::Array(self.json_results()));
        report.insert("run".to_owned(), self.json_run_metadata());
        report.insert("schema_version".to_owned(), json!(REPORT_SCHEMA_VERSION));
        report.insert("summary".to_owned(), json!(self.human_summary()));
        report.insert(
            "selected_scenario_ids".to_owned(),
            json!(self.selected_scenario_ids),
        );
        report.insert("type".to_owned(), json!(REPORT_KIND));
        report.insert(
            "runner_error".to_owned(),
            self.runner_error.clone().map_or(Value::Null, Value::String),
        );
        Value::Object(report)
    }

    /// Writes only the machine-readable report artifact to `path`.
    ///
    /// This method never appends to a task record and does not write raw
    /// diagnostics. Callers opt into the destination explicitly.
    ///
    /// # Errors
    ///
    /// Returns the filesystem error produced while creating or writing the
    /// explicitly requested artifact path.
    pub fn write_json(&self, path: impl AsRef<Path>) -> std::io::Result<()> {
        std::fs::write(path, self.serialize_json())
    }

    /// Returns a human summary that points at machine evidence when the run
    /// metadata contains a durable reference.
    #[must_use]
    pub fn human_summary(&self) -> String {
        let mut summary = format!(
            "{}; result_state={}",
            self.summary_line(),
            self.result_state()
        );
        let evidence = canonical_evidence(&self.run_metadata.evidence);
        if !evidence.is_empty() {
            summary.push_str("; machine_evidence=");
            summary.push_str(
                &evidence
                    .iter()
                    .map(|reference| reference.as_str())
                    .collect::<Vec<_>>()
                    .join(","),
            );
        }
        summary
    }

    fn json_run_metadata(&self) -> Value {
        let mut run = Map::new();
        run.insert(
            "backend".to_owned(),
            self.backend
                .map_or(Value::Null, |backend| json!(backend.as_str())),
        );
        run.insert(
            "backend_evidence".to_owned(),
            self.backend_evidence
                .map_or(Value::Null, |evidence| json!(evidence.as_str())),
        );
        run.insert(
            "backend_evidence_trusted".to_owned(),
            json!(
                self.backend_evidence
                    .is_some_and(BackendEvidence::is_trusted)
            ),
        );
        run.insert("command".to_owned(), json!(self.run_metadata.command));
        run.insert(
            "evidence".to_owned(),
            json!(
                canonical_evidence(&self.run_metadata.evidence)
                    .iter()
                    .map(|reference| reference.as_str())
                    .collect::<Vec<_>>()
            ),
        );
        run.insert("run_id".to_owned(), json!(self.run_metadata.run_id));
        run.insert(
            "observation_date".to_owned(),
            self.run_metadata
                .observation_date
                .clone()
                .map_or(Value::Null, Value::String),
        );
        run.insert(
            "policy".to_owned(),
            json!({
                "required_live": self.policy.requires_live(),
                "strict": self.policy.is_strict(),
            }),
        );
        run.insert("selected_ids".to_owned(), json!(self.selected_scenario_ids));
        run.insert(
            "task_record".to_owned(),
            self.run_metadata
                .task_record
                .clone()
                .map_or(Value::Null, Value::String),
        );
        run.insert(
            "task_records".to_owned(),
            json!(
                self.run_metadata
                    .task_records
                    .iter()
                    .map(|reference| {
                        json!({
                            "path": reference.path(),
                            "scenario_id": reference.scenario_id(),
                        })
                    })
                    .collect::<Vec<_>>()
            ),
        );
        Value::Object(run)
    }

    fn json_counts(&self) -> Value {
        json!({
            "fail": self.failed_count(),
            "pass": self.passed_count(),
            "skipped": self.skipped_count(),
            "total": self.scenario_count(),
            "unavailable": self.unavailable_count(),
        })
    }

    fn json_results(&self) -> Vec<Value> {
        self.results
            .iter()
            .map(|result| {
                let finding = result.finding();
                let mut value = Map::new();
                value.insert("actual".to_owned(), json!(finding.actual()));
                value.insert("backend".to_owned(), json!(finding.backend().as_str()));
                value.insert(
                    "backend_evidence".to_owned(),
                    json!(finding.backend().evidence().as_str()),
                );
                value.insert(
                    "backend_evidence_trusted".to_owned(),
                    json!(finding.backend().evidence().is_trusted()),
                );
                value.insert(
                    "capability_area".to_owned(),
                    json!(result.capability_area().unwrap_or_default()),
                );
                value.insert("context".to_owned(), json!(finding.context()));
                value.insert(
                    "evidence".to_owned(),
                    json!(
                        canonical_evidence(finding.evidence())
                            .iter()
                            .map(|reference| reference.as_str())
                            .collect::<Vec<_>>()
                    ),
                );
                value.insert("expected".to_owned(), json!(finding.expected()));
                value.insert("name".to_owned(), json!(finding.scenario_name()));
                value.insert("outcome".to_owned(), json!(result.outcome().as_str()));
                value.insert(
                    "reason".to_owned(),
                    result
                        .outcome()
                        .reason()
                        .map_or(Value::Null, |reason| json!(reason)),
                );
                value.insert(
                    "scenario_id".to_owned(),
                    json!(result.scenario_id().as_str()),
                );
                Value::Object(value)
            })
            .collect()
    }

    fn json_findings(&self) -> Vec<Value> {
        self.results
            .iter()
            .map(|result| {
                let finding = result.finding();
                let mut value = Map::new();
                value.insert("actual".to_owned(), json!(finding.actual()));
                value.insert("backend".to_owned(), json!(finding.backend().as_str()));
                value.insert(
                    "backend_evidence".to_owned(),
                    json!(finding.backend().evidence().as_str()),
                );
                value.insert(
                    "backend_evidence_trusted".to_owned(),
                    json!(finding.backend().evidence().is_trusted()),
                );
                value.insert("context".to_owned(), json!(finding.context()));
                value.insert(
                    "evidence".to_owned(),
                    json!(
                        canonical_evidence(finding.evidence())
                            .iter()
                            .map(|reference| reference.as_str())
                            .collect::<Vec<_>>()
                    ),
                );
                value.insert("expected".to_owned(), json!(finding.expected()));
                value.insert("outcome".to_owned(), json!(result.outcome().as_str()));
                value.insert(
                    "scenario_id".to_owned(),
                    json!(result.scenario_id().as_str()),
                );
                value.insert("scenario_name".to_owned(), json!(finding.scenario_name()));
                Value::Object(value)
            })
            .collect()
    }

    fn json_prerequisites(&self) -> Vec<Value> {
        self.prerequisite_details()
            .iter()
            .map(PrerequisiteDetail::json_value)
            .collect()
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

/// One explicit prerequisite detail attached to a skipped/unavailable result.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PrerequisiteDetail {
    scenario_id: ScenarioId,
    backend: BackendKind,
    state: PrerequisiteState,
    reason: String,
}

impl PrerequisiteDetail {
    fn from_result(result: &ScenarioResult) -> Option<Self> {
        let (state, reason) = match result.outcome() {
            ScenarioOutcome::Skipped { reason } => (PrerequisiteState::Missing, reason.clone()),
            ScenarioOutcome::Unavailable { reason } => {
                (PrerequisiteState::Unavailable, reason.clone())
            }
            ScenarioOutcome::Pass | ScenarioOutcome::Fail => return None,
        };
        Some(Self {
            scenario_id: result.scenario_id().clone(),
            backend: *result.finding().backend(),
            state,
            reason,
        })
    }

    /// Returns the scenario associated with this prerequisite detail.
    #[must_use]
    pub fn scenario_id(&self) -> &ScenarioId {
        &self.scenario_id
    }

    /// Returns the backend that could not be used.
    #[must_use]
    pub const fn backend(&self) -> BackendKind {
        self.backend
    }

    /// Returns the prerequisite state.
    #[must_use]
    pub const fn state(&self) -> PrerequisiteState {
        self.state
    }

    /// Returns the factual prerequisite reason.
    #[must_use]
    pub fn reason(&self) -> &str {
        &self.reason
    }

    fn json_value(&self) -> Value {
        let mut detail = Map::new();
        detail.insert("backend".to_owned(), json!(self.backend.as_str()));
        detail.insert(
            "backend_evidence".to_owned(),
            json!(self.backend.evidence().as_str()),
        );
        detail.insert(
            "backend_evidence_trusted".to_owned(),
            json!(self.backend.evidence().is_trusted()),
        );
        detail.insert("reason".to_owned(), json!(self.reason));
        detail.insert("scenario_id".to_owned(), json!(self.scenario_id.as_str()));
        detail.insert("state".to_owned(), json!(self.state.as_str()));
        Value::Object(detail)
    }
}

fn canonical_ids(ids: Vec<String>) -> Vec<String> {
    let ids: BTreeSet<String> = ids
        .into_iter()
        .filter(|id| !id.trim().is_empty())
        .map(|id| id.trim().to_owned())
        .collect();
    ids.into_iter().collect()
}

fn canonical_evidence<'a>(
    evidence: impl IntoIterator<Item = &'a EvidenceReference>,
) -> Vec<&'a EvidenceReference> {
    let mut sorted = evidence.into_iter().collect::<Vec<_>>();
    sorted.sort_by(|left, right| left.as_str().cmp(right.as_str()));
    sorted.dedup_by(|left, right| left.as_str() == right.as_str());
    sorted
}

#[cfg(test)]
mod tests {
    use super::{
        ReportResultState, RunMetadata, ScenarioResult, ValidationPolicy, ValidationReport,
    };
    use crate::finding::{EvidenceReference, Finding};
    use crate::outcome::ScenarioOutcome;
    use crate::scenario::{BackendEvidence, BackendKind, ScenarioId};

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

    fn result(
        id: &str,
        outcome: ScenarioOutcome,
        evidence: Vec<EvidenceReference>,
    ) -> ScenarioResult {
        let finding = Finding::new(
            ScenarioId::new(id),
            format!("scenario {id}"),
            "expected",
            "actual",
            BackendKind::InMemory,
            "test",
            evidence,
            outcome.clone(),
        );
        ScenarioResult::new(ScenarioId::new(id), outcome, finding).with_capability_area("test")
    }

    #[test]
    fn equivalent_results_have_canonical_machine_report_bytes() {
        let first = result(
            "CV-002",
            ScenarioOutcome::Fail,
            vec![
                EvidenceReference::new("path:z"),
                EvidenceReference::new("path:a"),
            ],
        );
        let second = result("CV-001", ScenarioOutcome::Pass, vec![]);
        let metadata = RunMetadata::new("run-1")
            .with_command("loom-validator --all")
            .with_evidence(EvidenceReference::path("reports/run-1.json"));
        let left = ValidationReport::from_results(vec![first.clone(), second.clone()])
            .with_backend(BackendKind::InMemory)
            .with_run_metadata(metadata.clone());
        let right = ValidationReport::from_results(vec![second, first])
            .with_backend(BackendKind::InMemory)
            .with_run_metadata(metadata);

        assert_eq!(left.serialize_json(), right.serialize_json());
        assert_eq!(left.to_json_deterministic(), right.to_json_deterministic());
        let value: serde_json::Value = serde_json::from_str(&left.serialize_json()).unwrap();
        assert_eq!(value["schema_version"], 1);
        assert_eq!(value["backend"], "in-memory");
        assert_eq!(value["backend_evidence"], "in-memory");
        assert_eq!(value["backend_evidence_trusted"], true);
        assert_eq!(value["result_state"], "scenario_failure");
        assert_eq!(value["counts"]["total"], 2);
        assert_eq!(value["counts"]["fail"], 1);
        assert_eq!(value["run"]["command"], "loom-validator --all");
        assert_eq!(
            value["run"]["selected_ids"],
            serde_json::json!(["CV-001", "CV-002"])
        );
        assert_eq!(value["run"]["backend"], "in-memory");
        assert_eq!(value["run"]["backend_evidence"], "in-memory");
        assert_eq!(value["run"]["backend_evidence_trusted"], true);
        assert_eq!(value["run"]["policy"]["strict"], false);
        assert_eq!(value["results"][0]["scenario_id"], "CV-001");
        assert_eq!(value["results"][0]["name"], "scenario CV-001");
        assert_eq!(value["results"][0]["capability_area"], "test");
        assert_eq!(value["results"][0]["backend_evidence"], "in-memory");
        assert_eq!(value["results"][0]["backend_evidence_trusted"], true);
        assert_eq!(value["results"][0]["outcome"], "pass");
        assert!(value["summary"].is_string());
        assert_eq!(
            value["selected_scenario_ids"],
            serde_json::json!(["CV-001", "CV-002"])
        );
        assert_eq!(
            value["run"]["evidence"],
            serde_json::json!(["path:reports/run-1.json"])
        );
        assert_eq!(value["findings"][0]["scenario_id"], "CV-001");
        let serialized = left.serialize_json();
        assert!(!serialized.contains("remediation"));
        assert!(!serialized.contains("suggested_fix"));
        assert!(!serialized.contains("suggested_remediation"));
    }

    #[test]
    fn machine_report_classifies_prerequisite_unavailable() {
        let report = ValidationReport::from_results(vec![ScenarioResult::prerequisite(
            ScenarioId::new("CV-010"),
            "live database",
            BackendKind::PostgreSQL,
            "missing LOOM_TEST_POSTGRES_URL",
        )]);

        assert_eq!(
            report.result_state(),
            ReportResultState::PrerequisiteUnavailable
        );
        assert_eq!(report.prerequisite_details().len(), 1);
        let value: serde_json::Value = serde_json::from_str(&report.serialize_json()).unwrap();
        assert_eq!(value["prerequisites"][0]["state"], "missing");
        assert_eq!(value["prerequisites"][0]["backend_evidence"], "postgresql");
        assert_eq!(value["prerequisites"][0]["backend_evidence_trusted"], true);
        assert_eq!(value["result_state"], "prerequisite_unavailable");
        assert!(!report.human_summary().contains("raw"));
    }

    #[test]
    fn runner_config_failure_is_not_a_scenario_finding() {
        let report = ValidationReport::runner_config_failure(
            vec!["CV-999".to_owned(), "not-an-id".to_owned()],
            "unknown scenario id(s): CV-999",
        );
        let value: serde_json::Value = serde_json::from_str(&report.serialize_json()).unwrap();

        assert_eq!(
            report.result_state(),
            ReportResultState::RunnerConfigFailure
        );
        assert!(report.results().is_empty());
        assert_eq!(value["findings"], serde_json::json!([]));
        assert_eq!(value["runner_error"], "unknown scenario id(s): CV-999");
        assert_eq!(
            value["selected_scenario_ids"],
            serde_json::json!(["CV-999", "not-an-id"])
        );
    }

    #[test]
    fn external_evidence_is_not_a_required_live_pass() {
        let result = result("CV-012", ScenarioOutcome::Pass, vec![]);
        let report = ValidationReport::from_results_with_policy(
            vec![result],
            ValidationPolicy::required_live(),
        )
        .with_backend(BackendKind::LoomClient);

        assert_eq!(report.backend_evidence(), Some(BackendEvidence::External));
        assert!(!report.gate_passes());

        let value: serde_json::Value = serde_json::from_str(&report.serialize_json()).unwrap();
        assert_eq!(value["backend_evidence"], "external");
        assert_eq!(value["backend_evidence_trusted"], false);
        assert_eq!(value["run"]["backend_evidence"], "external");
    }

    #[test]
    fn controlled_postgres_evidence_satisfies_required_live() {
        let finding = Finding::new(
            ScenarioId::new("CV-013"),
            "live backend",
            "service responds",
            "service responded",
            BackendKind::PostgreSQL,
            "controlled-harness",
            vec![],
            ScenarioOutcome::Pass,
        );
        let report = ValidationReport::from_results_with_policy(
            vec![ScenarioResult::new(
                ScenarioId::new("CV-013"),
                ScenarioOutcome::Pass,
                finding,
            )],
            ValidationPolicy::required_live(),
        );

        assert_eq!(report.backend_evidence(), Some(BackendEvidence::PostgreSQL));
        assert!(report.gate_passes());
    }
}
