//! Startup configuration from environment variables.
//!
//! Secrets (`CHRONICLE_ADMIN_PASSWORD`) are held in memory only for request
//! authentication. They are never logged, never persisted, and never echoed
//! back in responses. [`ChronicleConfig::describe`] exposes only non-secret
//! fields for startup logging.

use std::collections::HashMap;
use std::fmt;
use std::net::IpAddr;

use crate::upstream::UpstreamTarget;

/// Minimum accepted administrator password length (characters).
pub const MIN_ADMIN_PASSWORD_LEN: usize = 8;

/// Error describing why startup configuration is invalid.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConfigError(pub String);

impl fmt::Display for ConfigError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "invalid Chronicle configuration: {}", self.0)
    }
}

impl std::error::Error for ConfigError {}

/// Validated Chronicle server configuration.
#[derive(Debug, Clone)]
pub struct ChronicleConfig {
    /// Interface to bind (default `127.0.0.1`).
    pub bind: IpAddr,
    /// TCP port to bind (default `8080`).
    pub port: u16,
    /// C0 Python read-model upstream that serves historical reads.
    pub upstream: UpstreamTarget,
    /// Single administrator credentials, when Studio auth is configured.
    pub admin: Option<AdminCredentials>,
}

/// Single-administrator credentials from the environment.
#[derive(Debug, Clone)]
pub struct AdminCredentials {
    /// Administrator login name (ASCII, no `:` or whitespace).
    pub username: String,
    /// Administrator password (held in memory only).
    pub password: String,
}

impl ChronicleConfig {
    /// Read configuration from the process environment.
    pub fn from_env() -> Result<Self, ConfigError> {
        let vars: HashMap<String, String> = std::env::vars().collect();
        Self::from_map(&vars)
    }

    /// Read configuration from an explicit variable map (used by tests).
    pub fn from_map(vars: &HashMap<String, String>) -> Result<Self, ConfigError> {
        let get = |name: &str| -> Option<String> {
            vars.get(name).and_then(|value| {
                let trimmed = value.trim();
                if trimmed.is_empty() {
                    None
                } else {
                    Some(trimmed.to_string())
                }
            })
        };

        let bind: IpAddr = match get("CHRONICLE_BIND") {
            None => "127.0.0.1".parse().expect("loopback parses"),
            Some(raw) => raw.parse().map_err(|_| {
                ConfigError(format!("CHRONICLE_BIND is not an IP address: {raw:?}"))
            })?,
        };

        // The raw value is never echoed: error text reaches stderr and a
        // misplaced secret must not be reflected back into logs.
        let port: u16 = match get("CHRONICLE_PORT") {
            None => 8080,
            Some(raw) => raw.parse().map_err(|_| {
                let _ = raw;
                ConfigError("CHRONICLE_PORT is not a TCP port (1-65535)".to_string())
            })?,
        };
        if port == 0 {
            return Err(ConfigError(
                "CHRONICLE_PORT is not a TCP port (1-65535): \"0\"".to_string(),
            ));
        }

        let upstream_raw =
            get("CHRONICLE_UPSTREAM_URL").unwrap_or_else(|| "http://127.0.0.1:8081".to_string());
        // The raw URL is never echoed: it may embed userinfo credentials, and
        // this error is printed to stderr at startup. `UpstreamTarget::parse`
        // reasons never include the input for the same reason.
        let upstream = UpstreamTarget::parse(&upstream_raw)
            .map_err(|detail| ConfigError(format!("CHRONICLE_UPSTREAM_URL invalid: {detail}")))?;

        let admin_user = get("CHRONICLE_ADMIN_USER");
        let admin_password = get("CHRONICLE_ADMIN_PASSWORD");
        let admin = match (admin_user, admin_password) {
            (None, None) => None,
            (Some(_), None) | (None, Some(_)) => {
                return Err(ConfigError(
                    "CHRONICLE_ADMIN_USER and CHRONICLE_ADMIN_PASSWORD must be set together \
                     (Studio auth stays disabled only when both are absent)"
                        .to_string(),
                ));
            }
            (Some(username), Some(password)) => {
                validate_username(&username)?;
                validate_password(&password)?;
                Some(AdminCredentials { username, password })
            }
        };

        Ok(Self {
            bind,
            port,
            upstream,
            admin,
        })
    }

    /// Whether Studio authentication is configured.
    #[must_use]
    pub fn studio_auth_enabled(&self) -> bool {
        self.admin.is_some()
    }

    /// Non-secret startup description for logging.
    #[must_use]
    pub fn describe(&self) -> serde_json::Value {
        serde_json::json!({
            "service": "chronicle-server",
            "bind": self.bind.to_string(),
            "port": self.port,
            "upstream_host": self.upstream.host,
            "upstream_port": self.upstream.port,
            "studio_auth": if self.studio_auth_enabled() { "enabled" } else { "disabled" },
        })
    }
}

