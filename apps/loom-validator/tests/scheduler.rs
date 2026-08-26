//! Scheduler suite scaffold integration test (T12).

use loom_validator::{scheduler, validator_registry};

#[test]
fn scheduler_suite_scaffold_is_non_registering_and_disjoint() {
    assert_eq!(scheduler::SUITE, "scheduler");
    assert_eq!(scheduler::CV_RANGE, "CV-018..CV-020");
    assert_eq!(scheduler::CAPABILITY_AREA, "scheduler");
    assert_eq!(scheduler::suite_name(), "scheduler");
    assert!(scheduler::owns_cv("CV-018"));
    assert!(scheduler::owns_cv("CV-019"));
    assert!(scheduler::owns_cv("CV-020"));
    assert!(!scheduler::owns_cv("CV-017"));
    assert!(!scheduler::owns_cv("CV-021"));

    let registry = validator_registry();
    assert_eq!(registry.len(), 11);
    assert!(registry.get("CV-018").is_none());
    assert!(registry.get("CV-040").is_none());
}
