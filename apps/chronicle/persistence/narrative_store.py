"""Frozen context, existing ReviewItems, and atomic derived narrative publication."""
from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone

from psycopg.types.json import Jsonb

import canonical_store
import chapter_store
import control_plane
import narrative_acceptance as acceptance
import narrative_contract as contract
import history_edition_store
import reading_projection
from common import PersistenceConflict, PersistenceError, sha256_bytes, sha256_json
from step_runner import StepInput


PLAN_TYPE = "narrative-plan"
STEP_ATTEMPT_TYPE = "narrative-step-attempt"
STEP_TYPE = "narrative-step"


class StepBudgetExhausted(PersistenceError):
    """A narrative model node used its frozen finite attempt budget."""


def _reviewed_person_states(conn, *, publication_id) -> list[dict]:
    """Return the reviewed, published state facts for one source chapter.

    Reads only the immutable T05 person-state index already bound to the
    source publication's stream. It never inspects the un-reviewed accepted
    candidate and never re-runs the projection, and it keeps the source
    ``phase_ids`` verbatim: the composite facts check sees traceable,
    version-fixed source material, and the program never infers a composite
    phase from a matching year or event name. A 0.1/0.2 source with no
    published manifest contributes nothing.
    """
    try:
        publication_uuid = uuid.UUID(str(publication_id))
    except (ValueError, TypeError, AttributeError):
        return []
    row = conn.execute(
        "SELECT m.manifest_sha FROM chronicle.person_state_manifests m"
        " WHERE %s = ANY (m.chapter_publication_ids)",
        (publication_uuid,),
    ).fetchone()
    if row is None:
        return []
    manifest_sha = row[0]
    rows = conn.execute(
        """
        SELECT p.person_id, p.name, i.item_kind, i.dimension, i.value,
               i.relation, i.target, i.qualification, i.certainty,
               i.reason_codes, i.phase_ids, i.operation, i.from_phase_id,
               i.to_phase_id, i.source_facts
        FROM chronicle.person_state_items i
        JOIN chronicle.person_state_unit_people p
          USING (manifest_sha, stream_id, unit_id, person_id)
        JOIN chronicle.reading_units u
          ON u.stream_id = i.stream_id AND u.unit_id = i.unit_id
        WHERE i.manifest_sha = %s AND u.publication_id = %s
        ORDER BY i.person_id, i.item_kind, i.item_ordinal, i.item_id
        """,
        (manifest_sha, publication_uuid),
    ).fetchall()
    return [
        {
            "person_id": row[0],
            "person_name": row[1],
            "item_kind": row[2],
            "dimension": row[3],
            "value": row[4],
            "relation": row[5],
            "target": row[6],
            "qualification": row[7],
            "certainty": row[8],
            "reason_codes": list(row[9] or []),
            "phase_ids": list(row[10] or []),
            "operation": row[11],
            "from_phase_id": row[12],
            "to_phase_id": row[13],
            "source_facts": list(row[14] or []),
        }
        for row in rows
    ]


def _validated_source_selection(conn, *, catalog_sha=None, publication_ids=None) -> dict:
    """Validate one immutable catalog snapshot and its selected publications.

    A catalog hash in a persisted narrative scope is a snapshot reference, not
    a claim that the snapshot is still the latest catalog. The catalog row and
    its publication sequence define the historical visibility boundary. This
    helper is shared by the read-side action projection and the mutating
    narrative queue, so an old-but-retained frozen scope cannot be advertised
    as runnable and then rejected merely because a newer catalog was appended.
    """
    if catalog_sha is None:
        catalog_sha = canonical_store.read_latest_catalog_sha256(conn)
    if not isinstance(catalog_sha, str) or not catalog_sha:
        raise PersistenceError("historical narrative requires a published source catalog")
    catalog_row = conn.execute(
        "SELECT payload, publication_sequence FROM chronicle.canonical_catalogs "
        "WHERE artifact_sha256 = %s",
        (catalog_sha,),
    ).fetchone()
    if catalog_row is None:
        raise PersistenceConflict("frozen source catalog is no longer available")
    catalog, publication_sequence = catalog_row
    if publication_sequence is None:
        raise PersistenceConflict("frozen source catalog has no publication sequence")
    if not isinstance(catalog, dict):
        raise PersistenceConflict("frozen source catalog is invalid")
    rows = conn.execute("""WITH latest AS (
        SELECT DISTINCT ON (p.document_id) p.document_id, p.revision_id
        FROM chronicle.chapter_publications p
        JOIN chronicle.document_revisions r ON r.revision_id = p.revision_id
        JOIN chronicle.canonical_catalogs c ON c.artifact_sha256 = p.catalog_sha256
        WHERE c.publication_sequence <= (SELECT publication_sequence FROM chronicle.canonical_catalogs WHERE artifact_sha256 = %s)
        ORDER BY p.document_id, r.revision_no DESC
    ) SELECT p.publication_id FROM latest s
      JOIN chronicle.chapter_publications p ON p.revision_id = s.revision_id
        ORDER BY p.document_id, p.chapter_id""", (catalog_sha,)).fetchall()
    available = [str(row[0]) for row in rows]
    if publication_ids is None:
        publication_ids = available
    elif (not isinstance(publication_ids, list) or any(not isinstance(item, str) for item in publication_ids)
          or len(set(publication_ids)) != len(publication_ids) or not set(publication_ids) <= set(available)):
        raise PersistenceError("choose distinct complete chapters from the frozen published sources")
    selected_publication_ids = sorted(publication_ids)
    if not selected_publication_ids or len(selected_publication_ids) > contract.MAX_CHAPTERS:
        raise PersistenceError("historical narrative scope must contain 1–16 complete published chapters; reduce scope, never truncate")
    return {
        "catalog_sha": catalog_sha,
        "catalog": catalog,
        "publication_ids": selected_publication_ids,
    }


def validate_source_scope(conn, *, catalog_sha, publication_ids) -> dict:
    """Validate a persisted narrative source scope without loading model data.

    This is intentionally read-only and uses the same catalog/publication
    validator as :func:`source_descriptors` and :func:`queue_narrative`.
    Callers may use the returned normalized IDs for metadata only; execution
    must still load the full descriptors before creating a job.
    """
    return _validated_source_selection(
        conn, catalog_sha=catalog_sha, publication_ids=publication_ids
    )


