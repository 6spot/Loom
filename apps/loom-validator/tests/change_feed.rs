//! Change Feed suite scaffold integration test (T18).

use loom_validator::{change_feed, validator_registry};

#[test]
fn change_feed_suite_scaffold_is_non_registering_and_disjoint() {
    assert_eq!(change_feed::SUITE, "change_feed");
    assert_eq!(change_feed::CV_RANGE, "CV-038..CV-040");
    assert_eq!(change_feed::CAPABILITY_AREA, "change-feed");
    assert_eq!(change_feed::suite_name(), "change_feed");
    assert!(change_feed::owns_cv("CV-038"));
    assert!(change_feed::owns_cv("CV-040"));
    assert!(!change_feed::owns_cv("CV-037"));
    assert!(!change_feed::owns_cv("CV-012"));

    let registry = validator_registry();
    assert_eq!(registry.len(), 11);
    assert!(registry.get("CV-038").is_none());
    assert!(registry.get("CV-040").is_none());
}
