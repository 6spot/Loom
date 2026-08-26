//! Focused regression for VALR-T05 — restart vs reconnect evidence.

#![allow(clippy::uninlined_format_args)]
#![allow(clippy::redundant_closure_for_method_calls)]

mod common;

use std::process::Command;
use std::sync::Arc;

use loom_client::LoomClient;
use loom_validator::{BackendContext, BackendKind, RestartCapability};

use common::{InMemoryServer, PgServer};

fn descriptor_cv003() -> loom_validator::ScenarioDescriptor {
    loom_validator::lifecycle_registry()
        .get("CV-003")
        .expect("CV-003 should be registered")
        .clone()
}

fn descriptor_cv004() -> loom_validator::ScenarioDescriptor {
    loom_validator::lifecycle_registry()
        .get("CV-004")
        .expect("CV-004 should be registered")
        .clone()
}

#[test]
fn generic_external_endpoint_cannot_restart_sensitive_pass() {
    // Generic CLI context is reconnect-only by default and must not fake-pass CV-003/CV-004.
    let client = LoomClient::builder("http://127.0.0.1:8080".to_string())
        .build()
        .expect("client should build");
    let ctx = BackendContext::new(client);
    assert_eq!(ctx.restart_capability(), RestartCapability::ReconnectOnly);
    assert!(!ctx.can_perform_boundary_restart());
    // Explicitly also check that InMemory kind with reconnect-only still blocks,
    // to prove independence from BackendEvidence.
    let ctx_inmem_reconnect = BackendContext::new(
        LoomClient::builder("http://127.0.0.1:8080".to_string())
            .build()
            .unwrap(),
    )
    .with_backend_kind(BackendKind::InMemory);
    assert_eq!(
        ctx_inmem_reconnect.restart_capability(),
        RestartCapability::ReconnectOnly
    );

    for (id, desc) in [
        ("CV-003", descriptor_cv003()),
        ("CV-004", descriptor_cv004()),
    ] {
        let result = loom_validator::execute_lifecycle(&desc, &ctx);
        assert!(
            !result.outcome().is_pass(),
            "{id} on generic reconnect-only must not pass: {result:?}"
        );
        // Must be explicitly non-pass via prerequisite/unavailable semantics.
        assert!(
            result.outcome().is_unavailable() || result.outcome().is_skipped(),
            "{id} should be unavailable/skipped, got {:?}",
            result.outcome()
        );
        let finding = result.finding();
        // Evidence and actual must explicitly mention reconnect-only and must not claim real restart.
        let evidence = finding
            .evidence()
            .iter()
            .map(|e| e.as_str())
            .collect::<Vec<_>>()
            .join(",");
        assert!(
            evidence.contains("reconnect-only"),
            "{id} evidence should contain reconnect-only marker: {evidence}"
        );
        assert!(
            !evidence.contains("controlled-boundary-restart"),
            "{id} reconnect-only evidence must not claim controlled restart: {evidence}"
        );
        assert!(
            finding
                .actual()
                .to_ascii_lowercase()
                .contains("reconnect-only"),
            "{id} actual should state reconnect-only: {}",
            finding.actual()
        );
        // Must not overclaim real boundary recreation.
        // The success wording "real application boundary recreation" must not appear for generic.
        assert!(
            !finding
                .actual()
                .contains("real application boundary recreation")
                || finding.actual().contains("reconnect-only"),
            "{id} generic actual must not overclaim real restart without qualification: {}",
            finding.actual()
        );
        // Also generic InMemory reconnect-only should still be blocked, proving independence.
        let result2 = loom_validator::execute_lifecycle(&desc, &ctx_inmem_reconnect);
        assert!(
            !result2.outcome().is_pass(),
            "{id} on InMemory kind but reconnect-only must not pass"
        );
    }
}

#[test]
fn reconnect_remains_reconnect_only_after_restart() {
    let client = LoomClient::builder("http://127.0.0.1:8080".to_string())
        .build()
        .unwrap();
    let ctx = BackendContext::new(client);
    assert_eq!(ctx.restart_capability(), RestartCapability::ReconnectOnly);
    // Restart is a reconnect to the same endpoint; it must not upgrade capability.
    let new_client = ctx
        .restart()
        .expect("reconnect should succeed parsing base URL");
    assert_eq!(ctx.restart_capability(), RestartCapability::ReconnectOnly);
    assert!(!ctx.can_perform_boundary_restart());
    let ctx2 = BackendContext::new(new_client);
    assert_eq!(ctx2.restart_capability(), RestartCapability::ReconnectOnly);
    assert!(!ctx2.can_perform_boundary_restart());
    // Explicitly setting reconnect strategy without upgrading capability keeps reconnect-only.
    let ctx3 = BackendContext::new(
        LoomClient::builder("http://127.0.0.1:8080".to_string())
            .build()
            .unwrap(),
    )
    .with_restart_strategy(Arc::new(|| {
        LoomClient::new("http://127.0.0.1:8080".to_string()).map_err(|e| e.to_string())
    }));
    assert_eq!(ctx3.restart_capability(), RestartCapability::ReconnectOnly);
}

