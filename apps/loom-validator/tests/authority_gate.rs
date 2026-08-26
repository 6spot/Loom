//! VALR-T07 Stage-1 Validator authority regression gate.
//!
//! One integrated, repeatable gate that proves six regression classes
//! are closed **together**, not merely in isolated unit suites:
//!
//! 1. single-pass — each selected scenario executes at most once per CLI
//!    invocation, with normal (best-effort) continuation and fail-fast
//!    early-stop without replay.
//! 2. strict truth — `Fail`/`Skipped`/`Unavailable` never return success
//!    under `--strict` (best-effort stays success without strict).
//! 3. selection truth — explicit unknown scenario/group/empty selection is
//!    a configuration error (`exit 2`), not a synthetic pass.
//! 4. backend truth — a generic `LOOM_VALIDATOR_BASE_URL` remains
//!    `external` evidence even when ambient `LOOM_TEST_POSTGRES_URL` is
//!    present (valid or malformed); never inferred as trusted `postgresql`.
//! 5. restart truth — reconnect-only production context cannot fake-pass
//!    lifecycle restart scenarios `CV-003`/`CV-004`; the controlled
//!    `InMemory` (and `PostgreSQL` when live) boundary-rebuild harnesses
//!    still produce real `controlled-boundary-restart` evidence.
//! 6. required-live truth — only trusted `postgresql` evidence can satisfy
//!    `--required-live`; `InMemory`/`External`/any `Skipped`/`Unavailable`/
//!    `Fail` never satisfies.
//!
//! This test binary **is** the named gate:
//! `cargo test -p loom-validator --test authority_gate --all-features`
//! (or `bash tools/validator-authority-gate.sh`) is the single repeatable
//! entry. Every `#[test]` below performs real assertions against the
//! current production semantics; no test is allowed to be skipped,
//! ignored, or to lower assertions. The harness reuses T01–T06 public/test
//! surfaces (`Runner`, `BackendContext`/`BackendHarness`, lifecycle
//! execution, `common::{InMemoryServer,PgServer}`, CLI subprocess) and
//! never modifies production code.

#![allow(clippy::uninlined_format_args)]
#![allow(clippy::redundant_closure_for_method_calls)]

mod common;

use std::cell::RefCell;
use std::collections::BTreeMap;
use std::process::Command;
use std::sync::Arc;

use loom_client::LoomClient;
use loom_validator::{
    BackendContext, BackendEvidence, BackendKind, RestartCapability, Runner, ScenarioDescriptor,
    ScenarioOutcome, ScenarioResult, ValidationPolicy,
};
use loom_validator::{EvidenceReference, Finding, ScenarioRegistry};

// ---------------------------------------------------------------------------
// tiny local fixtures — reuse T01–T06 style but live inside this gate only
// ---------------------------------------------------------------------------

fn descriptor(id: &str, area: &str) -> ScenarioDescriptor {
    ScenarioDescriptor::new(
        id,
        format!("scenario {id}"),
        area,
        vec![BackendKind::LoomClient],
        "none",
        vec![],
        vec![],
    )
}

fn small_registry() -> ScenarioRegistry {
    let mut r = ScenarioRegistry::bootstrap();
    r.register(descriptor("CV-001", "world")).unwrap();
    r.register(descriptor("CV-002", "world")).unwrap();
    r.register(descriptor("CV-003", "agency")).unwrap();
    r
}

fn small_registry_two() -> ScenarioRegistry {
    let mut r = ScenarioRegistry::bootstrap();
    r.register(descriptor("CV-001", "world")).unwrap();
    r.register(descriptor("CV-002", "world")).unwrap();
    r
}

fn test_backend() -> BackendContext {
    let client = LoomClient::builder("http://localhost:8080".to_string())
        .build()
        .unwrap();
    BackendContext::new(client)
}

fn pg_backend() -> BackendContext {
    let client = LoomClient::builder("http://localhost:8080".to_string())
        .build()
        .unwrap();
    BackendContext::new(client).with_backend_kind(BackendKind::PostgreSQL)
}

fn inmemory_backend() -> BackendContext {
    let client = LoomClient::builder("http://localhost:8080".to_string())
        .build()
        .unwrap();
    BackendContext::new(client).with_backend_kind(BackendKind::InMemory)
}

fn passing_executor(desc: &ScenarioDescriptor, backend: &BackendContext) -> ScenarioResult {
    let finding = Finding::new(
        desc.id().clone(),
        desc.name(),
        "expected",
        "actual",
        *backend.backend_kind(),
        "ctx",
        vec![],
        ScenarioOutcome::Pass,
    );
    ScenarioResult::new(desc.id().clone(), ScenarioOutcome::Pass, finding)
}

fn passing_aware(desc: &ScenarioDescriptor, backend: &BackendContext) -> ScenarioResult {
    let finding = Finding::new(
        desc.id().clone(),
        desc.name(),
        "expected",
        "actual",
        *backend.backend_kind(),
        "ctx",
        vec![],
        ScenarioOutcome::Pass,
    );
    ScenarioResult::new(desc.id().clone(), ScenarioOutcome::Pass, finding)
}

fn mixed_executor(desc: &ScenarioDescriptor, backend: &BackendContext) -> ScenarioResult {
    let outcome = if desc.id_str() == "CV-002" {
        ScenarioOutcome::Fail
    } else {
        ScenarioOutcome::Pass
    };
    let finding = Finding::new(
        desc.id().clone(),
        desc.name(),
        "expected",
        "actual",
        *backend.backend_kind(),
        "ctx",
        vec![EvidenceReference::new("evidence:test")],
        outcome.clone(),
    );
    ScenarioResult::new(desc.id().clone(), outcome, finding)
}

fn skipped_executor(desc: &ScenarioDescriptor, backend: &BackendContext) -> ScenarioResult {
    let outcome = ScenarioOutcome::Skipped {
        reason: "missing prerequisite: test db".to_string(),
    };
    let finding = Finding::new(
        desc.id().clone(),
        desc.name(),
        "expected",
        "actual",
        *backend.backend_kind(),
        "ctx",
        vec![],
        outcome.clone(),
    );
    ScenarioResult::new(desc.id().clone(), outcome, finding)
}

