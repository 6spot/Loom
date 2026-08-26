//! World Binding suite scaffold integration test (T10).

use loom_validator::{validator_registry, world_binding};

#[test]
fn world_binding_suite_scaffold_is_non_registering_and_disjoint() {
    assert_eq!(world_binding::SUITE, "world_binding");
    assert_eq!(world_binding::CV_RANGE, "CV-012..CV-014");
    assert_eq!(world_binding::CAPABILITY_AREA, "world-binding");
    assert_eq!(world_binding::suite_name(), "world_binding");
    assert!(world_binding::owns_cv("CV-012"));
    assert!(world_binding::owns_cv("CV-013"));
    assert!(world_binding::owns_cv("CV-014"));
    assert!(!world_binding::owns_cv("CV-015"));
    assert!(!world_binding::owns_cv("CV-011"));

    let registry = validator_registry();
    assert_eq!(registry.len(), 11);
    assert!(registry.get("CV-001").is_some());
    assert!(registry.get("CV-011").is_some());
    assert!(registry.get("CV-012").is_none());
    assert!(registry.get("CV-014").is_none());
    assert!(registry.get("CV-040").is_none());
}
