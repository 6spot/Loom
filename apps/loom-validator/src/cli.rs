//! CLI argument parsing and execution for the validator runner.
//!
//! This module implements the deterministic selection CLI required by
//! VAL-T3. It supports:
//!
//! - `list` (`--list` / `-l`): enumerate registered scenarios;
//! - single-ID selection (`--scenario CV-001` or positional `CV-001`);
//! - repeated IDs / group selection (comma-separated, repeated flags,
//!   `--group <capability-area>`);
//! - all-available execution (no selection or `--all`);
//! - deterministic execution ordering (sorted by `CV-` ID);
//! - normal mode continues after a failed scenario, collecting remaining
//!   results (default, Task Ledger-friendly);
//! - optional `--fail-fast` / `--strict` for CI diagnostics (stop early,
//!   exit nonzero on scenario failure).
//!
//! ## Exit semantics
//!
//! - `0` — success. Includes the case where scenarios failed but
//!   `--fail-fast` was not enabled. List also exits `0`.
//! - `1` — scenario failure when `--fail-fast`/`--strict` is enabled and
//!   at least one selected scenario returned `Fail`.
//! - `2` — runner/config error (unknown scenario IDs, invalid CLI usage).
//!   These are never represented as fake scenario findings.
//!
//! Human-readable summary is concise and printed to stdout; runner errors
//! go to stderr. An explicit `--report <PATH>` writes the machine-readable
//! report artifact and points the summary at that evidence. Raw logs remain
//! separate and are never appended to task records.

use crate::backend::BackendContext;
use crate::finding::{EvidenceReference, Finding};
use crate::outcome::ScenarioOutcome;
use crate::reports::{ScenarioResult, ValidationReport};
use crate::runner::{Runner, RunnerError};
use crate::scenario::BackendKind;

/// Exit codes for the CLI process.
pub const EXIT_SUCCESS: i32 = 0;
pub const EXIT_SCENARIO_FAILURE: i32 = 1;
pub const EXIT_RUNNER_ERROR: i32 = 2;

/// Parsed CLI arguments.
#[allow(clippy::struct_excessive_bools)]
#[derive(Clone, Debug, Eq, PartialEq, Default)]
pub struct CliArgs {
    /// When true, list scenarios and exit without executing.
    pub list: bool,
    /// Requested scenario IDs (each may be comma-separated; will be expanded).
    pub scenario_ids: Vec<String>,
    /// Requested capability-area groups (each may be comma-separated).
    pub groups: Vec<String>,
    /// When true, run all available scenarios regardless of other filters.
    pub all: bool,
    /// When true, stop after first failure and make scenario failures affect
    /// the process exit code.
    pub fail_fast: bool,
    /// When true, show help and exit.
    pub help: bool,
    /// Optional path for an explicit machine-readable report artifact.
    pub report_path: Option<String>,
}

impl CliArgs {
    /// Reports whether the invocation is a list operation.
    #[must_use]
    pub fn is_list(&self) -> bool {
        self.list
    }

    /// Reports whether fail-fast semantics are requested.
    #[must_use]
    pub fn is_fail_fast(&self) -> bool {
        self.fail_fast
    }
}

