//! Same-origin web front, embedded at compile time.
//!
//! The zero-build browser UI from `apps/chronicle/web/` is served from this
//! binary so the Chronicle deployment path is one origin. Assets are
//! allowlisted explicitly (mirroring C0 `web_static.py`); request paths are
//! never joined to the filesystem, so traversal cannot escape the web root.

/// One servable static asset.
#[derive(Debug, Clone, Copy)]
pub struct Asset {
    /// URL path.
    pub path: &'static str,
    /// Response content type.
    pub content_type: &'static str,
    /// File bytes embedded at compile time.
    pub body: &'static [u8],
}

macro_rules! asset {
    ($path:literal, $content_type:literal, $file:literal) => {
        Asset {
            path: $path,
            content_type: $content_type,
            body: include_bytes!(concat!("../../web/", $file)),
        }
    };
}

/// Allowlisted UI assets (same set as C0 `web_static.py`).
pub static ASSETS: &[Asset] = &[
    asset!("/styles.css", "text/css; charset=utf-8", "styles.css"),
    asset!("/search.css", "text/css; charset=utf-8", "search.css"),
    asset!("/app.mjs", "text/javascript; charset=utf-8", "app.mjs"),
    asset!("/ui.mjs", "text/javascript; charset=utf-8", "ui.mjs"),
    asset!(
        "/search_ui.mjs",
        "text/javascript; charset=utf-8",
        "search_ui.mjs"
    ),
    asset!(
        "/route_safe.mjs",
        "text/javascript; charset=utf-8",
        "route_safe.mjs"
    ),
];

/// Embedded SPA shell.
pub static INDEX_HTML: &[u8] = include_bytes!("../../web/index.html");

/// Decide how to serve one browser path.
///
/// Returns `Some(asset-or-shell)` for explicit assets and SPA navigation
/// routes, `None` for everything else (API/health routes are handled
/// elsewhere and must not fall through to the shell).
pub fn resolve_web_path(path: &str) -> Option<(&'static str, &'static [u8])> {
    if let Some(asset) = ASSETS.iter().find(|asset| asset.path == path) {
        return Some((asset.content_type, asset.body));
    }
    if is_spa_path(path) {
        return Some(("text/html; charset=utf-8", INDEX_HTML));
    }
    None
}

fn is_spa_path(path: &str) -> bool {
    if path == "/" || path == "/timeline" || path == "/timeline/" {
        return true;
    }
    if path == "/search" || path == "/search/" {
        return true;
    }
    for prefix in ["/events/", "/entities/"] {
        if let Some(rest) = path.strip_prefix(prefix) {
            let id = rest.strip_suffix('/').unwrap_or(rest);
            if !id.is_empty() && !id.contains('/') {
                return true;
            }
        }
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn assets_resolve_with_content_types() {
        let (content_type, body) = resolve_web_path("/app.mjs").expect("asset");
        assert_eq!(content_type, "text/javascript; charset=utf-8");
        assert!(!body.is_empty());
        let (css_type, _) = resolve_web_path("/styles.css").expect("css");
        assert_eq!(css_type, "text/css; charset=utf-8");
    }

    #[test]
    fn spa_paths_resolve_to_shell() {
        for path in [
            "/",
            "/timeline",
            "/timeline/",
            "/search",
            "/events/some-id",
            "/events/some-id/",
            "/entities/some-id",
        ] {
            let (content_type, body) = resolve_web_path(path).expect(path);
            assert_eq!(content_type, "text/html; charset=utf-8");
            assert!(!body.is_empty(), "{path}");
        }
    }

    #[test]
    fn non_web_paths_do_not_resolve() {
        for path in [
            "/api/v1/public/timeline",
            "/v0/timeline",
            "/healthz",
            "/events/a/b",
            "/entities/",
            "/etc/passwd",
            "/../web/index.html",
            "/app.mjs.map",
        ] {
            assert!(resolve_web_path(path).is_none(), "{path}");
        }
    }

    #[test]
    fn shell_mentions_chronicle() {
        assert!(String::from_utf8_lossy(INDEX_HTML).contains("Chronicle"));
    }
}