fn unavailable_executor(desc: &ScenarioDescriptor, backend: &BackendContext) -> ScenarioResult {
    let outcome = ScenarioOutcome::Unavailable {
        reason: "environment unavailable".to_string(),
    };
    let finding = Finding::new(
        desc.id().clone(),
        desc.name(),
        "expected",
        "actual",
        *backend.backend_kind(),
        "ctx",
        vec![],
        outcome.clone(),
    );
    ScenarioResult::new(desc.id().clone(), outcome, finding)
}

// ---------------------------------------------------------------------------
// 1. single-pass: normal/best-effort continues, fail-fast stops, never replay
// ---------------------------------------------------------------------------

#[test]
#[allow(clippy::too_many_lines)]
fn single_pass_normal_continues_and_fail_fast_stops_without_replay() {
    // Library path: Runner::run_selected single-pass authority
    let runner = Runner::new(small_registry_two());
    let backend = test_backend();

    // Normal mode: two-scenario selection invokes each exactly once in sorted order,
    // and report is produced from the same single pass.
    {
        let selection = runner.resolve_ids(&["CV-001,CV-002".to_string()]).unwrap();
        let counts: RefCell<BTreeMap<String, usize>> = RefCell::new(BTreeMap::new());
        let order: RefCell<Vec<String>> = RefCell::new(Vec::new());
        let report = runner.run_selected(
            &selection,
            &backend,
            |desc, ctx| {
                *counts
                    .borrow_mut()
                    .entry(desc.id_str().to_string())
                    .or_insert(0) += 1;
                order.borrow_mut().push(desc.id_str().to_string());
                let finding = Finding::new(
                    desc.id().clone(),
                    desc.name(),
                    "expected",
                    format!("actual:{}", desc.id_str()),
                    *ctx.backend_kind(),
                    "test",
                    vec![EvidenceReference::new(format!(
                        "evidence:{}:{}",
                        desc.id_str(),
                        counts.borrow()[desc.id_str()]
                    ))],
                    ScenarioOutcome::Pass,
                );
                ScenarioResult::new(desc.id().clone(), ScenarioOutcome::Pass, finding)
            },
            false,
        );
        assert_eq!(
            counts.borrow().get("CV-001"),
            Some(&1),
            "CV-001 exactly once"
        );
        assert_eq!(
            counts.borrow().get("CV-002"),
            Some(&1),
            "CV-002 exactly once"
        );
        assert_eq!(*order.borrow(), vec!["CV-001", "CV-002"]);
        assert_eq!(report.scenario_count(), 2);
        assert_eq!(report.results()[0].finding().actual(), "actual:CV-001");
        assert_eq!(report.results()[1].finding().actual(), "actual:CV-002");
    }

    // Fail-fast: first failure → second never invoked, failing first exactly once.
    {
        let runner = Runner::new(small_registry());
        let selection = runner
            .resolve_ids(&[
                "CV-001".to_string(),
                "CV-002".to_string(),
                "CV-003".to_string(),
            ])
            .unwrap();
        let counts: RefCell<BTreeMap<String, usize>> = RefCell::new(BTreeMap::new());
        let report = runner.run_selected(
            &selection,
            &backend,
            |desc, _| {
                *counts
                    .borrow_mut()
                    .entry(desc.id_str().to_string())
                    .or_insert(0) += 1;
                let outcome = if desc.id_str() == "CV-001" {
                    ScenarioOutcome::Fail
                } else {
                    ScenarioOutcome::Pass
                };
                let finding = Finding::new(
                    desc.id().clone(),
                    desc.name(),
                    "expected",
                    format!("actual:{}", desc.id_str()),
                    BackendKind::LoomClient,
                    "test",
                    vec![],
                    outcome.clone(),
                );
                ScenarioResult::new(desc.id().clone(), outcome, finding)
            },
            true,
        );
        assert_eq!(
            counts.borrow().get("CV-001"),
            Some(&1),
            "failing first exactly once"
        );
        assert_eq!(
            counts.borrow().get("CV-002"),
            None,
            "second never under fail-fast"
        );
        assert_eq!(counts.borrow().get("CV-003"), None);
        assert_eq!(report.scenario_count(), 1);
        assert_eq!(report.results()[0].scenario_id().as_str(), "CV-001");
    }

    // Harness path: run_with_harness_selected preserves the same single-pass guarantees.
    {
        let runner = Runner::new(small_registry_two());
        let harness = loom_validator::BackendHarness::connect(
            BackendKind::LoomClient,
            "http://localhost:8080",
        )
        .unwrap();
        let selection = runner.resolve_ids(&["CV-001,CV-002".to_string()]).unwrap();
        let counts: RefCell<BTreeMap<String, usize>> = RefCell::new(BTreeMap::new());
        let report = runner.run_with_harness_selected(
            &selection,
            &harness,
            |desc, ctx| {
                *counts
                    .borrow_mut()
                    .entry(desc.id_str().to_string())
                    .or_insert(0) += 1;
                let finding = Finding::new(
                    desc.id().clone(),
                    desc.name(),
                    "expected",
                    format!("scope:{}", ctx.scope()),
                    *ctx.backend_kind(),
                    ctx.scope(),
                    vec![EvidenceReference::new(format!(
                        "invocation:{}:{}",
                        desc.id_str(),
                        counts.borrow()[desc.id_str()]
                    ))],
                    ScenarioOutcome::Pass,
                );
                ScenarioResult::new(desc.id().clone(), ScenarioOutcome::Pass, finding)
            },
            false,
        );
        assert_eq!(counts.borrow().get("CV-001"), Some(&1));
        assert_eq!(counts.borrow().get("CV-002"), Some(&1));
        assert_eq!(report.scenario_count(), 2);
        assert_eq!(report.results()[0].finding().actual(), "scope:CV-001");
        assert_eq!(report.results()[1].finding().actual(), "scope:CV-002");
    }

    // CLI path single-pass (execute_cli) — normal continues, fail-fast stops, never replay.
    {
        use loom_validator::{CliArgs, EXIT_SCENARIO_FAILURE, EXIT_SUCCESS, execute_cli};
        let runner = Runner::new(small_registry_two());
        // normal
        let args = CliArgs {
            scenario_ids: vec!["CV-001,CV-002".to_string()],
            ..Default::default()
        };
        let counts: RefCell<BTreeMap<String, usize>> = RefCell::new(BTreeMap::new());
        let code = execute_cli(
            &runner,
            &backend,
            &args,
            |desc, _| {
                *counts
                    .borrow_mut()
                    .entry(desc.id_str().to_string())
                    .or_insert(0) += 1;
                passing_executor(desc, &test_backend())
            },
            |_| {},
            |_| {},
        );
        assert_eq!(code, EXIT_SUCCESS);
        assert_eq!(counts.borrow().get("CV-001"), Some(&1));
        assert_eq!(counts.borrow().get("CV-002"), Some(&1));

        // fail-fast strict: first fails → second never invoked, exit 1 via strict gate
        let args2 = CliArgs {
            scenario_ids: vec!["CV-001,CV-002".to_string()],
            fail_fast: true,
            strict: true,
            ..Default::default()
        };
        let counts2: RefCell<BTreeMap<String, usize>> = RefCell::new(BTreeMap::new());
        let code2 = execute_cli(
            &runner,
            &backend,
            &args2,
            |desc, _| {
                *counts2
                    .borrow_mut()
                    .entry(desc.id_str().to_string())
                    .or_insert(0) += 1;
                let outcome = if desc.id_str() == "CV-001" {
                    ScenarioOutcome::Fail
                } else {
                    ScenarioOutcome::Pass
                };
                let finding = Finding::new(
                    desc.id().clone(),
                    desc.name(),
                    "expected",
                    "actual",
                    BackendKind::LoomClient,
                    "ctx",
                    vec![],
                    outcome.clone(),
                );
                ScenarioResult::new(desc.id().clone(), outcome, finding)
            },
            |_| {},
            |_| {},
        );
        assert_eq!(code2, EXIT_SCENARIO_FAILURE);
        assert_eq!(counts2.borrow().get("CV-001"), Some(&1));
        assert_eq!(counts2.borrow().get("CV-002"), None);
    }
}

