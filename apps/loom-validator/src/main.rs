//! Command-line entrypoint for the Loom validator.
//!
//! The CLI implements deterministic scenario selection with clear separation
//! between scenario outcomes and runner failures.
//!
//! ## Exit semantics
//!
//! - `0` — success. Includes scenario failures when not in `--fail-fast` mode
//!   (default Task Ledger-friendly behavior).
//! - `1` — scenario failure when `--fail-fast` / `--strict` is enabled.
//! - `2` — runner/config error (unknown IDs, invalid arguments).
//!   Never a synthetic scenario finding.
//!
//! Normal development mode continues after a failed scenario and collects
//! remaining results; `--fail-fast` exists only as an explicit opt-in for CI
//! diagnostics.

use loom_validator::run_from_args;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let exit_code = run_from_args(args);
    std::process::exit(exit_code);
}
