//! Reader route integration for C2-R1-T17.
//!
//! The production Rust front is the only browser entry: public chapter
//! directory / full translation / pinned source requests proxy anonymously
//! to the Python `/v0/chapters*` sidecar, `/chapters*` browser paths serve
//! the SPA shell for direct open and refresh, API errors stay typed JSON
//! (never the HTML shell), and Studio keeps its existing authentication.

use std::sync::Arc;
use std::time::Duration;

use chronicle_server::{build_router, AdminCredentials, AppState, UpstreamTarget};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::oneshot;

const ADMIN_AUTH: &str = "Basic YWRtaW46bG9uZy1wYXNzd29yZA=="; // admin:long-password
const KNOWN_PUBLICATION: &str = "01900000-0000-7000-8000-000000000001";
const KNOWN_ANCHOR: &str = "anc_known0123456789";
const UNKNOWN_PUBLICATION: &str = "01900000-0000-7000-8000-000000000002";

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

fn chapters_body(path: &str) -> (u16, String) {
    let directory = format!(
        "{{\"items\":[{{\"publication_id\":\"{KNOWN_PUBLICATION}\",\"chapter_title\":\"Reader Smoke Chapter\"}}],\"next_cursor\":null}}"
    );
    let detail = format!(
        "{{\"publication_id\":\"{KNOWN_PUBLICATION}\",\"chapter_title\":\"Reader Smoke Chapter\",\"translation_blocks\":[{{\"block_id\":\"b1\",\"text\":\"Full vernacular text.\",\"source_anchor_ids\":[\"{KNOWN_ANCHOR}\"]}}]}}"
    );
    let source = format!(
        "{{\"anchor_id\":\"{KNOWN_ANCHOR}\",\"view\":\"window\",\"segments\":[{{\"text\":\"Source excerpt.\",\"highlight\":true}}],\"next_cursor\":null,\"has_more\":false}}"
    );
    if path == "/v0/chapters" || path.starts_with("/v0/chapters?") {
        return (200, directory);
    }
    if path == format!("/v0/chapters/{KNOWN_PUBLICATION}") {
        return (200, detail);
    }
    if path.starts_with(&format!("/v0/chapters/{KNOWN_PUBLICATION}/sources/")) {
        let query_split: Vec<&str> = path.splitn(2, '?').collect();
        let anchor = query_split[0]
            .strip_prefix(&format!("/v0/chapters/{KNOWN_PUBLICATION}/sources/"))
            .unwrap_or("");
        if anchor == KNOWN_ANCHOR {
            return (200, source);
        }
        return (
            404,
            "{\"schema\":\"chronicle.error\",\"version\":\"0.1\",\"error\":{\"code\":\"not_found\",\"message\":\"anchor is not part of this publication\"}}".to_string(),
        );
    }
    if path.starts_with("/v0/chapters/") {
        return (
            404,
            "{\"schema\":\"chronicle.error\",\"version\":\"0.1\",\"error\":{\"code\":\"not_found\",\"message\":\"publication is not published\"}}".to_string(),
        );
    }
    (
        404,
        "{\"schema\":\"chronicle.error\",\"version\":\"0.1\",\"error\":{\"code\":\"not_found\",\"message\":\"route not found\"}}".to_string(),
    )
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
                let head_end = head
                    .windows(4)
                    .position(|w| w == b"\r\n\r\n")
                    .map(|i| i + 4)
                    .unwrap_or(head.len());
                let text = String::from_utf8_lossy(&head[..head_end]).to_string();
                let mut lines = text.lines();
                let request_line = lines.next().unwrap_or("").to_string();
                let mut parts = request_line.split_whitespace();
                let method = parts.next().unwrap_or("").to_string();
                let path = parts.next().unwrap_or("/").to_string();
                let (status, body) = if method != "GET" && path.starts_with("/v0/chapters") {
                    (
                        405,
                        "{\"schema\":\"chronicle.error\",\"version\":\"0.1\",\"error\":{\"code\":\"method_not_allowed\",\"message\":\"only GET is supported\"}}".to_string(),
                    )
                } else {
                    chapters_body(&path)
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

fn test_state(upstream: UpstreamTarget) -> AppState {
    AppState {
        admin: Some(AdminCredentials {
            username: "admin".to_string(),
            password: "long-password".to_string(),
        }),
        upstream,
    }
}

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

async fn get(port: u16, path: &str) -> (u16, String, Vec<u8>) {
    raw_request(port, "GET", path, None)
        .await
        .expect("live server answers")
}

fn json_payload(body: &[u8]) -> serde_json::Value {
    serde_json::from_slice(body).expect("response body is JSON")
}

#[tokio::test]
async fn public_chapter_routes_proxy_anonymously_to_v0() {
    let (upstream, _mock) = spawn_mock_upstream().await;
    let server = spawn_server(test_state(upstream)).await;

    let (status, head, body) = get(server.port, "/api/v1/public/chapters?limit=1").await;
    assert_eq!(status, 200);
    assert!(head.to_ascii_lowercase().contains("application/json"));
    let payload = json_payload(&body);
    assert_eq!(payload["items"][0]["publication_id"], KNOWN_PUBLICATION);

    let (status, _, body) = get(
        server.port,
        &format!("/api/v1/public/chapters/{KNOWN_PUBLICATION}"),
    )
    .await;
    assert_eq!(status, 200);
    let payload = json_payload(&body);
    assert_eq!(payload["publication_id"], KNOWN_PUBLICATION);
    assert_eq!(payload["translation_blocks"][0]["block_id"], "b1");

    let (status, _, body) = get(
        server.port,
        &format!("/api/v1/public/chapters/{KNOWN_PUBLICATION}/sources/{KNOWN_ANCHOR}?view=window"),
    )
    .await;
    assert_eq!(status, 200);
    let payload = json_payload(&body);
    assert_eq!(payload["anchor_id"], KNOWN_ANCHOR);

    // Legacy sidecar path stays reachable through the same front.
    let (status, _, body) = get(server.port, "/v0/chapters?limit=1").await;
    assert_eq!(status, 200);
    assert_eq!(
        json_payload(&body)["items"][0]["publication_id"],
        KNOWN_PUBLICATION
    );

    server.stop().await;
}

#[tokio::test]
async fn unpublished_chapters_and_foreign_anchors_stay_json_404() {
    let (upstream, _mock) = spawn_mock_upstream().await;
    let server = spawn_server(test_state(upstream)).await;

    for path in [
        format!("/api/v1/public/chapters/{UNKNOWN_PUBLICATION}"),
        format!("/api/v1/public/chapters/{KNOWN_PUBLICATION}/sources/no-such-anchor"),
        format!("/api/v1/public/chapters/{UNKNOWN_PUBLICATION}/sources/{KNOWN_ANCHOR}"),
    ] {
        let (status, head, body) = get(server.port, &path).await;
        assert_eq!((path.as_str(), status), (path.as_str(), 404));
        // API errors must keep the JSON contract, never the HTML shell.
        assert!(
            head.to_ascii_lowercase().contains("application/json"),
            "{path}"
        );
        let payload = json_payload(&body);
        assert_eq!(payload["schema"], "chronicle.error", "{path}");
        assert_eq!(payload["error"]["code"], "not_found", "{path}");
        assert!(
            !String::from_utf8_lossy(&body).contains("<!doctype"),
            "{path} must not serve the SPA shell"
        );
    }

    server.stop().await;
}

#[tokio::test]
async fn chapter_reads_reject_non_get_with_typed_error() {
    let (upstream, _mock) = spawn_mock_upstream().await;
    let server = spawn_server(test_state(upstream)).await;

    let (status, head, body) = raw_request(server.port, "POST", "/api/v1/public/chapters", None)
        .await
        .expect("live server answers");
    assert_eq!(status, 405);
    assert!(head.to_ascii_lowercase().contains("application/json"));
    let payload = json_payload(&body);
    assert_eq!(payload["schema"], "chronicle.error");
    assert_eq!(payload["error"]["code"], "method_not_allowed");

    server.stop().await;
}

#[tokio::test]
async fn chapters_browser_paths_serve_shell_for_direct_open_and_refresh() {
    let (upstream, _mock) = spawn_mock_upstream().await;
    let server = spawn_server(test_state(upstream)).await;

    for path in [
        "/chapters".to_string(),
        "/chapters/".to_string(),
        format!("/chapters/{KNOWN_PUBLICATION}"),
        format!("/chapters/{KNOWN_PUBLICATION}/"),
    ] {
        let (status, head, body) = get(server.port, &path).await;
        assert_eq!((path.as_str(), status), (path.as_str(), 200));
        assert!(head.contains("text/html"), "{path}");
        assert!(
            String::from_utf8_lossy(&body).contains("Chronicle"),
            "{path}"
        );
    }

    // Deeper nesting is not a reader route and must not resolve to the shell.
    let (status, _, _) = get(server.port, "/chapters/a/b").await;
    assert_eq!(status, 404);

    server.stop().await;
}

#[tokio::test]
async fn studio_auth_is_not_relaxed_by_reader_routes() {
    let (upstream, _mock) = spawn_mock_upstream().await;
    let server = spawn_server(test_state(upstream)).await;

    let (anon, _, _) = get(server.port, "/api/v1/studio/status").await;
    assert_eq!(anon, 401);
    let (ok, _, body) = raw_request(
        server.port,
        "GET",
        "/api/v1/studio/status",
        Some(ADMIN_AUTH),
    )
    .await
    .expect("live server answers");
    assert_eq!(ok, 200);
    let payload = json_payload(&body);
    assert_eq!(payload["schema"], "chronicle.studio-status");

    server.stop().await;
}
