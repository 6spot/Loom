//! C1-T15 Historical Moment namespace forwarding tests.

use std::sync::Arc;
use std::time::Duration;

use chronicle_server::{build_router, AppState, UpstreamTarget};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::oneshot;

async fn mock_upstream() -> (UpstreamTarget, tokio::task::JoinHandle<()>) {
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind upstream");
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
                    "{{\"schema\":\"chronicle.historical-moment\",\"proxied_path\":{path:?}}}"
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

async fn request(port: u16, method: &str, path: &str) -> (u16, String) {
    let mut stream = TcpStream::connect(format!("127.0.0.1:{port}"))
        .await
        .expect("connect");
    let head = format!("{method} {path} HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n");
    stream.write_all(head.as_bytes()).await.expect("write");
    let mut raw = Vec::new();
    stream.read_to_end(&mut raw).await.expect("read");
    let split = raw
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .expect("head")
        + 4;
    let status = String::from_utf8_lossy(&raw[..split])
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .and_then(|value| value.parse::<u16>().ok())
        .expect("status");
    (status, String::from_utf8_lossy(&raw[split..]).to_string())
}

async fn live_server(state: AppState) -> (u16, oneshot::Sender<()>, tokio::task::JoinHandle<()>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind server");
    let port = listener.local_addr().expect("addr").port();
    let (tx, rx) = oneshot::channel();
    let task = tokio::spawn(async move {
        axum::serve(listener, build_router(Arc::new(state)))
            .with_graceful_shutdown(async {
                let _ = rx.await;
            })
            .await
            .expect("serve");
    });
    for _ in 0..50 {
        if TcpStream::connect(format!("127.0.0.1:{port}"))
            .await
            .is_ok()
        {
            break;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    (port, tx, task)
}

#[tokio::test]
async fn public_and_legacy_historical_moment_forward_to_one_read_contract() {
    let (upstream, upstream_task) = mock_upstream().await;
    let (port, stop, server_task) = live_server(AppState {
        admin: None,
        upstream,
    })
    .await;

    let (status, body) = request(
        port,
        "GET",
        "/api/v1/public/historical-moment?year=208&limit=50",
    )
    .await;
    assert_eq!(status, 200);
    assert!(
        body.contains("/v0/historical-moment?year=208&limit=50"),
        "{body}"
    );

    let (status, body) = request(
        port,
        "GET",
        "/v0/historical-moment?from_year=208&to_year=209",
    )
    .await;
    assert_eq!(status, 200);
    assert!(
        body.contains("/v0/historical-moment?from_year=208&to_year=209"),
        "{body}"
    );

    let (status, _) = request(port, "POST", "/api/v1/public/historical-moment?year=208").await;
    assert_eq!(status, 405);

    let _ = stop.send(());
    server_task.await.expect("server join");
    upstream_task.abort();
}
