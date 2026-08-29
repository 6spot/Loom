//! VALR-T20 deterministic `PostgreSQL` required-live certification gate.
//!
//! Every positive row below is produced by a production suite executor and is
//! evaluated by the existing `ValidationPolicy::required_live()` policy.
//! Cargo's process status is never used as row evidence.

mod common;

use std::{collections::BTreeSet, env, fs, path::PathBuf, sync::Arc};

use common::{PgR2Server, PgServer};
use loom_client::LoomClient;
use loom_validator::{
    BackendContext, BackendEvidence, BackendKind, EvidenceReference, Finding, RunMetadata, Runner,
    ScenarioDescriptor, ScenarioId, ScenarioOutcome, ScenarioResult, ValidationPolicy,
    ValidationReport, action_ingress, change_feed, provenance, semantic_blob, validator_registry,
    world_binding, world_time,
};
use serde_json::{Value, json};

const REQUIRED_IDS: [&str; 10] = [
    "CV-014", "CV-016", "CV-022", "CV-023", "CV-030", "CV-031", "CV-032", "CV-033", "CV-039",
    "CV-040",
];
const GATE_COMMAND: &str = "bash tools/validator-pg18-gate.sh (cargo test -p loom-validator --test postgres_live_gate -- --nocapture --test-threads=1)";

fn descriptor(id: &str) -> ScenarioDescriptor {
    Runner::new(validator_registry())
        .resolve_selection(&[id.to_owned()], false)
        .expect("frozen T20 id must resolve")
        .into_iter()
        .next()
        .expect("frozen T20 id must select one descriptor")
        .clone()
}

trait Restartable: Clone + Send + Sync + 'static {
    fn restart(&self) -> Result<LoomClient, String>;
}
impl Restartable for PgServer {
    fn restart(&self) -> Result<LoomClient, String> {
        self.restart()
    }
}
impl Restartable for PgR2Server {
    fn restart(&self) -> Result<LoomClient, String> {
        self.restart()
    }
}
impl Restartable for common::t20::PumpServer {
    fn restart(&self) -> Result<LoomClient, String> {
        self.restart()
    }
}
impl Restartable for common::t20::ProvenanceServer {
    fn restart(&self) -> Result<LoomClient, String> {
        self.restart()
    }
}

fn context<T: Restartable>(client: LoomClient, server: T, scope: &str) -> BackendContext {
    let restart: Arc<dyn Fn() -> Result<LoomClient, String> + Send + Sync> =
        Arc::new(move || server.restart());
    BackendContext::new(client)
        .with_backend_kind(BackendKind::PostgreSQL)
        .with_scope(scope)
        .with_restart_strategy(restart)
        .with_controlled_boundary_restart()
}

fn run_one(id: &str) -> ScenarioResult {
    let result = match id {
        "CV-014" => {
            let (server, client) = PgR2Server::start().expect("CV-014 PG R2 fixture");
            world_binding::execute_world_binding(
                &descriptor(id),
                &context(client, server, "T20-CV-014"),
            )
        }
        "CV-016" => {
            let (server, client) =
                common::t20::PumpServer::start().expect("CV-016 PG pump fixture");
            let scenario = descriptor(id);
            let scenario_context = context(client, server.clone(), "T20-CV-016");
            let pump_driver = std::thread::spawn(move || {
                std::thread::sleep(std::time::Duration::from_millis(25));
                for _ in 0..200 {
                    server.pump_once().expect("CV-016 pump command");
                    std::thread::sleep(std::time::Duration::from_millis(25));
                }
            });
            let result = action_ingress::execute(&scenario, &scenario_context);
            pump_driver.join().expect("CV-016 pump driver");
            result
        }
        "CV-022" | "CV-023" => {
            let (server, client) = PgServer::start().expect("world-time PG fixture");
            world_time::execute(&descriptor(id), &context(client, server, id))
        }
        "CV-030" => {
            let (server, client) = PgServer::start().expect("semantic-blob PG fixture");
            semantic_blob::execute(&descriptor(id), &context(client, server, "T20-CV-030"))
        }
        "CV-031" | "CV-032" => {
            let (server, client) =
                common::t20::ProvenanceServer::start_neutral().expect("T16 neutral PG fixture");
            provenance::execute(&descriptor(id), &context(client, server, id))
        }
        "CV-033" => common::t20::run_cv033(),
        // CV-039 and CV-040 intentionally get separate contexts and separate
        // structured executor results; no aggregate test filter is used.
        "CV-039" | "CV-040" => {
            let (server, client) = PgServer::start().expect("change-feed PG fixture");
            change_feed::execute(&descriptor(id), &context(client, server, id))
        }
        _ => panic!("unexpected T20 id {id}"),
    };
    result.with_capability_area(descriptor(id).capability_area().as_str())
}

fn report_for(results: Vec<ScenarioResult>) -> ValidationReport {
    ValidationReport::from_results_with_policy(results, ValidationPolicy::required_live())
        .with_selected_scenario_ids(REQUIRED_IDS.iter().map(|id| (*id).to_owned()).collect())
        .with_backend_evidence(BackendEvidence::PostgreSQL)
        .with_run_metadata(
            RunMetadata::new("VALR-T20-PG18")
                .with_command(GATE_COMMAND)
                .with_evidence(EvidenceReference::path(
                    "target/validator/t20-pg18-live-gate.json",
                )),
        )
}

