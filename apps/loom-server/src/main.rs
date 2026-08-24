//! Linux/native process entrypoint for the Loom composition root.

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt().json().init();
    if let Err(error) = loom_server::run_from_env().await {
        tracing::error!(%error, "loom-server stopped before completing its lifecycle");
        std::process::exit(1);
    }
}