def source_descriptors(conn, *, catalog_sha=None, publication_ids=None, coverage=None) -> dict:
    """Select complete published chapters; never read unaccepted candidates."""
    selection = _validated_source_selection(
        conn, catalog_sha=catalog_sha, publication_ids=publication_ids
    )
    catalog_sha = selection["catalog_sha"]
    catalog = selection["catalog"]
    publication_ids = selection["publication_ids"]
    sources, selected_bundles = [], set()
    for publication_id in publication_ids:
        full = chapter_store.read_published_chapter(conn, publication_id=publication_id)
        row = conn.execute("SELECT checkpoint FROM chronicle.ingestion_job_stages WHERE job_id = %s AND stage = 'structure'", (full["job_id"],)).fetchone()
        chapters = (row[0] if row else {}).get("chapters", [])
        chapter = next((item for item in chapters if item["chapter_id"] == full["chapter_id"]), None)
        if chapter is None:
            raise PersistenceConflict("published chapter has no frozen natural-chapter bounds")
        title = conn.execute("SELECT title FROM chronicle.documents WHERE document_id = %s", (full["document_id"],)).fetchone()[0]
        bundles = conn.execute("SELECT bundle_label FROM chronicle.source_bundles WHERE artifact_sha256 = %s", (full["assembled_bundle_sha256"],)).fetchall()
        selected_bundles.update(row[0] for row in bundles)
        output = conn.execute("""SELECT payload FROM chronicle.ingestion_outputs
            WHERE job_id = %s AND artifact_type = 'assembled-source-bundle'
              AND artifact_sha256 = %s""", (full["job_id"], full["assembled_bundle_sha256"])).fetchone()
        if output is None:
            raise PersistenceConflict("published chapter has no frozen assembly mapping")
        local_map = output[0]["report"]["local_to_revision"]
        canonical = reading_projection.build_canonical_ref_map(catalog,
            bundle_label=reading_projection.bundle_label_for_revision(full["revision_id"]))
        source_refs = {}
        for collection in ("entities", "events"):
            source_refs[collection] = {}
            for record in full["artifact"]["candidate"]["bundle"].get(collection, []):
                local_ref = record["temp_id"]
                assembled_ref = local_map.get(f"({full['chapter_index']},{local_ref})")
                canonical_id = canonical[collection].get(assembled_ref)
                if canonical_id is None:
                    raise PersistenceConflict("published source record lost its canonical binding")
                source_refs[collection][local_ref] = canonical_id
        sources.append({**full, "title": chapter.get("title") or title, "document_title": title,
                        "bounds": chapter, "canonical_refs": source_refs,
                        "reviewed_person_states": _reviewed_person_states(
                            conn, publication_id=full["publication_id"]
                        )})
    identities = {}
    for kind, collection, table in (("entities", "canonical_entities", "staged_entities"), ("events", "canonical_events", "staged_events")):
        known = {}
        selected_ids = {value for source in sources for value in source["canonical_refs"][kind].values()}
        for item in catalog.get(collection, []):
            if item["canonical_id"] not in selected_ids:
                continue
            for representation in item.get("representations", []):
                if representation["bundle"] not in selected_bundles:
                    continue
                record = conn.execute(f"SELECT payload FROM chronicle.{table} WHERE bundle_label = %s AND record_ref = %s", (representation["bundle"], representation["ref"])).fetchone()
                if not record:
                    raise PersistenceConflict("catalog representation lost its immutable source")
                value = record[0]
                known.setdefault(item["canonical_id"], {
                    "name": value.get("canonical_name") or value.get("name") or value.get("title") or representation["ref"],
                    **({"kind": value.get("type") or "other"} if kind == "entities" else {}),
                })
        identities[kind] = known
    result = {"catalog_sha": catalog_sha, "sources": sources, **identities}
    if coverage is not None:
        if not isinstance(coverage, dict):
            raise PersistenceError("narrative coverage must be an object")
        result["coverage"] = copy.deepcopy(coverage)
    return result


def list_source_choices(conn, *, limit=50, offset=0):
    if type(limit) is not int or type(offset) is not int or not 1 <= limit <= 100 or offset < 0:
        raise PersistenceError("source selection requires limit 1–100 and a nonnegative offset")
    catalog = canonical_store.read_latest_catalog_sha256(conn)
    # This is a bounded operator directory. Production revalidates the selected IDs.
    rows = conn.execute("""WITH latest AS (
        SELECT DISTINCT ON (p.document_id) p.document_id, p.revision_id
        FROM chronicle.chapter_publications p JOIN chronicle.document_revisions r USING (revision_id)
        ORDER BY p.document_id, r.revision_no DESC
    ) SELECT p.publication_id, d.title, p.chapter_id, r.revision_no,
        (SELECT ch->>'title' FROM chronicle.ingestion_job_stages st,
            jsonb_array_elements(st.checkpoint->'chapters') ch
            WHERE st.job_id = p.job_id AND st.stage = 'structure' AND ch->>'chapter_id' = p.chapter_id),
        count(*) OVER ()
        FROM latest s JOIN chronicle.chapter_publications p ON p.revision_id = s.revision_id
        JOIN chronicle.chapter_artifacts a USING (artifact_sha256)
        JOIN chronicle.documents d ON d.document_id = p.document_id
        JOIN chronicle.document_revisions r ON r.revision_id = p.revision_id
        ORDER BY d.title, p.document_id, a.chapter_index LIMIT %s OFFSET %s""", (limit, offset)).fetchall()
    return {"catalog_sha": catalog, "items": [{"publication_id": str(r[0]), "document_title": r[1],
            "chapter_id": r[2], "revision_no": r[3], "title": r[4] or r[1]} for r in rows],
            "has_more": bool(rows and offset + len(rows) < rows[0][5]), "offset": offset}


def queue_narrative(
    conn, *, catalog_sha, publication_ids, model_selection=None, parent_job_id=None,
    coverage=None,
):
    """An ordinary IngestionJob reusing present over already published sources."""
    import resolve_publish
    with conn.transaction():
        resolve_publish.acquire_publish_lock(conn)
        if not isinstance(catalog_sha, str) or not isinstance(publication_ids, list):
            raise PersistenceError("a fixed source catalog is required")
        if parent_job_id is not None:
            parent = conn.execute(
                """SELECT revision_id, status, checkpoint
                   FROM chronicle.ingestion_jobs WHERE job_id = %s FOR UPDATE""",
                (parent_job_id,),
            ).fetchone()
            if parent is None:
                raise PersistenceError("unknown parent job")
            if parent[1] not in ("failed", "cancelled"):
                raise PersistenceConflict("only a failed or cancelled task can start a linked rerun")
            parent_scope = parent[2].get("narrative_scope") if isinstance(parent[2], dict) else None
            if (
                not isinstance(parent_scope, dict)
                or parent_scope.get("catalog_sha") != catalog_sha
                or parent_scope.get("publication_ids") != publication_ids
                or parent_scope.get("coverage") != coverage
            ):
                raise PersistenceConflict("narrative source selection changed; choose sources again")
        descriptors = source_descriptors(
            conn,
            catalog_sha=catalog_sha,
            publication_ids=publication_ids,
            coverage=coverage,
        )
        if parent_job_id is not None and parent[0] != uuid.UUID(descriptors["sources"][0]["revision_id"]):
            raise PersistenceConflict("narrative parent and source revision do not match")
        # Two expected review resumptions plus the ordinary three execution
        # attempts. Human gates must not consume every publication retry.
        job_id = control_plane.queue_job(conn, revision_id=uuid.UUID(descriptors["sources"][0]["revision_id"]), max_attempts=5)
        for stage in control_plane.STAGE_NAMES:
            if stage != "present":
                control_plane.advance_stage(conn, job_id=job_id, stage=stage, status="skipped")
        if coverage is not None and not isinstance(coverage, dict):
            raise PersistenceError("narrative coverage must be an object")
        scope = {"catalog_sha": catalog_sha, "publication_ids": publication_ids}
        if coverage is not None:
            scope["coverage"] = copy.deepcopy(coverage)
        conn.execute("UPDATE chronicle.ingestion_jobs SET checkpoint = %s WHERE job_id = %s",
                     (Jsonb({"narrative_scope": scope}), job_id))
        if model_selection is not None or parent_job_id is not None:
            if not isinstance(model_selection, dict):
                if model_selection is not None:
                    raise PersistenceError("narrative model selection must be an object")
            import studio_production
            request = {
                "version": "0.1",
                "model_selection": copy.deepcopy(model_selection),
                "parent_job_id": str(parent_job_id) if parent_job_id is not None else None,
            }
            control_plane.record_output(
                conn,
                job_id=job_id,
                revision_id=uuid.UUID(descriptors["sources"][0]["revision_id"]),
                artifact_type=studio_production.REQUEST_TYPE,
                artifact_sha256=sha256_json(request),
                payload=request,
            )
        return job_id


