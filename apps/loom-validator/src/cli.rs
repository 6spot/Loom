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
//! - optional `--fail-fast` controls execution stopping after the first hard
//!   `Fail`; `--strict` selects the strict gate policy independently.
//! - `--required-live` selects the required-live gate (strict + trusted
//!   `PostgreSQL` evidence) independently.
//!
//! ## Exit semantics
//!
//! - `0` — success. Includes the case where scenarios failed but `--strict`
//!   or `--required-live` was not enabled (best-effort). List also exits `0`.
//! - `1` — gate failure when `--strict` or `--required-live` is enabled and
//!   the selected gate is not satisfied (`Fail`, `Skipped`, `Unavailable`, or
//!   missing trusted `PostgreSQL` evidence for required-live).
//! - `2` — runner/config error (unknown scenario IDs, invalid CLI usage).
//!   These are never represented as fake scenario findings.
//!
//! Human-readable summary is concise and printed to stdout; runner errors
//! go to stderr. An explicit `--json <PATH>` (with `--report` retained as a
//! compatibility alias) writes the machine-readable report artifact and
//! points the summary at that evidence. Raw logs remain separate and are
//! never appended to task records.

use crate::backend::BackendContext;
use crate::finding::EvidenceReference;
use crate::reports::{ScenarioResult, ValidationPolicy, ValidationReport};
use crate::runner::{Runner, RunnerError};

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
    /// When true, stop after the first hard `Fail` (execution control only).
    pub fail_fast: bool,
    /// When true, use the strict gate policy (`Fail`, `Skipped`, `Unavailable` all fail).
    pub strict: bool,
    /// When true, require trusted `PostgreSQL` evidence (strict + at least one trusted `PostgreSQL` `Pass`).
    pub required_live: bool,
    /// When true, show help and exit.
    pub help: bool,
    /// Optional path for an explicit machine-readable report artifact.
    pub report_path: Option<String>,
    /// Preferred path for an explicit machine-readable JSON report artifact.
    pub json_path: Option<String>,
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

    /// Reports whether strict gate semantics are requested.
    #[must_use]
    pub fn is_strict(&self) -> bool {
        self.strict
    }

    /// Reports whether required-live gate semantics are requested.
    #[must_use]
    pub fn is_required_live(&self) -> bool {
        self.required_live
    }

    /// Returns the explicitly requested machine report path, if any.
    #[must_use]
    pub fn machine_report_path(&self) -> Option<&str> {
        self.json_path.as_deref().or(self.report_path.as_deref())
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
/// - `--fail-fast` (execution control)
/// - `--strict` (gate policy)
/// - `-h` / `--help`
/// - `--` terminates flag parsing; remaining args are positional scenario IDs
/// - any other positional arg is treated as a scenario ID (comma-separated)
///
/// # Errors
///
/// Returns an error string for unknown options or missing values.
#[allow(clippy::too_many_lines)]
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
            "--fail-fast" => {
                cli.fail_fast = true;
                i += 1;
            }
            "--strict" => {
                cli.strict = true;
                i += 1;
            }
            "--required-live" => {
                cli.required_live = true;
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
            "--json" | "--report" => {
                if i + 1 >= raw.len() {
                    return Err(format!("option {arg} requires a value"));
                }
                if arg == "--json" {
                    cli.json_path = Some(raw[i + 1].clone());
                } else {
                    cli.report_path = Some(raw[i + 1].clone());
                }
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
            s if s.starts_with("--json=") => {
                let val = s.strip_prefix("--json=").unwrap_or("").to_string();
                if val.is_empty() {
                    return Err("option --json requires a value".to_string());
                }
                cli.json_path = Some(val);
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
        --json <PATH>        Write the machine-readable report to PATH.
        --report <PATH>      Compatibility alias for --json.
        --all               Run all available scenarios (explicit)
        --fail-fast         Stop after first hard Fail (execution control only).
                             Without this flag the runner continues after
                             failures (default). Does not affect exit code
                             unless --strict is also enabled.
         --strict            Strict gate: exit 1 unless every selected
                             scenario returns Pass. Rejects Fail, Skipped
                             and Unavailable. Independent of --fail-fast.
         --required-live     Required-live gate: strict plus at least one
                             passing result with trusted controlled
                             PostgreSQL evidence. External/InMemory or any
                             Skipped/Unavailable/Fail makes the gate fail.
                             Fails closed when no trusted PostgreSQL Pass
                             exists. Independent of --fail-fast.
     -h, --help              Print this help

EXIT CODES:
     0  Success. Includes scenario failures when not in --strict/
        --required-live mode (best-effort). List also exits 0.
     1  Gate failure when --strict or --required-live is enabled and
        gate policy is not satisfied (Fail, Skipped, Unavailable, or
        missing trusted PostgreSQL evidence for --required-live).
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
        strict: bool,
        required_live: bool,
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
                strict: args.strict,
                required_live: args.required_live,
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
#[allow(clippy::too_many_lines)]
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
            if let Some(path) = args.machine_report_path() {
                let report = ValidationReport::runner_config_failure(
                    args.scenario_ids.clone(),
                    message.clone(),
                )
                .with_run_metadata(
                    crate::RunMetadata::default()
                        .with_command("loom-validator")
                        .with_evidence(EvidenceReference::path(path)),
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
        // Explicit selectors that resolve to zero are configuration errors
        // (VALR-T03). Runner already returns UnknownGroups/EmptySelection for
        // explicit empty, but keep a defensive CLI guard for any residual
        // empty path so a typo never becomes a green empty run.
        let explicit = !args.scenario_ids.is_empty() || !args.groups.is_empty();
        if explicit {
            let message = format!(
                "error: no scenarios matched selection: groups=[{}] ids=[{}]",
                args.groups.join(", "),
                args.scenario_ids.join(", ")
            );
            if let Some(path) = args.machine_report_path() {
                let report = ValidationReport::runner_config_failure(
                    args.scenario_ids.clone(),
                    message.clone(),
                )
                .with_run_metadata(
                    crate::RunMetadata::default()
                        .with_command("loom-validator")
                        .with_evidence(EvidenceReference::path(path)),
                );
                if let Err(write_error) = report.write_json(path) {
                    error_output(&format!("{message}; failed to write report: {write_error}"));
                    return EXIT_RUNNER_ERROR;
                }
            }
            error_output(&message);
            return EXIT_RUNNER_ERROR;
        }
        output("loom-validator: 0 scenario(s) selected");
        let report = ValidationReport::from_results(Vec::new());
        if let Some(path) = args.machine_report_path() {
            let report = report.with_run_metadata(
                crate::RunMetadata::default()
                    .with_command("loom-validator")
                    .with_evidence(EvidenceReference::path(path)),
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

    let policy = if args.required_live {
        ValidationPolicy::required_live()
    } else if args.strict {
        ValidationPolicy::strict()
    } else {
        ValidationPolicy::best_effort()
    };
    let mut report = runner
        .run_selected(&selection, backend, execute, args.fail_fast)
        .with_policy(policy);
    let has_machine_evidence = if let Some(path) = args.machine_report_path() {
        report = report.with_run_metadata(
            crate::RunMetadata::default()
                .with_command("loom-validator")
                .with_evidence(EvidenceReference::path(path)),
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

    if (args.strict || args.required_live) && !report.gate_passes() {
        EXIT_SCENARIO_FAILURE
    } else {
        EXIT_SUCCESS
    }
}

/// Runs the CLI from raw process args, creating a real backend harness and
/// executing the stable lifecycle (and any future) scenarios.
///
/// The harness connects over `LoomClient` to the real Loom endpoint selected by
/// `LOOM_VALIDATOR_BASE_URL`; real InMemory/PostgreSQL service boundary evidence
/// is produced by the integration tests and CI. Missing prerequisites are
/// reported as `skipped`/`unavailable` and never as `pass`.
/// `LOOM_VALIDATOR_BASE_URL=http://127.0.0.1:1` is the negative test and must
/// not yield a synthetic pass.
#[must_use]
#[allow(clippy::too_many_lines)]
pub fn run_from_args(args: Vec<String>) -> i32 {
    let registry = crate::validator_registry();
    let runner = Runner::new(registry);

    let parsed = match parse_args(args) {
        Ok(a) => a,
        Err(msg) => {
            eprintln!("error: {msg}");
            eprintln!("{}", help_text());
            return EXIT_RUNNER_ERROR;
        }
    };

    if parsed.help {
        println!("{}", help_text());
        return EXIT_SUCCESS;
    }
    if parsed.list {
        let client = match loom_client::LoomClient::builder(
            crate::backend::DEFAULT_VALIDATOR_BASE_URL.to_owned(),
        )
        .build()
        {
            Ok(c) => c,
            Err(err) => {
                eprintln!("error: failed to build Loom client: {err}");
                return EXIT_RUNNER_ERROR;
            }
        };
        let backend = BackendContext::new(client);
        return execute_cli(
            &runner,
            &backend,
            &parsed,
            execute_registered_scenario,
            |line| println!("{line}"),
            |line| eprintln!("{line}"),
        );
    }

    let base_url_env = std::env::var(crate::backend::LOOM_VALIDATOR_BASE_URL)
        .ok()
        .filter(|v| !v.trim().is_empty());
    let base_url = base_url_env
        .clone()
        .unwrap_or_else(|| crate::backend::DEFAULT_VALIDATOR_BASE_URL.to_owned());
    // A configured HTTP endpoint is generic consumer evidence. The CLI does
    // not control or inspect its storage, so an ambient
    // `LOOM_TEST_POSTGRES_URL` can never upgrade this identity to PostgreSQL.
    let kind = crate::scenario::BackendEvidence::External.backend_kind();

    let harness = match crate::backend::BackendHarness::connect(kind, base_url) {
        Ok(h) => h,
        Err(e) => {
            eprintln!("error: failed to connect backend: {e}");
            return EXIT_RUNNER_ERROR;
        }
    };
    let harness = if parsed.required_live {
        harness.with_policy(crate::reports::ValidationPolicy::required_live())
    } else if parsed.strict {
        harness.with_policy(crate::reports::ValidationPolicy::strict())
    } else {
        harness.with_policy(crate::reports::ValidationPolicy::best_effort())
    };

    let selection =
        match runner.resolve_with_groups(&parsed.scenario_ids, &parsed.groups, parsed.all) {
            Ok(sel) => sel,
            Err(e) => {
                eprintln!("error: {e}");
                return EXIT_RUNNER_ERROR;
            }
        };

    if selection.is_empty() {
        let explicit = !parsed.scenario_ids.is_empty() || !parsed.groups.is_empty();
        if explicit {
            eprintln!(
                "error: no scenarios matched selection: groups=[{}] ids=[{}]",
                parsed.groups.join(", "),
                parsed.scenario_ids.join(", ")
            );
            return EXIT_RUNNER_ERROR;
        }
        println!("loom-validator: 0 scenario(s) selected");
        let report = crate::reports::ValidationReport::from_results(Vec::new());
        if let Some(path) = parsed.machine_report_path() {
            let report = report.with_run_metadata(
                crate::reports::RunMetadata::default()
                    .with_command("loom-validator")
                    .with_evidence(crate::finding::EvidenceReference::path(path)),
            );
            if let Err(e) = report.write_json(path) {
                eprintln!("failed to write report: {e}");
                return EXIT_RUNNER_ERROR;
            }
            println!("loom-validator: {}", report.human_summary());
        } else {
            println!("loom-validator: {}", report.summary_line());
        }
        return EXIT_SUCCESS;
    }

    let mut report = runner.run_with_harness_selected(
        &selection,
        &harness,
        execute_registered_scenario,
        parsed.fail_fast,
    );

    let has_machine_evidence = if let Some(path) = parsed.machine_report_path() {
        let report_with_evidence = report.clone().with_run_metadata(
            crate::reports::RunMetadata::default()
                .with_command("loom-validator")
                .with_evidence(crate::finding::EvidenceReference::path(path)),
        );
        if let Err(e) = report_with_evidence.write_json(path) {
            eprintln!("failed to write report: {e}");
            return EXIT_RUNNER_ERROR;
        }
        report = report_with_evidence;
        true
    } else {
        false
    };

    for result in report.results() {
        println!(
            "  {} {} - {}",
            result.scenario_id().as_str(),
            result.outcome().as_str(),
            result.finding().scenario_name()
        );
    }
    if has_machine_evidence {
        println!("loom-validator: {}", report.human_summary());
    } else {
        println!("loom-validator: {}", report.summary_line());
    }

    if (parsed.strict || parsed.required_live) && !report.gate_passes() {
        EXIT_SCENARIO_FAILURE
    } else {
        EXIT_SUCCESS
    }
}

pub(crate) fn execute_registered_scenario(
    descriptor: &crate::scenario::ScenarioDescriptor,
    context: &BackendContext,
) -> crate::reports::ScenarioResult {
    match descriptor.id_str() {
        crate::action_ingress::CV_015 | crate::action_ingress::CV_016 => {
            crate::action_ingress::execute(descriptor, context)
        }
        crate::world_binding::CV_012
        | crate::world_binding::CV_013
        | crate::world_binding::CV_014 => {
            crate::world_binding::execute_world_binding(descriptor, context)
        }
        crate::scheduler::CV_020 => crate::scheduler::execute_scheduler(descriptor, context),
        crate::world_time::CV_021
        | crate::world_time::CV_022
        | crate::world_time::CV_023
        | crate::world_time::CV_024 => crate::world_time::execute(descriptor, context),
        crate::query_catalog::CV_025
        | crate::query_catalog::CV_026
        | crate::query_catalog::CV_027 => {
            crate::query_catalog::execute_query_catalog(descriptor, context)
        }
        crate::semantic_blob::CV_030 => crate::semantic_blob::execute(descriptor, context),
        crate::provenance::CV_031 | crate::provenance::CV_032 | crate::provenance::CV_033 => {
            crate::provenance::execute(descriptor, context)
        }
        crate::change_feed::CV_038 | crate::change_feed::CV_039 | crate::change_feed::CV_040 => {
            crate::change_feed::execute(descriptor, context)
        }
        crate::scenarios::CV_005
        | crate::scenarios::CV_006
        | crate::scenarios::CV_007
        | crate::scenarios::CV_008
        | crate::scenarios::CV_009 => crate::scenarios::execute_replay_fork(descriptor, context),
        crate::runtime_authority::CV_010 | crate::runtime_authority::CV_011 => {
            crate::runtime_authority::execute_runtime_authority(descriptor, context)
        }
        crate::lifecycle::CV_001
        | crate::lifecycle::CV_002
        | crate::lifecycle::CV_003
        | crate::lifecycle::CV_004 => crate::lifecycle::execute(descriptor, context),
        _ => crate::reports::ScenarioResult::unavailable(
            descriptor.id().clone(),
            descriptor.name(),
            *context.backend_kind(),
            "scenario is registered without an executor",
        )
        .with_capability_area(descriptor.capability_area().as_str()),
    }
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
        assert!(!args.strict);
    }

    #[test]
    fn parse_report_path() {
        let args =
            parse_args(vec!["loom-validator", "--json", "artifacts/validator.json"]).unwrap();
        assert_eq!(args.machine_report_path(), Some("artifacts/validator.json"));

        let alias = parse_args(vec!["loom-validator", "--report", "legacy.json"]).unwrap();
        assert_eq!(alias.machine_report_path(), Some("legacy.json"));
    }

    #[test]
    fn parse_alias_strict() {
        let args = parse_args(vec!["loom-validator".to_string(), "--strict".to_string()]).unwrap();
        assert!(args.strict);
        assert!(!args.fail_fast);
    }

    #[test]
    fn parse_strict_and_fail_fast_are_independent() {
        let strict_only =
            parse_args(vec!["loom-validator".to_string(), "--strict".to_string()]).unwrap();
        assert!(strict_only.strict);
        assert!(!strict_only.fail_fast);

        let ff_only = parse_args(vec![
            "loom-validator".to_string(),
            "--fail-fast".to_string(),
        ])
        .unwrap();
        assert!(ff_only.fail_fast);
        assert!(!ff_only.strict);

        let both = parse_args(vec![
            "loom-validator".to_string(),
            "--strict".to_string(),
            "--fail-fast".to_string(),
        ])
        .unwrap();
        assert!(both.strict);
        assert!(both.fail_fast);
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
            strict: true,
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
        // Fail-fast + strict: stops after CV-002 failure, exit 1 via strict gate.
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
        assert!(txt.contains("--strict"));
        assert!(txt.contains("--list"));
        assert!(txt.contains("deterministic"));
    }

    #[test]
    fn exit_semantics_are_distinct() {
        // Runner error is 2, strict gate failure is 1, success is 0.
        assert_ne!(EXIT_SUCCESS, EXIT_SCENARIO_FAILURE);
        assert_ne!(EXIT_SUCCESS, EXIT_RUNNER_ERROR);
        assert_ne!(EXIT_SCENARIO_FAILURE, EXIT_RUNNER_ERROR);
    }

    #[test]
    fn cli_single_pass_two_scenarios_each_exactly_once_in_normal_mode() {
        use std::cell::RefCell;
        use std::collections::BTreeMap;

        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-001,CV-002".to_string()],
            ..Default::default()
        };
        let counts: RefCell<BTreeMap<String, usize>> = RefCell::new(BTreeMap::new());
        let order: RefCell<Vec<String>> = RefCell::new(Vec::new());

        let mut out = Vec::new();
        let mut err = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            |desc, _ctx| {
                *counts
                    .borrow_mut()
                    .entry(desc.id_str().to_string())
                    .or_insert(0) += 1;
                order.borrow_mut().push(desc.id_str().to_string());
                let finding = Finding::new(
                    desc.id().clone(),
                    desc.name(),
                    "expected",
                    format!("actual:{}", desc.id_str()),
                    BackendKind::LoomClient,
                    "test",
                    vec![EvidenceReference::new(format!(
                        "evidence:{}:{}",
                        desc.id_str(),
                        counts.borrow()[desc.id_str()]
                    ))],
                    ScenarioOutcome::Pass,
                );
                ScenarioResult::new(desc.id().clone(), ScenarioOutcome::Pass, finding)
            },
            |l| out.push(l.to_string()),
            |l| err.push(l.to_string()),
        );

        assert_eq!(code, EXIT_SUCCESS);
        assert_eq!(counts.borrow().get("CV-001"), Some(&1));
        assert_eq!(counts.borrow().get("CV-002"), Some(&1));
        assert_eq!(*order.borrow(), vec!["CV-001", "CV-002"]);
        // Report contents are from the same single execution pass.
        let joined = out.join("\n");
        assert!(joined.contains("CV-001"));
        assert!(joined.contains("CV-002"));
        assert!(joined.contains("2 total"));
        assert!(err.is_empty());
    }

    #[test]
    fn cli_fail_fast_first_failure_second_never_invoked_and_first_exactly_once() {
        use std::cell::RefCell;
        use std::collections::BTreeMap;

        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-001,CV-002".to_string()],
            fail_fast: true,
            strict: true,
            ..Default::default()
        };
        let counts: RefCell<BTreeMap<String, usize>> = RefCell::new(BTreeMap::new());

        let mut out = Vec::new();
        let mut err = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            |desc, _ctx| {
                *counts
                    .borrow_mut()
                    .entry(desc.id_str().to_string())
                    .or_insert(0) += 1;
                let outcome = if desc.id_str() == "CV-001" {
                    ScenarioOutcome::Fail
                } else {
                    ScenarioOutcome::Pass
                };
                let finding = Finding::new(
                    desc.id().clone(),
                    desc.name(),
                    "expected",
                    format!("actual:{}", desc.id_str()),
                    BackendKind::LoomClient,
                    "test",
                    vec![EvidenceReference::new(format!(
                        "invocation:{}:{}",
                        desc.id_str(),
                        counts.borrow()[desc.id_str()]
                    ))],
                    outcome.clone(),
                );
                ScenarioResult::new(desc.id().clone(), outcome, finding)
            },
            |l| out.push(l.to_string()),
            |l| err.push(l.to_string()),
        );

        assert_eq!(code, EXIT_SCENARIO_FAILURE);
        assert_eq!(
            counts.borrow().get("CV-001"),
            Some(&1),
            "failing first scenario must be invoked exactly once"
        );
        assert_eq!(
            counts.borrow().get("CV-002"),
            None,
            "second scenario must never be invoked under fail-fast"
        );
        assert_eq!(counts.borrow().get("CV-001"), Some(&1));
        let joined = out.join("\n");
        assert!(joined.contains("CV-001"));
        assert!(
            !joined.contains("CV-002"),
            "report must not contain non-executed scenario"
        );
        // Ensure report reflects single-pass execution count.
        assert!(
            joined.contains("1 total") || joined.contains("1 fail") || !joined.contains("2 total")
        );
        assert!(err.is_empty());
    }

    #[test]
    fn cli_report_contents_are_from_same_execution_pass() {
        use std::cell::RefCell;

        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-001,CV-002".to_string()],
            ..Default::default()
        };
        let execution_ids: RefCell<Vec<String>> = RefCell::new(Vec::new());

        let mut out = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            |desc, _ctx| {
                execution_ids.borrow_mut().push(desc.id_str().to_string());
                let finding = Finding::new(
                    desc.id().clone(),
                    desc.name(),
                    "expected",
                    format!("actual:{}", desc.id_str()),
                    BackendKind::LoomClient,
                    "test",
                    vec![EvidenceReference::new(format!(
                        "evidence-for-{}",
                        desc.id_str()
                    ))],
                    ScenarioOutcome::Pass,
                );
                ScenarioResult::new(desc.id().clone(), ScenarioOutcome::Pass, finding)
            },
            |l| out.push(l.to_string()),
            |_| {},
        );

        assert_eq!(code, EXIT_SUCCESS);
        assert_eq!(*execution_ids.borrow(), vec!["CV-001", "CV-002"]);
        let joined = out.join("\n");
        // Each line's actual must correspond to execution order, not a second pass.
        let pos1 = joined.find("CV-001").unwrap();
        let pos2 = joined.find("CV-002").unwrap();
        assert!(pos1 < pos2);
        assert!(joined.contains("2 total"));
    }

    // --- VALR-T02 strict vs fail-fast separation ---

    fn skipped_executor(desc: &ScenarioDescriptor, _backend: &BackendContext) -> ScenarioResult {
        let outcome = ScenarioOutcome::Skipped {
            reason: "missing prerequisite: test db".to_string(),
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
    }

    fn unavailable_executor(
        desc: &ScenarioDescriptor,
        _backend: &BackendContext,
    ) -> ScenarioResult {
        let outcome = ScenarioOutcome::Unavailable {
            reason: "environment unavailable".to_string(),
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
    }

    #[test]
    fn strict_all_pass_exits_zero() {
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-001,CV-002".to_string()],
            strict: true,
            ..Default::default()
        };
        let mut out = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            passing_executor,
            |l| out.push(l.to_string()),
            |_| {},
        );
        assert_eq!(code, EXIT_SUCCESS);
        assert!(out.join("\n").contains("2 total"));
    }

    #[test]
    fn strict_fail_exits_nonzero() {
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-001,CV-002".to_string()],
            strict: true,
            ..Default::default()
        };
        let mut out = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            mixed_executor,
            |l| out.push(l.to_string()),
            |_| {},
        );
        assert_eq!(code, EXIT_SCENARIO_FAILURE);
    }

    #[test]
    fn strict_skipped_exits_nonzero() {
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-001".to_string()],
            strict: true,
            ..Default::default()
        };
        let code = execute_cli(&runner, &backend, &args, skipped_executor, |_| {}, |_| {});
        assert_eq!(code, EXIT_SCENARIO_FAILURE);
    }

    #[test]
    fn strict_unavailable_exits_nonzero() {
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-001".to_string()],
            strict: true,
            ..Default::default()
        };
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            unavailable_executor,
            |_| {},
            |_| {},
        );
        assert_eq!(code, EXIT_SCENARIO_FAILURE);
    }

    #[test]
    fn fail_fast_without_strict_stops_but_gate_unchanged() {
        use std::cell::RefCell;
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-001,CV-002,CV-003".to_string()],
            fail_fast: true,
            strict: false,
            ..Default::default()
        };
        let counts: RefCell<Vec<String>> = RefCell::new(Vec::new());
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            |desc, ctx| {
                counts.borrow_mut().push(desc.id_str().to_string());
                mixed_executor(desc, ctx)
            },
            |_| {},
            |_| {},
        );
        // Fail-fast stops after CV-002 (the failing one)
        assert_eq!(*counts.borrow(), vec!["CV-001", "CV-002"]);
        // But strict gate not enabled, so best-effort exit remains success
        assert_eq!(code, EXIT_SUCCESS);
    }

    #[test]
    fn strict_without_fail_fast_executes_all_but_still_fails() {
        use std::cell::RefCell;
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-001,CV-002,CV-003".to_string()],
            fail_fast: false,
            strict: true,
            ..Default::default()
        };
        let counts: RefCell<Vec<String>> = RefCell::new(Vec::new());
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            |desc, ctx| {
                counts.borrow_mut().push(desc.id_str().to_string());
                mixed_executor(desc, ctx)
            },
            |_| {},
            |_| {},
        );
        // Strict without fail-fast must run full selection
        assert_eq!(*counts.borrow(), vec!["CV-001", "CV-002", "CV-003"]);
        // Yet gate fails because CV-002 is Fail
        assert_eq!(code, EXIT_SCENARIO_FAILURE);
    }

    #[test]
    fn strict_sets_policy_gate_and_does_not_imply_fail_fast() {
        // Direct parse proof is in parse_strict_and_fail_fast_are_independent,
        // but also verify execution semantics: strict alone does not stop early.
        use std::cell::RefCell;
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        // Strict without fail-fast should NOT stop early even when first fails
        let args = CliArgs {
            scenario_ids: vec!["CV-001,CV-002".to_string()],
            strict: true,
            fail_fast: false,
            ..Default::default()
        };
        let counts: RefCell<Vec<String>> = RefCell::new(Vec::new());
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            |desc, _ctx| {
                counts.borrow_mut().push(desc.id_str().to_string());
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
            |_| {},
            |_| {},
        );
        assert_eq!(*counts.borrow(), vec!["CV-001", "CV-002"]);
        assert_eq!(code, EXIT_SCENARIO_FAILURE);
    }

    #[test]
    fn non_strict_best_effort_with_skipped_still_succeeds() {
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-001".to_string()],
            strict: false,
            ..Default::default()
        };
        let code = execute_cli(&runner, &backend, &args, skipped_executor, |_| {}, |_| {});
        // Best-effort preserves existing success even with Skipped
        assert_eq!(code, EXIT_SUCCESS);
    }

    // --- VALR-T03 selection integrity ---

    #[test]
    fn unknown_group_returns_exit_2() {
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs {
            groups: vec!["typo-group".to_string()],
            ..Default::default()
        };
        let mut err = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            passing_executor,
            |_| {},
            |l| err.push(l.to_string()),
        );
        assert_eq!(code, EXIT_RUNNER_ERROR);
        let msg = err.join("\n");
        assert!(msg.contains("unknown group"), "msg: {msg}");
        assert!(msg.contains("typo-group"), "msg: {msg}");
    }

    #[test]
    fn explicit_empty_selection_returns_exit_2() {
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        // Unknown group is the explicit empty case
        let args = CliArgs {
            groups: vec!["nonexistent".to_string()],
            ..Default::default()
        };
        let mut err = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            passing_executor,
            |_| {},
            |l| err.push(l.to_string()),
        );
        assert_eq!(code, EXIT_RUNNER_ERROR);
        assert!(
            err.join("\n").contains("unknown group")
                || err.join("\n").contains("no scenarios matched")
        );
    }

    #[test]
    fn unknown_scenario_id_returns_exit_2_with_clear_text() {
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-999".to_string()],
            ..Default::default()
        };
        let mut err = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            passing_executor,
            |_| {},
            |l| err.push(l.to_string()),
        );
        assert_eq!(code, EXIT_RUNNER_ERROR);
        let msg = err.join("\n");
        assert!(msg.contains("unknown scenario"), "msg: {msg}");
        assert!(msg.contains("CV-999"), "msg: {msg}");
    }

    #[test]
    fn valid_group_runs_deterministic_selection() {
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs {
            groups: vec!["world".to_string()],
            ..Default::default()
        };
        let mut out = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            passing_executor,
            |l| out.push(l.to_string()),
            |_| {},
        );
        assert_eq!(code, EXIT_SUCCESS);
        let joined = out.join("\n");
        assert!(joined.contains("CV-001"));
        assert!(joined.contains("CV-002"));
        // Deterministic order: CV-001 before CV-002
        assert!(joined.find("CV-001").unwrap() < joined.find("CV-002").unwrap());
        assert!(joined.contains("2 total"));
    }

    #[test]
    fn no_selector_retains_default_all_behavior() {
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs::default();
        let mut out = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            passing_executor,
            |l| out.push(l.to_string()),
            |_| {},
        );
        assert_eq!(code, EXIT_SUCCESS);
        assert!(out.join("\n").contains("3 total"));
    }

    #[test]
    fn strict_with_typo_cannot_return_zero() {
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-999".to_string()],
            strict: true,
            fail_fast: false,
            ..Default::default()
        };
        let mut err = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            passing_executor,
            |_| {},
            |l| err.push(l.to_string()),
        );
        assert_eq!(code, EXIT_RUNNER_ERROR);
        assert_ne!(code, EXIT_SUCCESS);
        assert_ne!(code, EXIT_SCENARIO_FAILURE);
        assert!(err.join("\n").contains("CV-999"));
    }

    #[test]
    fn strict_with_unknown_group_cannot_return_zero() {
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs {
            groups: vec!["typo-group".to_string()],
            strict: true,
            ..Default::default()
        };
        let mut err = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            passing_executor,
            |_| {},
            |l| err.push(l.to_string()),
        );
        assert_eq!(code, EXIT_RUNNER_ERROR);
        assert_ne!(code, 0);
    }

    #[test]
    fn decide_action_unknown_group_is_runner_error() {
        let runner = Runner::new(test_registry());
        let args = CliArgs {
            groups: vec!["unknown".to_string()],
            ..Default::default()
        };
        assert!(matches!(
            decide_action(&runner, &args),
            CliAction::RunnerError(_)
        ));
    }

    #[test]
    fn valid_selection_still_deterministic_after_t03() {
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        // Request in reverse order, should still be sorted
        let args = CliArgs {
            scenario_ids: vec!["CV-003,CV-001".to_string()],
            ..Default::default()
        };
        let mut out = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            passing_executor,
            |l| out.push(l.to_string()),
            |_| {},
        );
        assert_eq!(code, EXIT_SUCCESS);
        let joined = out.join("\n");
        let p1 = joined.find("CV-001").unwrap();
        let p3 = joined.find("CV-003").unwrap();
        assert!(p1 < p3);
    }

    // --- VALR-T06 required-live ---

    fn pg_backend() -> BackendContext {
        let client = LoomClient::builder("http://localhost:8080".to_string())
            .build()
            .unwrap();
        BackendContext::new(client).with_backend_kind(BackendKind::PostgreSQL)
    }

    fn inmemory_backend() -> BackendContext {
        let client = LoomClient::builder("http://localhost:8080".to_string())
            .build()
            .unwrap();
        BackendContext::new(client).with_backend_kind(BackendKind::InMemory)
    }

    #[test]
    fn parse_required_live_flag() {
        let args = parse_args(vec![
            "loom-validator".to_string(),
            "--required-live".to_string(),
        ])
        .unwrap();
        assert!(args.required_live);
        assert!(!args.strict);
        assert!(!args.fail_fast);

        let both = parse_args(vec![
            "loom-validator".to_string(),
            "--required-live".to_string(),
            "--fail-fast".to_string(),
        ])
        .unwrap();
        assert!(both.required_live);
        assert!(both.fail_fast);
        assert!(!both.strict);
    }

    fn passing_aware(desc: &ScenarioDescriptor, backend: &BackendContext) -> ScenarioResult {
        let finding = Finding::new(
            desc.id().clone(),
            desc.name(),
            "expected",
            "actual",
            *backend.backend_kind(),
            "ctx",
            vec![],
            ScenarioOutcome::Pass,
        );
        ScenarioResult::new(desc.id().clone(), ScenarioOutcome::Pass, finding)
    }

    #[test]
    fn required_live_all_pass_postgresql_passes() {
        let runner = Runner::new(test_registry());
        let backend = pg_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-001,CV-002".to_string()],
            required_live: true,
            ..Default::default()
        };
        let code = execute_cli(&runner, &backend, &args, passing_aware, |_| {}, |_| {});
        assert_eq!(code, EXIT_SUCCESS);
    }

    #[test]
    fn required_live_all_pass_external_fails() {
        let runner = Runner::new(test_registry());
        let backend = test_backend(); // LoomClient / External
        let args = CliArgs {
            scenario_ids: vec!["CV-001,CV-002".to_string()],
            required_live: true,
            ..Default::default()
        };
        let code = execute_cli(&runner, &backend, &args, passing_aware, |_| {}, |_| {});
        assert_eq!(code, EXIT_SCENARIO_FAILURE);
    }

    #[test]
    fn required_live_all_pass_inmemory_fails() {
        let runner = Runner::new(test_registry());
        let backend = inmemory_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-001,CV-002".to_string()],
            required_live: true,
            ..Default::default()
        };
        let code = execute_cli(&runner, &backend, &args, passing_aware, |_| {}, |_| {});
        assert_eq!(code, EXIT_SCENARIO_FAILURE);
    }

    #[test]
    fn required_live_postgresql_with_skipped_fails() {
        let runner = Runner::new(test_registry());
        let backend = pg_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-001,CV-002".to_string()],
            required_live: true,
            ..Default::default()
        };
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            |desc, ctx| {
                if desc.id_str() == "CV-001" {
                    skipped_executor(desc, ctx)
                } else {
                    passing_executor(desc, ctx)
                }
            },
            |_| {},
            |_| {},
        );
        assert_eq!(code, EXIT_SCENARIO_FAILURE);
    }

    #[test]
    fn required_live_postgresql_with_unavailable_fails() {
        let runner = Runner::new(test_registry());
        let backend = pg_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-001".to_string()],
            required_live: true,
            ..Default::default()
        };
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            unavailable_executor,
            |_| {},
            |_| {},
        );
        assert_eq!(code, EXIT_SCENARIO_FAILURE);
    }

    #[test]
    fn required_live_postgresql_with_fail_fails() {
        let runner = Runner::new(test_registry());
        let backend = pg_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-001,CV-002".to_string()],
            required_live: true,
            ..Default::default()
        };
        let code = execute_cli(&runner, &backend, &args, mixed_executor, |_| {}, |_| {});
        assert_eq!(code, EXIT_SCENARIO_FAILURE);
    }

    #[test]
    fn ambient_postgres_url_cannot_upgrade_external_required_live() {
        // Controlled evidence comes from explicit harness construction,
        // not ambient LOOM_TEST_POSTGRES_URL. External backend must still
        // fail required-live even when an unrelated PG URL is configured
        // elsewhere (the harness kind is the authority). This unit test
        // proves the external path fails required-live; the subprocess
        // regression `backend_evidence` proves ambient PG cannot upgrade
        // external evidence to PostgreSQL.
        let runner = Runner::new(test_registry());
        let backend = test_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-001".to_string()],
            required_live: true,
            ..Default::default()
        };
        let code = execute_cli(&runner, &backend, &args, passing_executor, |_| {}, |_| {});
        assert_eq!(code, EXIT_SCENARIO_FAILURE);
        // Also verify harness-level external evidence remains external
        let harness = crate::backend::BackendHarness::connect(
            BackendKind::LoomClient,
            "http://localhost:8080",
        )
        .unwrap();
        assert_eq!(
            harness.backend_evidence(),
            crate::scenario::BackendEvidence::External
        );
        assert!(!harness.backend_evidence().is_trusted());
    }

    #[test]
    fn required_live_selection_error_remains_exit_2() {
        let runner = Runner::new(test_registry());
        let backend = pg_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-999".to_string()],
            required_live: true,
            ..Default::default()
        };
        let mut err = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            passing_executor,
            |_| {},
            |l| err.push(l.to_string()),
        );
        assert_eq!(code, EXIT_RUNNER_ERROR);
        assert_ne!(code, EXIT_SCENARIO_FAILURE);
        assert!(err.join("\n").contains("CV-999"));
    }

    #[test]
    fn required_live_unknown_group_remains_exit_2() {
        let runner = Runner::new(test_registry());
        let backend = pg_backend();
        let args = CliArgs {
            groups: vec!["unknown-group".to_string()],
            required_live: true,
            ..Default::default()
        };
        let mut err = Vec::new();
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            passing_executor,
            |_| {},
            |l| err.push(l.to_string()),
        );
        assert_eq!(code, EXIT_RUNNER_ERROR);
        assert!(err.join("\n").contains("unknown group"));
    }

    #[test]
    fn required_live_single_pass_is_preserved() {
        use std::cell::RefCell;
        let runner = Runner::new(test_registry());
        let backend = pg_backend();
        let args = CliArgs {
            scenario_ids: vec!["CV-001,CV-002".to_string()],
            required_live: true,
            fail_fast: false,
            ..Default::default()
        };
        let counts: RefCell<Vec<String>> = RefCell::new(Vec::new());
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            |desc, ctx| {
                counts.borrow_mut().push(desc.id_str().to_string());
                passing_aware(desc, ctx)
            },
            |_| {},
            |_| {},
        );
        assert_eq!(code, EXIT_SUCCESS);
        assert_eq!(*counts.borrow(), vec!["CV-001", "CV-002"]);
    }

    #[test]
    fn required_live_harness_external_fails_even_with_pg_url() {
        use crate::backend::BackendHarness;
        let runner = Runner::new(test_registry());
        // Generic harness is always external, never upgrades to PostgreSQL
        // even when LOOM_TEST_POSTGRES_URL is configured elsewhere.
        // The harness kind is the authority; ambient configuration does not
        // change evidence class (see `backend_evidence` subprocess test).
        let harness = BackendHarness::connect(BackendKind::LoomClient, "http://localhost:8080")
            .unwrap()
            .with_policy(crate::reports::ValidationPolicy::required_live());
        let selection = runner.resolve_ids(&["CV-001".to_string()]).unwrap();
        let report =
            runner.run_with_harness_selected(&selection, &harness, passing_executor, false);
        assert!(!report.gate_passes());
        assert_eq!(
            report.backend_evidence(),
            Some(crate::scenario::BackendEvidence::External)
        );
    }

    #[test]
    fn help_text_documents_required_live() {
        let txt = help_text();
        assert!(txt.contains("--required-live"));
        assert!(txt.contains("required-live"));
    }
}
