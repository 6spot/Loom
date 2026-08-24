//! Command-line entrypoint for the Loom validator skeleton.

use loom_validator::{Runner, ScenarioRegistry};

fn main() {
    let report = Runner::new(ScenarioRegistry::bootstrap()).run();
    println!(
        "loom-validator: enumerated {} scenario(s)",
        report.scenario_count()
    );
}