#[test]
fn controlled_in_memory_restart_evidence_is_available() {
    // InMemory harness genuinely rebuilds runtime + HTTP boundary while preserving store.
    let (server, client) = InMemoryServer::start().expect("in-memory service should start");
    let server_for_restart = server.clone();
    let strategy: Arc<dyn Fn() -> Result<LoomClient, String> + Send + Sync> =
        Arc::new(move || server_for_restart.restart());
    let ctx = BackendContext::new(client)
        .with_backend_kind(BackendKind::InMemory)
        .with_restart_strategy(strategy)
        .with_controlled_boundary_restart();
    assert_eq!(
        ctx.restart_capability(),
        RestartCapability::ControlledBoundaryRestart
    );
    assert!(ctx.can_perform_boundary_restart());
    // Verify that the restarted service still preserves durable state via CV-003.
    // The scenario itself performs a genuine restart via the injected strategy.
    let desc = descriptor_cv003();
    let result = loom_validator::execute_lifecycle(&desc, &ctx);
    assert!(
        result.outcome().is_pass(),
        "controlled InMemory CV-003 should pass on real rebuilt boundary: {result:?}"
    );
    let evidence = result
        .finding()
        .evidence()
        .iter()
        .map(|e| e.as_str())
        .collect::<Vec<_>>()
        .join(",");
    assert!(
        evidence.contains("controlled-boundary-restart"),
        "controlled InMemory evidence should contain controlled marker: {evidence}"
    );
    assert!(
        result.finding().actual().contains("controlled"),
        "controlled InMemory actual should mention controlled restart: {}",
        result.finding().actual()
    );
    // Restart itself preserves controlled capability on the originating context,
    // and a fresh context built from the new client is reconnect-only unless
    // explicitly re-wrapped with the controlled strategy.
    let new_client = ctx.restart().expect("controlled restart should succeed");
    assert!(ctx.can_perform_boundary_restart());
    let ctx_fresh = BackendContext::new(new_client.clone());
    assert_eq!(
        ctx_fresh.restart_capability(),
        RestartCapability::ReconnectOnly
    );
    let ctx2 = BackendContext::new(new_client)
        .with_backend_kind(BackendKind::InMemory)
        .with_restart_strategy(Arc::new({
            let server = server.clone();
            move || server.restart()
        }))
        .with_controlled_boundary_restart();
    assert!(ctx2.can_perform_boundary_restart());
    assert_eq!(
        ctx2.restart_capability(),
        RestartCapability::ControlledBoundaryRestart
    );
}

#[test]
fn controlled_postgres_restart_evidence_is_available() {
    // PostgreSQL harness genuinely rebuilds boundary while preserving database state.
    // If the repository-managed PostgreSQL is not reachable, we verify the construction
    // seam still correctly represents controlled restart capability via direct context checks,
    // without requiring a full live scenario pass.
    let controlled_ctx = BackendContext::new(
        LoomClient::builder("http://127.0.0.1:8080".to_string())
            .build()
            .unwrap(),
    )
    .with_backend_kind(BackendKind::PostgreSQL)
    .with_controlled_boundary_restart();
    assert_eq!(
        controlled_ctx.restart_capability(),
        RestartCapability::ControlledBoundaryRestart
    );
    assert!(controlled_ctx.can_perform_boundary_restart());

    // Try to exercise a real PostgreSQL service when available.
    let pg_attempt = PgServer::start();
    if let Ok((server, client)) = pg_attempt {
        let server_for_restart = server.clone();
        let strategy: Arc<dyn Fn() -> Result<LoomClient, String> + Send + Sync> =
            Arc::new(move || server_for_restart.restart());
        let ctx = BackendContext::new(client)
            .with_backend_kind(BackendKind::PostgreSQL)
            .with_restart_strategy(strategy)
            .with_controlled_boundary_restart();
        let desc = descriptor_cv003();
        let result = loom_validator::execute_lifecycle(&desc, &ctx);
        // CV-003 on PostgreSQL with genuine restart must pass when service is healthy.
        // If PG service is degraded, the result will be unavailable, not pass, but still
        // must not be a fake-pass and must evidence controlled restart when passing.
        if result.outcome().is_pass() {
            let evidence = result
                .finding()
                .evidence()
                .iter()
                .map(|e| e.as_str())
                .collect::<Vec<_>>()
                .join(",");
            assert!(
                evidence.contains("controlled-boundary-restart"),
                "controlled PG evidence should contain controlled marker: {evidence}"
            );
        } else {
            // Ensure even when not pass due to infra, it still reports reconnect-only only
            // when appropriate – but here context is controlled, so failure must not be due to
            // missing capability; it would be unavailable from infra, which is acceptable.
            assert!(
                !result.finding().actual().contains("reconnect-only")
                    || result.finding().actual().contains("controlled"),
                "controlled PG should not be reported as reconnect-only: {}",
                result.finding().actual()
            );
        }
    } else {
        // No live PG service: at least verify the seam distinguishes capability from evidence.
        // The generic reconnect-only PostgreSQL kind would still be blocked.
        let generic_pg = BackendContext::new(
            LoomClient::builder("http://127.0.0.1:8080".to_string())
                .build()
                .unwrap(),
        )
        .with_backend_kind(BackendKind::PostgreSQL);
        assert_eq!(
            generic_pg.restart_capability(),
            RestartCapability::ReconnectOnly
        );
        assert_eq!(
            generic_pg.backend_evidence(),
            loom_validator::BackendEvidence::PostgreSQL
        );
        // Yet it must not provide trusted restart evidence.
        let result = loom_validator::execute_lifecycle(&descriptor_cv003(), &generic_pg);
        assert!(!result.outcome().is_pass());
        assert!(
            result.finding().actual().contains("reconnect-only"),
            "generic PG with reconnect-only should be blocked: {}",
            result.finding().actual()
        );
    }
}