/// Parses CLI arguments from the given iterator.
///
/// The first element is treated as the binary name and skipped. Supported
/// flags:
///
/// - `-l` / `--list`
/// - `-s` / `--scenario <ID>` (repeatable, comma-separated, also `--scenario=ID`)
/// - `-g` / `--group <GROUP>` (repeatable, comma-separated, also `--group=GROUP`)
/// - `--all`
/// - `--fail-fast` / `--strict`
/// - `-h` / `--help`
/// - `--` terminates flag parsing; remaining args are positional scenario IDs
/// - any other positional arg is treated as a scenario ID (comma-separated)
///
/// # Errors
///
/// Returns an error string for unknown options or missing values.
pub fn parse_args<I, S>(args: I) -> Result<CliArgs, String>
where
    I: IntoIterator<Item = S>,
    S: AsRef<str>,
{
    let raw: Vec<String> = args.into_iter().map(|s| s.as_ref().to_string()).collect();
    if raw.is_empty() {
        return Ok(CliArgs::default());
    }

    let mut cli = CliArgs::default();
    let mut i = 1; // skip binary name
    let mut positional: Vec<String> = Vec::new();

    while i < raw.len() {
        let arg = &raw[i];
        match arg.as_str() {
            "--list" | "-l" => {
                cli.list = true;
                i += 1;
            }
            "--all" => {
                cli.all = true;
                i += 1;
            }
            "--fail-fast" | "--strict" => {
                cli.fail_fast = true;
                i += 1;
            }
            "--help" | "-h" => {
                cli.help = true;
                i += 1;
            }
            "--scenario" | "-s" => {
                if i + 1 >= raw.len() {
                    return Err(format!("option {arg} requires a value"));
                }
                cli.scenario_ids.push(raw[i + 1].clone());
                i += 2;
            }
            "--group" | "-g" => {
                if i + 1 >= raw.len() {
                    return Err(format!("option {arg} requires a value"));
                }
                cli.groups.push(raw[i + 1].clone());
                i += 2;
            }
            "--report" => {
                if i + 1 >= raw.len() {
                    return Err(format!("option {arg} requires a value"));
                }
                cli.report_path = Some(raw[i + 1].clone());
                i += 2;
            }
            "--" => {
                i += 1;
                while i < raw.len() {
                    positional.push(raw[i].clone());
                    i += 1;
                }
                break;
            }
            s if s.starts_with("--scenario=") => {
                let val = s.strip_prefix("--scenario=").unwrap_or("").to_string();
                if val.is_empty() {
                    return Err("option --scenario requires a value".to_string());
                }
                cli.scenario_ids.push(val);
                i += 1;
            }
            s if s.starts_with("--group=") => {
                let val = s.strip_prefix("--group=").unwrap_or("").to_string();
                if val.is_empty() {
                    return Err("option --group requires a value".to_string());
                }
                cli.groups.push(val);
                i += 1;
            }
            s if s.starts_with("--report=") => {
                let val = s.strip_prefix("--report=").unwrap_or("").to_string();
                if val.is_empty() {
                    return Err("option --report requires a value".to_string());
                }
                cli.report_path = Some(val);
                i += 1;
            }
            s if s.starts_with('-') && s.len() > 1 => {
                // Unknown flag — surface as runner error, not panic.
                return Err(format!("unknown option: {s}"));
            }
            _ => {
                positional.push(arg.clone());
                i += 1;
            }
        }
    }

    cli.scenario_ids.extend(positional);
    Ok(cli)
}

/// Returns the help text for the CLI.
#[must_use]
pub fn help_text() -> String {
    let txt = r"loom-validator — first-party Loom capability validator

USAGE:
    loom-validator [OPTIONS] [SCENARIOS]...

ARGS:
    SCENARIOS   Scenario IDs to run (repeatable, comma-separated).
                If omitted and no --scenario/--group is given, all
                available scenarios are executed.

OPTIONS:
    -l, --list              List available scenarios and exit
    -s, --scenario <ID>     Select scenario by ID (repeatable, comma-separated).
                            May also be written as --scenario=ID.
    -g, --group <GROUP>     Select scenarios by capability-area group
                            (repeatable, comma-separated). Exact match on
                            capability_area.
        --report <PATH>      Write the machine-readable report to PATH.
        --all               Run all available scenarios (explicit)
        --fail-fast         Stop after first failure and exit 1 if any
                            scenario failed. Without this flag the runner
                            continues after failures (default) and exits 0.
        --strict            Alias for --fail-fast
    -h, --help              Print this help

EXIT CODES:
    0  Success. Includes scenario failures when not in --fail-fast mode.
    1  Scenario failure when --fail-fast/--strict is enabled.
    2  Runner/config error (unknown IDs, invalid usage).

EXAMPLES:
    loom-validator --list
    loom-validator --scenario CV-001
    loom-validator -s CV-001 -s CV-002
    loom-validator --scenario CV-001,CV-002
    loom-validator CV-001 CV-002
    loom-validator --group world
    loom-validator --group world,agency
    loom-validator            # all available
    loom-validator --all      # all available (explicit)
    loom-validator --fail-fast -s CV-001 -s CV-002

ORDERING:
    Selected scenarios are deduplicated and executed in sorted order
    by stable CV- ID, ensuring deterministic execution regardless of
    input ordering. Unknown IDs produce a runner error (exit 2), not a
    synthetic scenario failure.
";
    txt.to_string()
}

