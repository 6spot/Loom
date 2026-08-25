//! Task Ledger feedback collected by validator runs.
//!
//! Feedback is deliberately a small, append-only bridge. It consumes the
//! factual fields already present in [`ValidationReport`], resolves an
//! explicitly supplied task-record path, and writes concise Markdown. It does
//! not scan for task files, infer a filename from a scenario ID, or copy raw
//! process output into a task record.
//!
//! ## Observer-only / report-only authority boundary
//!
//! The validator is an observer. This bridge may append concise factual
//! findings to an explicitly selected Task Ledger record, but it must never
//! edit task frontmatter (`status`, `started_at`/`completed_at`,
//! `completion_pr`/`merge_sha`), acceptance checklist history, architecture
//! documents, or implementation source as a reaction to a finding. Remediation
//! requires a separately planned task or accepted Architecture Amendment; the
//! validator never applies fixes automatically.
//!
//! ## Non-blocking dispatcher contract
//!
//! Normal feedback mode records the failure and returns `Ok` so the outer
//! recursive dispatcher can continue with unrelated READY leaves. An explicit
//! diagnostic/CI strict mode may return a nonzero exit code for visibility,
//! but it still cannot mutate task state, rewrite history, or apply fixes.
//! The mode changes exit behavior only, not mutation authority.

use std::collections::BTreeSet;
use std::fmt;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::PathBuf;

use crate::reports::{RunMetadata, ValidationReport};

/// Maximum length of one factual Markdown field written by the feedback
/// bridge. Long values are rendered as a bounded summary rather than turning
/// a task record into a copy of stdout, stderr, or a machine report.
const MAX_FIELD_CHARS: usize = 512;

/// Facts a validator run can append to its Task Ledger handoff.
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

    /// Appends all material findings from a report to their explicit task
    /// records.
    ///
    /// Target resolution and task-record reads happen before the first append.
    /// Consequently a missing or ambiguous target is reported as a feedback
    /// configuration error without writing to another task or partially
    /// updating a set of task records.
    ///
    /// # Errors
    ///
    /// Returns [`TaskLedgerFeedbackError`] when report metadata does not name
    /// exactly one target, required run metadata is absent, or the selected
    /// task record cannot be read or appended.
    pub fn append_report(
        &mut self,
        report: &ValidationReport,
    ) -> Result<FeedbackAppendSummary, TaskLedgerFeedbackError> {
        let summary = append_report_impl(report)?;
        self.record_fact(format!(
            "appended {} validation finding(s) to {} task record(s)",
            summary.findings_appended, summary.files_updated
        ));
        Ok(summary)
    }

    /// Alias for [`Self::append_report`] for callers that name the input a
    /// validation report.
    ///
    /// # Errors
    ///
    /// Propagates the errors described by [`Self::append_report`].
    pub fn append_validation_report(
        &mut self,
        report: &ValidationReport,
    ) -> Result<FeedbackAppendSummary, TaskLedgerFeedbackError> {
        self.append_report(report)
    }

    /// Appends a report without retaining a separate in-memory fact list.
    ///
    /// # Errors
    ///
    /// Returns [`TaskLedgerFeedbackError`] when report metadata does not name
    /// exactly one target, required run metadata is absent, or the selected
    /// task record cannot be read or appended.
    pub fn append_report_to_task_ledger(
        report: &ValidationReport,
    ) -> Result<FeedbackAppendSummary, TaskLedgerFeedbackError> {
        append_report_impl(report)
    }
}

/// Appends a validation report to explicitly selected Task Ledger records.
///
/// # Errors
///
/// Returns [`TaskLedgerFeedbackError`] when report metadata does not name
/// exactly one target, required run metadata is absent, or the selected task
/// record cannot be read or appended.
pub fn append_report_to_task_ledger(
    report: &ValidationReport,
) -> Result<FeedbackAppendSummary, TaskLedgerFeedbackError> {
    TaskLedgerFeedback::append_report_to_task_ledger(report)
}

/// Observer-only exit semantics for Task Ledger feedback.
///
/// Normal mode (default) always returns [`crate::cli::EXIT_SUCCESS`] so the
/// outer recursive dispatcher can continue with unrelated READY leaves.
/// Strict diagnostic/CI mode returns [`crate::cli::EXIT_SCENARIO_FAILURE`]
/// when the report contains a failure, but it still does not mutate task state
/// or apply fixes. The mode changes exit behavior only, not mutation authority.
///
/// Remediation, when needed, requires a separately planned task or accepted
/// Architecture Amendment.
#[must_use]
#[allow(dead_code)]
pub fn feedback_exit_code(report: &ValidationReport, strict: bool) -> i32 {
    if strict && report.has_failures() {
        crate::cli::EXIT_SCENARIO_FAILURE
    } else {
        crate::cli::EXIT_SUCCESS
    }
}

/// Counts the durable entries produced by one feedback append.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct FeedbackAppendSummary {
    files_updated: usize,
    findings_appended: usize,
}

