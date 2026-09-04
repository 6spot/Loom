//! Single-administrator HTTP Basic authentication for Studio routes.
//!
//! Public routes never require credentials. Every privileged Studio route
//! requires a valid `Authorization: Basic` credential pair that matches the
//! environment-configured administrator. Comparison is constant-time over
//! both fields so valid usernames cannot be probed by timing.

use crate::config::AdminCredentials;

/// Decode one `Authorization` header value into `(username, password)`.
///
/// Returns `None` for missing, non-Basic, non-UTF8, or malformed credentials.
pub fn parse_basic_credentials(header_value: &str) -> Option<(String, String)> {
    let encoded = header_value.strip_prefix("Basic ")?;
    if encoded.contains(char::is_whitespace) {
        return None;
    }
    let decoded = base64_decode(encoded)?;
    let text = String::from_utf8(decoded).ok()?;
    let (username, password) = text.split_once(':')?;
    if username.is_empty() {
        return None;
    }
    Some((username.to_string(), password.to_string()))
}

/// Constant-time byte equality. Short-circuits nothing observable beyond
/// length-independent accumulation.
#[must_use]
pub fn constant_time_eq(left: &[u8], right: &[u8]) -> bool {
    if left.len() != right.len() {
        return false;
    }
    let mut diff: u8 = 0;
    for (a, b) in left.iter().zip(right.iter()) {
        diff |= a ^ b;
    }
    diff == 0
}

/// Check presented credentials against the configured administrator.
///
/// Both fields are always compared (no short-circuit) so a wrong username
/// takes the same observable path as a wrong password.
#[must_use]
pub fn credentials_match(admin: &AdminCredentials, username: &str, password: &str) -> bool {
    let user_ok = constant_time_eq(admin.username.as_bytes(), username.as_bytes());
    let pass_ok = constant_time_eq(admin.password.as_bytes(), password.as_bytes());
    user_ok & pass_ok
}

fn base64_decode(input: &str) -> Option<Vec<u8>> {
    // Minimal RFC 4648 decoder without padding surprises: strict alphabet,
    // padding only at the end, output length derived from quantum count.
    // Dependency-free so the auth boundary stays auditable.
    if input.is_empty() || !input.len().is_multiple_of(4) {
        return None;
    }
    let data = match input.strip_suffix("==") {
        Some(prefix) => prefix,
        None => match input.strip_suffix('=') {
            Some(prefix) => prefix,
            None => input,
        },
    };
    if data.contains('=') {
        return None;
    }
    let mut sextets = Vec::with_capacity(data.len());
    for byte in data.bytes() {
        let sextet = match byte {
            b'A'..=b'Z' => byte - b'A',
            b'a'..=b'z' => byte - b'a' + 26,
            b'0'..=b'9' => byte - b'0' + 52,
            b'+' => 62,
            b'/' => 63,
            _ => return None,
        };
        sextets.push(sextet);
    }
    if sextets.len() % 4 == 1 {
        return None;
    }
    let mut out = Vec::with_capacity(sextets.len() * 3 / 4 + 3);
    for quantum in sextets.chunks(4) {
        let mut iter = quantum.iter().copied().chain(std::iter::repeat(0));
        let a = iter.next().unwrap_or(0) as u32;
        let b = iter.next().unwrap_or(0) as u32;
        let c = iter.next().unwrap_or(0) as u32;
        let d = iter.next().unwrap_or(0) as u32;
        let triple = (a << 18) | (b << 12) | (c << 6) | d;
        out.push(((triple >> 16) & 0xFF) as u8);
        out.push(((triple >> 8) & 0xFF) as u8);
        out.push((triple & 0xFF) as u8);
    }
    // Padding was already stripped from `data`, so the expected length comes
    // from full quanta (3 bytes each) plus the trailing partial quantum
    // (2 chars -> 1 byte, 3 chars -> 2 bytes). A 1-char tail is invalid.
    let expected = data.len() / 4 * 3
        + match data.len() % 4 {
            0 => 0,
            2 => 1,
            3 => 2,
            _ => return None,
        };
    out.truncate(expected);
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_valid_basic_header() {
        // "admin:long-password" in base64.
        let (user, pass) =
            parse_basic_credentials("Basic YWRtaW46bG9uZy1wYXNzd29yZA==").expect("parses");
        assert_eq!(user, "admin");
        assert_eq!(pass, "long-password");
    }

    #[test]
    fn rejects_malformed_headers() {
        assert!(parse_basic_credentials("Bearer token").is_none());
        assert!(parse_basic_credentials("Basic !!!not-base64!!!").is_none());
        assert!(parse_basic_credentials("Basic").is_none());
        // Empty username (" :pass").
        assert!(parse_basic_credentials("Basic OmJhcw==").is_none());
        // No colon at all.
        assert!(parse_basic_credentials("Basic bm9jb2xvbg==").is_none());
    }

    #[test]
    fn matching_is_exact_and_constant_time_shape() {
        let admin = AdminCredentials {
            username: "admin".to_string(),
            password: "long-password".to_string(),
        };
        assert!(credentials_match(&admin, "admin", "long-password"));
        assert!(!credentials_match(&admin, "admin", "long-passwore"));
        assert!(!credentials_match(&admin, "admin", "long-password2"));
        assert!(!credentials_match(&admin, "other", "long-password"));
        assert!(constant_time_eq(b"abc", b"abc"));
        assert!(!constant_time_eq(b"abc", b"abd"));
        assert!(!constant_time_eq(b"abc", b"abcd"));
    }
}