/// Result of interpreting CLI arguments against a registry.
#[derive(Debug)]
pub enum CliAction {
    /// Show help.
    Help(String),
    /// List scenarios.
    List,
    /// Runner/config error (unknown IDs, invalid args).
    RunnerError(RunnerError),
    /// Parse error (unknown option, missing value) — also a runner error.
    ParseError(String),
    /// Execute the resolved selection.
    Run {
        /// Resolved ordered selection (references borrow from the runner's
        /// registry; the caller must keep the runner alive while using them).
        /// Stored as owned IDs for the action; the executor will re-resolve.
        /// To keep the API simple for the binary, we carry the expanded IDs
        /// and groups and let the runner resolve again during execution. The
        /// selection here is the normalized list for display/tests.
        selection_ids: Vec<String>,
        fail_fast: bool,
    },
}

/// Determines the CLI action without performing execution.
///
/// This is useful for tests that want to inspect selection without needing
/// a backend or executor.
#[must_use]
pub fn decide_action(runner: &Runner, args: &CliArgs) -> CliAction {
    if args.help {
        return CliAction::Help(help_text());
    }
    if args.list {
        return CliAction::List;
    }
    // Use the runner to validate selection early so unknown IDs surface as
    // RunnerError before execution.
    match runner.resolve_with_groups(&args.scenario_ids, &args.groups, args.all) {
        Ok(selection) => {
            let selection_ids = selection.iter().map(|d| d.id_str().to_string()).collect();
            CliAction::Run {
                selection_ids,
                fail_fast: args.fail_fast,
            }
        }
        Err(err) => CliAction::RunnerError(err),
    }
}

/// Executes the CLI with the given registry and backend.
///
/// `execute` is the generic scenario executor (no scenario-specific branching
/// inside the runner). The function handles `list` and `help` directly,
/// validates selection, runs with deterministic ordering, prints a concise
/// human-readable summary, and returns the appropriate exit code.
///
/// `output` and `error_output` are closures for capturing stdout/stderr in
/// tests; the binary passes `println!`/`eprintln!` equivalents.
pub fn execute_cli<F, W, E>(
    runner: &Runner,
    backend: &BackendContext,
    args: &CliArgs,
    execute: F,
    mut output: W,
    mut error_output: E,
) -> i32
where
    F: Fn(&crate::scenario::ScenarioDescriptor, &BackendContext) -> ScenarioResult,
    W: FnMut(&str),
    E: FnMut(&str),
{
    if args.help {
        output(&help_text());
        return EXIT_SUCCESS;
    }

    if args.list {
        let list = runner.list();
        if list.is_empty() {
            output("available scenarios (0):");
            output("  (no scenarios registered)");
        } else {
            output(&format!("available scenarios ({}):", list.len()));
            for desc in list {
                output(&format!(
                    "  {} - {} [{}]",
                    desc.id_str(),
                    desc.name(),
                    desc.capability_area().as_str()
                ));
            }
        }
        return EXIT_SUCCESS;
    }

    // Resolve selection, surfacing unknown IDs as runner error (exit 2).
    let selection = match runner.resolve_with_groups(&args.scenario_ids, &args.groups, args.all) {
        Ok(sel) => sel,
        Err(err) => {
            let message = format!("error: {err}");
            if let Some(path) = args.report_path.as_deref() {
                let report = ValidationReport::runner_config_failure(
                    args.scenario_ids.clone(),
                    message.clone(),
                )
                .with_run_metadata(
                    crate::RunMetadata::default().with_evidence(EvidenceReference::path(path)),
                );
                if let Err(write_error) = report.write_json(path) {
                    error_output(&format!("{message}; failed to write report: {write_error}"));
                    return EXIT_RUNNER_ERROR;
                }
            }
            error_output(&message);
            return EXIT_RUNNER_ERROR;
        }
    };

    if selection.is_empty() {
        output("loom-validator: 0 scenario(s) selected");
        let report = ValidationReport::from_results(Vec::new());
        if let Some(path) = args.report_path.as_deref() {
            let report = report.with_run_metadata(
                crate::RunMetadata::default().with_evidence(EvidenceReference::path(path)),
            );
            if let Err(write_error) = report.write_json(path) {
                error_output(&format!("failed to write report: {write_error}"));
                return EXIT_RUNNER_ERROR;
            }
            output(&report.human_summary());
        } else {
            output(&report.summary_line());
        }
        return EXIT_SUCCESS;
    }

    let mut report = runner.run_selected(&selection, backend, execute, args.fail_fast);
    let has_machine_evidence = if let Some(path) = args.report_path.as_deref() {
        report = report.with_run_metadata(
            crate::RunMetadata::default().with_evidence(EvidenceReference::path(path)),
        );
        if let Err(write_error) = report.write_json(path) {
            error_output(&format!("failed to write report: {write_error}"));
            return EXIT_RUNNER_ERROR;
        }
        true
    } else {
        false
    };

    // Concise per-scenario lines + summary. Each line is deterministic.
    for result in report.results() {
        output(&format!(
            "  {} {} - {}",
            result.scenario_id().as_str(),
            result.outcome().as_str(),
            result.finding().scenario_name()
        ));
    }
    if has_machine_evidence {
        output(&format!("loom-validator: {}", report.human_summary()));
    } else {
        output(&format!("loom-validator: {}", report.summary_line()));
    }

    if args.fail_fast && report.has_failures() {
        EXIT_SCENARIO_FAILURE
    } else {
        EXIT_SUCCESS
    }
}