impl FeedbackAppendSummary {
    /// Returns the number of distinct task-record files changed.
    #[must_use]
    pub const fn files_updated(&self) -> usize {
        self.files_updated
    }

    /// Returns the number of concise finding entries appended.
    #[must_use]
    pub const fn findings_appended(&self) -> usize {
        self.findings_appended
    }

    /// Returns the number of entries appended.
    #[must_use]
    pub const fn entries_appended(&self) -> usize {
        self.findings_appended
    }
}

/// Failure while resolving or appending validator feedback.
#[derive(Debug)]
pub enum TaskLedgerFeedbackError {
    /// No explicit target was supplied for a scenario.
    MissingTarget { scenario_id: String },
    /// More than one explicit target was supplied for a scenario.
    AmbiguousTarget {
        scenario_id: String,
        paths: Vec<String>,
    },
    /// A run must provide an observation date for durable feedback.
    MissingObservationDate { scenario_id: String },
    /// A run must provide a run ID or an explicit `run:` evidence reference.
    MissingRunReference { scenario_id: String },
    /// A run supplied a malformed observation date.
    InvalidObservationDate { scenario_id: String, value: String },
    /// Reading or appending an explicitly selected record failed.
    Io {
        path: PathBuf,
        source: std::io::Error,
    },
}

impl fmt::Display for TaskLedgerFeedbackError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::MissingTarget { scenario_id } => write!(
                formatter,
                "feedback/config error: no explicit Task Ledger target for scenario {scenario_id}"
            ),
            Self::AmbiguousTarget { scenario_id, paths } => write!(
                formatter,
                "feedback/config error: ambiguous Task Ledger target for scenario {scenario_id}: {}",
                paths.join(", ")
            ),
            Self::MissingObservationDate { scenario_id } => write!(
                formatter,
                "feedback/config error: missing observation date for scenario {scenario_id}"
            ),
            Self::MissingRunReference { scenario_id } => write!(
                formatter,
                "feedback/config error: missing run reference for scenario {scenario_id}"
            ),
            Self::InvalidObservationDate { scenario_id, value } => write!(
                formatter,
                "feedback/config error: invalid observation date {value:?} for scenario {scenario_id}"
            ),
            Self::Io { path, source } => write!(
                formatter,
                "Task Ledger feedback I/O failed for {}: {source}",
                path.display()
            ),
        }
    }
}

impl std::error::Error for TaskLedgerFeedbackError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Io { source, .. } => Some(source),
            Self::MissingTarget { .. }
            | Self::AmbiguousTarget { .. }
            | Self::MissingObservationDate { .. }
            | Self::MissingRunReference { .. }
            | Self::InvalidObservationDate { .. } => None,
        }
    }
}

fn append_report_impl(
    report: &ValidationReport,
) -> Result<FeedbackAppendSummary, TaskLedgerFeedbackError> {
    let metadata = report.run_metadata();
    let mut pending = Vec::new();
    let mut paths = BTreeSet::new();

    // Resolve and read every selected record before opening any file in append
    // mode. This keeps target/configuration failures from causing partial
    // feedback writes.
    for result in report.results() {
        let scenario_id = result.scenario_id().as_str().to_owned();
        let path = resolve_target(metadata, &scenario_id)?;
        let contents = fs::read_to_string(&path).map_err(|source| TaskLedgerFeedbackError::Io {
            path: path.clone(),
            source,
        })?;
        let capability_gate = declares_capability_gate(&contents, &scenario_id);
        let should_append = !result.outcome().is_pass() || capability_gate;
        if !should_append {
            continue;
        }

        let observation_date = observation_date(metadata, &scenario_id)?;
        let run_reference = run_reference(metadata, &scenario_id)?;
        let entry = render_entry(result, metadata, &observation_date, &run_reference);
        paths.insert(path.clone());
        pending.push((path, contents, entry));
    }

    for (path, contents, entry) in &pending {
        let mut file = OpenOptions::new()
            .create(false)
            .append(true)
            .open(path)
            .map_err(|source| TaskLedgerFeedbackError::Io {
                path: path.clone(),
                source,
            })?;
        if !contents.is_empty() && !contents.ends_with('\n') {
            file.write_all(b"\n")
                .map_err(|source| TaskLedgerFeedbackError::Io {
                    path: path.clone(),
                    source,
                })?;
        }
        file.write_all(entry.as_bytes())
            .map_err(|source| TaskLedgerFeedbackError::Io {
                path: path.clone(),
                source,
            })?;
    }

    Ok(FeedbackAppendSummary {
        files_updated: paths.len(),
        findings_appended: pending.len(),
    })
}

