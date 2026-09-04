//! C0 Python read-model upstream addressing and minimal HTTP/1.0 forwarding.
//!
//! The Rust server never opens the Chronicle database itself (governance:
//! no SQLx/PostgreSQL driver outside `loom-storage`, no inline SQL). Public
//! historical reads are forwarded to the proven C0 Python read server, which
//! remains the single historical read authority during the C1 migration.

use std::fmt;
use std::time::Duration;

use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;
use tokio::time::timeout;

/// Default upstream port when the URL carries no explicit port.
pub const DEFAULT_HTTP_PORT: u16 = 80;

/// How long to wait for the upstream TCP connect.
pub const CONNECT_TIMEOUT: Duration = Duration::from_secs(5);

/// How long to wait for the complete upstream response.
pub const RESPONSE_TIMEOUT: Duration = Duration::from_secs(15);

/// Maximum upstream response head (status line + headers).
pub const MAX_HEAD_BYTES: usize = 32 * 1024;

/// Maximum upstream response body accepted for proxying.
pub const MAX_BODY_BYTES: usize = 8 * 1024 * 1024;

/// Maximum proxied request body accepted from Studio clients.
///
/// The Python sidecar enforces the real per-file upload ceiling
/// (`CHRONICLE_MAX_UPLOAD_BYTES`, default 10 MiB); this bound only keeps a
/// malicious client from exhausting proxy memory, so it sits above that
/// ceiling plus JSON framing overhead.
pub const MAX_PROXY_BODY_BYTES: usize = 12 * 1024 * 1024;

/// Parsed `http://host[:port]` upstream target. HTTPS and embedded userinfo
/// are rejected so credentials can never leak into logs or proxied requests.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UpstreamTarget {
    /// DNS name or IP literal (no credentials, no port).
    pub host: String,
    /// TCP port.
    pub port: u16,
}

impl UpstreamTarget {
    /// Parse an upstream URL of the form `http://host[:port][/...]`.
    pub fn parse(raw: &str) -> Result<Self, String> {
        let rest = raw
            .strip_prefix("http://")
            .ok_or_else(|| "only plain http:// upstreams are supported".to_string())?;
        if rest.contains('@') {
            return Err("upstream URL must not embed userinfo/credentials".to_string());
        }
        let authority = rest.split('/').next().unwrap_or("");
        if authority.is_empty() {
            return Err("upstream URL has no host".to_string());
        }
        if let Some((host, port_raw)) = authority.rsplit_once(':') {
            if host.is_empty() {
                return Err("upstream URL has no host".to_string());
            }
            // An IPv6 literal contains more than one ':'; a single trailing
            // segment is a port only when it parses as u16.
            if host.contains(':') && port_raw.parse::<u16>().is_err() {
                return Err("IPv6 upstream literals are not supported".to_string());
            }
            // The raw port text is never echoed: error text can reach logs and
            // a misplaced secret must not be reflected back.
            let port: u16 = port_raw
                .parse()
                .map_err(|_| "upstream port is not 1-65535".to_string())?;
            if port == 0 {
                return Err("upstream port is not 1-65535".to_string());
            }
            Ok(Self {
                host: host.to_string(),
                port,
            })
        } else {
            Ok(Self {
                host: authority.to_string(),
                port: DEFAULT_HTTP_PORT,
            })
        }
    }

    /// `host:port` dial string.
    #[must_use]
    pub fn dial(&self) -> String {
        format!("{}:{}", self.host, self.port)
    }
}

/// Upstream failure classification for typed error mapping.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum UpstreamError {
    /// TCP connect failed or timed out.
    Unreachable(String),
    /// Response incomplete, unparseable, or over limits.
    BadResponse(String),
    /// Complete response took too long.
    TimedOut,
}

impl fmt::Display for UpstreamError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Unreachable(detail) => write!(f, "upstream unreachable: {detail}"),
            Self::BadResponse(detail) => write!(f, "upstream bad response: {detail}"),
            Self::TimedOut => write!(f, "upstream response timed out"),
        }
    }
}

impl std::error::Error for UpstreamError {}

/// Forwarded upstream response.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UpstreamResponse {
    /// HTTP status code (100-599).
    pub status: u16,
    /// Response content type, if the upstream supplied one.
    pub content_type: Option<String>,
    /// Raw response body bytes.
    pub body: Vec<u8>,
}

