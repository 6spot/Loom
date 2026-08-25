//! CLI entrypoint.

use clap::Parser;
use loom_cli::{Cli, execute};

#[tokio::main]
async fn main() {
    let cli = Cli::parse();
    let code = execute(cli).await;
    std::process::exit(code);
}
