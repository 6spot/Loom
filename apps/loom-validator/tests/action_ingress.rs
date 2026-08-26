//! Action Ingress suite scaffold integration test (T11).

use loom_validator::{action_ingress, validator_registry};

#[test]
fn action_ingress_suite_scaffold_is_non_registering_and_disjoint() {
    assert_eq!(action_ingress::SUITE, "action_ingress");
    assert_eq!(action_ingress::CV_RANGE, "CV-015..CV-017");
    assert_eq!(action_ingress::CAPABILITY_AREA, "action-ingress");
    assert_eq!(action_ingress::suite_name(), "action_ingress");
    assert!(action_ingress::owns_cv("CV-015"));
    assert!(action_ingress::owns_cv("CV-016"));
    assert!(action_ingress::owns_cv("CV-017"));
    assert!(!action_ingress::owns_cv("CV-014"));
    assert!(!action_ingress::owns_cv("CV-018"));

    let registry = validator_registry();
    assert_eq!(registry.len(), 11);
    assert!(registry.get("CV-015").is_none());
    assert!(registry.get("CV-040").is_none());
}