fn stable_finding_locator(result: &ScenarioResult) -> (&'static str, String) {
    let finding = result.finding();
    let scenario_id = result.scenario_id().as_str();
    if let Some(reference) = finding
        .evidence()
        .iter()
        .map(EvidenceReference::as_str)
        .find(|reference| reference.starts_with("validator:") && reference.contains(scenario_id))
    {
        return ("finding-evidence", reference.to_owned());
    }

    // CV-039 and CV-040 expose their independent scenario locator in Finding
    // context rather than in the evidence list. Keep that stable context
    // value, while deliberately excluding the rest of the runtime context.
    let context = finding.context();
    assert!(
        context.starts_with("validator:") && context.contains(scenario_id),
        "{} has no stable Finding locator: context={context:?} evidence={:?}",
        result.scenario_id(),
        finding.evidence()
    );
    ("finding-context", context.to_owned())
}

fn stable_restart_evidence_reference(result: &ScenarioResult) -> String {
    result
        .finding()
        .evidence()
        .iter()
        .map(EvidenceReference::as_str)
        .find(|reference| {
            reference.starts_with("restart_capability:")
                || reference.starts_with("validator:restart:")
        })
        .map_or_else(
            || {
                panic!(
                    "{} structured finding has no stable restart evidence: {:?}",
                    result.scenario_id(),
                    result.finding().evidence()
                )
            },
            ToOwned::to_owned,
        )
}

fn canonical_matrix_row(result: &ScenarioResult) -> Value {
    let finding = result.finding();
    let (evidence_reference_kind, evidence_reference) = stable_finding_locator(result);
    let restart_evidence_reference = stable_restart_evidence_reference(result);
    let restart_capability = restart_evidence_reference
        .strip_prefix("restart_capability:")
        .or_else(|| restart_evidence_reference.strip_prefix("validator:restart:"))
        .unwrap_or_else(|| {
            panic!(
                "{} stable restart evidence has no capability: {:?}",
                result.scenario_id(),
                restart_evidence_reference
            )
        });

    // The full structured result has already been checked by the required-live
    // policy and by the assertions in the live gate. Only this stable
    // projection is persisted; runtime actual/context/evidence values are
    // intentionally not part of the canonical digest input.
    json!({
        "cv_id": result.scenario_id().as_str(),
        "outcome": result.outcome().as_str(),
        "backend": finding.backend().as_str(),
        "trusted_backend_evidence_class": finding.backend().evidence().as_str(),
        "backend_evidence_trusted": finding.backend().evidence().is_trusted(),
        "evidence_reference": evidence_reference,
        "evidence_reference_kind": evidence_reference_kind,
        "restart_capability": restart_capability,
        "restart_evidence": {
            "class": restart_capability,
            "reference": restart_evidence_reference,
        },
        "prerequisite_status": result.outcome().as_str(),
        "live_pg_evidence_required": true,
        "command": GATE_COMMAND,
    })
}

fn canonical_artifact(report: &ValidationReport, results: &[ScenarioResult]) -> Value {
    let backend_evidence = report
        .backend_evidence()
        .expect("required-live report backend evidence");
    let rows = results.iter().map(canonical_matrix_row).collect::<Vec<_>>();
    let canonical_counts = json!({
        "total": report.scenario_count(),
        "pass": report.passed_count(),
        "fail": report.failed_count(),
        "skipped": report.skipped_count(),
        "unavailable": report.unavailable_count(),
    });
    json!({
        "schema_version": 2,
        "type": "loom-validator.pg18-live-gate",
        "representation": "canonical-stable-evidence-projection",
        "gate": "VALR-T20",
        "command": GATE_COMMAND,
        "backend_evidence": backend_evidence.as_str(),
        "backend_evidence_trusted": backend_evidence.is_trusted(),
        "live_pg_required_rows": REQUIRED_IDS,
        "rows": rows,
        "validator_report": {
            "selected_scenario_ids": report.selected_scenario_ids(),
            "backend_evidence": backend_evidence.as_str(),
            "backend_evidence_trusted": backend_evidence.is_trusted(),
            "policy": {
                "required_live": report.policy().requires_live(),
                "strict": report.policy().is_strict(),
            },
            "counts": canonical_counts,
            "result_state": if report.gate_passes() { "pass" } else { "fail" },
            "source": "structured-validator-results",
        },
        "gate_passes": report.gate_passes(),
    })
}

fn report_path() -> PathBuf {
    env::var_os("LOOM_T20_REPORT_PATH").map_or_else(
        || PathBuf::from("target/validator/t20-pg18-live-gate.json"),
        PathBuf::from,
    )
}