fn resolve_target(
    metadata: &RunMetadata,
    scenario_id: &str,
) -> Result<PathBuf, TaskLedgerFeedbackError> {
    let mut candidates = BTreeSet::new();
    if let Some(path) = metadata.task_record()
        && !path.trim().is_empty()
    {
        candidates.insert(path.to_owned());
    }
    for reference in metadata.task_records() {
        if reference.scenario_id().trim() == scenario_id && !reference.path().trim().is_empty() {
            candidates.insert(reference.path().to_owned());
        }
    }

    match candidates.len() {
        0 => Err(TaskLedgerFeedbackError::MissingTarget {
            scenario_id: scenario_id.to_owned(),
        }),
        1 => Ok(candidates.into_iter().next().unwrap_or_default().into()),
        _ => Err(TaskLedgerFeedbackError::AmbiguousTarget {
            scenario_id: scenario_id.to_owned(),
            paths: candidates.into_iter().collect(),
        }),
    }
}

fn observation_date(
    metadata: &RunMetadata,
    scenario_id: &str,
) -> Result<String, TaskLedgerFeedbackError> {
    let value = metadata
        .observation_date()
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| TaskLedgerFeedbackError::MissingObservationDate {
            scenario_id: scenario_id.to_owned(),
        })?;
    if !is_iso_date(value) {
        return Err(TaskLedgerFeedbackError::InvalidObservationDate {
            scenario_id: scenario_id.to_owned(),
            value: value.to_owned(),
        });
    }
    Ok(value.to_owned())
}

fn run_reference(
    metadata: &RunMetadata,
    scenario_id: &str,
) -> Result<String, TaskLedgerFeedbackError> {
    if !metadata.run_id().trim().is_empty() {
        return Ok(metadata.run_id().to_owned());
    }
    if let Some(reference) = metadata
        .evidence()
        .iter()
        .map(crate::finding::EvidenceReference::as_str)
        .find(|reference| reference.starts_with("run:") && reference.len() > 4)
    {
        return Ok(reference.trim_start_matches("run:").to_owned());
    }
    Err(TaskLedgerFeedbackError::MissingRunReference {
        scenario_id: scenario_id.to_owned(),
    })
}

fn render_entry(
    result: &crate::reports::ScenarioResult,
    metadata: &RunMetadata,
    observation_date: &str,
    run_reference: &str,
) -> String {
    let finding = result.finding();
    let mut evidence = BTreeSet::new();
    for reference in finding.evidence() {
        evidence.insert(reference.as_str().to_owned());
    }
    for reference in metadata.evidence() {
        evidence.insert(reference.as_str().to_owned());
    }
    let evidence = if evidence.is_empty() {
        "none".to_owned()
    } else {
        evidence
            .into_iter()
            .map(|reference| format!("`{}`", markdown_field(&reference)))
            .collect::<Vec<_>>()
            .join(", ")
    };

    format!(
        "## Capability Validation\n\n- Scenario ID: `{}`\n- Scenario name: `{}`\n- Outcome: `{}`\n- Observation date: `{}`\n- Run reference: `{}`\n\n## Validation Findings\n\n- Expected: {}\n- Actual: {}\n- Backend: `{}`\n- Context: {}\n- Evidence: {}\n\n",
        markdown_field(result.scenario_id().as_str()),
        markdown_field(finding.scenario_name()),
        markdown_field(result.outcome().as_str()),
        markdown_field(observation_date),
        markdown_field(run_reference),
        markdown_field(finding.expected()),
        markdown_field(finding.actual()),
        markdown_field(finding.backend().as_str()),
        markdown_field(finding.context()),
        evidence,
    )
}

fn markdown_field(value: &str) -> String {
    let sanitized: String = value
        .chars()
        .map(|character| {
            if character.is_control() || character == '`' {
                ' '
            } else {
                character
            }
        })
        .collect();
    if sanitized.chars().count() <= MAX_FIELD_CHARS {
        return sanitized;
    }
    let mut output: String = sanitized.chars().take(MAX_FIELD_CHARS - 1).collect();
    output.push('…');
    output
}

fn is_iso_date(value: &str) -> bool {
    let bytes = value.as_bytes();
    bytes.len() == 10
        && bytes[4] == b'-'
        && bytes[7] == b'-'
        && bytes
            .iter()
            .enumerate()
            .all(|(index, byte)| matches!(index, 4 | 7) || byte.is_ascii_digit())
}

