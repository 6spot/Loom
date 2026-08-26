//! Query/History/Catalog suite scaffold (T14).
//!
//! Owner: T14 (#319) — `CV-025..CV-027`.
//! Central registry integration is reserved for T19 (#324). This module must
//! not register scenarios in `validator_registry`; T19 alone edits
//! `registry.rs`/`lib.rs` and CLI dispatch. No `CV-012..CV-040` behavior is
//! implemented here. Placeholders are non-executable and never produce `Pass`.

/// Suite identifier for file ownership.
pub const SUITE: &str = "query_catalog";

/// Owned CV range for this suite.
pub const CV_RANGE: &str = "CV-025..CV-027";

/// Capability area label for this suite.
pub const CAPABILITY_AREA: &str = "query-catalog";

/// Returns the suite identifier.
#[must_use]
pub fn suite_name() -> &'static str {
    SUITE
}

/// Returns true if `cv_id` belongs to this suite's owned CV range.
#[must_use]
pub fn owns_cv(cv_id: &str) -> bool {
    matches!(cv_id, "CV-025" | "CV-026" | "CV-027")
}
