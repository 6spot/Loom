//! World Time suite scaffold integration test (T13).

use loom_validator::{validator_registry, world_time};

#[test]
fn world_time_suite_scaffold_is_non_registering_and_disjoint() {
    assert_eq!(world_time::SUITE, "world_time");
    assert_eq!(world_time::CV_RANGE, "CV-021..CV-024");
    assert_eq!(world_time::CAPABILITY_AREA, "world-time");
    assert_eq!(world_time::suite_name(), "world_time");
    assert!(world_time::owns_cv("CV-021"));
    assert!(world_time::owns_cv("CV-024"));
    assert!(!world_time::owns_cv("CV-020"));
    assert!(!world_time::owns_cv("CV-025"));

    let registry = validator_registry();
    assert_eq!(registry.len(), 11);
    assert!(registry.get("CV-021").is_none());
    assert!(registry.get("CV-040").is_none());
}