fn validate_username(username: &str) -> Result<(), ConfigError> {
    if !username.is_ascii() {
        return Err(ConfigError(
            "CHRONICLE_ADMIN_USER must be ASCII".to_string(),
        ));
    }
    if username.contains([':', ' ', '\t', '\n', '\r']) || username.contains(char::is_control) {
        return Err(ConfigError(
            "CHRONICLE_ADMIN_USER must not contain ':', whitespace, or control characters"
                .to_string(),
        ));
    }
    Ok(())
}

fn validate_password(password: &str) -> Result<(), ConfigError> {
    if password.chars().count() < MIN_ADMIN_PASSWORD_LEN {
        return Err(ConfigError(format!(
            "CHRONICLE_ADMIN_PASSWORD must be at least {MIN_ADMIN_PASSWORD_LEN} characters"
        )));
    }
    if password.contains(char::is_control) {
        return Err(ConfigError(
            "CHRONICLE_ADMIN_PASSWORD must not contain control characters".to_string(),
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn vars(pairs: &[(&str, &str)]) -> HashMap<String, String> {
        pairs
            .iter()
            .map(|(key, value)| ((*key).to_string(), (*value).to_string()))
            .collect()
    }

    #[test]
    fn defaults_bind_loopback_and_disable_studio() {
        let config = ChronicleConfig::from_map(&vars(&[])).expect("defaults parse");
        assert_eq!(config.bind.to_string(), "127.0.0.1");
        assert_eq!(config.port, 8080);
        assert_eq!(config.upstream.host, "127.0.0.1");
        assert_eq!(config.upstream.port, 8081);
        assert!(!config.studio_auth_enabled());
    }

    #[test]
    fn admin_requires_both_user_and_password() {
        let only_user = ChronicleConfig::from_map(&vars(&[("CHRONICLE_ADMIN_USER", "admin")]));
        assert!(only_user.is_err());
        let only_password =
            ChronicleConfig::from_map(&vars(&[("CHRONICLE_ADMIN_PASSWORD", "long-password")]));
        assert!(only_password.is_err());
    }

    #[test]
    fn short_password_is_rejected() {
        let result = ChronicleConfig::from_map(&vars(&[
            ("CHRONICLE_ADMIN_USER", "admin"),
            ("CHRONICLE_ADMIN_PASSWORD", "short"),
        ]));
        assert!(result.is_err());
    }

    #[test]
    fn username_with_colon_is_rejected() {
        let result = ChronicleConfig::from_map(&vars(&[
            ("CHRONICLE_ADMIN_USER", "ad:min"),
            ("CHRONICLE_ADMIN_PASSWORD", "long-password"),
        ]));
        assert!(result.is_err());
    }

    #[test]
    fn bad_port_and_bind_are_rejected() {
        assert!(ChronicleConfig::from_map(&vars(&[("CHRONICLE_PORT", "0")])).is_err());
        assert!(ChronicleConfig::from_map(&vars(&[("CHRONICLE_PORT", "http")])).is_err());
        assert!(ChronicleConfig::from_map(&vars(&[("CHRONICLE_BIND", "not-an-ip")])).is_err());
    }

    #[test]
    fn describe_never_contains_secrets() {
        let config = ChronicleConfig::from_map(&vars(&[
            ("CHRONICLE_ADMIN_USER", "admin"),
            ("CHRONICLE_ADMIN_PASSWORD", "super-secret-password"),
        ]))
        .expect("valid config");
        let rendered = config.describe().to_string();
        assert!(!rendered.contains("super-secret-password"));
        assert!(!rendered.contains("admin"));
    }

    #[test]
    fn invalid_upstream_url_never_echoes_input() {
        // Regression test: this ConfigError is printed to stderr at startup,
        // so even a URL with embedded userinfo must not round-trip into it.
        for raw in [
            "http://ci-user:ci-secret-password@upstream:8081",
            "https://anything.example/x",
            "http://upstream:not-a-port",
            "not-a-url",
        ] {
            let error = ChronicleConfig::from_map(&vars(&[("CHRONICLE_UPSTREAM_URL", raw)]))
                .expect_err("invalid upstream URL is rejected");
            let rendered = error.to_string();
            assert!(
                !rendered.contains(raw),
                "config error echoes input for {raw:?}: {rendered:?}"
            );
            assert!(
                !rendered.contains("ci-secret-password"),
                "config error leaks password: {rendered:?}"
            );
            assert!(
                !rendered.contains("ci-user"),
                "config error leaks username: {rendered:?}"
            );
        }
    }

    #[test]
    fn invalid_port_never_echoes_input() {
        let error = ChronicleConfig::from_map(&vars(&[("CHRONICLE_PORT", "sup3r-s3cret")]))
            .expect_err("invalid port is rejected");
        let rendered = error.to_string();
        assert!(
            !rendered.contains("sup3r-s3cret"),
            "config error echoes input: {rendered:?}"
        );
    }
}