// ---------------------------------------------------------------------------
// 2. strict truth: Fail/Skipped/Unavailable → non-zero under strict
// ---------------------------------------------------------------------------

#[test]
#[allow(clippy::too_many_lines)]
fn strict_truth_fail_skipped_unavailable_are_nonzero() {
    use loom_validator::{CliArgs, EXIT_SCENARIO_FAILURE, EXIT_SUCCESS, execute_cli};

    let runner = Runner::new(small_registry_two());
    let backend = test_backend();

    // strict + all Pass => exit 0 (gate passes)
    let strict_pass = CliArgs {
        scenario_ids: vec!["CV-001,CV-002".to_string()],
        strict: true,
        ..Default::default()
    };
    let code = execute_cli(
        &runner,
        &backend,
        &strict_pass,
        passing_executor,
        |_| {},
        |_| {},
    );
    assert_eq!(code, EXIT_SUCCESS, "strict + all Pass must be 0");

    // strict + Fail => exit 1
    let strict_fail = CliArgs {
        scenario_ids: vec!["CV-001,CV-002".to_string()],
        strict: true,
        ..Default::default()
    };
    let code = execute_cli(
        &runner,
        &backend,
        &strict_fail,
        mixed_executor,
        |_| {},
        |_| {},
    );
    assert_eq!(code, EXIT_SCENARIO_FAILURE, "strict + Fail must be 1");

    // strict + Skipped => exit 1
    let strict_skipped = CliArgs {
        scenario_ids: vec!["CV-001".to_string()],
        strict: true,
        ..Default::default()
    };
    let code = execute_cli(
        &runner,
        &backend,
        &strict_skipped,
        skipped_executor,
        |_| {},
        |_| {},
    );
    assert_eq!(code, EXIT_SCENARIO_FAILURE, "strict + Skipped must be 1");

    // strict + Unavailable => exit 1
    let code = execute_cli(
        &runner,
        &backend,
        &strict_skipped,
        unavailable_executor,
        |_| {},
        |_| {},
    );
    assert_eq!(
        code, EXIT_SCENARIO_FAILURE,
        "strict + Unavailable must be 1"
    );

    // best-effort without strict stays 0 even when a scenario fails (normal continuation)
    let best_effort = CliArgs {
        scenario_ids: vec!["CV-001,CV-002".to_string()],
        fail_fast: false,
        strict: false,
        ..Default::default()
    };
    let mut out = Vec::new();
    let code = execute_cli(
        &runner,
        &backend,
        &best_effort,
        mixed_executor,
        |l| out.push(l.to_string()),
        |_| {},
    );
    assert_eq!(code, EXIT_SUCCESS, "best-effort with Fail must remain 0");
    assert!(out.join("\n").contains("CV-002"), "best-effort runs all");

    // fail-fast without strict: stops after Fail but still best-effort exit 0
    let fail_fast_best = CliArgs {
        scenario_ids: vec!["CV-001,CV-002".to_string()],
        fail_fast: true,
        strict: false,
        ..Default::default()
    };
    let counts: RefCell<Vec<String>> = RefCell::new(Vec::new());
    let code = execute_cli(
        &Runner::new({
            let mut r = ScenarioRegistry::bootstrap();
            r.register(descriptor("CV-001", "world")).unwrap();
            r.register(descriptor("CV-002", "world")).unwrap();
            r.register(descriptor("CV-003", "world")).unwrap();
            r
        }),
        &backend,
        &CliArgs {
            scenario_ids: vec!["CV-001,CV-002,CV-003".to_string()],
            fail_fast: true,
            strict: false,
            ..Default::default()
        },
        |desc, ctx| {
            counts.borrow_mut().push(desc.id_str().to_string());
            mixed_executor(desc, ctx)
        },
        |_| {},
        |_| {},
    );
    // mixed_executor fails on CV-002, so fail-fast should have run CV-001 and CV-002 only
    assert_eq!(*counts.borrow(), vec!["CV-001", "CV-002"]);
    let _ = fail_fast_best; // keep binding used
    assert_eq!(
        code, EXIT_SUCCESS,
        "fail-fast without strict does not change gate"
    );

    // strict without fail-fast: full selection runs, gate still fails
    let strict_no_ff = CliArgs {
        scenario_ids: vec!["CV-001,CV-002,CV-003".to_string()],
        strict: true,
        fail_fast: false,
        ..Default::default()
    };
    let counts: RefCell<Vec<String>> = RefCell::new(Vec::new());
    let code = execute_cli(
        &Runner::new({
            let mut r = ScenarioRegistry::bootstrap();
            r.register(descriptor("CV-001", "world")).unwrap();
            r.register(descriptor("CV-002", "world")).unwrap();
            r.register(descriptor("CV-003", "world")).unwrap();
            r
        }),
        &backend,
        &strict_no_ff,
        |desc, ctx| {
            counts.borrow_mut().push(desc.id_str().to_string());
            mixed_executor(desc, ctx)
        },
        |_| {},
        |_| {},
    );
    assert_eq!(
        *counts.borrow(),
        vec!["CV-001", "CV-002", "CV-003"],
        "strict alone runs all"
    );
    assert_eq!(code, EXIT_SCENARIO_FAILURE);
}