/// Returns whether a task record explicitly declares a scenario as a
/// capability gate.
///
/// The declaration is intentionally narrow: either `capability_gate(s)` in
/// YAML front matter or a bullet under a `## Capability Gates` heading. A
/// scenario ID appearing in ordinary prose or in an earlier feedback entry is
/// not treated as a declaration.
fn declares_capability_gate(contents: &str, scenario_id: &str) -> bool {
    let lines: Vec<&str> = contents.lines().collect();
    let mut in_front_matter = false;
    let mut in_gate_section = false;
    let mut front_gate_key = false;
    for (index, line) in lines.iter().enumerate() {
        let trimmed = line.trim();
        if index == 0 && trimmed == "---" {
            in_front_matter = true;
            continue;
        }
        if in_front_matter && trimmed == "---" {
            in_front_matter = false;
            front_gate_key = false;
            continue;
        }
        if in_front_matter {
            if let Some((key, value)) = trimmed.split_once(':') {
                front_gate_key = matches!(key.trim(), "capability_gate" | "capability_gates");
                if front_gate_key && contains_scenario_id(value, scenario_id) {
                    return true;
                }
            } else if front_gate_key && contains_scenario_id(trimmed, scenario_id) {
                return true;
            } else if !trimmed.starts_with('-') && !trimmed.is_empty() {
                front_gate_key = false;
            }
            continue;
        }

        if trimmed.starts_with('#') {
            let heading = trimmed.trim_start_matches('#').trim();
            in_gate_section = heading.eq_ignore_ascii_case("capability gates");
            continue;
        }
        if in_gate_section && contains_scenario_id(trimmed, scenario_id) {
            return true;
        }
    }
    false
}