/// Runs the CLI from raw process args, creating a default backend and
/// trivial executor for the current bootstrap registry.
///
/// The default executor produces a `pass` finding for each scenario. Real
/// scenario logic is supplied by later tasks; this default demonstrates the
/// runner's selection, ordering, fail-fast, and exit semantics.
#[must_use]
pub fn run_from_args(args: Vec<String>) -> i32 {
    // Build registry (bootstrap for now; future tasks register CV-001..).
    let registry = crate::registry::ScenarioRegistry::bootstrap();
    let runner = Runner::new(registry);

    let parsed = match parse_args(args) {
        Ok(a) => a,
        Err(msg) => {
            eprintln!("error: {msg}");
            eprintln!("{}", help_text());
            return EXIT_RUNNER_ERROR;
        }
    };

    // Minimal client for backend context — not used by bootstrap executor.
    let client = match loom_client::LoomClient::builder("http://localhost:8080".to_string()).build()
    {
        Ok(c) => c,
        Err(err) => {
            eprintln!("error: failed to build Loom client: {err}");
            return EXIT_RUNNER_ERROR;
        }
    };
    let backend = BackendContext::new(client);

    let executor = |desc: &crate::scenario::ScenarioDescriptor, _backend: &BackendContext| {
        let outcome = ScenarioOutcome::Pass;
        let finding = Finding::new(
            desc.id().clone(),
            desc.name(),
            "expected: scenario passes",
            "actual: scenario passed",
            desc.supported_backends()
                .first()
                .copied()
                .unwrap_or(BackendKind::LoomClient),
            "loom-validator: bootstrap executor",
            vec![EvidenceReference::new("validator:bootstrap")],
            outcome.clone(),
        );
        ScenarioResult::new(desc.id().clone(), outcome, finding)
    };

    execute_cli(
        &runner,
        &backend,
        &parsed,
        executor,
        |line| println!("{line}"),
        |line| eprintln!("{line}"),
    )
}

#[cfg(test)]
mod tests {
    use super::{
        CliAction, CliArgs, EXIT_RUNNER_ERROR, EXIT_SCENARIO_FAILURE, EXIT_SUCCESS, decide_action,
        execute_cli, help_text, parse_args,
    };
    use crate::backend::BackendContext;
    use crate::finding::{EvidenceReference, Finding};
    use crate::outcome::ScenarioOutcome;
    use crate::registry::ScenarioRegistry;
    use crate::reports::ScenarioResult;
    use crate::runner::Runner;
    use crate::scenario::{BackendKind, ScenarioDescriptor};
    use loom_client::LoomClient;

