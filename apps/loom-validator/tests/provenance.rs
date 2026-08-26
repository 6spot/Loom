//! Provenance suite scaffold integration test (T16).

use loom_validator::{provenance, validator_registry};

#[test]
fn provenance_suite_scaffold_is_non_registering_and_disjoint() {
    assert_eq!(provenance::SUITE, "provenance");
    assert_eq!(provenance::CV_RANGE, "CV-031..CV-033");
    assert_eq!(provenance::CAPABILITY_AREA, "provenance");
    assert_eq!(provenance::suite_name(), "provenance");
    assert!(provenance::owns_cv("CV-031"));
    assert!(provenance::owns_cv("CV-033"));
    assert!(!provenance::owns_cv("CV-030"));
    assert!(!provenance::owns_cv("CV-034"));

    let registry = validator_registry();
    assert_eq!(registry.len(), 11);
    assert!(registry.get("CV-031").is_none());
    assert!(registry.get("CV-040").is_none());
}
