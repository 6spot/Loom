//! Small, dependency-free command-line contract for the validator.

use std::fmt;

use crate::reports::ValidationReport;
use crate::runner::{ExecutionOptions, RunnerError, ScenarioSelection};

/// Parsed validator command.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CliCommand {
    /// List registered scenario metadata without executing scenarios.
    List,
    /// Execute the selected scenarios.
    Run(CliRunOptions),
    /// Print command help.
    Help,
}

/// Options parsed for a `run` command.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CliRunOptions {
    selection: ScenarioSelection,
    fail_fast: bool,
    nonzero: bool,
}

impl CliRunOptions {
    /// Returns the scenario selection.
    #[must_use]
    pub const fn selection(&self) -> &ScenarioSelection {
        &self.selection
    }

    /// Returns whether execution stops after the first scenario failure.
    #[must_use]
    pub const fn fail_fast(&self) -> bool {
        self.fail_fast
    }

    /// Returns whether a scenario failure produces a nonzero process status.
    #[must_use]
    pub const fn nonzero(&self) -> bool {
        self.nonzero
    }

    /// Converts CLI options to runner execution options.
    #[must_use]
    pub fn execution_options(&self) -> ExecutionOptions {
        ExecutionOptions::new(self.selection.clone()).with_fail_fast(self.fail_fast)
    }

    /// Returns the process status for a completed report.
    ///
    /// The default mode intentionally returns zero even when a scenario
    /// failed, allowing Task Ledger/development runs to collect all findings.
    /// `--nonzero` and `--fail-fast` opt into status `1` for scenario failure.
    #[must_use]
    pub fn exit_code(&self, report: &ValidationReport) -> u8 {
        u8::from(self.nonzero && report.has_failures())
    }
}

/// A parsed command-line invocation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Cli {
    command: CliCommand,
}

impl Cli {
    /// Parses arguments in the same shape as `std::env::args()` (including the
    /// executable name as the first argument).
    ///
    /// Supported forms are:
    ///
    /// ```text
    /// loom-validator list
    /// loom-validator run
    /// loom-validator run CV-001 CV-002
    /// loom-validator run --scenario CV-001 --scenario CV-002
    /// loom-validator run --all
    /// loom-validator run --fail-fast
    /// ```
    ///
    /// `--scenario` may be repeated and accepts comma-separated IDs. Repeated
    /// IDs are de-duplicated by the runner. With no selection, `run` executes
    /// all available scenarios. With no command, the invocation is equivalent
    /// to `run` for backwards compatibility with the validator skeleton.
    ///
    /// # Errors
    ///
    /// Returns [`CliError`] for an unknown option, missing option value, or
    /// conflicting selection mode.
    pub fn parse_from<I, S>(args: I) -> Result<Self, CliError>
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        let mut args = args.into_iter().map(Into::into);
        let _program = args.next();
        let mut saw_list = false;
        let mut saw_run = false;
        let mut saw_all = false;
        let mut ids = Vec::new();
        let mut fail_fast = false;
        let mut nonzero = false;

        while let Some(arg) = args.next() {
            match arg.as_str() {
                "list" | "--list" => {
                    saw_list = true;
                }
                "run" => {
                    saw_run = true;
                }
                "all" | "--all" | "-a" => {
                    saw_all = true;
                }
                "--fail-fast" => {
                    fail_fast = true;
                    nonzero = true;
                }
                "--nonzero" => {
                    nonzero = true;
                }
                "-h" | "--help" => return Ok(Self::new(CliCommand::Help)),
                option if option == "--scenario" || option == "--id" || option == "-s" => {
                    let value = args
                        .next()
                        .ok_or_else(|| CliError::new(format!("{option} requires a scenario ID")))?;
                    add_ids(&mut ids, &value)?;
                }
                option if option.starts_with("--scenario=") || option.starts_with("--id=") => {
                    let Some((_, value)) = option.split_once('=') else {
                        return Err(CliError::new("scenario option requires an ID"));
                    };
                    add_ids(&mut ids, value)?;
                }
                "--" => {
                    for value in args {
                        add_ids(&mut ids, &value)?;
                    }
                    break;
                }
                option if option.starts_with('-') => {
                    return Err(CliError::new(format!("unknown option: {option}")));
                }
                value => add_ids(&mut ids, value)?,
            }
        }

        if saw_list {
            if saw_run || saw_all || !ids.is_empty() || fail_fast || nonzero {
                return Err(CliError::new(
                    "list cannot be combined with run or execution options",
                ));
            }
            return Ok(Self::new(CliCommand::List));
        }

        if saw_all && !ids.is_empty() {
            return Err(CliError::new(
                "--all cannot be combined with explicit scenario IDs",
            ));
        }