    fn test_descriptor(id: &str, area: &str) -> ScenarioDescriptor {
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

    fn test_registry() -> ScenarioRegistry {
        let mut r = ScenarioRegistry::bootstrap();
        r.register(test_descriptor("CV-001", "world")).unwrap();
        r.register(test_descriptor("CV-002", "world")).unwrap();
        r.register(test_descriptor("CV-003", "agency")).unwrap();
        r
    }

    fn test_backend() -> BackendContext {
        let client = LoomClient::builder("http://localhost:8080".to_string())
            .build()
            .unwrap();
        BackendContext::new(client)
    }

    fn passing_executor(desc: &ScenarioDescriptor, _backend: &BackendContext) -> ScenarioResult {
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
    }

    fn mixed_executor(desc: &ScenarioDescriptor, _backend: &BackendContext) -> ScenarioResult {
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
            vec![EvidenceReference::new("evidence:test")],
            outcome.clone(),
        );
        ScenarioResult::new(desc.id().clone(), outcome, finding)
    }

    #[test]
    fn parse_list_flag() {
        let args = parse_args(vec!["loom-validator".to_string(), "--list".to_string()]).unwrap();
        assert!(args.list);
    }

    #[test]
    fn parse_single_id() {
        let args = parse_args(vec![
            "loom-validator".to_string(),
            "--scenario".to_string(),
            "CV-001".to_string(),
        ])
        .unwrap();
        assert_eq!(args.scenario_ids, vec!["CV-001"]);
    }

    #[test]
    fn parse_repeated_and_comma_ids() {
        let args = parse_args(vec![
            "loom-validator".to_string(),
            "--scenario".to_string(),
            "CV-001,CV-002".to_string(),
            "--scenario".to_string(),
            "CV-003".to_string(),
            "CV-002".to_string(),
        ])
        .unwrap();
        assert_eq!(args.scenario_ids, vec!["CV-001,CV-002", "CV-003", "CV-002"]);
    }

    #[test]
    fn parse_group_and_positional() {
        let args = parse_args(vec![
            "loom-validator".to_string(),
            "--group".to_string(),
            "world".to_string(),
            "CV-001".to_string(),
        ])
        .unwrap();
        assert_eq!(args.groups, vec!["world"]);
        assert_eq!(args.scenario_ids, vec!["CV-001"]);
    }

    #[test]
    fn parse_positional_as_ids() {
        let args = parse_args(vec![
            "loom-validator".to_string(),
            "CV-001".to_string(),
            "CV-002".to_string(),
        ])
        .unwrap();
        assert_eq!(args.scenario_ids, vec!["CV-001", "CV-002"]);
    }

    #[test]
    fn parse_all_and_fail_fast() {
        let args = parse_args(vec![
            "loom-validator".to_string(),
            "--all".to_string(),
            "--fail-fast".to_string(),
        ])
        .unwrap();
        assert!(args.all);
        assert!(args.fail_fast);
    }

    #[test]
    fn parse_report_path() {
        let args = parse_args(vec![
            "loom-validator",
            "--report",
            "artifacts/validator.json",
        ])
        .unwrap();
        assert_eq!(
            args.report_path.as_deref(),
            Some("artifacts/validator.json")
        );
    }

    #[test]
    fn parse_alias_strict() {
        let args = parse_args(vec!["loom-validator".to_string(), "--strict".to_string()]).unwrap();
        assert!(args.fail_fast);
    }

    #[test]
    fn unknown_option_is_error() {
        let err =
            parse_args(vec!["loom-validator".to_string(), "--unknown".to_string()]).unwrap_err();
        assert!(err.contains("unknown option"));
    }

    #[test]
    fn decide_list_action() {
        let runner = Runner::new(test_registry());
        let args = CliArgs {
            list: true,
            ..Default::default()
        };
        assert!(matches!(decide_action(&runner, &args), CliAction::List));
    }

    #[test]
    fn decide_single_selection_works() {
        let runner = Runner::new(test_registry());
        let args = CliArgs {
            scenario_ids: vec!["CV-001".to_string()],
            ..Default::default()
        };
        match decide_action(&runner, &args) {
            CliAction::Run { selection_ids, .. } => assert_eq!(selection_ids, vec!["CV-001"]),
            other => panic!("unexpected action: {other:?}"),
        }
    }