fn contains_scenario_id(value: &str, scenario_id: &str) -> bool {
    value
        .split(|character: char| !character.is_ascii_alphanumeric() && character != '-')
        .any(|token| token == scenario_id)
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicU64, Ordering};

    use super::{
        FeedbackAppendSummary, TaskLedgerFeedback, TaskLedgerFeedbackError,
        declares_capability_gate,
    };
    use crate::finding::{EvidenceReference, Finding};
    use crate::outcome::ScenarioOutcome;
    use crate::reports::{RunMetadata, ScenarioResult, ValidationReport};
    use crate::scenario::{BackendKind, ScenarioId};

    static NEXT_FIXTURE: AtomicU64 = AtomicU64::new(0);

    fn fixture_path(name: &str) -> PathBuf {
        let id = NEXT_FIXTURE.fetch_add(1, Ordering::Relaxed);
        std::env::temp_dir().join(format!(
            "loom-validator-feedback-{name}-{}-{id}.md",
            std::process::id()
        ))
    }

    fn report(path: &str, outcome: ScenarioOutcome, metadata: RunMetadata) -> ValidationReport {
        let actual = if outcome.is_fail() {
            "actual raw stdout should not be copied\n".repeat(100)
        } else {
            "actual capability".to_owned()
        };
        let finding = Finding::new(
            ScenarioId::new("CV-001"),
            "synthetic capability",
            "expected capability",
            actual,
            BackendKind::InMemory,
            "validator test context",
            vec![EvidenceReference::path("reports/run.json")],
            outcome.clone(),
        );
        ValidationReport::from_results(vec![ScenarioResult::new(
            ScenarioId::new("CV-001"),
            outcome,
            finding,
        )])
        .with_run_metadata(metadata.with_task_record(path))
    }

    fn metadata() -> RunMetadata {
        RunMetadata::new("run-t6-001")
            .with_observation_date("2026-08-25")
            .with_evidence(EvidenceReference::path("reports/run.json"))
    }

    #[test]
    fn synthetic_failure_appends_one_concise_finding_to_explicit_record() {
        let path = fixture_path("failure");
        fs::write(&path, "---\ntask: VAL-T6\n---\n\nExisting entry\n").unwrap();
        let report = report(path.to_str().unwrap(), ScenarioOutcome::Fail, metadata());

        let summary = TaskLedgerFeedback::append_report_to_task_ledger(&report).unwrap();
        let contents = fs::read_to_string(&path).unwrap();
        assert_eq!(
            summary,
            FeedbackAppendSummary {
                files_updated: 1,
                findings_appended: 1,
            }
        );
        assert_eq!(contents.matches("## Validation Findings").count(), 1);
        assert!(contents.starts_with("---\ntask: VAL-T6\n---\n\nExisting entry\n"));
        assert!(contents.contains("Scenario ID: `CV-001`"));
        assert!(contents.contains("Expected: expected capability"));
        assert!(contents.contains("Backend: `in-memory`"));
        assert!(contents.contains("Observation date: `2026-08-25`"));
        assert!(contents.contains("Run reference: `run-t6-001`"));
        assert!(!contents.contains("actual raw stdout should not be copied\nactual raw stdout"));
        fs::remove_file(path).unwrap();
    }

    #[test]
    fn rerun_only_appends_and_preserves_the_original_entry() {
        let path = fixture_path("rerun");
        fs::write(&path, "record header\n").unwrap();
        let report = report(path.to_str().unwrap(), ScenarioOutcome::Fail, metadata());
        TaskLedgerFeedback::append_report_to_task_ledger(&report).unwrap();
        let first = fs::read_to_string(&path).unwrap();
        TaskLedgerFeedback::append_report_to_task_ledger(&report).unwrap();
        let second = fs::read_to_string(&path).unwrap();
        assert!(second.starts_with(&first));
        assert_eq!(second.matches("## Validation Findings").count(), 2);
        fs::remove_file(path).unwrap();
    }

    #[test]
    fn missing_or_ambiguous_target_is_a_config_error_without_writes() {
        let missing = report("unused-record.md", ScenarioOutcome::Fail, metadata())
            .with_run_metadata(metadata());
        let error = TaskLedgerFeedback::append_report_to_task_ledger(&missing).unwrap_err();
        assert!(matches!(
            error,
            TaskLedgerFeedbackError::MissingTarget { .. }
        ));

        let empty = ValidationReport::from_results(vec![]);
        let summary = TaskLedgerFeedback::append_report_to_task_ledger(&empty).unwrap();
        assert_eq!(summary, FeedbackAppendSummary::default());

        let path = fixture_path("ambiguous");
        fs::write(&path, "original\n").unwrap();
        let report = report(
            path.to_str().unwrap(),
            ScenarioOutcome::Fail,
            metadata().with_task_record_for_scenario("CV-001", "another-record.md"),
        );
        let error = TaskLedgerFeedback::append_report_to_task_ledger(&report).unwrap_err();
        assert!(matches!(
            error,
            TaskLedgerFeedbackError::AmbiguousTarget { .. }
        ));
        assert_eq!(fs::read_to_string(&path).unwrap(), "original\n");
        fs::remove_file(path).unwrap();
    }

    #[test]
    fn pass_is_recorded_only_for_an_explicit_capability_gate() {
        let path = fixture_path("pass-gate");
        fs::write(&path, "---\ncapability_gates:\n  - CV-001\n---\n").unwrap();
        let pass_report = report(path.to_str().unwrap(), ScenarioOutcome::Pass, metadata());
        let summary = TaskLedgerFeedback::append_report_to_task_ledger(&pass_report).unwrap();
        let contents = fs::read_to_string(&path).unwrap();
        assert_eq!(summary.findings_appended(), 1);
        assert!(contents.contains("Outcome: `pass`"));
        fs::remove_file(path).unwrap();

        let path = fixture_path("pass-no-gate");
        fs::write(&path, "---\ntask: VAL-T6\n---\n").unwrap();
        let pass_report = report(path.to_str().unwrap(), ScenarioOutcome::Pass, metadata());
        let summary = TaskLedgerFeedback::append_report_to_task_ledger(&pass_report).unwrap();
        assert_eq!(summary, FeedbackAppendSummary::default());
        assert_eq!(
            fs::read_to_string(&path).unwrap(),
            "---\ntask: VAL-T6\n---\n"
        );
        fs::remove_file(path).unwrap();
    }

    #[test]
    fn gate_parser_does_not_treat_feedback_entries_as_declarations() {
        assert!(!declares_capability_gate(
            "## Capability Validation\n- Scenario ID: `CV-001`\n",
            "CV-001"
        ));
        assert!(declares_capability_gate(
            "## Capability Gates\n- `CV-001`\n",
            "CV-001"
        ));
    }

    #[test]
    fn missing_run_reference_is_a_config_error() {
        let path = fixture_path("run-ref");
        fs::write(&path, "record\n").unwrap();
        let report = report(
            path.to_str().unwrap(),
            ScenarioOutcome::Fail,
            RunMetadata::default().with_observation_date("2026-08-25"),
        );
        let error = TaskLedgerFeedback::append_report_to_task_ledger(&report).unwrap_err();
        assert!(matches!(
            error,
            TaskLedgerFeedbackError::MissingRunReference { .. }
        ));
        assert_eq!(fs::read_to_string(&path).unwrap(), "record\n");
        fs::remove_file(path).unwrap();
    }

    #[test]
    fn markdown_field_caps_at_512_including_truncation_marker() {
        let long = "a".repeat(600);
        let rendered = super::markdown_field(&long);
        assert_eq!(rendered.chars().count(), 512);
        assert!(rendered.ends_with('…'));
        // Undisrupted limit: exactly 512 chars is not truncated.
        let exact = "b".repeat(512);
        let rendered_exact = super::markdown_field(&exact);
        assert_eq!(rendered_exact.chars().count(), 512);
        assert!(!rendered_exact.ends_with('…'));
        assert_eq!(rendered_exact, exact);
        // One over limit still caps at 512 with marker.
        let over = "c".repeat(513);
        let rendered_over = super::markdown_field(&over);
        assert_eq!(rendered_over.chars().count(), 512);
        assert!(rendered_over.ends_with('…'));
        // Control characters and backticks are sanitized before counting.
        let with_controls = format!("{}{}", "`\n`".repeat(10), "d".repeat(600));
        let rendered_controls = super::markdown_field(&with_controls);
        assert_eq!(rendered_controls.chars().count(), 512);
        assert!(!rendered_controls.contains('`'));
        assert!(!rendered_controls.contains('\n'));
        assert!(rendered_controls.ends_with('…'));
    }

    #[test]
    fn long_actual_is_bounded_in_task_record_including_ellipsis() {
        let path = fixture_path("long-actual-600");
        fs::write(&path, "---\ntask: VAL-T6\n---\n").unwrap();
        let long_actual = "x".repeat(600);
        let finding = Finding::new(
            ScenarioId::new("CV-001"),
            "synthetic capability",
            "expected capability",
            long_actual.clone(),
            BackendKind::InMemory,
            "validator test context",
            vec![EvidenceReference::path("reports/run.json")],
            ScenarioOutcome::Fail,
        );
        let report = ValidationReport::from_results(vec![ScenarioResult::new(
            ScenarioId::new("CV-001"),
            ScenarioOutcome::Fail,
            finding,
        )])
        .with_run_metadata(metadata().with_task_record(path.to_str().unwrap()));
        TaskLedgerFeedback::append_report_to_task_ledger(&report).unwrap();
        let contents = fs::read_to_string(&path).unwrap();
        assert!(!contents.contains(&long_actual));
        let actual_line = contents
            .lines()
            .find(|line| line.starts_with("- Actual: "))
            .expect("actual line");
        let value = actual_line.trim_start_matches("- Actual: ");
        assert_eq!(value.chars().count(), 512);
        assert!(value.ends_with('…'));
        assert!(!contents.contains(&"x".repeat(513)));
        fs::remove_file(path).unwrap();
    }

    // --- VAL-T7 observer-only / report-only guardrails ---

    fn representative_task_contents() -> String {
        [
            "---",
            "task: VAL-T7",
            "issue: 259",
            "status: in_progress",
            "depends_on: [258]",
            "created_at: 2026-08-24",
            "started_at: 2026-08-25",
            "completed_at:",
            "completion_pr:",
            "merge_sha:",
            "---",
            "# VAL-T7 — Enforce report-only feedback",
            "",
            "## Acceptance",
            "",
            "- [ ] failed validation leaves task metadata byte-for-byte unchanged",
            "- [x] earlier checklist item completed",
            "- [ ] failed validation does not modify implementation/architecture files",
            "",
            "## Capability Gates",
            "",
            "- CV-999",
            "",
            "## Progress Log",
            "",
            "- 2026-08-25 — initial entry",
            "",
            "## Verification Evidence",
            "",
            "- existing evidence that must be preserved",
            "",
        ]
        .join("\n")
    }

    fn frontmatter_of(contents: &str) -> String {
        let mut parts = contents.splitn(3, "---");
        let Some(_) = parts.next() else {
            return String::new();
        };
        let Some(front) = parts.next() else {
            return String::new();
        };
        front.to_owned()
    }

    #[test]
    fn failed_validation_leaves_task_metadata_byte_for_byte_unchanged() {
        let path = fixture_path("guardrail-metadata");
        let original = representative_task_contents();
        fs::write(&path, &original).unwrap();
        let original_frontmatter = frontmatter_of(&original);
        let original_bytes = original.clone();

        let report = report(path.to_str().unwrap(), ScenarioOutcome::Fail, metadata());
        let summary = TaskLedgerFeedback::append_report_to_task_ledger(&report).unwrap();
        assert_eq!(summary.findings_appended(), 1);

        let after = fs::read_to_string(&path).unwrap();
        // Frontmatter section must be byte-for-byte identical.
        assert_eq!(
            frontmatter_of(&after),
            original_frontmatter,
            "frontmatter was mutated by feedback"
        );
        // Protected fields must not have been rewritten.
        assert!(after.contains("status: in_progress"));
        assert!(after.contains("started_at: 2026-08-25"));
        assert!(after.contains("completed_at:"));
        assert!(after.contains("completion_pr:"));
        assert!(after.contains("merge_sha:"));
        // Checklist history preserved.
        assert!(after.contains("- [x] earlier checklist item completed"));
        assert!(
            after.contains("- [ ] failed validation leaves task metadata byte-for-byte unchanged")
        );
        // Original prefix preserved verbatim (append-only).
        assert!(
            after.starts_with(&original_bytes) || {
                // Allow single trailing newline normalization before append.
                let normalized = if original_bytes.ends_with('\n') {
                    original_bytes.clone()
                } else {
                    format!("{original_bytes}\n")
                };
                after.starts_with(&normalized)
            }
        );
        // Only the allowed validation section was appended.
        assert!(after.contains("## Capability Validation"));
        assert!(after.contains("## Validation Findings"));
        assert_eq!(after.matches("## Capability Validation").count(), 1);
        // Must not have altered non-validation headings content beyond append.
        let before_validation = after.split("## Capability Validation").next().unwrap();
        assert!(before_validation.contains("## Verification Evidence"));
        assert!(before_validation.contains("existing evidence that must be preserved"));

        fs::remove_file(path).unwrap();
    }

    #[test]
    fn failed_validation_does_not_modify_implementation_or_architecture_files() {
        let task_path = fixture_path("guardrail-task-impl");
        let arch_path = fixture_path("guardrail-architecture");
        let impl_path = fixture_path("guardrail-implementation");

        let task_original = representative_task_contents();
        let arch_original = "# Architecture\n\nAuthoritative core runtime contracts.\n";
        let impl_original = "pub fn important_runtime_logic() {}\n";

        fs::write(&task_path, &task_original).unwrap();
        fs::write(&arch_path, arch_original).unwrap();
        fs::write(&impl_path, impl_original).unwrap();

        let report = report(
            task_path.to_str().unwrap(),
            ScenarioOutcome::Fail,
            metadata(),
        );
        TaskLedgerFeedback::append_report_to_task_ledger(&report).unwrap();

        // Task file: only append, not rewrite.
        let task_after = fs::read_to_string(&task_path).unwrap();
        assert!(
            task_after.starts_with(&task_original)
                || task_after.starts_with(&format!("{task_original}\n"))
        );

        // Architecture and implementation files must be byte-for-byte unchanged.
        assert_eq!(
            fs::read_to_string(&arch_path).unwrap(),
            arch_original,
            "architecture document was mutated"
        );
        assert_eq!(
            fs::read_to_string(&impl_path).unwrap(),
            impl_original,
            "implementation source was mutated"
        );

        // Also ensure no remediation fields leaked into task file.
        assert!(!task_after.contains("suggested_fix"));
        assert!(!task_after.contains("remediation"));
        assert!(!task_after.contains("suggested_remediation"));

        fs::remove_file(task_path).unwrap();
        fs::remove_file(arch_path).unwrap();
        fs::remove_file(impl_path).unwrap();
    }

    #[test]
    fn append_only_finding_is_preserved_and_unrelated_work_remains_eligible() {
        let task_a = fixture_path("guardrail-related-a");
        let task_b = fixture_path("guardrail-related-b");

        fs::write(&task_a, representative_task_contents()).unwrap();
        fs::write(&task_b, representative_task_contents()).unwrap();

        // First failure on task A — dispatcher records it and continues.
        let report_a = report(task_a.to_str().unwrap(), ScenarioOutcome::Fail, metadata());
        let summary_a = TaskLedgerFeedback::append_report_to_task_ledger(&report_a).unwrap();
        assert_eq!(summary_a.findings_appended(), 1);
        let after_a_first = fs::read_to_string(&task_a).unwrap();
        assert_eq!(after_a_first.matches("## Validation Findings").count(), 1);

        // Unrelated READY leaf B is still eligible — append to B must succeed
        // and must not affect A's durable finding.
        let report_b = report(task_b.to_str().unwrap(), ScenarioOutcome::Fail, metadata());
        let summary_b = TaskLedgerFeedback::append_report_to_task_ledger(&report_b).unwrap();
        assert_eq!(summary_b.findings_appended(), 1);
        let after_b = fs::read_to_string(&task_b).unwrap();
        assert_eq!(after_b.matches("## Validation Findings").count(), 1);

        // A's finding is preserved.
        let after_a_second = fs::read_to_string(&task_a).unwrap();
        assert_eq!(after_a_second, after_a_first);
        assert_eq!(after_a_second.matches("## Validation Findings").count(), 1);

        // A second resolution appended to A does not rewrite the first.
        TaskLedgerFeedback::append_report_to_task_ledger(&report_a).unwrap();
        let after_a_third = fs::read_to_string(&task_a).unwrap();
        assert!(after_a_third.starts_with(&after_a_first));
        assert_eq!(after_a_third.matches("## Validation Findings").count(), 2);
        assert!(after_a_third.contains("existing evidence that must be preserved"));

        fs::remove_file(task_a).unwrap();
        fs::remove_file(task_b).unwrap();
    }

    #[test]
    fn normal_feedback_mode_records_failure_and_returns_control_for_dispatcher() {
        let task_path = fixture_path("guardrail-normal-dispatcher");
        fs::write(&task_path, representative_task_contents()).unwrap();

        let report_obj = report(
            task_path.to_str().unwrap(),
            ScenarioOutcome::Fail,
            metadata(),
        );
        // Normal mode: append returns Ok so dispatcher can continue.
        let result = TaskLedgerFeedback::append_report_to_task_ledger(&report_obj);
        assert!(
            result.is_ok(),
            "normal mode must not block dispatcher on failure"
        );
        let summary = result.unwrap();
        assert_eq!(summary.findings_appended(), 1);

        // Verify the outer dispatcher would see the finding but still be free
        // to dispatch unrelated work (simulated by running another append).
        let unrelated_path = fixture_path("guardrail-normal-unrelated");
        fs::write(&unrelated_path, representative_task_contents()).unwrap();
        let unrelated_report = report(
            unrelated_path.to_str().unwrap(),
            ScenarioOutcome::Fail,
            metadata(),
        );
        let unrelated_result = TaskLedgerFeedback::append_report_to_task_ledger(&unrelated_report);
        assert!(
            unrelated_result.is_ok(),
            "dispatcher must remain eligible for unrelated READY leaf after a failure"
        );

        // File still only appended.
        let contents = fs::read_to_string(&task_path).unwrap();
        assert!(contents.contains("Outcome: `fail`"));
        assert!(contents.contains("## Validation Findings"));

        fs::remove_file(task_path).unwrap();
        fs::remove_file(unrelated_path).unwrap();
    }

    #[test]
    fn strict_diagnostic_mode_changes_exit_behavior_only_not_mutation_authority() {
        // Strict mode must change exit code but not mutation behavior.
        let normal_path = fixture_path("guardrail-strict-normal");
        let strict_path = fixture_path("guardrail-strict-strict");

        let base_contents = representative_task_contents();
        fs::write(&normal_path, &base_contents).unwrap();
        fs::write(&strict_path, &base_contents).unwrap();

        let report_normal = report(
            normal_path.to_str().unwrap(),
            ScenarioOutcome::Fail,
            metadata(),
        );
        let report_strict = report(
            strict_path.to_str().unwrap(),
            ScenarioOutcome::Fail,
            metadata(),
        );

        // Both modes perform the identical file mutation.
        TaskLedgerFeedback::append_report_to_task_ledger(&report_normal).unwrap();
        TaskLedgerFeedback::append_report_to_task_ledger(&report_strict).unwrap();

        let after_normal = fs::read_to_string(&normal_path).unwrap();
        let after_strict = fs::read_to_string(&strict_path).unwrap();

        // Normalize the path-dependent run reference? Both use explicit task_record
        // path, but render entry includes scenario/backend/evidence which are same;
        // the only potential difference is the task path is embedded nowhere in the
        // rendered entry (only content). So files should be identical except for
        // maybe the evidence ordering — which is deterministic. Assert they are equal.
        assert_eq!(
            after_normal, after_strict,
            "strict mode must not mutate task state differently from normal mode"
        );

        // Frontmatter still preserved in strict mode.
        assert_eq!(
            frontmatter_of(&after_strict),
            frontmatter_of(&base_contents)
        );
        assert!(after_strict.contains("status: in_progress"));
        assert!(!after_strict.contains("suggested_fix"));

        // Exit semantics differ: normal returns 0, strict returns 1 on failure.
        let normal_code = super::feedback_exit_code(&report_normal, false);
        let strict_code = super::feedback_exit_code(&report_strict, true);
        assert_eq!(normal_code, crate::cli::EXIT_SUCCESS);
        assert_eq!(strict_code, crate::cli::EXIT_SCENARIO_FAILURE);

        // Strict still does not apply fixes: no file other than explicit task record was touched.
        let untouched = fixture_path("guardrail-strict-untouched");
        fs::write(&untouched, "untouched implementation").unwrap();
        let untouched_before = fs::read_to_string(&untouched).unwrap();
        TaskLedgerFeedback::append_report_to_task_ledger(&report_strict).unwrap();
        assert_eq!(fs::read_to_string(&untouched).unwrap(), untouched_before);

        fs::remove_file(normal_path).unwrap();
        fs::remove_file(strict_path).unwrap();
        fs::remove_file(untouched).unwrap();
    }

    #[test]
    fn strict_mode_without_failure_does_not_change_success_exit() {
        let path = fixture_path("guardrail-strict-success");
        fs::write(&path, "---\ncapability_gates:\n  - CV-001\n---\n").unwrap();
        let passing = report(path.to_str().unwrap(), ScenarioOutcome::Pass, metadata());
        // Passing scenario is only recorded when gate declares it.
        let summary = TaskLedgerFeedback::append_report_to_task_ledger(&passing).unwrap();
        assert_eq!(summary.findings_appended(), 1);
        assert_eq!(
            super::feedback_exit_code(&passing, false),
            crate::cli::EXIT_SUCCESS
        );
        assert_eq!(
            super::feedback_exit_code(&passing, true),
            crate::cli::EXIT_SUCCESS
        );
        fs::remove_file(path).unwrap();
    }

    #[test]
    fn remediation_requires_separately_planned_task_documented_in_finding() {
        let path = fixture_path("guardrail-remediation");
        fs::write(&path, representative_task_contents()).unwrap();
        let report = report(path.to_str().unwrap(), ScenarioOutcome::Fail, metadata());
        TaskLedgerFeedback::append_report_to_task_ledger(&report).unwrap();
        let contents = fs::read_to_string(&path).unwrap();
        // Finding records factual observation only, not remediation.
        assert!(contents.contains("Expected: expected capability"));
        assert!(contents.contains("Actual:"));
        assert!(contents.contains("Backend:"));
        assert!(contents.contains("Evidence:"));
        assert!(!contents.to_lowercase().contains("remediation"));
        assert!(!contents.contains("suggested_fix"));
        // The file still requires an external task/amendment for any fix; the
        // validator never transitions status.
        assert!(contents.contains("status: in_progress"));
        assert!(!contents.contains("status: completed"));
        fs::remove_file(path).unwrap();
    }
}
