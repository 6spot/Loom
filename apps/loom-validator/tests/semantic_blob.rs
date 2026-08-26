//! Semantic Blob suite scaffold integration test (T15).

use loom_validator::{semantic_blob, validator_registry};

#[test]
fn semantic_blob_suite_scaffold_is_non_registering_and_disjoint() {
    assert_eq!(semantic_blob::SUITE, "semantic_blob");
    assert_eq!(semantic_blob::CV_RANGE, "CV-028..CV-030");
    assert_eq!(semantic_blob::CAPABILITY_AREA, "semantic-blob");
    assert_eq!(semantic_blob::suite_name(), "semantic_blob");
    assert!(semantic_blob::owns_cv("CV-028"));
    assert!(semantic_blob::owns_cv("CV-030"));
    assert!(!semantic_blob::owns_cv("CV-027"));
    assert!(!semantic_blob::owns_cv("CV-031"));

    let registry = validator_registry();
    assert_eq!(registry.len(), 11);
    assert!(registry.get("CV-028").is_none());
    assert!(registry.get("CV-040").is_none());
}