// ---------------------------------------------------------------------------
// 3. selection truth: unknown/empty → exit 2
// ---------------------------------------------------------------------------

#[test]
#[allow(clippy::too_many_lines)]
fn selection_truth_unknown_and_empty_are_exit_2() {
    use loom_validator::{CliArgs, EXIT_RUNNER_ERROR, RunnerError, execute_cli, parse_args};

    let runner = Runner::new(small_registry());

    // Runner layer: unknown scenario ID is RunnerError::UnknownScenarioIds
    let err = runner.resolve_ids(&["CV-999".to_string()]).unwrap_err();
    assert!(matches!(err, RunnerError::UnknownScenarioIds(_)));
    assert!(format!("{err}").contains("unknown scenario"));

    // Runner layer: unknown group is RunnerError::UnknownGroups (VALR-T03)
    let err = runner
        .resolve_with_groups(&[], &["typo-group".to_string()], false)
        .unwrap_err();
    assert!(matches!(err, RunnerError::UnknownGroups(_)));
    assert!(format!("{err}").contains("unknown group"));
    assert!(format!("{err}").contains("typo-group"));

    // Runner layer: empty group string is InvalidSelection
    let err = runner
        .resolve_with_groups(&[], &["world,".to_string()], false)
        .unwrap_err();
    assert_eq!(
        err,
        RunnerError::InvalidSelection("empty group".to_string())
    );

    // CLI library layer: unknown group → exit 2 with clear text
    let backend = test_backend();
    let args = CliArgs {
        groups: vec!["typo-group".to_string()],
        ..Default::default()
    };
    let mut err_out = Vec::new();
    let code = execute_cli(
        &runner,
        &backend,
        &args,
        passing_executor,
        |_| {},
        |l| err_out.push(l.to_string()),
    );
    assert_eq!(code, EXIT_RUNNER_ERROR, "unknown group must be exit 2");
    let msg = err_out.join("\n");
    assert!(
        msg.contains("unknown group") && msg.contains("typo-group"),
        "msg: {msg}"
    );

    // CLI library: unknown scenario → exit 2
    let args = CliArgs {
        scenario_ids: vec!["CV-999".to_string()],
        ..Default::default()
    };
    let mut err_out = Vec::new();
    let code = execute_cli(
        &runner,
        &backend,
        &args,
        passing_executor,
        |_| {},
        |l| err_out.push(l.to_string()),
    );
    assert_eq!(code, EXIT_RUNNER_ERROR, "unknown scenario must be exit 2");
    assert!(err_out.join("\n").contains("CV-999"));

    // CLI library: strict + typo cannot be exit 0
    let args = CliArgs {
        scenario_ids: vec!["CV-999".to_string()],
        strict: true,
        ..Default::default()
    };
    let code = execute_cli(&runner, &backend, &args, passing_executor, |_| {}, |_| {});
    assert_eq!(code, EXIT_RUNNER_ERROR);
    assert_ne!(code, 0);

    // CLI subprocess: unknown scenario and unknown group both exit 2
    let bin = env!("CARGO_BIN_EXE_loom-validator");
    for case in [
        vec!["--scenario", "CV-999"],
        vec!["--group", "typo-group"],
        vec!["--required-live", "--scenario", "CV-999"],
        vec!["--required-live", "--group", "typo-group"],
    ] {
        let output = Command::new(bin)
            .args(&case)
            .output()
            .expect("validator binary should execute");
        assert_eq!(
            output.status.code(),
            Some(2),
            "CLI {case:?} must be exit 2, stderr={}",
            String::from_utf8_lossy(&output.stderr)
        );
    }

    // Subprocess with explicit unknown scenario + strict must still be exit 2 (not gate failure)
    let output = Command::new(bin)
        .args(["--strict", "--scenario", "CV-999"])
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(2));
    assert!(
        String::from_utf8_lossy(&output.stderr).contains("CV-999")
            || String::from_utf8_lossy(&output.stderr).contains("unknown")
    );

    // Parsing helper: decide_action for unknown group is runner error
    let args = parse_args(vec![
        "loom-validator".to_string(),
        "--group".to_string(),
        "unknown".to_string(),
    ])
    .unwrap();
    assert!(matches!(
        loom_validator::decide_action(&runner, &args),
        loom_validator::CliAction::RunnerError(_)
    ));

    // No selector (the `all` default) remains success with deterministic ordering
    let args = CliArgs::default();
    let mut out = Vec::new();
    let code = execute_cli(
        &runner,
        &backend,
        &args,
        passing_executor,
        |l| out.push(l.to_string()),
        |_| {},
    );
    assert_eq!(code, 0);
    assert!(out.join("\n").contains("3 total") || out.join("\n").contains("total"));
}