def job_scope(conn, job_id):
    row = conn.execute("SELECT checkpoint->'narrative_scope' FROM chronicle.ingestion_jobs WHERE job_id = %s", (job_id,)).fetchone()
    return row[0] if row else None


def build_context(descriptors: dict, revision_source) -> dict:
    """Load every full chapter through the same hash-verified revision reader."""
    sources, text_cache = [], {}
    for source_index, full in enumerate(descriptors["sources"], 1):
        job_id = full["job_id"]
        if job_id not in text_cache:
            text_cache[job_id] = revision_source(uuid.UUID(job_id))
        text, source_sha = text_cache[job_id]
        bounds = full["bounds"]
        if not 0 <= bounds["start"] < bounds["end"] <= len(text):
            raise PersistenceConflict("natural chapter bounds no longer match the source")
        chapter_text = text[bounds["start"]:bounds["end"]]
        artifact = full["artifact"]
        if source_sha != artifact["source_sha256"] or sha256_bytes(chapter_text.encode()) != artifact["normalized_sha256"]:
            raise PersistenceConflict("full chapter source hash differs from its accepted artifact")
        evidence = []
        for anchor in full["publication"].get("anchors", []):
            if not 0 <= anchor["start"] < anchor["end"] <= len(chapter_text) or chapter_text[anchor["start"]:anchor["end"]] != anchor["quote"]:
                raise PersistenceConflict("published evidence no longer matches its complete chapter")
            evidence.append({"id": "e_" + sha256_json([full["publication_id"], anchor["anchor_id"]])[:24],
                             "anchor_id": anchor["anchor_id"], "quote": anchor["quote"],
                             "start": anchor["start"], "end": anchor["end"]})
        if not evidence:
            raise PersistenceError("complete chapter has no published evidence anchors")
        sources.append({"source_id": f"source_{source_index:03}", "publication_id": full["publication_id"],
                        "document_id": full["document_id"], "source_metadata": artifact["candidate"]["bundle"]["source"],
                        "revision_id": full["revision_id"], "source_sha": source_sha,
                        "artifact_sha": full["artifact_sha256"], "title": full["title"],
                        "document_title": full["document_title"], "chapter_text": chapter_text,
                        "translation": [{"block_id": block["block_id"], "text": block["text"]}
                            for block in full["publication"]["translation_blocks"]],
                        "source_claims": [{key: value for key, value in record.items() if key not in {"extraction", "assessment", "kind"}}
                            for record in artifact["candidate"]["bundle"].get("claims", [])],
                        "source_entities": [{key: value for key, value in record.items() if key in {"temp_id", "type", "canonical_name", "aliases"}}
                            for record in artifact["candidate"]["bundle"].get("entities", [])],
                        "source_events": [{key: value for key, value in record.items() if key not in {"extraction", "kind"}}
                            for record in artifact["candidate"]["bundle"].get("events", [])],
                        # C2-R3-T08 composite input: the reviewed, version-fixed
                        # source state facts. They are attributable material for
                        # the facts check; the program never equates a source
                        # phase with a composite phase by year or event name.
                        "reviewed_person_states": list(full.get("reviewed_person_states") or []),
                        "canonical_refs": full["canonical_refs"], "evidence": evidence})
    result = {"schema": "chronicle.narrative-context", "version": contract.VERSION,
              "catalog_sha": descriptors["catalog_sha"], "sources": sources,
              "entities": descriptors["entities"], "events": descriptors["events"]}
    if isinstance(descriptors.get("coverage"), dict):
        result["coverage"] = copy.deepcopy(descriptors["coverage"])
    return result


def _narrative_job_revision(conn, job_id):
    row = conn.execute(
        "SELECT revision_id FROM chronicle.ingestion_jobs WHERE job_id = %s",
        (job_id,),
    ).fetchone()
    if row is None:
        raise PersistenceError(f"unknown narrative job {job_id}")
    return row[0]


def read_outputs(conn, *, job_id) -> list[dict]:
    """Read and hash-check every durable narrative plan/step output."""
    rows = conn.execute(
        """SELECT artifact_type, artifact_sha256, payload
           FROM chronicle.ingestion_outputs
           WHERE job_id = %s AND artifact_type LIKE 'narrative-%%'
           ORDER BY created_at, output_id""",
        (job_id,),
    ).fetchall()
    result = []
    for artifact_type, digest, payload in rows:
        if not isinstance(payload, dict) or sha256_json(payload) != digest:
            raise PersistenceConflict("narrative output hash drift")
        result.append({"artifact_type": artifact_type, "output_sha256": digest, **payload})
    return result


