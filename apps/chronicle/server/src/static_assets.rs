//! Same-origin web front, embedded at compile time.
//!
//! The C1 React/TypeScript/Vite build from `apps/chronicle/webapp/` (built
//! output committed under `apps/chronicle/web/dist/` with deterministic asset
//! names) is served from this binary so the Chronicle deployment path stays
//! one origin: one build serves public Chronicle routes and `/studio/*`.
//! The C0 zero-build assets (`/app.mjs`, `/ui.mjs`, ...) remain allowlisted
//! for compatibility. Request paths are never joined to the filesystem, so
//! traversal cannot escape the web root.

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

/// Allowlisted UI assets (C0 set from `web_static.py`, plus the C1 Vite build
/// output with deterministic filenames from `webapp/vite.config.ts`).
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
    asset!(
        "/assets/index.js",
        "text/javascript; charset=utf-8",
        "dist/assets/index.js"
    ),
    asset!(
        "/assets/index.css",
        "text/css; charset=utf-8",
        "dist/assets/index.css"
    ),
    asset!(
        "/assets/StudioLayout.js",
        "text/javascript; charset=utf-8",
        "dist/assets/StudioLayout.js"
    ),
    asset!(
        "/assets/StudioHomePage.js",
        "text/javascript; charset=utf-8",
        "dist/assets/StudioHomePage.js"
    ),
    asset!(
        "/assets/StudioLoginPage.js",
        "text/javascript; charset=utf-8",
        "dist/assets/StudioLoginPage.js"
    ),
    asset!(
        "/assets/StudioImportsPage.js",
        "text/javascript; charset=utf-8",
        "dist/assets/StudioImportsPage.js"
    ),
    asset!(
        "/assets/StudioImportDetailPage.js",
        "text/javascript; charset=utf-8",
        "dist/assets/StudioImportDetailPage.js"
    ),
    asset!(
        "/assets/StudioReviewPage.js",
        "text/javascript; charset=utf-8",
        "dist/assets/StudioReviewPage.js"
    ),
    asset!(
        "/assets/StudioReviewDetailPage.js",
        "text/javascript; charset=utf-8",
        "dist/assets/StudioReviewDetailPage.js"
    ),
    asset!(
        "/assets/StudioSourcesPage.js",
        "text/javascript; charset=utf-8",
        "dist/assets/StudioSourcesPage.js"
    ),
    asset!(
        "/assets/studio-api.js",
        "text/javascript; charset=utf-8",
        "dist/assets/studio-api.js"
    ),
    asset!(
        "/assets/useMutation.js",
        "text/javascript; charset=utf-8",
        "dist/assets/useMutation.js"
    ),
    asset!(
        "/assets/input.js",
        "text/javascript; charset=utf-8",
        "dist/assets/input.js"
    ),
    asset!(
        "/assets/button.js",
        "text/javascript; charset=utf-8",
        "dist/assets/button.js"
    ),
    asset!(
        "/assets/card.js",
        "text/javascript; charset=utf-8",
        "dist/assets/card.js"
    ),
    asset!(
        "/assets/badge.js",
        "text/javascript; charset=utf-8",
        "dist/assets/badge.js"
    ),
    asset!(
        "/assets/cn.js",
        "text/javascript; charset=utf-8",
        "dist/assets/cn.js"
    ),
];

/// Embedded SPA shell: the current React build (public + Studio routes).
pub static INDEX_HTML: &[u8] = include_bytes!("../../web/dist/index.html");

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

fn is_single_segment(rest: &str) -> bool {
    let id = rest.strip_suffix('/').unwrap_or(rest);
    !id.is_empty() && !id.contains('/')
}

fn is_spa_path(path: &str) -> bool {
    if path == "/" || path == "/timeline" || path == "/timeline/" {
        return true;
    }
    if path == "/search" || path == "/search/" {
        return true;
    }
    // The Studio shell itself is public because it carries no privileged
    // data; every Studio API is authenticated server-side. Nested detail
    // routes are still shell-only navigation and never bypass API auth.
    if path == "/studio" || path == "/studio/" {
        return true;
    }
    if let Some(rest) = path.strip_prefix("/studio/imports/") {
        return is_single_segment(rest);
    }
    if let Some(rest) = path.strip_prefix("/studio/review/") {
        return is_single_segment(rest);
    }
    if let Some(rest) = path.strip_prefix("/studio/") {
        let id = rest.strip_suffix('/').unwrap_or(rest);
        if !id.is_empty()
            && !id.contains('/')
            && matches!(id, "login" | "imports" | "review" | "sources")
        {
            return true;
        }
        return false;
    }
    for prefix in ["/events/", "/entities/"] {
        if let Some(rest) = path.strip_prefix(prefix) {
            return is_single_segment(rest);
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
            "/studio",
            "/studio/",
            "/studio/login",
            "/studio/imports",
            "/studio/imports/019-example-job",
            "/studio/imports/019-example-job/",
            "/studio/review",
            "/studio/review/019-example-review",
            "/studio/review/019-example-review/",
            "/studio/sources",
        ] {
            let (content_type, body) = resolve_web_path(path).expect(path);
            assert_eq!(content_type, "text/html; charset=utf-8");
            assert!(!body.is_empty(), "{path}");
        }
    }

    #[test]
    fn react_build_assets_resolve() {
        for path in [
            "/assets/index.js",
            "/assets/index.css",
            "/assets/StudioLayout.js",
            "/assets/StudioHomePage.js",
            "/assets/StudioImportsPage.js",
            "/assets/StudioImportDetailPage.js",
            "/assets/StudioReviewPage.js",
            "/assets/StudioReviewDetailPage.js",
            "/assets/StudioSourcesPage.js",
            "/assets/studio-api.js",
            "/assets/useMutation.js",
            "/assets/input.js",
        ] {
            assert!(resolve_web_path(path).is_some(), "{path}");
        }
    }

    #[test]
    fn studio_nested_or_unknown_paths_do_not_resolve() {
        for path in [
            "/studio/imports/job/extra",
            "/studio/review/item/extra",
            "/studio/unknown",
            "/studio/../api/v1/studio/status",
        ] {
            assert!(resolve_web_path(path).is_none(), "{path}");
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
