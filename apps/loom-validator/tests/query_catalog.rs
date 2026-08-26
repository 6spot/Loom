//! Query Catalog suite scaffold integration test (T14).

use loom_validator::{query_catalog, validator_registry};

#[test]
fn query_catalog_suite_scaffold_is_non_registering_and_disjoint() {
    assert_eq!(query_catalog::SUITE, "query_catalog");
    assert_eq!(query_catalog::CV_RANGE, "CV-025..CV-027");
    assert_eq!(query_catalog::CAPABILITY_AREA, "query-catalog");
    assert_eq!(query_catalog::suite_name(), "query_catalog");
    assert!(query_catalog::owns_cv("CV-025"));
    assert!(query_catalog::owns_cv("CV-027"));
    assert!(!query_catalog::owns_cv("CV-024"));
    assert!(!query_catalog::owns_cv("CV-028"));

    let registry = validator_registry();
    assert_eq!(registry.len(), 11);
    assert!(registry.get("CV-025").is_none());
    assert!(registry.get("CV-040").is_none());
}