// ---------------------------------------------------------------------------
// 4. backend truth: external + ambient LOOM_TEST_POSTGRES_URL ≠ trusted postgresql
// ---------------------------------------------------------------------------

#[test]
#[allow(clippy::too_many_lines)]
fn backend_truth_external_not_upgraded_by_ambient_pg() {
    // Harness layer: generic LoomClient harness is external even when PG env exists conceptually
    let harness =
        loom_validator::BackendHarness::connect(BackendKind::LoomClient, "http://localhost:8080")
            .unwrap();
    assert_eq!(harness.backend_evidence(), BackendEvidence::External);
    assert!(!harness.backend_evidence().is_trusted());
    assert_eq!(
        harness.start("CV-001").backend_evidence(),
        BackendEvidence::External
    );

    // InMemory and PostgreSQL harnesses keep distinct trusted classes
    let inmem =
        loom_validator::BackendHarness::connect(BackendKind::InMemory, "http://localhost:8080")
            .unwrap();
    assert_eq!(inmem.backend_evidence(), BackendEvidence::InMemory);
    let pg = loom_validator::BackendHarness::connect_with_evidence(
        BackendEvidence::PostgreSQL,
        "http://localhost:8080",
    )
    .unwrap();
    assert_eq!(pg.backend_evidence(), BackendEvidence::PostgreSQL);
    assert!(pg.backend_evidence().is_trusted());

    // CLI subprocess: generic endpoint with VALID and MALFORMED ambient PG URL stays external
    let bin = env!("CARGO_BIN_EXE_loom-validator");
    for pg_url in [
        "postgresql://loom:loom@127.0.0.1:5432/loom",
        "not-a-postgres-url",
    ] {
        let report_path = std::env::temp_dir().join(format!(
            "loom-validator-authority-gate-backend-{}-{}.json",
            std::process::id(),
            pg_url.len()
        ));
        let output = Command::new(bin)
            .env("LOOM_VALIDATOR_BASE_URL", "http://127.0.0.1:1")
            .env("LOOM_TEST_POSTGRES_URL", pg_url)
            .args([
                "--scenario",
                "CV-001",
                "--json",
                report_path.to_str().unwrap(),
            ])
            .output()
            .expect("validator binary should execute");
        assert!(
            output.status.success(),
            "generic endpoint should be reported, not runner error: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        let report = std::fs::read_to_string(&report_path).expect("report should be written");
        let value: serde_json::Value = serde_json::from_str(&report).expect("valid JSON");
        assert_eq!(
            value["backend_evidence"], "external",
            "pg_url={pg_url} report={value}"
        );
        assert_eq!(value["backend_evidence_trusted"], false);
        assert_eq!(value["run"]["backend_evidence"], "external");
        assert_eq!(value["results"][0]["backend_evidence"], "external");
        assert_ne!(
            value["backend_evidence"], "postgresql",
            "ambient PG must not upgrade external"
        );
        let _ = std::fs::remove_file(&report_path);
    }

    // CLI subprocess with required-live: external still fails even with valid PG URL
    for pg_url in [
        "postgresql://loom:loom@127.0.0.1:5432/loom",
        "not-a-postgres-url",
    ] {
        let report_path = std::env::temp_dir().join(format!(
            "loom-validator-authority-gate-req-live-ext-{}-{}.json",
            std::process::id(),
            pg_url.len()
        ));
        let output = Command::new(bin)
            .env("LOOM_VALIDATOR_BASE_URL", "http://127.0.0.1:1")
            .env("LOOM_TEST_POSTGRES_URL", pg_url)
            .args([
                "--required-live",
                "--scenario",
                "CV-001",
                "--json",
                report_path.to_str().unwrap(),
            ])
            .output()
            .unwrap();
        assert_eq!(
            output.status.code(),
            Some(1),
            "external endpoint must fail required-live even with pg_url={pg_url}"
        );
        let report = std::fs::read_to_string(&report_path).unwrap();
        let value: serde_json::Value = serde_json::from_str(&report).unwrap();
        assert_eq!(value["backend_evidence"], "external");
        assert_eq!(value["run"]["policy"]["required_live"], true);
        let _ = std::fs::remove_file(report_path);
    }
}

// ---------------------------------------------------------------------------
// 5. restart truth: reconnect-only cannot fake real restart; controlled passes
// ---------------------------------------------------------------------------

#[test]
#[allow(clippy::too_many_lines)]
fn restart_truth_reconnect_only_cannot_fake_and_controlled_passes() {
    let cv003 = loom_validator::lifecycle_registry()
        .get("CV-003")
        .expect("CV-003 registered")
        .clone();
    let cv004 = loom_validator::lifecycle_registry()
        .get("CV-004")
        .expect("CV-004 registered")
        .clone();

    // Generic reconnect-only context cannot pass CV-003/CV-004
    let client = LoomClient::builder("http://127.0.0.1:8080".to_string())
        .build()
        .unwrap();
    let ctx = BackendContext::new(client);
    assert_eq!(ctx.restart_capability(), RestartCapability::ReconnectOnly);
    assert!(!ctx.can_perform_boundary_restart());

    // Also prove InMemory kind with reconnect-only still blocks (backend vs restart orthogonal)
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

    for (id, desc) in [("CV-003", cv003.clone()), ("CV-004", cv004.clone())] {
        let result = loom_validator::execute_lifecycle(&desc, &ctx);
        assert!(
            !result.outcome().is_pass(),
            "{id} reconnect-only must not pass: {result:?}"
        );
        assert!(
            result.outcome().is_unavailable() || result.outcome().is_skipped(),
            "{id} should be unavailable/skipped"
        );
        let evidence = result
            .finding()
            .evidence()
            .iter()
            .map(|e| e.as_str())
            .collect::<Vec<_>>()
            .join(",");
        assert!(
            evidence.contains("reconnect-only"),
            "{id} evidence must contain reconnect-only: {evidence}"
        );
        assert!(
            !evidence.contains("controlled-boundary-restart"),
            "{id} must not claim controlled restart: {evidence}"
        );
        assert!(
            result
                .finding()
                .actual()
                .to_ascii_lowercase()
                .contains("reconnect-only"),
            "{id} actual must state reconnect-only"
        );

        // InMemory kind but reconnect-only still blocked → independence proof
        let result2 = loom_validator::execute_lifecycle(&desc, &ctx_inmem_reconnect);
        assert!(
            !result2.outcome().is_pass(),
            "{id} InMemory kind reconnect-only still blocked"
        );
    }

    // Reconnect remains reconnect-only after restart
    let client = LoomClient::builder("http://127.0.0.1:8080".to_string())
        .build()
        .unwrap();
    let ctx = BackendContext::new(client);
    let new_client = ctx
        .restart()
        .expect("reconnect should succeed parsing base URL");
    assert_eq!(ctx.restart_capability(), RestartCapability::ReconnectOnly);
    let ctx2 = BackendContext::new(new_client);
    assert_eq!(ctx2.restart_capability(), RestartCapability::ReconnectOnly);
    assert!(!ctx2.can_perform_boundary_restart());
    let ctx3 = BackendContext::new(
        LoomClient::builder("http://127.0.0.1:8080".to_string())
            .build()
            .unwrap(),
    )
    .with_restart_strategy(Arc::new(|| {
        LoomClient::new("http://127.0.0.1:8080".to_string()).map_err(|e| e.to_string())
    }));
    assert_eq!(ctx3.restart_capability(), RestartCapability::ReconnectOnly);

    // Controlled InMemory harness genuinely rebuilds boundary and passes CV-003
    let (server, client) = common::InMemoryServer::start().expect("in-memory service should start");
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
    let result = loom_validator::execute_lifecycle(&cv003, &ctx);
    assert!(
        result.outcome().is_pass(),
        "controlled InMemory CV-003 must pass on real rebuilt boundary: {result:?}"
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
        "controlled InMemory evidence must contain controlled marker: {evidence}"
    );
    assert!(
        result.finding().actual().contains("controlled"),
        "controlled actual must mention controlled: {}",
        result.finding().actual()
    );

    // Controlled PostgreSQL seam: capability distinguishes from evidence
    let controlled_pg_ctx = BackendContext::new(
        LoomClient::builder("http://127.0.0.1:8080".to_string())
            .build()
            .unwrap(),
    )
    .with_backend_kind(BackendKind::PostgreSQL)
    .with_controlled_boundary_restart();
    assert_eq!(
        controlled_pg_ctx.restart_capability(),
        RestartCapability::ControlledBoundaryRestart
    );
    assert!(controlled_pg_ctx.can_perform_boundary_restart());

    if let Ok((pg_server, pg_client)) = common::PgServer::start() {
        let server_for_restart = pg_server.clone();
        let strategy: Arc<dyn Fn() -> Result<LoomClient, String> + Send + Sync> =
            Arc::new(move || server_for_restart.restart());
        let ctx = BackendContext::new(pg_client)
            .with_backend_kind(BackendKind::PostgreSQL)
            .with_restart_strategy(strategy)
            .with_controlled_boundary_restart();
        let result = loom_validator::execute_lifecycle(&cv003, &ctx);
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
                "controlled PG evidence must contain controlled marker: {evidence}"
            );
        } else {
            assert!(
                !result.finding().actual().contains("reconnect-only")
                    || result.finding().actual().contains("controlled"),
                "controlled PG should not be reported as reconnect-only: {}",
                result.finding().actual()
            );
        }
    } else {
        // Without live PG, generic PG reconnect-only must still be blocked
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
        assert_eq!(generic_pg.backend_evidence(), BackendEvidence::PostgreSQL);
        let result = loom_validator::execute_lifecycle(&cv003, &generic_pg);
        assert!(!result.outcome().is_pass());
        assert!(result.finding().actual().contains("reconnect-only"));
    }

    // Subprocess generic CLI report must not claim pass for restart-sensitive scenario
    let bin = env!("CARGO_BIN_EXE_loom-validator");
    let report_path = std::env::temp_dir().join(format!(
        "loom-validator-authority-gate-restart-generic-{}.json",
        std::process::id()
    ));
    let output = Command::new(bin)
        .env("LOOM_VALIDATOR_BASE_URL", "http://127.0.0.1:8080")
        .env(
            "LOOM_TEST_POSTGRES_URL",
            "postgresql://loom:loom@127.0.0.1:5432/loom",
        )
        .args([
            "--scenario",
            "CV-003",
            "--json",
            report_path.to_str().unwrap(),
        ])
        .output()
        .unwrap();
    assert!(
        output.status.success() || output.status.code() == Some(0),
        "generic CLI report should be written, not runner error"
    );
    let report = std::fs::read_to_string(&report_path).unwrap();
    let value: serde_json::Value = serde_json::from_str(&report).unwrap();
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
            "generic external CV-003 must not pass as real restart: {value}"
        );
    }
    let report_str = report.to_ascii_lowercase();
    assert!(
        report_str.contains("reconnect-only"),
        "generic report must mention reconnect-only"
    );
    assert!(
        !report_str.contains("controlled-boundary-restart")
            || report_str.contains("reconnect-only"),
        "must not claim controlled without reconnect-only qualification"
    );
    let _ = std::fs::remove_file(report_path);
}

