//! Regression coverage for Validator's storage-evidence boundary.

use std::process::Command;

#[test]
fn generic_cli_endpoint_never_infers_postgres_from_ambient_configuration() {
    for (index, postgres_url) in [
        ("valid", "postgresql://loom:loom@127.0.0.1:5432/loom"),
        ("malformed", "not-a-postgres-url"),
    ] {
        let report_path = std::env::temp_dir().join(format!(
            "loom-validator-me278-backend-evidence-{}-{index}.json",
            std::process::id()
        ));

        let output = Command::new(env!("CARGO_BIN_EXE_loom-validator"))
            .env("LOOM_VALIDATOR_BASE_URL", "http://127.0.0.1:1")
            .env("LOOM_TEST_POSTGRES_URL", postgres_url)
            .args([
                "--scenario",
                "CV-001",
                "--json",
                report_path.to_str().expect("temporary path is UTF-8"),
            ])
            .output()
            .expect("validator binary should execute");

        assert!(
            output.status.success(),
            "generic negative endpoint should be reported, not fail runner configuration: {}",
            String::from_utf8_lossy(&output.stderr)
        );

        let report = std::fs::read_to_string(&report_path).expect("report should be written");
        let value: serde_json::Value =
            serde_json::from_str(&report).expect("report should be valid JSON");
        assert_eq!(value["backend_evidence"], "external");
        assert_eq!(value["backend_evidence_trusted"], false);
        assert_eq!(value["run"]["backend_evidence"], "external");
        assert_eq!(value["results"][0]["backend_evidence"], "external");
        assert_ne!(value["backend_evidence"], "postgresql");

        let _ = std::fs::remove_file(report_path);
    }
}