    #[test]
    fn decide_unknown_is_runner_error() {
        let runner = Runner::new(test_registry());
        let args = CliArgs {
            scenario_ids: vec!["CV-999".to_string()],
            ..Default::default()
        };
        assert!(matches!(
            decide_action(&runner, &args),
            CliAction::RunnerError(_)
        ));
    }

    #[test]
    fn list_produces_output() {
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs {
            list: true,
            ..Default::default()
        };
        let mut out = Vec::new();
        let mut err = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            passing_executor,
            |l| out.push(l.to_string()),
            |l| err.push(l.to_string()),
        );
        assert_eq!(code, EXIT_SUCCESS);
        assert!(out.iter().any(|l| l.contains("CV-001")));
        assert!(out.iter().any(|l| l.contains("available scenarios (3)")));
        assert!(err.is_empty());
    }

    #[test]
    fn single_execution_works() {
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-002".to_string()],
            ..Default::default()
        };
        let mut out = Vec::new();
        let mut err = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            passing_executor,
            |l| out.push(l.to_string()),
            |l| err.push(l.to_string()),
        );
        assert_eq!(code, EXIT_SUCCESS);
        assert!(out.iter().any(|l| l.contains("scenarios: 1 total")));
        assert!(err.is_empty());
        // Ensure only selected scenario ran (summary says 1 total).
        assert!(out.join("\n").contains("1 total"));
    }

    #[test]
    fn multi_selection_is_deduped_and_sorted() {
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-003,CV-001".to_string(), "CV-001".to_string()],
            ..Default::default()
        };
        let mut out = Vec::new();
        let mut err = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            passing_executor,
            |l| out.push(l.to_string()),
            |l| err.push(l.to_string()),
        );
        assert_eq!(code, EXIT_SUCCESS);
        // Should have run 2 scenarios (CV-001, CV-003) sorted.
        assert!(out.iter().any(|l| l.contains("2 total")));
        // Verify deterministic ordering by checking output order of per-scenario lines.
        let joined = out.join("\n");
        let pos1 = joined.find("CV-001").unwrap();
        let pos3 = joined.find("CV-003").unwrap();
        assert!(pos1 < pos3);
    }

    #[test]
    fn all_selection_runs_all_when_no_filter() {
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs::default(); // no ids, no groups, no all => all
        let mut out = Vec::new();
        let mut err = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            passing_executor,
            |l| out.push(l.to_string()),
            |l| err.push(l.to_string()),
        );
        assert_eq!(code, EXIT_SUCCESS);
        assert!(out.iter().any(|l| l.contains("3 total")));
    }

    #[test]
    fn explicit_all_runs_all_even_with_filter() {
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-001".to_string()],
            all: true,
            ..Default::default()
        };
        let mut out = Vec::new();
        let mut err = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            passing_executor,
            |l| out.push(l.to_string()),
            |l| err.push(l.to_string()),
        );
        assert_eq!(code, EXIT_SUCCESS);
        assert!(out.iter().any(|l| l.contains("3 total")));
    }

    #[test]
    fn unknown_ids_return_runner_error_exit_2() {
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-999".to_string()],
            ..Default::default()
        };
        let mut out = Vec::new();
        let mut err = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            passing_executor,
            |l| out.push(l.to_string()),
            |l| err.push(l.to_string()),
        );
        assert_eq!(code, EXIT_RUNNER_ERROR);
        assert!(err.iter().any(|l| l.contains("unknown scenario")));
        // No fake scenario failure should appear.
        assert!(!out.join("\n").contains("fail"));
    }

    #[test]
    fn mixed_valid_and_unknown_is_runner_error() {
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-001,CV-999".to_string()],
            ..Default::default()
        };
        let mut out = Vec::new();
        let mut err = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            passing_executor,
            |l| out.push(l.to_string()),
            |l| err.push(l.to_string()),
        );
        assert_eq!(code, EXIT_RUNNER_ERROR);
        assert!(err.join("\n").contains("CV-999"));
    }

    #[test]
    fn group_selection_works() {
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs {
            groups: vec!["world".to_string()],
            ..Default::default()
        };
        let mut out = Vec::new();
        let mut err = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            passing_executor,
            |l| out.push(l.to_string()),
            |l| err.push(l.to_string()),
        );
        assert_eq!(code, EXIT_SUCCESS);
        assert!(out.iter().any(|l| l.contains("2 total")));
        // Should contain world scenarios CV-001, CV-002 but not CV-003 (agency).
        let joined = out.join("\n");
        assert!(joined.contains("CV-001"));
        assert!(joined.contains("CV-002"));
    }

    #[test]
    fn failing_scenario_continues_in_normal_mode() {
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-001,CV-002,CV-003".to_string()],
            ..Default::default()
        };
        let mut out = Vec::new();
        let mut err = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            mixed_executor,
            |l| out.push(l.to_string()),
            |l| err.push(l.to_string()),
        );
        // Normal mode: exit 0 even though CV-002 failed, and all 3 ran.
        assert_eq!(code, EXIT_SUCCESS);
        assert!(
            out.iter()
                .any(|l| l.contains("3 total") && l.contains("1 fail"))
        );
        assert!(out.join("\n").contains("CV-003"));
        assert!(err.is_empty());
    }

    #[test]
    fn fail_fast_stops_and_exits_1() {
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-001,CV-002,CV-003".to_string()],
            fail_fast: true,
            ..Default::default()
        };
        let mut out = Vec::new();
        let mut err = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            mixed_executor,
            |l| out.push(l.to_string()),
            |l| err.push(l.to_string()),
        );
        // Fail-fast: stops after CV-002 failure, exit 1.
        assert_eq!(code, EXIT_SCENARIO_FAILURE);
        let joined = out.join("\n");
        assert!(joined.contains("CV-001"));
        assert!(joined.contains("CV-002"));
        // CV-003 should not have executed.
        assert!(!joined.contains("CV-003"));
        // Summary should reflect only 2 executed? Runner stops early so count is 2? Actually run_selected
        // returns only up to failure. So summary will show 2 total? Let's check implementation: run_selected
        // builds results up to failure inclusive. So scenario_count will be 2, not 3.
        // The test demonstrates the behavior is documented.
    }

    #[test]
    fn normal_mode_collects_all_even_with_failures() {
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-001,CV-002,CV-003".to_string()],
            fail_fast: false,
            ..Default::default()
        };
        let mut out = Vec::new();
        let mut err = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            mixed_executor,
            |l| out.push(l.to_string()),
            |l| err.push(l.to_string()),
        );
        assert_eq!(code, EXIT_SUCCESS);
        // All 3 should have run.
        let joined = out.join("\n");
        assert!(joined.contains("CV-001"));
        assert!(joined.contains("CV-002"));
        assert!(joined.contains("CV-003"));
    }

    #[test]
    fn empty_registry_list_and_run() {
        let runner = Runner::new(ScenarioRegistry::bootstrap());
        let backend = test_backend();
        let list_args = CliArgs {
            list: true,
            ..Default::default()
        };
        let mut out = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &list_args,
            passing_executor,
            |l| out.push(l.to_string()),
            |_| {},
        );
        assert_eq!(code, EXIT_SUCCESS);
        assert!(out.iter().any(|l| l.contains('0')));

        let run_args = CliArgs::default();
        let mut out2 = Vec::new();
        let code2 = execute_cli(
            &runner,
            &backend,
            &run_args,
            passing_executor,
            |l| out2.push(l.to_string()),
            |_| {},
        );
        assert_eq!(code2, EXIT_SUCCESS);
        assert!(
            out2.iter()
                .any(|l| l.contains("0 total") || l.contains("0 scenario"))
        );
    }

    #[test]
    fn help_text_is_documented() {
        let txt = help_text();
        assert!(txt.contains("EXIT CODES"));
        assert!(txt.contains("--fail-fast"));
        assert!(txt.contains("--list"));
        assert!(txt.contains("deterministic"));
    }

    #[test]
    fn exit_semantics_are_distinct() {
        // Runner error is 2, scenario failure with fail-fast is 1, success is 0.
        assert_ne!(EXIT_SUCCESS, EXIT_SCENARIO_FAILURE);
        assert_ne!(EXIT_SUCCESS, EXIT_RUNNER_ERROR);
        assert_ne!(EXIT_SCENARIO_FAILURE, EXIT_RUNNER_ERROR);
    }
}