def freeze_pipeline(conn, *, job_id, worker, context, config) -> dict:
    """Freeze source context, prompt schemas and model choices for this job."""
    import resolve_publish

    if not isinstance(context, dict) or not isinstance(config, dict):
        raise PersistenceError("narrative pipeline requires a JSON context and model configuration")
    value = {
        "schema": "chronicle.narrative-plan",
        "version": contract.VERSION,
        "context": copy.deepcopy(context),
        "context_sha256": sha256_json(context),
        "config": copy.deepcopy(config),
        "pipeline_fingerprint": sha256_json({"context": context, "config": config}),
        "status": "frozen",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with conn.transaction():
        resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
        plans = [row for row in read_outputs(conn, job_id=job_id) if row["artifact_type"] == PLAN_TYPE]
        if plans:
            if len(plans) != 1 or any(
                plans[0].get(key) != value.get(key)
                for key in ("context", "context_sha256", "config", "pipeline_fingerprint")
            ):
                raise PersistenceConflict(
                    "narrative_pipeline_drift: source, prompt or model configuration is frozen for this job"
                )
            return plans[0]
        revision_id = _narrative_job_revision(conn, job_id)
        digest = sha256_json(value)
        control_plane.record_output_fenced(
            conn,
            job_id=job_id,
            revision_id=revision_id,
            worker=worker,
            artifact_type=PLAN_TYPE,
            artifact_sha256=digest,
            payload=value,
        )
        resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
    return {"artifact_type": PLAN_TYPE, "output_sha256": digest, **value}


def node_key(plan: dict, *, step: str, round: int, slot: str,
             data: dict, prompt: str, model_config: dict) -> str:
    return StepInput(
        pipeline_fingerprint=plan["pipeline_fingerprint"],
        step=step,
        round=round,
        slot=slot,
        data=data,
        prompt=prompt,
        model_config=model_config,
    ).fingerprint()


def begin_step_attempt(
    conn,
    *,
    job_id,
    worker,
    plan,
    step,
    round,
    slot,
    data,
    prompt,
    model_config,
    max_attempts,
    retryable=True,
    retry_prompt=None,
) -> tuple[dict, bool]:
    """Reuse a complete model node or reserve its next durable attempt."""
    import resolve_publish

    if not isinstance(max_attempts, int) or max_attempts < 1:
        raise PersistenceError("narrative step max_attempts must be positive")
    with conn.transaction():
        resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
        key = node_key(
            plan, step=step, round=round, slot=slot, data=data,
            prompt=prompt, model_config=model_config,
        )
        records = read_outputs(conn, job_id=job_id)
        results = [
            record for record in records
            if record["artifact_type"] == STEP_TYPE and record.get("node_key") == key
        ]
        completed = [record for record in results if record.get("status") == "completed"]
        if completed:
            if len(completed) != 1:
                raise PersistenceConflict("one narrative model node has multiple completed results")
            return completed[0], True
        invalid = [record for record in results if record.get("status") == "invalid"]
        previous = max(invalid, key=lambda record: record.get("attempt", 0)) if invalid else None
        starts = [
            record for record in records
            if record["artifact_type"] == STEP_ATTEMPT_TYPE and record.get("node_key") == key
        ]
        if previous is not None and not retryable:
            return previous, True
        if len(starts) >= max_attempts:
            raise StepBudgetExhausted(
                f"{step}/{slot}: {max_attempts} saved attempts exhausted"
            )
        actual_prompt = prompt
        if previous is not None:
            if retry_prompt is None:
                raise PersistenceError(f"{step}/{slot}: retry prompt adapter is required")
            actual_prompt = retry_prompt(prompt, previous)
        attempt = len(starts) + 1
        value = {
            "schema": "chronicle.narrative-step-attempt",
            "version": contract.VERSION,
            "pipeline_fingerprint": plan["pipeline_fingerprint"],
            "context_sha256": plan["context_sha256"],
            "node_key": key,
            "step": step,
            "round": round,
            "slot": slot,
            "attempt": attempt,
            "input_sha256": sha256_json(data),
            "model": model_config.get("model"),
            "model_config": copy.deepcopy(model_config),
            "prompt": actual_prompt,
            "base_prompt_sha256": sha256_json(prompt),
            "input": copy.deepcopy(data),
            "retry_of": previous["output_sha256"] if previous is not None else None,
            "status": "started",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        revision_id = _narrative_job_revision(conn, job_id)
        digest = sha256_json(value)
        control_plane.record_output_fenced(
            conn,
            job_id=job_id,
            revision_id=revision_id,
            worker=worker,
            artifact_type=STEP_ATTEMPT_TYPE,
            artifact_sha256=digest,
            payload=value,
        )
        resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
        return {"artifact_type": STEP_ATTEMPT_TYPE, "output_sha256": digest, **value}, False


def finish_step_attempt(
    conn,
    *,
    job_id,
    worker,
    attempt,
    raw_text,
    parsed,
    validation_errors,
    receipt,
    status,
    error=None,
) -> dict:
    """Persist the full response/diagnostic after a durable attempt start."""
    import resolve_publish

    if status not in {"completed", "invalid", "failed"}:
        raise PersistenceError("narrative step result has an invalid status")
    errors = list(validation_errors or [])
    value = {
        "schema": "chronicle.narrative-step",
        "version": contract.VERSION,
        **{
            key: attempt[key]
            for key in (
                "pipeline_fingerprint", "context_sha256", "node_key", "step",
                "round", "slot", "attempt", "input_sha256", "model",
            )
        },
        "attempt_sha256": attempt["output_sha256"],
        "raw_text": raw_text if isinstance(raw_text, str) else "",
        # Keep the historical names on the new record too; old review tooling
        # can inspect a narrative response without a compatibility write path.
        "raw_response": raw_text if isinstance(raw_text, str) else "",
        "parsed": copy.deepcopy(parsed),
        "validation_errors": errors,
        "validation_error": "; ".join(str(item) for item in errors) if errors else error,
        "receipt": copy.deepcopy(receipt) if isinstance(receipt, dict) else {},
        "status": status,
        "error": error,
    }
    with conn.transaction():
        resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
        records = read_outputs(conn, job_id=job_id)
        if any(
            record["artifact_type"] == STEP_TYPE
            and record.get("attempt_sha256") == attempt["output_sha256"]
            for record in records
        ):
            raise PersistenceConflict("narrative attempt already has a saved result")
        if not any(
            record["artifact_type"] == STEP_ATTEMPT_TYPE
            and record["output_sha256"] == attempt["output_sha256"]
            for record in records
        ):
            raise PersistenceConflict("narrative attempt has no durable start")
        revision_id = _narrative_job_revision(conn, job_id)
        digest = sha256_json(value)
        control_plane.record_output_fenced(
            conn,
            job_id=job_id,
            revision_id=revision_id,
            worker=worker,
            artifact_type=STEP_TYPE,
            artifact_sha256=digest,
            payload=value,
        )
        resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
    return {"artifact_type": STEP_TYPE, "output_sha256": digest, **value}


def _candidate_frontier(conn, job_id, kind):
    """Read the append-only current candidate for one job/kind."""
    if kind not in {"facts", "prose"}:
        raise PersistenceError("unknown narrative candidate kind")
    return conn.execute(
        """
        SELECT candidate_sha, context_payload, candidate_payload, review_id,
               model_version, upstream_candidate_sha, revision_no, parent_candidate_sha,
               context_sha
        FROM (
            SELECT candidate_sha, context_payload, candidate_payload, review_id,
                   model_version, upstream_candidate_sha, 0 AS revision_no,
                   NULL::text AS parent_candidate_sha, context_sha
            FROM chronicle.narrative_candidates
            WHERE job_id = %s AND kind = %s
            UNION ALL
            SELECT candidate_sha, context_payload, candidate_payload, review_id,
                   model_version, upstream_candidate_sha, revision_no,
                   parent_candidate_sha, context_sha
            FROM chronicle.narrative_candidate_versions
            WHERE job_id = %s AND kind = %s
        ) candidates
        ORDER BY revision_no DESC, candidate_sha DESC
        LIMIT 1
        """,
        (job_id, kind, job_id, kind),
    ).fetchone()


def _candidate_view(conn, job_id, kind, row):
    """Materialize one candidate row without silently moving its frontier."""
    review_id = row[3]
    review = conn.execute(
        "SELECT status, payload FROM chronicle.review_items WHERE review_id = %s",
        (review_id,),
    ).fetchone() if review_id is not None else None
    acceptance_row = conn.execute(
        """
        SELECT acceptance_id, acceptance_type, payload
        FROM chronicle.narrative_acceptances
        WHERE job_id = %s AND kind = %s AND candidate_sha256 = %s
        """,
        (job_id, kind, row[0]),
    ).fetchone()
    review_payload = review[1] if review and isinstance(review[1], dict) else {}
    acceptance_payload = (
        acceptance_row[2] if acceptance_row and isinstance(acceptance_row[2], dict) else None
    )
    if review is not None:
        status = review[0]
    elif acceptance_row is not None:
        status = "accepted"
    else:
        status = "unaccepted"
    return {
        "candidate_sha": row[0],
        "context": row[1],
        "candidate": row[2],
        "review_id": str(review_id) if review_id is not None else None,
        "status": status,
        "decision": review_payload.get("decision"),
        "model": row[4],
        "kind": kind,
        "review_payload": review_payload,
        "acceptance_id": str(acceptance_row[0]) if acceptance_row else None,
        "acceptance_type": acceptance_row[1] if acceptance_row else None,
        "acceptance": acceptance_payload,
        "upstream_candidate_sha": row[5],
        "revision_no": row[6],
        "parent_candidate_sha": row[7],
        "context_sha": row[8],
    }


def read_candidate(conn, job_id, kind):
    row = _candidate_frontier(conn, job_id, kind)
    return _candidate_view(conn, job_id, kind, row) if row else None


def _dismiss_current_candidate_review(conn, *, job_id, kind, superseded_by):
    """Dismiss an open gate when an immutable replacement supersedes it."""
    row = _candidate_frontier(conn, job_id, kind)
    if not row or row[3] is None:
        return
    status = conn.execute(
        "SELECT status FROM chronicle.review_items WHERE review_id = %s",
        (row[3],),
    ).fetchone()
    if status is None or status[0] != "open":
        return
    review_id = uuid.UUID(str(row[3]))
    conn.execute(
        "UPDATE chronicle.review_items SET payload = payload || %s WHERE review_id = %s",
        (Jsonb({"superseded_by_revision": superseded_by}), review_id),
    )
    control_plane.resolve_review_item(conn, review_id=review_id, status="dismissed")


def _step_output_map(conn, job_id):
    return {
        (record["artifact_type"], record["output_sha256"]): record
        for record in read_outputs(conn, job_id=job_id)
    }


def _automatic_frontier(
    conn,
    *,
    job_id,
    kind,
    context,
    candidate,
    plan,
    candidate_records,
    comparison_records,
    issues,
):
    """Return whether the durable model frontier satisfies policy acceptance."""
    if not isinstance(plan, dict) or not candidate_records or list(issues or []):
        return None
    if plan.get("context_sha256") != sha256_json(context) or not plan.get("pipeline_fingerprint"):
        return None
    configured_steps = (plan.get("config") or {}).get("steps")
    if not isinstance(configured_steps, dict):
        return None

    def configured_slots(step):
        slots = configured_steps.get(step)
        return slots if isinstance(slots, list) and slots else None

    outputs = _step_output_map(conn, job_id)
    model_outputs = []
    generation_step = f"{kind}_generate"
    generation_slots = configured_slots(generation_step)
    if generation_slots is None or len(candidate_records) != len(generation_slots):
        return None
    if {item.get("slot") for item in candidate_records} != set(generation_slots):
        return None
    for item in candidate_records:
        if item.get("status") != "completed" or not item.get("output_sha256"):
            return None
        result = outputs.get((STEP_TYPE, item["output_sha256"]))
        if result is None or result.get("status") != "completed":
            return None
        if result.get("step") != generation_step:
            return None
        if result.get("pipeline_fingerprint") != plan["pipeline_fingerprint"] or result.get("context_sha256") != plan["context_sha256"]:
            return None
        if result.get("parsed") != item.get("parsed"):
            return None
        model_outputs.append(item["output_sha256"])
    selected = [item for item in candidate_records if item.get("parsed") == candidate]
    if not selected:
        return None

    model_opinions = []
    if len(candidate_records) > 1:
        if not comparison_records:
            return None
        comparison_step = f"{kind}_compare"
        comparison_slots = configured_slots(comparison_step)
        if comparison_slots is None or len(comparison_records) != len(comparison_slots):
            return None
        if {item.get("slot") for item in comparison_records} != set(comparison_slots):
            return None
        candidate_set = {item["output_sha256"] for item in candidate_records}
        selections = set()
        for item in comparison_records:
            if item.get("status") != "completed" or not item.get("output_sha256"):
                return None
            result = outputs.get((STEP_TYPE, item["output_sha256"]))
            if result is None or result.get("status") != "completed":
                return None
            if result.get("step") != comparison_step:
                return None
            if result.get("pipeline_fingerprint") != plan["pipeline_fingerprint"] or result.get("context_sha256") != plan["context_sha256"]:
                return None
            if result.get("parsed") != item.get("parsed"):
                return None
            parsed = item.get("parsed") if isinstance(item.get("parsed"), dict) else {}
            selected_sha = parsed.get("selected_sha256")
            if not isinstance(selected_sha, str) or selected_sha not in candidate_set:
                return None
            selections.add(selected_sha)
            if parsed.get("disagreements"):
                return None
            if any(
                isinstance(difference, dict) and difference.get("assessment") == "disputed"
                for difference in (parsed.get("differences") or [])
            ):
                return None
            model_opinions.append(item["output_sha256"])
        if len(selections) != 1:
            return None
        selected_sha = next(iter(selections))
        selected_candidate = next(
            (item for item in candidate_records if item.get("output_sha256") == selected_sha),
            None,
        )
        if selected_candidate is None or selected_candidate.get("parsed") != candidate:
            return None
    elif comparison_records:
        # The worker deliberately skips comparison when one complete candidate
        # exists; unexpected comparison evidence must not be silently ignored.
        return None
    return {
        "model_output_sha256s": model_outputs,
        "model_opinion_sha256s": model_opinions,
    }


def save_candidate(
    conn,
    *,
    job_id,
    worker,
    kind,
    context,
    candidate,
    model,
    plan=None,
    candidate_records=None,
    comparison_records=None,
    issues=None,
    upstream_candidate_sha=None,
):
    import resolve_publish
    with conn.transaction():
        resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
        existing = read_candidate(conn, job_id, kind)
        if existing and existing.get("upstream_candidate_sha") == upstream_candidate_sha:
            if existing["context"] != context or existing["candidate"] != candidate:
                raise PersistenceConflict(
                    "candidate frontier already contains a different draft for this input"
                )
            return existing
        if kind == "facts":
            contract.validate_facts(candidate, context)
        elif kind == "prose":
            fact_row = read_candidate(conn, job_id, "facts")
            if fact_row is None:
                raise PersistenceConflict("prose cannot be saved before facts")
            facts = approved_content(fact_row)
            contract.validate_prose(candidate, context, facts)
            if fact_row["context"] != context:
                raise PersistenceConflict("facts and prose use different frozen contexts")
        else:
            raise PersistenceError("unknown narrative candidate kind")
        resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
        digest = sha256_json({
            "job_id": str(job_id), "kind": kind, "context": context,
            "candidate": candidate, "upstream_candidate_sha": upstream_candidate_sha,
        })
        candidate_records = list(candidate_records or [])
        comparison_records = list(comparison_records or [])
        history = candidate_records + comparison_records
        review_payload = {
            "scope": "narrative", "stage": "present", "narrative_kind": kind,
            "candidate_sha": digest, "plan_version": "narrative-review-v1",
            "blocking": True, "allowed_decisions": ["approve", "reject", "revise"],
            "issues": copy.deepcopy(list(issues or [])),
            "candidate_count": len(candidate_records),
            "upstream_candidate_sha": upstream_candidate_sha,
            "candidates": [
                {
                    "output_sha256": item.get("output_sha256"),
                    "step": item.get("step"),
                    "slot": item.get("slot"),
                    "model": item.get("model"),
                    "status": item.get("status"),
                    "candidate": copy.deepcopy(item.get("parsed")),
                    "raw_text": item.get("raw_text"),
                    "validation_errors": list(item.get("validation_errors") or []),
                }
                for item in candidate_records
            ],
            "comparisons": [
                {
                    "output_sha256": item.get("output_sha256"),
                    "step": item.get("step"),
                    "slot": item.get("slot"),
                    "model": item.get("model"),
                    "status": item.get("status"),
                    "comparison": copy.deepcopy(item.get("parsed")),
                    "raw_text": item.get("raw_text"),
                    "validation_errors": list(item.get("validation_errors") or []),
                }
                for item in comparison_records
            ],
            "step_output_sha256s": [
                item.get("output_sha256") for item in history if item.get("output_sha256")
            ],
            "model_output_sha256s": [
                item.get("output_sha256") for item in candidate_records if item.get("output_sha256")
            ],
            "model_opinion_sha256s": [
                item.get("output_sha256") for item in comparison_records if item.get("output_sha256")
            ],
        }
        if plan is not None:
            review_payload["pipeline_fingerprint"] = plan.get("pipeline_fingerprint")
            review_payload["context_sha256"] = plan.get("context_sha256")
        automatic = _automatic_frontier(
            conn, job_id=job_id, kind=kind, context=context, candidate=candidate,
            plan=plan, candidate_records=candidate_records,
            comparison_records=comparison_records, issues=issues,
        )
        if existing:
            _dismiss_current_candidate_review(
                conn, job_id=job_id, kind=kind, superseded_by=digest
            )
        if kind == "facts":
            # A facts revision invalidates any prose gate bound to the old
            # facts frontier.  The worker will regenerate prose after the new
            # facts acceptance; the stale gate must not block resume.
            prose_row = read_candidate(conn, job_id, "prose")
            if prose_row and prose_row.get("upstream_candidate_sha") != digest:
                _dismiss_current_candidate_review(
                    conn, job_id=job_id, kind="prose", superseded_by=digest
                )
        review_id = None
        if automatic is None:
            review_payload["acceptance_mode"] = "exception_review"
            review_payload["pending_issues"] = copy.deepcopy(list(issues or []))
            review_id = control_plane.open_review_item(
                conn, job_id=job_id, kind="stage_gate", payload=review_payload
            )
        else:
            review_payload["acceptance_mode"] = "policy_model_review"
        if existing:
            parent_candidate_sha = existing["candidate_sha"]
            revision_no = int(existing.get("revision_no") or 0) + 1
            conn.execute("""INSERT INTO chronicle.narrative_candidate_versions
                (candidate_sha, job_id, kind, review_id, parent_candidate_sha, revision_no,
                 upstream_candidate_sha, context_sha, context_payload, candidate_payload, model_version)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (digest, job_id, kind, review_id, parent_candidate_sha, revision_no,
                 upstream_candidate_sha, sha256_json(context), Jsonb(context), Jsonb(candidate), model))
        else:
            conn.execute("""INSERT INTO chronicle.narrative_candidates
                (candidate_sha, job_id, kind, review_id, upstream_candidate_sha,
                 context_sha, context_payload, candidate_payload, model_version)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (digest, job_id, kind, review_id, upstream_candidate_sha,
                 sha256_json(context), Jsonb(context), Jsonb(candidate), model))
        if automatic is not None:
            receipt = acceptance.build_receipt(
                job_id=job_id, kind=kind, acceptance_type="policy_model_review",
                input_sha256=sha256_json(context), candidate_sha256=digest,
                content=candidate, pipeline_fingerprint=plan["pipeline_fingerprint"],
                model_output_sha256s=automatic["model_output_sha256s"],
                model_opinion_sha256s=automatic["model_opinion_sha256s"],
                decision_reason=(
                    "全部结构、语义、来源引用和模型比较均通过；"
                    "同一候选指纹的模型结果无未解决异议。"
                ),
            )
            acceptance.validate_receipt(receipt)
            acceptance_id = uuid.uuid4()
            conn.execute("""INSERT INTO chronicle.narrative_acceptances
                (acceptance_id, job_id, kind, acceptance_type, policy_version,
                 input_sha256, candidate_sha256, draft_sha256, content_sha256,
                 pipeline_fingerprint, model_output_sha256s, model_opinion_sha256s,
                 decision, decision_reason, review_id, payload)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (acceptance_id, job_id, kind, "policy_model_review", acceptance.POLICY_VERSION,
                 receipt["input_sha256"], receipt["candidate_sha256"], receipt["draft_sha256"],
                 receipt["content_sha256"], receipt["pipeline_fingerprint"],
                 receipt["model_output_sha256s"], receipt["model_opinion_sha256s"],
                 receipt["decision"], receipt["decision_reason"], None, Jsonb(receipt)))
        return read_candidate(conn, job_id, kind)


def read_last_attempt(conn, *, job_id, kind, context):
    """Continue corrections after a retry only within the same frozen input."""
    row = conn.execute("""SELECT payload FROM chronicle.ingestion_outputs
        WHERE job_id = %s AND artifact_type = %s AND payload->>'context_sha' = %s
        ORDER BY (payload->>'attempt_sequence')::integer DESC NULLS LAST,
                 created_at DESC, output_id DESC LIMIT 1""",
        (job_id, f"narrative-{kind}-attempt", sha256_json(context))).fetchone()
    return row[0] if row else None


def save_attempt(conn, *, job_id, worker, kind, context, prompt, response, model, error):
    """Keep bounded model diagnostics in the existing ingestion output log."""
    import resolve_publish
    with conn.transaction():
        resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
        revision = conn.execute("SELECT revision_id FROM chronicle.ingestion_jobs WHERE job_id = %s", (job_id,)).fetchone()[0]
        # The job row is locked by the lease fence. Repeated identical model
        # responses are still distinct attempts, not content-addressed cache hits.
        sequence = conn.execute("""SELECT count(*) + 1 FROM chronicle.ingestion_outputs
            WHERE job_id = %s AND artifact_type = %s""", (job_id, f"narrative-{kind}-attempt")).fetchone()[0]
        payload = {"kind": kind, "attempt_sequence": sequence, "context_sha": sha256_json(context),
                   "prompt_sha": sha256_bytes(prompt.encode()), "model": model,
                   "raw_response": response, "validation_error": error}
        control_plane.record_output_fenced(conn, job_id=job_id, revision_id=revision, worker=worker,
            artifact_type=f"narrative-{kind}-attempt", artifact_sha256=sha256_json(payload), payload=payload)


def approved_content(row):
    if not row:
        raise PersistenceConflict("narrative content has not been accepted")
    if row["status"] == "accepted":
        receipt = row.get("acceptance")
        if not isinstance(receipt, dict):
            raise PersistenceConflict("narrative acceptance receipt is missing")
        acceptance.validate_receipt(receipt)
        if (
            receipt.get("acceptance_type") != "policy_model_review"
            or receipt.get("input_sha256") != row.get("context_sha")
            or receipt.get("candidate_sha256") != row["candidate_sha"]
            or receipt.get("draft_sha256") != sha256_json(row["candidate"])
            or receipt.get("content_sha256") != sha256_json(row["candidate"])
        ):
            raise PersistenceConflict("automatic narrative acceptance is not bound to this candidate")
        return copy.deepcopy(row["candidate"])
    decision = row.get("decision")
    if row["status"] != "resolved" or not decision or decision.get("decision") != "approve":
        raise PersistenceConflict("narrative content has not been accepted")
    if sha256_json(decision.get("content")) != decision.get("content_sha"):
        raise PersistenceConflict("review content hash mismatch")
    receipt = row.get("acceptance")
    if (
        not isinstance(receipt, dict)
        or receipt.get("acceptance_type") != "human"
        or receipt.get("input_sha256") != row.get("context_sha")
        or receipt.get("candidate_sha256") != row["candidate_sha"]
        or receipt.get("draft_sha256") != sha256_json(row["candidate"])
        or receipt.get("content_sha256") != decision.get("content_sha")
        or receipt.get("review_id") != row.get("review_id")
        or decision.get("candidate_sha") != row["candidate_sha"]
        or decision.get("content") != row["candidate"]
    ):
        raise PersistenceConflict("human narrative acceptance receipt is missing or stale")
    acceptance.validate_receipt(receipt)
    return copy.deepcopy(decision["content"])


def review_detail(conn, review_id):
    row = conn.execute(
        """
        SELECT job_id, kind, candidate_sha, context_payload, candidate_payload,
               review_id, model_version, upstream_candidate_sha, 0 AS revision_no,
               NULL::text AS parent_candidate_sha, context_sha
        FROM chronicle.narrative_candidates WHERE review_id = %s
        UNION ALL
        SELECT job_id, kind, candidate_sha, context_payload, candidate_payload,
               review_id, model_version, upstream_candidate_sha, revision_no,
               parent_candidate_sha, context_sha
        FROM chronicle.narrative_candidate_versions WHERE review_id = %s
        LIMIT 1
        """,
        (review_id, review_id),
    ).fetchone()
    return _candidate_view(conn, row[0], row[1], row[2:]) if row else None


def decide(conn, *, review_id, candidate_sha, decision, rationale, content=None, reviewed_conclusion_ids=None):
    if not isinstance(decision, str) or decision not in {"approve", "reject"} or not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 4000:
        raise PersistenceError("narrative review requires approve/reject and a nonempty rationale up to 4000 characters")
    with conn.transaction():
        identity = conn.execute("SELECT job_id FROM chronicle.review_items WHERE review_id = %s", (review_id,)).fetchone()
        if not identity:
            raise PersistenceError("unknown narrative review")
        # Match the ordinary job-before-review lock order used by lifecycle operations.
        job = conn.execute("SELECT status FROM chronicle.ingestion_jobs WHERE job_id = %s FOR UPDATE", (identity[0],)).fetchone()
        conn.execute("SELECT review_id FROM chronicle.review_items WHERE review_id = %s FOR UPDATE", (review_id,))
        row = review_detail(conn, review_id)
        if job[0] not in {"running", "needs_review"}:
            raise PersistenceConflict("cannot decide a cancelled or terminal job")
        if not row or row["candidate_sha"] != candidate_sha or row["status"] != "open":
            raise PersistenceConflict("review is stale or already decided; reload the exact candidate")
        accepted = content if content is not None else row["candidate"]
        if decision == "approve":
            if accepted != row["candidate"]:
                raise PersistenceConflict(
                    "human edits require a new narrative draft; use revise_candidate before approval"
                )
            if row["kind"] == "facts":
                contract.validate_facts(accepted, row["context"])
                ids = [fact["id"] for fact in accepted["conclusions"]]
                if (not isinstance(reviewed_conclusion_ids, list) or
                    any(not isinstance(item, str) for item in reviewed_conclusion_ids) or
                    sorted(reviewed_conclusion_ids) != sorted(ids)):
                    raise PersistenceError("approve requires explicit review coverage for every conclusion")
            else:
                contract.validate_prose(accepted, row["context"], approved_content(read_candidate(conn, identity[0], "facts")))
        result = {"decision": decision, "rationale": rationale.strip(), "content": accepted,
                  "content_sha": sha256_json(accepted), "candidate_sha": candidate_sha,
                  "reviewed_conclusion_ids": reviewed_conclusion_ids or []}
        conn.execute("UPDATE chronicle.review_items SET payload = payload || %s WHERE review_id = %s", (Jsonb({"decision": result}), review_id))
        control_plane.resolve_review_item(conn, review_id=review_id)
        if decision == "approve":
            review_payload = row.get("review_payload") or {}
            model_outputs = list(review_payload.get("model_output_sha256s") or [
                item.get("output_sha256")
                for item in review_payload.get("candidates", [])
                if isinstance(item, dict) and item.get("output_sha256")
            ])
            model_opinions = list(review_payload.get("model_opinion_sha256s") or [
                item.get("output_sha256")
                for item in review_payload.get("comparisons", [])
                if isinstance(item, dict) and item.get("output_sha256")
            ])
            receipt = acceptance.build_receipt(
                job_id=identity[0], kind=row["kind"], acceptance_type="human",
                input_sha256=row["context_sha"], candidate_sha256=candidate_sha,
                content=accepted, pipeline_fingerprint=review_payload.get("pipeline_fingerprint"),
                model_output_sha256s=model_outputs, model_opinion_sha256s=model_opinions,
                decision_reason=rationale, review_id=review_id,
            )
            acceptance.validate_receipt(receipt)
            acceptance_id = uuid.uuid4()
            conn.execute("""INSERT INTO chronicle.narrative_acceptances
                (acceptance_id, job_id, kind, acceptance_type, policy_version,
                 input_sha256, candidate_sha256, draft_sha256, content_sha256,
                 pipeline_fingerprint, model_output_sha256s, model_opinion_sha256s,
                 decision, decision_reason, review_id, payload)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (acceptance_id, identity[0], row["kind"], "human", acceptance.POLICY_VERSION,
                 receipt["input_sha256"], receipt["candidate_sha256"], receipt["draft_sha256"],
                 receipt["content_sha256"], receipt["pipeline_fingerprint"],
                 receipt["model_output_sha256s"], receipt["model_opinion_sha256s"],
                 receipt["decision"], receipt["decision_reason"], review_id, Jsonb(receipt)))
        if decision == "reject":
            control_plane.cancel_job(conn, job_id=identity[0])
        return review_detail(conn, review_id)


def revise_candidate(
    conn,
    *,
    job_id,
    worker=None,
    kind,
    candidate_sha,
    content,
    rationale,
):
    """Append a human-edited draft and open a fresh review for it.

    The previous candidate and acceptance remain immutable.  Publication can
    only see the new frontier, so an old acceptance cannot accidentally
    authorize an edited draft or an old prose/facts pairing.
    """
    import resolve_publish

    if kind not in {"facts", "prose"}:
        raise PersistenceError("unknown narrative candidate kind")
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 4000:
        raise PersistenceError("narrative revision requires a nonempty rationale up to 4000 characters")
    with conn.transaction():
        if worker is not None:
            resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
        job = conn.execute(
            "SELECT status FROM chronicle.ingestion_jobs WHERE job_id = %s FOR UPDATE",
            (job_id,),
        ).fetchone()
        if job is None or job[0] not in {"running", "needs_review"}:
            raise PersistenceConflict("cannot revise a cancelled or terminal job")
        row = read_candidate(conn, job_id, kind)
        if not row or row["candidate_sha"] != candidate_sha:
            raise PersistenceConflict("revision is stale; reload the exact candidate frontier")
        if content == row["candidate"]:
            raise PersistenceError("revision must change the candidate draft")
        upstream_candidate_sha = row.get("upstream_candidate_sha")
        if kind == "facts":
            contract.validate_facts(content, row["context"])
        else:
            facts_row = read_candidate(conn, job_id, "facts")
            facts = approved_content(facts_row)
            contract.validate_prose(content, row["context"], facts)
            upstream_candidate_sha = facts_row["candidate_sha"]
        revision_no = int(row.get("revision_no") or 0) + 1
        digest = sha256_json({
            "job_id": str(job_id), "kind": kind, "context": row["context"],
            "candidate": content, "parent_candidate_sha": row["candidate_sha"],
            "revision_no": revision_no, "upstream_candidate_sha": upstream_candidate_sha,
        })
        previous_review = row.get("review_payload") or {}
        payload = copy.deepcopy(previous_review)
        # A resolved review's decision is evidence for the old candidate only;
        # never copy it into the new open gate created by a revision.
        payload.pop("decision", None)
        original_candidates = list(payload.get("candidates") or [])
        original_comparisons = list(payload.get("comparisons") or [])
        original_step_outputs = list(payload.get("step_output_sha256s") or [])
        original_issues = list(payload.get("issues") or [])
        if not original_candidates and isinstance(row.get("acceptance"), dict):
            # Automatic candidates have no ReviewItem, but a later human edit
            # still receives the complete original model frontier rather than
            # a thin pointer to it.
            output_map = _step_output_map(conn, job_id)
            receipt = row["acceptance"]
            payload["pipeline_fingerprint"] = receipt.get("pipeline_fingerprint")
            payload["context_sha256"] = receipt.get("input_sha256")
            for output_sha in receipt.get("model_output_sha256s") or []:
                result = output_map.get((STEP_TYPE, output_sha))
                if result is None:
                    continue
                original_candidates.append({
                    "output_sha256": output_sha,
                    "step": result.get("step"), "slot": result.get("slot"),
                    "model": result.get("model"), "status": result.get("status"),
                    "candidate": copy.deepcopy(result.get("parsed")),
                    "raw_text": result.get("raw_text"),
                    "validation_errors": list(result.get("validation_errors") or []),
                })
            for output_sha in receipt.get("model_opinion_sha256s") or []:
                result = output_map.get((STEP_TYPE, output_sha))
                if result is None:
                    continue
                original_comparisons.append({
                    "output_sha256": output_sha,
                    "step": result.get("step"), "slot": result.get("slot"),
                    "model": result.get("model"), "status": result.get("status"),
                    "comparison": copy.deepcopy(result.get("parsed")),
                    "raw_text": result.get("raw_text"),
                    "validation_errors": list(result.get("validation_errors") or []),
                })
            original_step_outputs = [
                *[item.get("output_sha256") for item in original_candidates if item.get("output_sha256")],
                *[item.get("output_sha256") for item in original_comparisons if item.get("output_sha256")],
            ]
        model_output_hashes = list(payload.get("model_output_sha256s") or [
            item.get("output_sha256") for item in original_candidates
            if isinstance(item, dict) and item.get("output_sha256")
        ])
        model_opinion_hashes = list(payload.get("model_opinion_sha256s") or [
            item.get("output_sha256") for item in original_comparisons
            if isinstance(item, dict) and item.get("output_sha256")
        ])
        payload.update({
            "scope": "narrative", "stage": "present", "narrative_kind": kind,
            "candidate_sha": digest, "parent_candidate_sha": row["candidate_sha"],
            "revision_no": revision_no, "review_mode": "manual_revision",
            "revision_rationale": rationale.strip(),
            "acceptance_mode": "exception_review", "blocking": True,
            "allowed_decisions": ["approve", "reject", "revise"],
            "candidate_count": len(original_candidates),
            "candidates": original_candidates, "comparisons": original_comparisons,
            "step_output_sha256s": original_step_outputs,
            "model_output_sha256s": model_output_hashes,
            "model_opinion_sha256s": model_opinion_hashes,
            "issues": original_issues + [{
                "id": "manual_revision_unreviewed",
                "type": "manual_edit",
                "message": "人工修改已形成新稿，必须重新完成受影响内容的结构、语义和来源核对。",
                "evidence": [], "represented": False,
            }],
            "pending_issues": ["manual_revision_unreviewed"],
            "upstream_candidate_sha": upstream_candidate_sha,
        })
        if row.get("review_id") is not None and row["status"] == "open":
            _dismiss_current_candidate_review(
                conn, job_id=job_id, kind=kind, superseded_by=digest
            )
        if kind == "facts":
            # Prose is downstream of facts.  Keep its immutable audit row but
            # remove an obsolete open gate before the new facts review opens.
            prose_row = read_candidate(conn, job_id, "prose")
            if prose_row and prose_row.get("upstream_candidate_sha") != digest:
                _dismiss_current_candidate_review(
                    conn, job_id=job_id, kind="prose", superseded_by=digest
                )
        if job[0] == "running":
            # A revision made while the worker is between model calls must
            # park the same present stage before a later resume can publish.
            control_plane.set_job_status(conn, job_id=job_id, status="needs_review")
            control_plane.advance_stage(
                conn, job_id=job_id, stage="present", status="needs_review"
            )
        new_review_id = control_plane.open_review_item(
            conn, job_id=job_id, kind="stage_gate", payload=payload
        )
        conn.execute("""INSERT INTO chronicle.narrative_candidate_versions
            (candidate_sha, job_id, kind, review_id, parent_candidate_sha, revision_no,
             upstream_candidate_sha, context_sha, context_payload, candidate_payload, model_version)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (digest, job_id, kind, new_review_id, row["candidate_sha"], revision_no,
             upstream_candidate_sha, row["context_sha"], Jsonb(row["context"]),
             Jsonb(content), "human-revision"))
        return read_candidate(conn, job_id, kind)


# Short alias for callers that model the operation as creating a new draft.
revise = revise_candidate


def publish(conn, *, job_id, worker):
    import resolve_publish
    with conn.transaction():
        control_plane.require_job_lease(conn, job_id=job_id, worker=worker)
        resolve_publish.acquire_publish_lock(conn)
        resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
        facts_row, prose_row = read_candidate(conn, job_id, "facts"), read_candidate(conn, job_id, "prose")
        facts, prose = approved_content(facts_row), approved_content(prose_row)
        context = facts_row["context"]
        if context != prose_row["context"]:
            raise PersistenceConflict("narrative reviews bind different source contexts")
        if canonical_store.read_latest_catalog_sha256(conn) != context["catalog_sha"]:
            raise resolve_publish.PublicationPlanStale("new sources changed the narrative context; preserve this review and regenerate in a follow-up job")
        publication = contract.compile_publication(context, facts, prose)
        resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
        conn.execute("""INSERT INTO chronicle.historical_narratives
            (version_sha, job_id, catalog_sha, facts_review_id, prose_review_id,
             facts_acceptance_id, prose_acceptance_id, facts_sha, prose_sha, payload)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (version_sha) DO NOTHING""",
            (publication["publication_version"], job_id, context["catalog_sha"],
             uuid.UUID(facts_row["review_id"]) if facts_row["review_id"] else None,
             uuid.UUID(prose_row["review_id"]) if prose_row["review_id"] else None,
             uuid.UUID(facts_row["acceptance_id"]) if facts_row["acceptance_id"] else None,
             uuid.UUID(prose_row["acceptance_id"]) if prose_row["acceptance_id"] else None,
             sha256_json(facts), sha256_json(prose), Jsonb(publication)))
        # The approved narrative is itself a complete reviewed fragment.  Make
        # it the public history edition through the edition store before the
        # final lease fence; public history never falls back to this source
        # table.
        edition = history_edition_store.publish_narrative_fragment(
            conn,
            fragment_version=publication["publication_version"],
            job_id=job_id,
            worker=worker,
        )
        resolve_publish.require_unexpired_lease(conn, job_id=job_id, worker=worker)
        publication["edition_version"] = edition["edition_version"]
        publication["history_edition_version"] = edition["edition_version"]
        return publication


def read_publication(conn, version=None):
    if version is not None and (not isinstance(version, str) or len(version) != 64 or any(char not in "0123456789abcdef" for char in version)):
        raise PersistenceError("invalid historical publication version")
    if version is None:
        row = conn.execute("SELECT payload FROM chronicle.historical_narratives ORDER BY publication_sequence DESC LIMIT 1").fetchone()
    else:
        row = conn.execute("SELECT payload FROM chronicle.historical_narratives WHERE version_sha = %s", (version,)).fetchone()
    return row[0] if row else None