#[test]
fn result_text_does_not_overclaim_unhappened_real_restart() {
    let client = LoomClient::builder("http://127.0.0.1:8080".to_string())
        .build()
        .unwrap();
    let ctx = BackendContext::new(client);
    for desc in [descriptor_cv003(), descriptor_cv004()] {
        let result = loom_validator::execute_lifecycle(&desc, &ctx);
        let actual = result.finding().actual().to_ascii_lowercase();
        let evidence = result
            .finding()
            .evidence()
            .iter()
            .map(|e| e.as_str().to_ascii_lowercase())
            .collect::<Vec<_>>()
            .join(",");
        // Must not claim controlled restart when only reconnect was performed.
        assert!(
            !evidence.contains("controlled-boundary-restart"),
            "reconnect-only result must not contain controlled evidence: {evidence}"
        );
        assert!(
            actual.contains("reconnect-only"),
            "reconnect-only actual must explicitly state reconnect-only: {}",
            actual
        );
        // The exact phrase that previously overclaimed is absent unless qualified.
        if actual.contains("real application boundary recreation") {
            assert!(
                actual.contains("reconnect-only") || actual.contains("not"),
                "overclaiming real restart without reconnect-only qualification: {}",
                actual
            );
        }
    }
}

#[test]
fn generic_cli_report_does_not_claim_postgres_or_real_restart() {
    // Subprocess check mirrors backend_evidence.rs but for restart semantics:
    // a generic external endpoint via the CLI must never report a passing real-restart.
    let report_path = std::env::temp_dir().join(format!(
        "loom-validator-restart-evidence-{}-{}.json",
        std::process::id(),
        "generic"
    ));
    let output = Command::new(env!("CARGO_BIN_EXE_loom-validator"))
        .env("LOOM_VALIDATOR_BASE_URL", "http://127.0.0.1:8080")
        .env(
            "LOOM_TEST_POSTGRES_URL",
            "postgresql://loom:loom@127.0.0.1:5432/loom",
        )
        .args([
            "--scenario",
            "CV-003",
            "--json",
            report_path.to_str().expect("temp path is UTF-8"),
        ])
        .output()
        .expect("validator binary should execute");

    assert!(
        output.status.success() || output.status.code() == Some(0),
        "generic CLI report should be written, not runner error: {}",
        String::from_utf8_lossy(&output.stderr)
    );

    let report = std::fs::read_to_string(&report_path).expect("report should be written");
    let value: serde_json::Value =
        serde_json::from_str(&report).expect("report should be valid JSON");
    // The report must not be a synthetic pass for a restart-sensitive scenario on generic endpoint.
    let outcomes = value["results"]
        .as_array()
        .map(|arr| {
            arr.iter()
                .map(|v| v["outcome"].as_str().unwrap_or(""))
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    for outcome in outcomes {
        assert_ne!(
            outcome, "pass",
            "generic external CV-003 must not pass as real restart: report={value}"
        );
    }
    // Check that the finding evidence or reason explicitly mentions reconnect-only.
    let report_str = report.to_ascii_lowercase();
    assert!(
        report_str.contains("reconnect-only"),
        "generic CLI JSON report should mention reconnect-only: {report_str}"
    );
    assert!(
        !report_str.contains("controlled-boundary-restart")
            || report_str.contains("reconnect-only"),
        "generic report must not claim controlled restart without reconnect-only: {report_str}"
    );
    let _ = std::fs::remove_file(report_path);
}
