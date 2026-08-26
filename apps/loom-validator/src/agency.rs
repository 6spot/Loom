//! Agency Wake suite scaffold (T17).
//!
//! Owner: T17 (#322) — `CV-034..CV-037`.
//! Central registry integration is reserved for T19 (#324). This module must
//! not register scenarios in `validator_registry`; T19 alone edits
//! `registry.rs`/`lib.rs` and CLI dispatch. No `CV-012..CV-040` behavior is
//! implemented here. Placeholders are non-executable and never produce `Pass`.

/// Suite identifier for file ownership.
pub const SUITE: &str = "agency";

/// Owned CV range for this suite.
pub const CV_RANGE: &str = "CV-034..CV-037";

/// Capability area label for this suite.
pub const CAPABILITY_AREA: &str = "agency";

/// Returns the suite identifier.
#[must_use]
pub fn suite_name() -> &'static str {
    SUITE
}

/// Returns true if `cv_id` belongs to this suite's owned CV range.
#[must_use]
pub fn owns_cv(cv_id: &str) -> bool {
    matches!(cv_id, "CV-034" | "CV-035" | "CV-036" | "CV-037")
}