/// Forward one `GET` request to the upstream and return its response.
///
/// Only the path+query portion is forwarded; the caller maps public and
/// legacy routes onto equivalent C0 `/v0/*` paths before calling.
pub async fn fetch_upstream(
    target: &UpstreamTarget,
    path_and_query: &str,
) -> Result<UpstreamResponse, UpstreamError> {
    if !path_and_query.starts_with('/') {
        return Err(UpstreamError::BadResponse(
            "forwarded path must start with '/'".to_string(),
        ));
    }
    if path_and_query.contains(['\r', '\n']) {
        return Err(UpstreamError::BadResponse(
            "forwarded path must not contain CR/LF".to_string(),
        ));
    }

    let request = format!(
        "GET {path_and_query} HTTP/1.0\r\nHost: {}\r\nConnection: close\r\n\r\n",
        target.host
    );
    let work = async {
        let mut stream = TcpStream::connect(target.dial())
            .await
            .map_err(|err| UpstreamError::Unreachable(err.to_string()))?;
        stream
            .write_all(request.as_bytes())
            .await
            .map_err(|err| UpstreamError::Unreachable(err.to_string()))?;
        read_response(&mut stream).await
    };
    timeout(RESPONSE_TIMEOUT, work)
        .await
        .map_err(|_| UpstreamError::TimedOut)?
}

async fn read_response(stream: &mut TcpStream) -> Result<UpstreamResponse, UpstreamError> {
    let mut buffer = Vec::with_capacity(8 * 1024);
    let mut chunk = [0_u8; 4096];
    let head_end = loop {
        let read = stream
            .read(&mut chunk)
            .await
            .map_err(|err| UpstreamError::BadResponse(err.to_string()))?;
        if read == 0 {
            break None;
        }
        buffer.extend_from_slice(&chunk[..read]);
        if buffer.len() > MAX_HEAD_BYTES + MAX_BODY_BYTES {
            return Err(UpstreamError::BadResponse(
                "response exceeds size limit".to_string(),
            ));
        }
        if let Some(index) = find_head_end(&buffer) {
            break Some(index);
        }
        if buffer.len() > MAX_HEAD_BYTES {
            return Err(UpstreamError::BadResponse(
                "response head exceeds limit".to_string(),
            ));
        }
    };
    let head_end =
        head_end.ok_or_else(|| UpstreamError::BadResponse("empty response".to_string()))?;
    let head = std::str::from_utf8(&buffer[..head_end])
        .map_err(|_| UpstreamError::BadResponse("response head is not ASCII".to_string()))?;
    let (status, content_type, content_length) = parse_head(head)?;
    let mut body = buffer[head_end..].to_vec();
    if let Some(expected) = content_length {
        while body.len() < expected {
            if body.len() > MAX_BODY_BYTES {
                return Err(UpstreamError::BadResponse(
                    "body exceeds size limit".to_string(),
                ));
            }
            let read = stream
                .read(&mut chunk)
                .await
                .map_err(|err| UpstreamError::BadResponse(err.to_string()))?;
            if read == 0 {
                break;
            }
            body.extend_from_slice(&chunk[..read]);
        }
        if body.len() < expected {
            return Err(UpstreamError::BadResponse(
                "upstream closed connection mid-body".to_string(),
            ));
        }
        body.truncate(expected);
    } else {
        // No Content-Length: drain until close (HTTP/1.0 default).
        loop {
            if body.len() > MAX_BODY_BYTES {
                return Err(UpstreamError::BadResponse(
                    "body exceeds size limit".to_string(),
                ));
            }
            let read = stream
                .read(&mut chunk)
                .await
                .map_err(|err| UpstreamError::BadResponse(err.to_string()))?;
            if read == 0 {
                break;
            }
            body.extend_from_slice(&chunk[..read]);
        }
    }
    Ok(UpstreamResponse {
        status,
        content_type,
        body,
    })
}

fn find_head_end(buffer: &[u8]) -> Option<usize> {
    buffer
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .map(|index| index + 4)
}

fn parse_head(head: &str) -> Result<(u16, Option<String>, Option<usize>), UpstreamError> {
    let mut lines = head.split("\r\n");
    let status_line = lines
        .next()
        .ok_or_else(|| UpstreamError::BadResponse("missing status line".to_string()))?;
    let status: u16 = status_line
        .split_whitespace()
        .nth(1)
        .and_then(|code| code.parse().ok())
        .filter(|code| (100..600).contains(code))
        .ok_or_else(|| UpstreamError::BadResponse("invalid status line".to_string()))?;
    let mut content_type = None;
    let mut content_length = None;
    for line in lines {
        if line.is_empty() {
            continue;
        }
        let (name, value) = line
            .split_once(':')
            .ok_or_else(|| UpstreamError::BadResponse("invalid header line".to_string()))?;
        match name.trim().to_ascii_lowercase().as_str() {
            "content-type" => content_type = Some(value.trim().to_string()),
            "content-length" => {
                let length: usize = value.trim().parse().map_err(|_| {
                    UpstreamError::BadResponse("invalid content-length".to_string())
                })?;
                if length > MAX_BODY_BYTES {
                    return Err(UpstreamError::BadResponse(
                        "body exceeds size limit".to_string(),
                    ));
                }
                content_length = Some(length);
            }
            _ => {}
        }
    }
    Ok((status, content_type, content_length))
}

/// Cheap TCP reachability probe for Studio status reporting.
pub async fn probe_upstream(target: &UpstreamTarget) -> bool {
    timeout(CONNECT_TIMEOUT, TcpStream::connect(target.dial()))
        .await
        .is_ok_and(|result| result.is_ok())
}

