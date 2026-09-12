//! C2-R3-T10 public source person-state forwarding tests.
//!
//! The Rust server owns only transport: every `/api/v1/public/reading-streams/
//! .../people[/{person_id}/states]` request is forwarded byte-for-byte to the
//! Python sidecar's `/v0/reading-streams/...` contract, preserving the full
//! `catalog`/`stream`/`unit`/`person`/`section` query. These tests boot the
//! real router against a mock TCP upstream that echoes the forwarded path so a
//! mapping regression (e.g. the deeper `units/.../people` subpath being
//! swallowed) is caught before any real stack exists.
//!
//! The Studio person-state decision path stays behind the authenticated
//! `/api/v1/studio/jobs/{*rest}` proxy; no anonymous route can reach it.

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
                let body = format!("{{\"proxied_path\":{path:?}}}");
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
    let split = raw.windows(4).position(|w| w == b"\r\n\r\n").expect("head") + 4;
    let status = String::from_utf8_lossy(&raw[..split])
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .and_then(|value| value.parse::<u16>().ok())
        .expect("status");
    (status, String::from_utf8_lossy(&raw[split..]).to_string())
}

async fn live_server(
    upstream: UpstreamTarget,
) -> (u16, oneshot::Sender<()>, tokio::task::JoinHandle<()>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind server");
    let port = listener.local_addr().expect("addr").port();
    let (tx, rx) = oneshot::channel();
    let state = AppState {
        admin: None,
        upstream,
    };
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

const STREAM_ID: &str = "01a08df4-64ee-7c14-9273-1306e41578bd";
const UNIT_ID: &str = "ru_0123456789abcdef01234567";
const PERSON_ID: &str = "01a08e83-d302-7d83-8d0b-6e163ee27737";
const ITEM_ID: &str = "psi_0123456789abcdef01234567";
const CATALOG: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

#[tokio::test]
async fn person_state_paths_map_to_the_python_v0_contract() {
    let (upstream, upstream_task) = mock_upstream().await;
    let (port, stop, server_task) = live_server(upstream).await;

    let people_base = format!("/api/v1/public/reading-streams/{STREAM_ID}/units/{UNIT_ID}/people");
    let states_base = format!("{people_base}/{PERSON_ID}/states");
    let cases = [
        (
            format!("{people_base}?catalog={CATALOG}&limit=6"),
            format!(
                "/v0/reading-streams/{STREAM_ID}/units/{UNIT_ID}/people?catalog={CATALOG}&limit=6"
            ),
        ),
        (
            format!("{states_base}?catalog={CATALOG}&section=identities"),
            format!(
                "/v0/reading-streams/{STREAM_ID}/units/{UNIT_ID}/people/{PERSON_ID}/states?catalog={CATALOG}&section=identities"
            ),
        ),
        (
            format!("{states_base}?catalog={CATALOG}&section=evidence&item_id={ITEM_ID}&limit=50"),
            format!(
                "/v0/reading-streams/{STREAM_ID}/units/{UNIT_ID}/people/{PERSON_ID}/states?catalog={CATALOG}&section=evidence&item_id={ITEM_ID}&limit=50"
            ),
        ),
    ];

    for (public_path, upstream_path) in cases {
        let (status, body) = request(port, "GET", &public_path).await;
        assert_eq!(status, 200, "path {public_path}: {body}");
        assert!(
            body.contains(&upstream_path),
            "path {public_path} forwarded body {body} missing {upstream_path}"
        );
    }

    let _ = stop.send(());
    server_task.await.expect("server join");
    upstream_task.abort();
}

#[tokio::test]
async fn person_state_routes_reject_non_get_with_typed_405() {
    let (upstream, upstream_task) = mock_upstream().await;
    let (port, stop, server_task) = live_server(upstream).await;

    let (status, body) = request(
        port,
        "POST",
        &format!(
            "/api/v1/public/reading-streams/{STREAM_ID}/units/{UNIT_ID}/people?catalog={CATALOG}"
        ),
    )
    .await;
    assert_eq!(status, 405);
    assert!(body.contains("method_not_allowed"), "{body}");

    let _ = stop.send(());
    server_task.await.expect("server join");
    upstream_task.abort();
}

#[tokio::test]
async fn person_state_upstream_outage_maps_to_typed_503() {
    // Bind then drop the listener so the port is closed, forcing a connect
    // failure from the proxy.
    let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind");
    let port = listener.local_addr().expect("addr").port();
    drop(listener);

    let (server_port, stop, server_task) = live_server(UpstreamTarget {
        host: "127.0.0.1".to_string(),
        port,
    })
    .await;

    let (status, body) = request(
        server_port,
        "GET",
        &format!(
            "/api/v1/public/reading-streams/{STREAM_ID}/units/{UNIT_ID}/people/{PERSON_ID}/states?catalog={CATALOG}&section=identities"
        ),
    )
    .await;
    assert_eq!(status, 503);
    assert!(body.contains("upstream_unavailable"), "{body}");

    let _ = stop.send(());
    server_task.await.expect("server join");
}