// ---------------------------------------------------------------------------
// 6. required-live truth: only trusted postgresql passes
// ---------------------------------------------------------------------------

#[test]
#[allow(clippy::too_many_lines)]
fn required_live_truth_only_controlled_postgres_satisfies() {
    use loom_validator::{
        CliArgs, EXIT_RUNNER_ERROR, EXIT_SCENARIO_FAILURE, EXIT_SUCCESS, execute_cli,
    };

    let runner = Runner::new(small_registry_two());

    // required-live + all Pass controlled PostgreSQL => exit 0
    let pg = pg_backend();
    let args = CliArgs {
        scenario_ids: vec!["CV-001,CV-002".to_string()],
        required_live: true,
        ..Default::default()
    };
    let code = execute_cli(&runner, &pg, &args, passing_aware, |_| {}, |_| {});
    assert_eq!(
        code, EXIT_SUCCESS,
        "PostgreSQL + all Pass must satisfy required-live"
    );

    // required-live + all Pass external => exit 1
    let ext = test_backend();
    let code = execute_cli(&runner, &ext, &args, passing_aware, |_| {}, |_| {});
    assert_eq!(
        code, EXIT_SCENARIO_FAILURE,
        "External must NOT satisfy required-live"
    );

    // required-live + all Pass InMemory => exit 1
    let mem = inmemory_backend();
    let code = execute_cli(&runner, &mem, &args, passing_aware, |_| {}, |_| {});
    assert_eq!(
        code, EXIT_SCENARIO_FAILURE,
        "InMemory must NOT satisfy required-live"
    );

    // required-live + PostgreSQL + Skipped => exit 1
    let code = execute_cli(
        &runner,
        &pg,
        &CliArgs {
            scenario_ids: vec!["CV-001,CV-002".to_string()],
            required_live: true,
            ..Default::default()
        },
        |desc, ctx| {
            if desc.id_str() == "CV-001" {
                skipped_executor(desc, ctx)
            } else {
                passing_aware(desc, ctx)
            }
        },
        |_| {},
        |_| {},
    );
    assert_eq!(
        code, EXIT_SCENARIO_FAILURE,
        "Skipped must fail required-live even with PG"
    );

    // required-live + PostgreSQL + Unavailable => exit 1
    let code = execute_cli(
        &runner,
        &pg,
        &CliArgs {
            scenario_ids: vec!["CV-001".to_string()],
            required_live: true,
            ..Default::default()
        },
        unavailable_executor,
        |_| {},
        |_| {},
    );
    assert_eq!(code, EXIT_SCENARIO_FAILURE);

    // required-live + PostgreSQL + Fail => exit 1
    let code = execute_cli(&runner, &pg, &args, mixed_executor, |_| {}, |_| {});
    assert_eq!(code, EXIT_SCENARIO_FAILURE);

    // ambient PG cannot upgrade external: harness external still fails required-live
    let harness =
        loom_validator::BackendHarness::connect(BackendKind::LoomClient, "http://localhost:8080")
            .unwrap()
            .with_policy(ValidationPolicy::required_live());
    let selection = runner.resolve_ids(&["CV-001".to_string()]).unwrap();
    let report = runner.run_with_harness_selected(&selection, &harness, passing_aware, false);
    assert!(
        !report.gate_passes(),
        "harness external must fail required-live"
    );
    assert_eq!(report.backend_evidence(), Some(BackendEvidence::External));

    // selection errors remain exit 2 under required-live (not gate failure)
    let code = execute_cli(
        &runner,
        &pg,
        &CliArgs {
            scenario_ids: vec!["CV-999".to_string()],
            required_live: true,
            ..Default::default()
        },
        passing_aware,
        |_| {},
        |_| {},
    );
    assert_eq!(
        code, EXIT_RUNNER_ERROR,
        "unknown scenario with required-live must be exit 2"
    );

    let code = execute_cli(
        &runner,
        &pg,
        &CliArgs {
            groups: vec!["typo-group".to_string()],
            required_live: true,
            ..Default::default()
        },
        passing_aware,
        |_| {},
        |_| {},
    );
    assert_eq!(code, EXIT_RUNNER_ERROR);

    // single-pass preserved under required-live (no replay)
    let counts: RefCell<Vec<String>> = RefCell::new(Vec::new());
    let code = execute_cli(
        &runner,
        &pg,
        &CliArgs {
            scenario_ids: vec!["CV-001,CV-002".to_string()],
            required_live: true,
            fail_fast: false,
            ..Default::default()
        },
        |desc, ctx| {
            counts.borrow_mut().push(desc.id_str().to_string());
            passing_aware(desc, ctx)
        },
        |_| {},
        |_| {},
    );
    assert_eq!(code, EXIT_SUCCESS);
    assert_eq!(*counts.borrow(), vec!["CV-001", "CV-002"]);

    // Report layer: InMemory all Pass is not a required-live pass; strict Skipped/Unavailable also fails
    {
        use loom_validator::{Finding, ScenarioResult};
        let pg_pass = {
            let finding = Finding::new(
                loom_validator::ScenarioId::new("CV-014"),
                "live",
                "expected",
                "actual",
                BackendKind::PostgreSQL,
                "ctx",
                vec![],
                ScenarioOutcome::Pass,
            );
            ScenarioResult::new(
                loom_validator::ScenarioId::new("CV-014"),
                ScenarioOutcome::Pass,
                finding,
            )
        };
        let mem_pass = {
            let finding = Finding::new(
                loom_validator::ScenarioId::new("CV-014"),
                "in-memory",
                "expected",
                "actual",
                BackendKind::InMemory,
                "ctx",
                vec![],
                ScenarioOutcome::Pass,
            );
            ScenarioResult::new(
                loom_validator::ScenarioId::new("CV-014"),
                ScenarioOutcome::Pass,
                finding,
            )
        };
        assert!(
            !loom_validator::ValidationReport::from_results_with_policy(
                vec![mem_pass],
                ValidationPolicy::required_live()
            )
            .gate_passes(),
            "InMemory alone must not satisfy required-live"
        );
        assert!(
            loom_validator::ValidationReport::from_results_with_policy(
                vec![pg_pass.clone()],
                ValidationPolicy::required_live()
            )
            .gate_passes(),
            "PostgreSQL Pass must satisfy"
        );

        // Pass + Skipped with PG still fails
        let skipped = {
            let finding = Finding::new(
                loom_validator::ScenarioId::new("CV-015"),
                "needs db",
                "db present",
                "db missing",
                BackendKind::PostgreSQL,
                "ctx",
                vec![],
                ScenarioOutcome::Skipped {
                    reason: "missing prerequisite".to_string(),
                },
            );
            ScenarioResult::new(
                loom_validator::ScenarioId::new("CV-015"),
                ScenarioOutcome::Skipped {
                    reason: "missing prerequisite".to_string(),
                },
                finding,
            )
        };
        assert!(
            !loom_validator::ValidationReport::from_results_with_policy(
                vec![pg_pass, skipped],
                ValidationPolicy::required_live()
            )
            .gate_passes(),
            "Pass+Skipped must fail required-live"
        );
    }

    // Subprocess required-live with external endpoint fails even with valid/malformed PG URL
    let bin = env!("CARGO_BIN_EXE_loom-validator");
    for pg_url in [
        "postgresql://loom:loom@127.0.0.1:5432/loom",
        "not-a-postgres-url",
    ] {
        let report_path = std::env::temp_dir().join(format!(
            "loom-validator-authority-gate-req-live-{}-{}.json",
            std::process::id(),
            pg_url.len()
        ));
        let output = Command::new(bin)
            .env("LOOM_VALIDATOR_BASE_URL", "http://127.0.0.1:1")
            .env("LOOM_TEST_POSTGRES_URL", pg_url)
            .args([
                "--required-live",
                "--scenario",
                "CV-001",
                "--json",
                report_path.to_str().unwrap(),
            ])
            .output()
            .unwrap();
        assert_eq!(
            output.status.code(),
            Some(1),
            "external must fail required-live even with pg_url {pg_url}"
        );
        let report = std::fs::read_to_string(&report_path).unwrap();
        let value: serde_json::Value = serde_json::from_str(&report).unwrap();
        assert_eq!(value["backend_evidence"], "external");
        assert_eq!(value["backend_evidence_trusted"], false);
        assert_ne!(value["backend_evidence"], "postgresql");
        assert_eq!(value["run"]["policy"]["required_live"], true);
        let _ = std::fs::remove_file(report_path);
    }
}

