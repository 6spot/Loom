//! Regression coverage for required-live `PostgreSQL` evidence gating (VALR-T06).

use std::process::Command;

#[test]
fn required_live_with_external_endpoint_fails_even_with_pg_url() {
    for pg_url in [
        "postgresql://loom:loom@127.0.0.1:5432/loom",
        "not-a-postgres-url",
    ] {
        let report_path = std::env::temp_dir().join(format!(
            "loom-validator-required-live-external-{}-{}.json",
            std::process::id(),
            pg_url.len()
        ));

        let output = Command::new(env!("CARGO_BIN_EXE_loom-validator"))
            .env("LOOM_VALIDATOR_BASE_URL", "http://127.0.0.1:1")
            .env("LOOM_TEST_POSTGRES_URL", pg_url)
            .args([
                "--required-live",
                "--scenario",
                "CV-001",
                "--json",
                report_path.to_str().expect("temp path is UTF-8"),
            ])
            .output()
            .expect("validator binary should execute");

        assert_eq!(
            output.status.code(),
            Some(1),
            "external endpoint must fail required-live (exit 1), not succeed: stderr={}",
            String::from_utf8_lossy(&output.stderr)
        );

        let report = std::fs::read_to_string(&report_path).expect("report should be written");
        let value: serde_json::Value =
            serde_json::from_str(&report).expect("report should be valid JSON");
        assert_eq!(value["backend_evidence"], "external");
        assert_eq!(value["backend_evidence_trusted"], false);
        assert_eq!(value["run"]["backend_evidence"], "external");
        // Must not be inferred as postgresql from ambient env
        assert_ne!(value["backend_evidence"], "postgresql");
        assert_eq!(value["run"]["policy"]["required_live"], true);
        assert_eq!(value["run"]["policy"]["strict"], true);

        let _ = std::fs::remove_file(report_path);
    }
}

#[test]
fn required_live_selection_error_remains_exit_2() {
    let report_path = std::env::temp_dir().join(format!(
        "loom-validator-required-live-selection-error-{}.json",
        std::process::id()
    ));

    let output = Command::new(env!("CARGO_BIN_EXE_loom-validator"))
        .env("LOOM_VALIDATOR_BASE_URL", "http://127.0.0.1:1")
        .args([
            "--required-live",
            "--scenario",
            "CV-999",
            "--json",
            report_path.to_str().expect("temp path is UTF-8"),
        ])
        .output()
        .expect("validator binary should execute");

    assert_eq!(
        output.status.code(),
        Some(2),
        "unknown scenario with --required-live must be exit 2, not gate failure: stderr={}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(
        String::from_utf8_lossy(&output.stderr).contains("CV-999"),
        "error text must mention invalid selector"
    );
    // runner_error variant writes report with runner_error, not findings
    if report_path.exists() {
        let report = std::fs::read_to_string(&report_path).unwrap();
        let value: serde_json::Value = serde_json::from_str(&report).unwrap();
        assert_eq!(value["result_state"], "runner_config_failure");
        let _ = std::fs::remove_file(report_path);
    }
}

#[test]
fn required_live_with_unknown_group_remains_exit_2() {
    let output = Command::new(env!("CARGO_BIN_EXE_loom-validator"))
        .env("LOOM_VALIDATOR_BASE_URL", "http://127.0.0.1:1")
        .args(["--required-live", "--group", "typo-group"])
        .output()
        .expect("validator binary should execute");

    assert_eq!(
        output.status.code(),
        Some(2),
        "unknown group with --required-live must be exit 2: stderr={}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(
        String::from_utf8_lossy(&output.stderr).contains("typo-group")
            || String::from_utf8_lossy(&output.stderr).contains("unknown group"),
        "error must mention unknown group"
    );
}