#[test]
fn t20_live_gate_runs_exactly_ten_structured_required_live_rows() {
    let runner = Runner::new(validator_registry());
    let ids = REQUIRED_IDS
        .iter()
        .map(|id| (*id).to_owned())
        .collect::<Vec<_>>();
    let selection = runner
        .resolve_selection(&ids, false)
        .expect("T20 selection must resolve");
    assert_eq!(
        selection
            .iter()
            .map(|item| item.id_str())
            .collect::<Vec<_>>(),
        REQUIRED_IDS.to_vec()
    );

    let results = REQUIRED_IDS
        .iter()
        .map(|id| run_one(id))
        .collect::<Vec<_>>();
    assert_eq!(results.len(), REQUIRED_IDS.len());
    assert_eq!(
        results
            .iter()
            .map(|result| result.scenario_id().as_str())
            .collect::<Vec<_>>(),
        REQUIRED_IDS.to_vec()
    );
    assert!(
        results.iter().all(|result| result.outcome().is_pass()),
        "T20 live rows must all pass: {results:#?}"
    );

    let report = report_for(results.clone());
    assert!(
        report.gate_passes(),
        "required-live report rejected live rows: {}",
        report.serialize_json()
    );
    let rows = results.iter().map(canonical_matrix_row).collect::<Vec<_>>();
    let references = rows
        .iter()
        .map(|row| row["evidence_reference"].as_str().unwrap())
        .collect::<BTreeSet<_>>();
    assert_eq!(
        references.len(),
        REQUIRED_IDS.len(),
        "row evidence references must be unique"
    );
    let artifact = canonical_artifact(&report, &results);
    let path = report_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).expect("report directory");
    }
    fs::write(
        &path,
        serde_json::to_vec_pretty(&artifact).expect("report JSON"),
    )
    .expect("write T20 artifact");
    println!("T20 PostgreSQL live matrix: {}", path.display());
    println!(
        "{}",
        serde_json::to_string(&artifact).expect("compact report JSON")
    );
}

fn pass_fixture_result(actual: &str, runtime_evidence: &str) -> ScenarioResult {
    let id = ScenarioId::new("CV-014");
    let finding = Finding::new(
        id.clone(),
        "determinism fixture",
        "stable projection",
        actual,
        BackendKind::PostgreSQL,
        "validator:CV-014:postgresql",
        vec![
            EvidenceReference::new(runtime_evidence),
            EvidenceReference::new("validator:world_binding:CV-014"),
            EvidenceReference::new("restart_capability:controlled-boundary-restart"),
        ],
        ScenarioOutcome::Pass,
    );
    ScenarioResult::new(id, ScenarioOutcome::Pass, finding)
}

#[test]
fn canonical_projection_ignores_runtime_values_and_is_byte_stable() {
    let first = pass_fixture_result(
        "event_id=aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "runtime:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    );
    let second = pass_fixture_result(
        "event_id=bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "runtime:bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    );
    assert_ne!(first.finding().actual(), second.finding().actual());
    assert_ne!(first.finding().evidence(), second.finding().evidence());

    let canonical_bytes = |result: ScenarioResult| {
        let report = report_for(vec![result.clone()]);
        assert!(report.gate_passes());
        serde_json::to_vec(&canonical_artifact(&report, &[result]))
            .expect("canonical artifact should serialize")
    };
    let first_bytes = canonical_bytes(first);
    let second_bytes = canonical_bytes(second);
    assert_eq!(
        first_bytes, second_bytes,
        "runtime UUIDs must not alter canonical artifact bytes"
    );
    let canonical = String::from_utf8(first_bytes).expect("artifact is UTF-8");
    assert!(!canonical.contains("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"));
    assert!(!canonical.contains("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"));
}

fn fixture_result(outcome: ScenarioOutcome, backend: BackendKind) -> ScenarioResult {
    let id = ScenarioId::new("CV-999");
    let finding = Finding::new(
        id.clone(),
        "negative",
        "pass",
        "negative fixture",
        backend,
        "negative-test",
        vec![],
        outcome.clone(),
    );
    ScenarioResult::new(id, outcome, finding)
}

#[test]
fn t20_required_live_policy_is_fail_closed_for_zero_nonpass_and_ambient_evidence() {
    assert!(
        !ValidationReport::from_results_with_policy(Vec::new(), ValidationPolicy::required_live())
            .gate_passes(),
        "zero selected rows cannot pass"
    );
    for outcome in [
        ScenarioOutcome::Skipped {
            reason: "filter matched zero tests".to_owned(),
        },
        ScenarioOutcome::Unavailable {
            reason: "database unavailable".to_owned(),
        },
        ScenarioOutcome::Fail,
    ] {
        let report = ValidationReport::from_results_with_policy(
            vec![fixture_result(outcome, BackendKind::PostgreSQL)],
            ValidationPolicy::required_live(),
        );
        assert!(
            !report.gate_passes(),
            "non-pass outcome must fail closed: {report:?}"
        );
    }
    let external = ValidationReport::from_results_with_policy(
        vec![fixture_result(
            ScenarioOutcome::Pass,
            BackendKind::LoomClient,
        )],
        ValidationPolicy::required_live(),
    );
    assert!(
        !external.gate_passes(),
        "ambient/external pass cannot satisfy required-live"
    );
}