// ---------------------------------------------------------------------------
// Integrated gate smoke: one test that explicitly names the six classes
// and fails if any is not exercised. This guarantees the gate binary
// itself proves closure together.
// ---------------------------------------------------------------------------

#[test]
#[allow(clippy::too_many_lines)]
fn stage1_authority_gate_all_six_classes_are_exercised_together() {
    // This single test orchestrates the six proofs via library calls,
    // ensuring they are not merely separate binaries. It re-asserts the
    // critical invariants that define Stage-1 closure.

    // 1) single-pass: report derives from exactly one execution pass
    {
        let runner = Runner::new(small_registry_two());
        let backend = test_backend();
        let selection = runner.resolve_ids(&["CV-001,CV-002".to_string()]).unwrap();
        let run_count: RefCell<usize> = RefCell::new(0);
        let report = runner.run_selected(
            &selection,
            &backend,
            |desc, ctx| {
                *run_count.borrow_mut() += 1;
                passing_executor(desc, ctx)
            },
            false,
        );
        assert_eq!(
            *run_count.borrow(),
            2,
            "single-pass normal must invoke exactly twice"
        );
        assert_eq!(report.scenario_count(), 2);
    }

    // 2) strict truth:Unavailable never passes strict gate
    {
        let r = loom_validator::ValidationReport::from_results_with_policy(
            vec![loom_validator::ScenarioResult::unavailable(
                loom_validator::ScenarioId::new("CV-099"),
                "live",
                BackendKind::PostgreSQL,
                "missing",
            )],
            ValidationPolicy::strict(),
        );
        assert!(!r.gate_passes(), "Unavailable must fail strict");
    }

    // 3) selection truth: unknown group is exit 2 via runner
    {
        let runner = Runner::new(small_registry());
        let err = runner
            .resolve_with_groups(&[], &["typo-group".to_string()], false)
            .unwrap_err();
        assert!(format!("{err}").contains("unknown group"));
    }

    // 4) backend truth: external evidence is not upgraded
    {
        let harness = loom_validator::BackendHarness::connect(
            BackendKind::LoomClient,
            "http://localhost:8080",
        )
        .unwrap();
        assert_eq!(harness.backend_evidence(), BackendEvidence::External);
        assert!(!harness.backend_evidence().is_trusted());
    }

    // 5) restart truth: reconnect-only vs controlled are distinct
    {
        let generic = BackendContext::new(
            LoomClient::builder("http://127.0.0.1:8080".to_string())
                .build()
                .unwrap(),
        );
        assert_eq!(
            generic.restart_capability(),
            RestartCapability::ReconnectOnly
        );
        let controlled = BackendContext::new(
            LoomClient::builder("http://127.0.0.1:8080".to_string())
                .build()
                .unwrap(),
        )
        .with_controlled_boundary_restart();
        assert_eq!(
            controlled.restart_capability(),
            RestartCapability::ControlledBoundaryRestart
        );
        assert!(controlled.can_perform_boundary_restart());
        assert!(!generic.can_perform_boundary_restart());
    }

    // 6) required-live truth: only PostgreSQL passes
    {
        let pg_report = loom_validator::ValidationReport::from_results_with_policy(
            vec![{
                let finding = Finding::new(
                    loom_validator::ScenarioId::new("CV-100"),
                    "live",
                    "expected",
                    "actual",
                    BackendKind::PostgreSQL,
                    "ctx",
                    vec![],
                    ScenarioOutcome::Pass,
                );
                ScenarioResult::new(
                    loom_validator::ScenarioId::new("CV-100"),
                    ScenarioOutcome::Pass,
                    finding,
                )
            }],
            ValidationPolicy::required_live(),
        );
        assert!(pg_report.gate_passes());

        let ext_report = loom_validator::ValidationReport::from_results_with_policy(
            vec![{
                let finding = Finding::new(
                    loom_validator::ScenarioId::new("CV-101"),
                    "ext",
                    "expected",
                    "actual",
                    BackendKind::LoomClient,
                    "ctx",
                    vec![],
                    ScenarioOutcome::Pass,
                );
                ScenarioResult::new(
                    loom_validator::ScenarioId::new("CV-101"),
                    ScenarioOutcome::Pass,
                    finding,
                )
            }],
            ValidationPolicy::required_live(),
        );
        assert!(!ext_report.gate_passes());
    }

    // Gate marker: if we reach here, all six were exercised in one invocation.
    // The binary name itself is the gate proof.
}