        let selection = if saw_all || ids.is_empty() {
            ScenarioSelection::all()
        } else {
            ScenarioSelection::ids(ids)
        };
        let _ = saw_run;
        Ok(Self::new(CliCommand::Run(CliRunOptions {
            selection,
            fail_fast,
            nonzero,
        })))
    }

    /// Returns the parsed command.
    #[must_use]
    pub const fn command(&self) -> &CliCommand {
        &self.command
    }

    const fn new(command: CliCommand) -> Self {
        Self { command }
    }
}

/// A command-line configuration error.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CliError(String);

impl CliError {
    fn new(message: impl Into<String>) -> Self {
        Self(message.into())
    }

    /// Creates a configuration error from an owned message.
    #[must_use]
    pub fn from_message(message: impl Into<String>) -> Self {
        Self(message.into())
    }
}

impl fmt::Display for CliError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for CliError {}

impl From<RunnerError> for CliError {
    fn from(error: RunnerError) -> Self {
        Self(error.to_string())
    }
}

/// Human-readable command help.
pub const USAGE: &str = "Usage: loom-validator [list | run] [OPTIONS] [SCENARIO_ID ...]\n\nCommands:\n  list                  List available scenarios\n  run                   Run all scenarios (the default command)\n\nOptions:\n  -s, --scenario ID     Select a scenario; may be repeated or comma-separated\n  -a, --all             Select every available scenario\n      --fail-fast      Stop after the first scenario failure and exit nonzero\n      --nonzero         Exit nonzero when any scenario fails, but continue\n  -h, --help            Show this help\n\nUnknown IDs and invalid options are runner/configuration errors. Scenario failures\nare collected and do not affect the default process exit status.\n";

fn add_ids(ids: &mut Vec<String>, value: &str) -> Result<(), CliError> {
    for id in value.split(',') {
        if id.is_empty() {
            return Err(CliError::new("scenario ID cannot be empty"));
        }
        ids.push(id.to_string());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{Cli, CliCommand};
    use crate::runner::{RunnerError, ScenarioSelection};

    #[test]
    fn parses_list() {
        let cli = Cli::parse_from(["loom-validator", "list"]).unwrap();
        assert_eq!(cli.command(), &CliCommand::List);
    }

    #[test]
    fn parses_single_and_repeated_ids() {
        let cli = Cli::parse_from([
            "loom-validator",
            "run",
            "--scenario",
            "CV-002",
            "--scenario=CV-001,CV-002",
        ])
        .unwrap();
        let CliCommand::Run(options) = cli.command() else {
            panic!("expected run command");
        };
        assert_eq!(
            options.selection(),
            &ScenarioSelection::ids(["CV-002", "CV-001", "CV-002"])
        );
    }

    #[test]
    fn defaults_to_all_and_fail_fast_implies_nonzero() {
        let cli = Cli::parse_from(["loom-validator", "--fail-fast"]).unwrap();
        let CliCommand::Run(options) = cli.command() else {
            panic!("expected run command");
        };
        assert_eq!(options.selection(), &ScenarioSelection::all());
        assert!(options.fail_fast());
        assert!(options.nonzero());
    }

    #[test]
    fn rejects_conflicting_all_and_ids() {
        let error = Cli::parse_from(["loom-validator", "--all", "CV-001"]).unwrap_err();
        assert!(error.to_string().contains("--all"));
    }

    #[test]
    fn runner_errors_are_distinct_from_cli_errors() {
        let error = RunnerError::UnknownScenario("CV-999".to_string());
        assert_eq!(error.to_string(), "unknown scenario id: CV-999");
    }

    #[test]
    fn scenario_failure_is_nonzero_only_when_explicitly_requested() {
        let default = Cli::parse_from(["loom-validator", "run"]).unwrap();
        let nonzero = Cli::parse_from(["loom-validator", "run", "--nonzero"]).unwrap();
        let report = crate::ValidationReport::from_results(vec![crate::ScenarioResult::new(
            crate::ScenarioId::new("CV-001"),
            crate::ScenarioOutcome::Fail,
            crate::Finding::new(
                crate::ScenarioId::new("CV-001"),
                "scenario",
                "expected",
                "actual",
                crate::BackendKind::LoomClient,
                "test",
                vec![],
                crate::ScenarioOutcome::Fail,
            ),
        )]);
        let CliCommand::Run(default) = default.command() else {
            panic!("expected run command");
        };
        let CliCommand::Run(nonzero) = nonzero.command() else {
            panic!("expected run command");
        };
        assert_eq!(default.exit_code(&report), 0);
        assert_eq!(nonzero.exit_code(&report), 1);
    }
}
