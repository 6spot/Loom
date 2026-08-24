//! Command-line entrypoint for the Loom validator.

use std::process;

use loom_client::LoomClient;
use loom_validator::{
    BackendContext, Cli, CliCommand, CliError, Finding, Runner, ScenarioOutcome, ScenarioRegistry,
    ScenarioResult, USAGE,
};

fn main() {
    let exit_code = match try_main(std::env::args()) {
        Ok(exit_code) => exit_code,
        Err(error) => {
            eprintln!("loom-validator: error: {error}");
            2
        }
    };
    process::exit(i32::from(exit_code));
}

fn try_main<I, S>(args: I) -> Result<u8, CliError>
where
    I: IntoIterator<Item = S>,
    S: Into<String>,
{
    let cli = Cli::parse_from(args)?;
    let runner = Runner::new(ScenarioRegistry::bootstrap());

    match cli.command() {
        CliCommand::Help => {
            print!("{USAGE}");
            Ok(0)
        }
        CliCommand::List => {
            let descriptors: Vec<_> = runner.registry().iter().collect();
            println!("available scenarios ({}):", descriptors.len());
            for descriptor in descriptors {
                let backends = descriptor
                    .supported_backends()
                    .iter()
                    .map(ToString::to_string)
                    .collect::<Vec<_>>()
                    .join(",");
                println!(
                    "{}  {}  capability={}  backends={backends}",
                    descriptor.id(),
                    descriptor.name(),
                    descriptor.capability_area()
                );
            }
            Ok(0)
        }
        CliCommand::Run(options) => {
            let backend = BackendContext::new(
                LoomClient::builder("http://localhost:8080".to_string())
                    .build()
                    .map_err(|error| CliError::from_message(error.to_string()))?,
            );
            let report = runner.run_with_options(
                &options.execution_options(),
                &backend,
                |descriptor, _| {
                    // The bootstrap registry intentionally has no concrete
                    // scenario executors yet. If a descriptor is registered
                    // before an executor is wired, report that fact as an
                    // explicit unavailable scenario outcome rather than as a
                    // runner/configuration error or a fabricated pass.
                    let outcome = ScenarioOutcome::Unavailable {
                        reason: "scenario executor is not configured".to_string(),
                    };
                    let finding = Finding::new(
                        descriptor.id().clone(),
                        descriptor.name(),
                        "scenario executor configured",
                        "scenario executor missing",
                        descriptor.supported_backends()[0].clone(),
                        descriptor.capability_area().to_string(),
                        vec![],
                        outcome.clone(),
                    );
                    ScenarioResult::new(descriptor.id().clone(), outcome, finding)
                },
            )?;
            println!("loom-validator: {}", report.render_summary());
            Ok(options.exit_code(&report))
        }
    }
}
