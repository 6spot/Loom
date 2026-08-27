//! Agency suite scaffold integration test (T17).

use loom_validator::{agency, validator_registry};

#[test]
fn agency_suite_scaffold_is_non_registering_and_disjoint() {
    assert_eq!(agency::SUITE, "agency");
    assert_eq!(agency::CV_RANGE, "CV-034..CV-037");
    assert_eq!(agency::CAPABILITY_AREA, "agency");
    assert_eq!(agency::suite_name(), "agency");
    assert!(agency::owns_cv("CV-034"));
    assert!(agency::owns_cv("CV-037"));
    assert!(!agency::owns_cv("CV-033"));
    assert!(!agency::owns_cv("CV-038"));

    let registry = validator_registry();
    assert_eq!(registry.len(), 31);
    assert!(registry.get("CV-034").is_none());
    assert!(registry.get("CV-040").is_some());
}
