#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DEFAULT_POSTGRES_URL="postgresql://loom:loom@127.0.0.1:15432/loom_control"
export LOOM_TEST_POSTGRES_URL="${LOOM_TEST_POSTGRES_URL:-$DEFAULT_POSTGRES_URL}"
REPORT_PATH="${LOOM_T20_REPORT_PATH:-target/validator/t20-pg18-live-gate.json}"
mkdir -p "$(dirname "$REPORT_PATH")"

# The repository-managed default is started on demand. An explicit URL is
# caller-owned (the CI job supplies its ephemeral service) and is never
# replaced or silently downgraded.
if [[ "$LOOM_TEST_POSTGRES_URL" == "$DEFAULT_POSTGRES_URL" ]]; then
  bash tools/postgres-test.sh up
fi

# Each entry is: CV ID | integration target | exact test filter. The list is
# the explicit PG-mandatory set frozen by T08 and is intentionally independent
# of supported_backends metadata.
CASES=(
  "CV-014|world_binding|cv014_revision_activation_preserves_binding_on_live_postgres_with_r2_when_configured"
  "CV-016|action_ingress|cv016_via_pg_with_restart_if_available"
  "CV-022|world_time|cv022_due_work_blocks_advance_on_live_postgres_and_survives_restart"
  "CV-023|world_time|cv023_chronology_reconstructs_after_live_postgres_restart"
  "CV-030|semantic_blob|cv030_pinned_read_pass_on_live_postgres"
  "CV-031|provenance|cv031_event_session_revision_survives_live_postgres_restart"
  "CV-032|provenance|cv032_new_session_uses_r2_and_live_postgres_history_does_not_drift"
  "CV-033|provenance|cv033_proves_public_provenance_through_live_postgres_restart"
  "CV-039|change_feed|cv038_to_cv040_pass_on_live_postgres_with_controlled_restart"
  "CV-040|change_feed|cv038_to_cv040_pass_on_live_postgres_with_controlled_restart"
)

rows_file="$(mktemp)"
logs_dir="$(mktemp -d)"
trap 'rm -f "$rows_file"; rm -rf "$logs_dir"' EXIT

gate_passes=true
for case_spec in "${CASES[@]}"; do
  IFS='|' read -r cv_id target test_filter <<<"$case_spec"
  command_text="cargo test -p loom-validator --test $target $test_filter -- --nocapture --test-threads=1"
  log_path="$logs_dir/$cv_id.log"
  echo "T20 $cv_id: $command_text"
  if bash -c "$command_text" >"$log_path" 2>&1; then
    # CV-014's existing integration test intentionally returns successfully
    # after recording an unavailable prerequisite. A certification gate must
    # reject that path rather than treating the test process exit as evidence.
    if [[ "$cv_id" == CV-014 ]] && grep -Eiq 'skipping.*postgres|postgres.*prerequisite|without live db' "$log_path"; then
      outcome="fail"
      gate_passes=false
      echo "  T20 $cv_id: prerequisite/unavailable path is not live evidence"
    else
      outcome="pass"
    fi
  else
    outcome="fail"
    gate_passes=false
  fi
  sed 's/^/  /' "$log_path"
  printf '%s\t%s\t%s\n' "$cv_id" "$outcome" "$command_text" >>"$rows_file"
done

export T20_ROWS_FILE="$rows_file"
export T20_REPORT_PATH="$REPORT_PATH"
export T20_GATE_PASSES="$gate_passes"
python3 - <<'PY'
import json
import os
from pathlib import Path

restart_required = {
    "CV-014", "CV-016", "CV-022", "CV-023", "CV-030",
    "CV-031", "CV-032", "CV-033", "CV-039", "CV-040",
}
rows = []
with open(os.environ["T20_ROWS_FILE"], encoding="utf-8") as source:
    for line in source:
        cv_id, outcome, command = line.rstrip("\n").split("\t", 2)
        rows.append({
            "cv_id": cv_id,
            "outcome": outcome,
            "trusted_backend_evidence_class": "postgresql" if outcome == "pass" else "unknown",
            "restart_capability": "controlled-boundary-restart",
            "restart_required": cv_id in restart_required,
            "restart_evidence": outcome == "pass" and cv_id in restart_required,
            "prerequisite_status": "satisfied" if outcome == "pass" else "failed",
            "live_pg_evidence_required": True,
            "command": command,
        })
report = {
    "schema_version": 1,
    "type": "loom-validator.pg18-live-gate",
    "gate": "VALR-T20",
    "command": "bash tools/validator-pg18-gate.sh",
    "backend_evidence": "postgresql",
    "backend_evidence_trusted": True,
    "live_pg_required_rows": [row["cv_id"] for row in rows],
    "rows": rows,
    "gate_passes": os.environ["T20_GATE_PASSES"] == "true",
}
path = Path(os.environ["T20_REPORT_PATH"])
path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(f"T20 PostgreSQL live matrix: {path}")
print(json.dumps(report, sort_keys=True))
PY

if [[ "$gate_passes" != true ]]; then
  echo "T20 PostgreSQL 18 live gate failed" >&2
  exit 1
fi
echo "T20 PostgreSQL 18 live gate passed: ${#CASES[@]} PG-required rows"
