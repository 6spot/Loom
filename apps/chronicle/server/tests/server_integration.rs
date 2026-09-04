//! End-to-end boundary tests for the Chronicle server.
//!
//! A mock C0 upstream (raw TCP) plus a live Axum server on an ephemeral port
//! prove namespace separation, Studio auth enforcement, proxy mapping, typed
//! errors, the web front, and graceful shutdown without any database.

use std::sync::Arc;
use std::time::Duration;

use chronicle_server::{build_router, AdminCredentials, AppState, UpstreamTarget};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::oneshot;

const ADMIN_AUTH: &str = "Basic YWRtaW46bG9uZy1wYXNzd29yZA=="; // admin:long-password

struct LiveServer {
    port: u16,
    shutdown: Option<oneshot::Sender<()>>,
    task: tokio::task::JoinHandle<()>,
}

impl LiveServer {
    async fn stop(mut self) {
        if let Some(tx) = self.shutdown.take() {
            let _ = tx.send(());
        }
        tokio::time::timeout(Duration::from_secs(5), &mut self.task)
            .await
            .expect("shutdown completes")
            .expect("server task joins");
    }
}

async fn spawn_mock_upstream() -> (UpstreamTarget, tokio::task::JoinHandle<()>) {
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind upstream");
    let port = listener.local_addr().expect("addr").port();
    let task = tokio::spawn(async move {
        loop {
            let Ok((mut socket, _)) = listener.accept().await else {
                break;
            };
            tokio::spawn(async move {
                let mut buffer = vec![0_u8; 4096];
                let mut head = Vec::new();
                // Read until end of request head.
                loop {
                    match socket.read(&mut buffer).await {
                        Ok(0) | Err(_) => return,
                        Ok(read) => {
                            head.extend_from_slice(&buffer[..read]);
                            if head.windows(4).any(|w| w == b"\r\n\r\n") || head.len() > 8192 {
                                break;
                            }
                        }
                    }
                }
                let text = String::from_utf8_lossy(&head).to_string();
                let request_line = text.lines().next().unwrap_or("").to_string();
                let mut parts = request_line.split_whitespace();
                let _method = parts.next().unwrap_or("");
                let path = parts.next().unwrap_or("/").to_string();
                let (status, body) = if path.starts_with("/v0/") {
                    (
                        200,
                        format!("{{\"schema\":\"chronicle.mock\",\"proxied_path\":{path:?}}}"),
                    )
                } else if path == "/healthz" {
                    (200, "{\"status\":\"ok\"}".to_string())
                } else {
                    (404, "{\"error\":\"mock only serves /v0/*\"}".to_string())
                };
                let response = format!(
                    "HTTP/1.0 {status} OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                );
                let _ = socket.write_all(response.as_bytes()).await;
            });
        }
    });
    (
        UpstreamTarget {
            host: "127.0.0.1".to_string(),
            port,
        },
        task,
    )
}

async fn spawn_server(state: AppState) -> LiveServer {
    let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind server");
    let port = listener.local_addr().expect("addr").port();
    let (tx, rx) = oneshot::channel::<()>();
    let app = build_router(Arc::new(state));
    let task = tokio::spawn(async move {
        axum::serve(listener, app)
            .with_graceful_shutdown(async {
                rx.await.ok();
            })
            .await
            .expect("serve");
    });
    // Wait until the live server answers health before running assertions.
    for _ in 0..100 {
        match raw_request(port, "GET", "/healthz", None).await {
            Ok((200, _, _)) => break,
            _ => tokio::time::sleep(Duration::from_millis(20)).await,
        }
    }
    LiveServer {
        port,
        shutdown: Some(tx),
        task,
    }
}

fn test_state(upstream: UpstreamTarget, with_admin: bool) -> AppState {
    AppState {
        admin: with_admin.then(|| AdminCredentials {
            username: "admin".to_string(),
            password: "long-password".to_string(),
        }),
        upstream,
    }
}

/// Minimal raw HTTP/1.0 client: returns (status, headers, body).
async fn raw_request(
    port: u16,
    method: &str,
    path: &str,
    auth: Option<&str>,
) -> Result<(u16, String, Vec<u8>), String> {
    let mut stream = TcpStream::connect(format!("127.0.0.1:{port}"))
        .await
        .map_err(|err| err.to_string())?;
    let mut request =
        format!("{method} {path} HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n");
    if let Some(value) = auth {
        request.push_str(&format!("Authorization: {value}\r\n"));
    }
    request.push_str("\r\n");
    stream.write_all(request.as_bytes()).await.expect("write");
    let mut raw = Vec::new();
    stream.read_to_end(&mut raw).await.expect("read");
    let head_end = raw
        .windows(4)
        .position(|w| w == b"\r\n\r\n")
        .map(|i| i + 4)
        .ok_or_else(|| "response head".to_string())?;
    let head = String::from_utf8_lossy(&raw[..head_end]).to_string();
    let status: u16 = head
        .lines()
        .next()
        .unwrap_or("")
        .split_whitespace()
        .nth(1)
        .and_then(|code| code.parse().ok())
        .ok_or_else(|| "status".to_string())?;
    Ok((status, head, raw[head_end..].to_vec()))
}

async fn get(port: u16, path: &str, auth: Option<&str>) -> (u16, String, Vec<u8>) {
    raw_request(port, "GET", path, auth)
        .await
        .expect("live server answers")
}

#[tokio::test]
async fn health_is_public_and_database_independent() {
    let (upstream, _mock) = spawn_mock_upstream().await;
    let server = spawn_server(test_state(upstream, true)).await;
    let (status, _, body) = get(server.port, "/healthz", None).await;
    assert_eq!(status, 200);
    assert_eq!(body, b"{\"status\":\"ok\"}");
    server.stop().await;
}

#[tokio::test]
async fn public_namespaces_proxy_to_c0_paths() {
    let (upstream, _mock) = spawn_mock_upstream().await;
    let server = spawn_server(test_state(upstream, true)).await;
    for (public, expected_proxied) in [
        ("/api/v1/public/timeline?limit=1", "/v0/timeline?limit=1"),
        (
            "/api/v1/public/search?q=%E6%9B%B9",
            "/v0/search?q=%E6%9B%B9",
        ),
        ("/api/v1/public/events/some-id", "/v0/events/some-id"),
        ("/api/v1/public/entities/some-id", "/v0/entities/some-id"),
        ("/v0/timeline?limit=1", "/v0/timeline?limit=1"),
        ("/v0/events/some-id", "/v0/events/some-id"),
    ] {
        let (status, _, body) = get(server.port, public, None).await;
        assert_eq!((public, status), (public, 200));
        let payload: serde_json::Value = serde_json::from_slice(&body).expect("json");
        assert_eq!(payload["proxied_path"], expected_proxied, "{public}");
    }
    server.stop().await;
}

#[tokio::test]
async fn public_reads_reject_non_get_with_typed_error() {
    let (upstream, _mock) = spawn_mock_upstream().await;
    let server = spawn_server(test_state(upstream, true)).await;
    let (status, _, body) = raw_request(server.port, "POST", "/api/v1/public/timeline", None)
        .await
        .expect("live server answers");
    assert_eq!(status, 405);
    let payload: serde_json::Value = serde_json::from_slice(&body).expect("json");
    assert_eq!(payload["schema"], "chronicle.error");
    assert_eq!(payload["error"]["code"], "method_not_allowed");
    server.stop().await;
}

#[tokio::test]
async fn studio_status_requires_admin_credentials() {
    let (upstream, _mock) = spawn_mock_upstream().await;
    let server = spawn_server(test_state(upstream, true)).await;

    let (missing, missing_head, missing_body) =
        get(server.port, "/api/v1/studio/status", None).await;
    assert_eq!(missing, 401);
    assert!(missing_head
        .to_ascii_lowercase()
        .contains("www-authenticate"));
    let payload: serde_json::Value = serde_json::from_slice(&missing_body).expect("json");
    assert_eq!(payload["error"]["code"], "unauthorized");

    let wrong = "Basic YWRtaW46d3JvbmctcGFzc3dvcmQ="; // admin:wrong-password
    let (denied, _, _) = get(server.port, "/api/v1/studio/status", Some(wrong)).await;
    assert_eq!(denied, 401);

    let (ok, _, body) = get(server.port, "/api/v1/studio/status", Some(ADMIN_AUTH)).await;
    assert_eq!(ok, 200);
    let payload: serde_json::Value = serde_json::from_slice(&body).expect("json");
    assert_eq!(payload["schema"], "chronicle.studio-status");
    assert_eq!(payload["admin_user"], "admin");
    assert_eq!(payload["upstream"]["reachable"], true);
    // The admin password is never echoed back.
    assert!(!String::from_utf8_lossy(&body).contains("long-password"));
    server.stop().await;
}

#[tokio::test]
async fn studio_is_fail_closed_without_configuration() {
    let (upstream, _mock) = spawn_mock_upstream().await;
    let server = spawn_server(test_state(upstream, false)).await;
    let (status, _, body) = get(server.port, "/api/v1/studio/status", Some(ADMIN_AUTH)).await;
    assert_eq!(status, 503);
    let payload: serde_json::Value = serde_json::from_slice(&body).expect("json");
    assert_eq!(payload["error"]["code"], "studio_auth_unconfigured");
    // Unknown Studio paths do not leak existence information either.
    let (hidden, _, hidden_body) = get(server.port, "/api/v1/studio/jobs", None).await;
    assert_eq!(hidden, 503);
    let payload: serde_json::Value = serde_json::from_slice(&hidden_body).expect("json");
    assert_eq!(payload["error"]["code"], "studio_auth_unconfigured");
    server.stop().await;
}

#[tokio::test]
async fn unknown_studio_paths_need_auth_then_404() {
    let (upstream, _mock) = spawn_mock_upstream().await;
    let server = spawn_server(test_state(upstream, true)).await;
    let (anon, _, _) = get(server.port, "/api/v1/studio/jobs", None).await;
    assert_eq!(anon, 401);
    let (status, _, body) = get(server.port, "/api/v1/studio/jobs", Some(ADMIN_AUTH)).await;
    assert_eq!(status, 404);
    let payload: serde_json::Value = serde_json::from_slice(&body).expect("json");
    assert_eq!(payload["error"]["code"], "not_found");
    server.stop().await;
}

#[tokio::test]
async fn upstream_outage_maps_to_typed_503() {
    let down = UpstreamTarget {
        host: "127.0.0.1".to_string(),
        port: 1,
    };
    let server = spawn_server(test_state(down, true)).await;
    let (status, _, body) = get(server.port, "/api/v1/public/timeline", None).await;
    assert_eq!(status, 503);
    let payload: serde_json::Value = serde_json::from_slice(&body).expect("json");
    assert_eq!(payload["schema"], "chronicle.error");
    assert_eq!(payload["error"]["code"], "upstream_unavailable");
    server.stop().await;
}

#[tokio::test]
async fn web_front_serves_shell_and_assets() {
    let (upstream, _mock) = spawn_mock_upstream().await;
    let server = spawn_server(test_state(upstream, true)).await;
    let (shell, shell_head, shell_body) = get(server.port, "/timeline", None).await;
    assert_eq!(shell, 200);
    assert!(shell_head.contains("text/html"));
    assert!(String::from_utf8_lossy(&shell_body).contains("Chronicle"));
    let (asset, asset_head, asset_body) = get(server.port, "/app.mjs", None).await;
    assert_eq!(asset, 200);
    assert!(asset_head.contains("text/javascript"));
    assert!(!asset_body.is_empty());
    let (missing, _, _) = get(server.port, "/no-such-page", None).await;
    assert_eq!(missing, 404);
    // API-shaped unknowns never fall through to the shell.
    let (api_missing, _, api_body) = get(server.port, "/api/v1/public/nope", None).await;
    assert_eq!(api_missing, 404);
    let payload: serde_json::Value = serde_json::from_slice(&api_body).expect("json");
    assert_eq!(payload["schema"], "chronicle.error");
    server.stop().await;
}

#[tokio::test]
async fn studio_shell_and_react_assets_serve_without_auth() {
    // The Studio shell carries no privileged data (auth is enforced on the
    // Studio APIs), so it is public like the other SPA routes.
    let (upstream, _mock) = spawn_mock_upstream().await;
    let server = spawn_server(test_state(upstream, true)).await;
    for path in [
        "/studio",
        "/studio/login",
        "/studio/imports",
        "/studio/review",
        "/studio/sources",
    ] {
        let (status, head, body) = get(server.port, path, None).await;
        assert_eq!((path, status), (path, 200));
        assert!(head.contains("text/html"), "{path}");
        assert!(
            String::from_utf8_lossy(&body).contains("Chronicle"),
            "{path}"
        );
    }
    let (bundle, bundle_head, bundle_body) = get(server.port, "/assets/index.js", None).await;
    assert_eq!(bundle, 200);
    assert!(bundle_head.contains("text/javascript"));
    assert!(!bundle_body.is_empty());
    // Unknown Studio sub-paths must not resolve to the shell.
    let (unknown, _, _) = get(server.port, "/studio/unknown", None).await;
    assert_eq!(unknown, 404);
    server.stop().await;
}