/// Forward one Studio request (method + body) to the upstream.
///
/// The Rust server owns auth and routing but never touches the Chronicle
/// database itself (governance: no SQLx/PostgreSQL driver outside
/// `loom-storage`, no inline SQL). Authenticated Studio document
/// operations are forwarded byte-for-byte to the internal Python sidecar,
/// which owns the application persistence behind `CHRONICLE_DATABASE_URL`.
pub async fn forward_upstream(
    target: &UpstreamTarget,
    method: &str,
    path_and_query: &str,
    content_type: Option<&str>,
    body: &[u8],
) -> Result<UpstreamResponse, UpstreamError> {
    if method.is_empty()
        || !method
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
    {
        return Err(UpstreamError::BadResponse(
            "forwarded method is not a valid token".to_string(),
        ));
    }
    if !path_and_query.starts_with('/') {
        return Err(UpstreamError::BadResponse(
            "forwarded path must start with '/'".to_string(),
        ));
    }
    if path_and_query.contains(['\r', '\n']) {
        return Err(UpstreamError::BadResponse(
            "forwarded path must not contain CR/LF".to_string(),
        ));
    }
    let content_type_valid = content_type.is_none_or(|value: &str| {
        !value.contains(['\r', '\n'])
            && value
                .bytes()
                .all(|byte| byte.is_ascii_graphic() || byte == b' ')
    });
    if !content_type_valid {
        return Err(UpstreamError::BadResponse(
            "forwarded content type is not a valid header value".to_string(),
        ));
    }
    if body.len() > MAX_PROXY_BODY_BYTES {
        return Err(UpstreamError::BadResponse(
            "proxied body exceeds size limit".to_string(),
        ));
    }

    let mut request = format!(
        "{method} {path_and_query} HTTP/1.0\r\nHost: {}\r\nConnection: close\r\n",
        target.host
    );
    if let Some(content_type) = content_type {
        request.push_str(&format!("Content-Type: {content_type}\r\n"));
    }
    request.push_str(&format!("Content-Length: {}\r\n\r\n", body.len()));
    let owned_body = body.to_vec();
    let work = async {
        let mut stream = TcpStream::connect(target.dial())
            .await
            .map_err(|err| UpstreamError::Unreachable(err.to_string()))?;
        stream
            .write_all(request.as_bytes())
            .await
            .map_err(|err| UpstreamError::Unreachable(err.to_string()))?;
        if !owned_body.is_empty() {
            stream
                .write_all(&owned_body)
                .await
                .map_err(|err| UpstreamError::Unreachable(err.to_string()))?;
        }
        read_response(&mut stream).await
    };
    timeout(RESPONSE_TIMEOUT, work)
        .await
        .map_err(|_| UpstreamError::TimedOut)?
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::io::AsyncWriteExt;
    use tokio::net::TcpListener;

    #[test]
    fn parse_accepts_host_and_optional_port() {
        let target = UpstreamTarget::parse("http://127.0.0.1:8081").expect("parses");
        assert_eq!(target.host, "127.0.0.1");
        assert_eq!(target.port, 8081);
        let defaulted = UpstreamTarget::parse("http://read-model").expect("parses");
        assert_eq!(defaulted.port, DEFAULT_HTTP_PORT);
    }

    #[test]
    fn parse_rejects_https_userinfo_and_empty_host() {
        assert!(UpstreamTarget::parse("https://127.0.0.1:8081").is_err());
        assert!(UpstreamTarget::parse("http://user:pass@host:8081/x").is_err());
        assert!(UpstreamTarget::parse("http:///path").is_err());
        assert!(UpstreamTarget::parse("http://host:0").is_err());
    }

    #[tokio::test]
    async fn fetch_returns_status_and_body() {
        let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind");
        let addr = listener.local_addr().expect("addr");
        tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.expect("accept");
            let mut head = [0_u8; 1024];
            let _ = socket.read(&mut head).await;
            let body = br#"{"status":"ok"}"#;
            let response = format!(
                "HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n",
                body.len()
            );
            socket.write_all(response.as_bytes()).await.expect("head");
            socket.write_all(body).await.expect("body");
        });
        let target = UpstreamTarget {
            host: "127.0.0.1".to_string(),
            port: addr.port(),
        };
        let response = fetch_upstream(&target, "/v0/timeline?limit=1")
            .await
            .expect("fetch");
        assert_eq!(response.status, 200);
        assert_eq!(response.body, br#"{"status":"ok"}"#);
        assert_eq!(response.content_type.as_deref(), Some("application/json"));
    }

    #[tokio::test]
    async fn fetch_unreachable_maps_to_unreachable() {
        let target = UpstreamTarget {
            host: "127.0.0.1".to_string(),
            port: 1,
        };
        let error = fetch_upstream(&target, "/v0/timeline")
            .await
            .expect_err("fails");
        assert!(matches!(error, UpstreamError::Unreachable(_)));
    }
}
