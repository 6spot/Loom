//! C1-T14 Coverage namespace/auth forwarding tests.

use std::sync::Arc;
use std::time::Duration;

use chronicle_server::{build_router, AdminCredentials, AppState, UpstreamTarget};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::oneshot;

const ADMIN_AUTH: &str = "Basic YWRtaW46bG9uZy1wYXNzd29yZA=="; // admin:long-password

async fn mock_upstream() -> (UpstreamTarget, tokio::task::JoinHandle<()>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind upstream");
    let port = listener.local_addr().expect("addr").port();
    let task = tokio::spawn(async move {
        while let Ok((mut socket, _)) = listener.accept().await {
            tokio::spawn(async move {
                let mut raw = vec![0_u8; 4096];
                let read = socket.read(&mut raw).await.unwrap_or(0);
                let text = String::from_utf8_lossy(&raw[..read]);
                let path = text
                    .lines()
                    .next()
                    .and_then(|line| line.split_whitespace().nth(1))
                    .unwrap_or("/");
                let body = format!(
                    "{{\"schema\":\"chronicle.coverage\",\"proxied_path\":{path:?}}}"
                );
                let response = format!(
                    "HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
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

async fn request(port: u16, method: &str, path: &str, auth: Option<&str>) -> (u16, String, String) {
    let mut stream = TcpStream::connect(format!("127.0.0.1:{port}"))
        .await
        .expect("connect");
    let mut head = format!("{method} {path} HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n");
    if let Some(auth) = auth {
        head.push_str(&format!("Authorization: {auth}\r\n"));
    }
    head.push_str("\r\n");
    stream.write_all(head.as_bytes()).await.expect("write");
    let mut raw = Vec::new();
    stream.read_to_end(&mut raw).await.expect("read");
    let split = raw.windows(4).position(|w| w == b"\r\n\r\n").expect("head") + 4;
    let headers = String::from_utf8_lossy(&raw[..split]).to_string();
    let status = headers
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .and_then(|value| value.parse::<u16>().ok())
        .expect("status");
    (status, headers, String::from_utf8_lossy(&raw[split..]).to_string())
}

async fn live_server(state: AppState) -> (u16, oneshot::Sender<()>, tokio::task::JoinHandle<()>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind server");
    let port = listener.local_addr().expect("addr").port();
    let (tx, rx) = oneshot::channel();
    let task = tokio::spawn(async move {
        axum::serve(listener, build_router(Arc::new(state)))
            .with_graceful_shutdown(async { let _ = rx.await; })
            .await
            .expect("serve");
    });
    for _ in 0..50 {
        if TcpStream::connect(format!("127.0.0.1:{port}")).await.is_ok() {
            break;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    (port, tx, task)
}

#[tokio::test]
async fn public_and_legacy_coverage_forward_to_one_upstream_contract() {
    let (upstream, upstream_task) = mock_upstream().await;
    let (port, stop, server_task) = live_server(AppState { admin: None, upstream }).await;

    let (status, _, body) = request(
        port,
        "GET",
        "/api/v1/public/coverage?from_year=208&to_year=208",
        None,
    )
    .await;
    assert_eq!(status, 200);
    assert!(body.contains("/v0/coverage?from_year=208&to_year=208"), "{body}");

    let (status, _, body) = request(port, "GET", "/v0/coverage", None).await;
    assert_eq!(status, 200);
    assert!(body.contains("/v0/coverage"), "{body}");

    let (status, _, _) = request(port, "POST", "/api/v1/public/coverage", None).await;
    assert_eq!(status, 405);

    let _ = stop.send(());
    server_task.await.expect("server join");
    upstream_task.abort();
}

#[tokio::test]
async fn studio_coverage_is_auth_gated_but_uses_same_read_projection() {
    let (upstream, upstream_task) = mock_upstream().await;
    let admin = AdminCredentials {
        username: "admin".to_string(),
        password: "long-password".to_string(),
    };
    let (port, stop, server_task) = live_server(AppState {
        admin: Some(admin),
        upstream,
    })
    .await;

    let (status, headers, _) = request(port, "GET", "/api/v1/studio/coverage", None).await;
    assert_eq!(status, 401);
    assert!(headers.to_ascii_lowercase().contains("www-authenticate: basic"));

    let (status, _, body) = request(
        port,
        "GET",
        "/api/v1/studio/coverage?from_year=208&to_year=210",
        Some(ADMIN_AUTH),
    )
    .await;
    assert_eq!(status, 200);
    assert!(body.contains("/v0/coverage?from_year=208&to_year=210"), "{body}");

    let _ = stop.send(());
    server_task.await.expect("server join");
    upstream_task.abort();
}
