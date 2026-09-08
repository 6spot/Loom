//! Live HTTP regression for Chronicle's embedded Vite asset graph.
//!
//! R17 proved that a successful Vite build is not enough: the production Rust
//! front must actually embed and serve every deterministic lazy chunk referenced
//! by the committed build. This test starts the real Axum router on an ephemeral
//! port and requests every embedded Vite JS/CSS asset over HTTP.

use std::sync::Arc;
use std::time::Duration;

use chronicle_server::static_assets::ASSETS;
use chronicle_server::{build_router, AdminCredentials, AppState, UpstreamTarget};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

async fn get(port: u16, path: &str) -> Result<(u16, String, Vec<u8>), String> {
    let mut stream = TcpStream::connect(("127.0.0.1", port))
        .await
        .map_err(|err| err.to_string())?;
    let request = format!("GET {path} HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n");
    stream
        .write_all(request.as_bytes())
        .await
        .map_err(|err| err.to_string())?;

    let mut raw = Vec::new();
    stream
        .read_to_end(&mut raw)
        .await
        .map_err(|err| err.to_string())?;
    let head_end = raw
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .map(|index| index + 4)
        .ok_or_else(|| format!("missing response head for {path}"))?;
    let head = String::from_utf8_lossy(&raw[..head_end]).to_string();
    let status = head
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .and_then(|code| code.parse::<u16>().ok())
        .ok_or_else(|| format!("missing status for {path}"))?;
    Ok((status, head, raw[head_end..].to_vec()))
}

#[tokio::test]
async fn production_front_serves_every_committed_vite_asset_over_http() {
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind Chronicle production front");
    let port = listener.local_addr().expect("front addr").port();
    let state = AppState {
        admin: Some(AdminCredentials {
            username: "asset-test-admin".to_string(),
            password: "asset-test-password-0123456789".to_string(),
        }),
        // Static routes are upstream-independent; an unreachable target makes
        // the test prove that serving the web front does not require read-side
        // availability.
        upstream: UpstreamTarget {
            host: "127.0.0.1".to_string(),
            port: 1,
        },
    };
    let app = build_router(Arc::new(state));
    let server = tokio::spawn(async move {
        axum::serve(listener, app)
            .await
            .expect("serve Chronicle production front");
    });

    let mut ready = false;
    for _ in 0..100 {
        if matches!(get(port, "/studio/review").await, Ok((200, _, _))) {
            ready = true;
            break;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    assert!(ready, "Chronicle production front did not become ready");

    for route in ["/studio/review", "/studio/coverage"] {
        let (status, head, body) = get(port, route).await.expect("Studio shell response");
        assert_eq!(status, 200, "{route}");
        assert!(
            head.to_ascii_lowercase()
                .contains("content-type: text/html"),
            "{route}: {head}"
        );
        assert!(
            String::from_utf8_lossy(&body).contains("Chronicle"),
            "{route} did not return the SPA shell"
        );
    }

    let vite_assets = ASSETS
        .iter()
        .filter(|asset| asset.path.starts_with("/assets/"))
        .collect::<Vec<_>>();
    assert!(
        !vite_assets.is_empty(),
        "Vite asset allowlist must not be empty"
    );

    for asset in vite_assets {
        let (status, head, body) = get(port, asset.path).await.expect(asset.path);
        assert_eq!(status, 200, "production HTTP asset missing: {}", asset.path);
        assert!(
            head.to_ascii_lowercase()
                .contains(&format!("content-type: {}", asset.content_type).to_ascii_lowercase()),
            "wrong Content-Type for {}: {}",
            asset.path,
            head
        );
        assert!(!body.is_empty(), "empty production asset: {}", asset.path);
    }

    server.abort();
    let _ = server.await;
}
