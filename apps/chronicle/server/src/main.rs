//! Chronicle C1-T2 application server entry point.
//!
//! Long-lived Rust HTTP boundary for Chronicle: public/Studio namespaces,
//! single-admin Studio auth, health, same-origin web front. Historical reads
//! are served from the C0 Python read model through `CHRONICLE_UPSTREAM_URL`;
//! this binary never opens the Chronicle database directly.

use std::net::SocketAddr;
use std::sync::Arc;

use chronicle_server::{build_router, AppState, ChronicleConfig};

#[tokio::main]
async fn main() -> std::process::ExitCode {
    match run().await {
        Ok(()) => std::process::ExitCode::SUCCESS,
        Err(message) => {
            eprintln!(
                "{{\"service\":\"chronicle-server\",\"level\":\"error\",\"message\":{message:?}}}"
            );
            std::process::ExitCode::FAILURE
        }
    }
}

async fn run() -> Result<(), String> {
    let config = ChronicleConfig::from_env().map_err(|err| err.to_string())?;
    println!("{}", config.describe());

    let state = Arc::new(AppState {
        admin: config.admin.clone(),
        upstream: config.upstream.clone(),
    });
    let app = build_router(state);
    let addr = SocketAddr::new(config.bind, config.port);
    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .map_err(|err| format!("cannot bind {addr}: {err}"))?;
    println!(
        "{{\"service\":\"chronicle-server\",\"level\":\"info\",\"message\":\"listening\",\"bind\":{:?}}}",
        listener.local_addr().map(|addr| addr.to_string()),
    );

    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await
        .map_err(|err| format!("server error: {err}"))?;
    println!(
        "{{\"service\":\"chronicle-server\",\"level\":\"info\",\"message\":\"shutdown complete\"}}"
    );
    Ok(())
}

/// Resolve when SIGINT or SIGTERM is received (SIGTERM via Unix handler).
async fn shutdown_signal() {
    let ctrl_c = async {
        tokio::signal::ctrl_c()
            .await
            .expect("ctrl-c handler installs");
    };
    #[cfg(unix)]
    let terminate = async {
        tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
            .expect("sigterm handler installs")
            .recv()
            .await;
    };
    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        () = ctrl_c => {},
        () = terminate => {},
    }
    println!("{{\"service\":\"chronicle-server\",\"level\":\"info\",\"message\":\"shutdown signal received\"}}");
}
