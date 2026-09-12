"""Durable substeps inside the existing chapter extract stage.

Only this adapter waits for models. The store owns fenced append-only writes;
pure protocols own patches/acceptance. The outer chapter worker still owns
chunk runs, assembly, identity review and atomic publication.
"""
from __future__ import annotations

import copy
import json
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from threading import Event

import psycopg

import chapter_content_review as reviews
import chapter_production as protocol
import chapter_production_store as store
import control_plane
import staged_chapter_contract as contract
from common import LeaseLost, PersistenceConflict, PersistenceError, sha256_json
from model_provider import ModelProviderError
from resolve_publish import require_unexpired_lease


class PipelineFailure(PersistenceError):
    """A recorded technical/output failure; an ordinary retry reuses successes."""


class PipelineHalted(PersistenceError):
    def __init__(self, outcome):
        super().__init__(outcome)
        self.outcome = outcome


def _payload(record):
    return {key: value for key, value in record.items() if key not in ("output_sha256", "artifact_type")}


def _issue(message, *, target="chapter", evidence=None, kind="processing_error", identity=None):
    return {"id": "issue_" + sha256_json([identity or message, target])[:24],
            "type": kind, "target": target, "message": message,
            "evidence": evidence or [], "represented": False}


def _dedupe_issues(issues):
    result = {}
    for issue in issues:
        old = result.get(issue["id"])
        if old is not None and old != issue:
            raise PersistenceConflict("opinion ID changed its historical meaning")
        result[issue["id"]] = issue
    return list(result.values())


class Runner:
    def __init__(self, database_url, *, job_id, chunk_id, worker, request,
                 models, limits, lease_seconds, on_event=None, halt=None):
        self.database_url = database_url
        self.job_id, self.chunk_id, self.worker = job_id, chunk_id, worker
        self.request, self.models, self.limits = request, models, limits
        self.lease_seconds, self.on_event, self.halt = lease_seconds, on_event, halt
        with psycopg.connect(database_url) as conn:
            self.plan = store.freeze_pipeline(conn, job_id=job_id, chunk_id=chunk_id,
                worker=worker, request=request, config=models.public_config())

    def _write_args(self):
        return {"job_id": self.job_id, "chunk_id": self.chunk_id, "worker": self.worker}

    def _records(self):
        with psycopg.connect(self.database_url) as conn:
            records = store.read_outputs(conn, job_id=self.job_id, chunk_id=self.chunk_id)
        if any(r.get("pipeline_fingerprint") != self.plan["pipeline_fingerprint"] for r in records):
            raise PersistenceConflict("chapter pipeline contains a foreign configuration")
        return records

    def _heartbeat(self):
        if self.halt:
            outcome = self.halt(self.job_id)
            if outcome is not None:
                raise PipelineHalted(outcome)
        with psycopg.connect(self.database_url, connect_timeout=5) as conn:
            require_unexpired_lease(conn, job_id=self.job_id, worker=self.worker)
            control_plane.heartbeat_job_strict(conn, job_id=self.job_id,
                worker=self.worker, lease_seconds=self.lease_seconds)

    def _emit(self, event, **values):
        if self.on_event:
            self.on_event(event, {"chapter_id": self.request["chapter_id"],
                                 "chunk_id": str(self.chunk_id), **values})

    def _invoke(self, step, slot, prompt, cancelled):
        model = self.models.model_for(step, slot)
        config = self.models.config_for(step, slot)
        started = time.monotonic()
        try:
            if cancelled.is_set():
                raise ModelProviderError("model attempt cancelled before dispatch")
            observed = getattr(model, "complete_with_receipt", None)
            if callable(observed):
                raw, receipt = observed(prompt, total_timeout_seconds=config["total_timeout_seconds"],
                                        cancelled=cancelled.is_set)
            else:  # Explicit in-process test injection, never an env fallback.
                raw = model.complete(prompt)
                receipt = {"status": "completed", "model": model.name, "usage": None,
                           "elapsed_seconds": round(time.monotonic() - started, 3),
                           "http_attempts": None, "injected_provider": True}
            if not isinstance(raw, str):
                return "", None, ["model returned a non-text value"], receipt, "invalid", None
            if len(raw) > self.limits.max_response_chars:
                return raw, None, ["model text exceeds response character limit"], receipt, "invalid", None
            parsed, errors = protocol.parse_step(step, raw)
            return raw, parsed, errors, receipt, "invalid" if errors else "completed", None
        except ModelProviderError as exc:
            return exc.raw_text, None, [], exc.receipt, "failed", str(exc)
        except Exception as exc:
            # Custom provider exceptions may embed a key or request. Only a
            # safe class name is exposed; no exception repr enters Studio.
            return "", None, [], {"usage": None, "elapsed_seconds": round(time.monotonic() - started, 3)}, "failed", f"model adapter failed ({type(exc).__name__})"

    def _semantic_errors(self, step, parsed, data):
        if step in ("extraction", "linking"):
            return [] if parsed.get("chapter_id") == self.request["chapter_id"] else ["output chapter mismatch"]
        if step == "review":
            return protocol.review_errors(parsed, request=self.request,
                candidate=data["candidate"], history=data["history"],
                previous_issues=data["previous_issues"])
        if step == "repair":
            errors = []
            if parsed["candidate_sha256"] != data["candidate_sha256"] or parsed["history_sha256"] != data["history_sha256"]:
                errors.append("repair binds a different candidate or opinion history")
            known = {issue["id"] for issue in data["issues"]}
            if set(parsed["addressed_issue_ids"]) - known or not parsed["addressed_issue_ids"]:
                errors.append("repair must name existing issues it addresses")
            try:
                protocol.apply_patches(data["candidate"], parsed["patches"])
            except PersistenceError as exc:
                errors.append(str(exc))
            return errors
        if step == "comparison":
            candidates = {candidate["candidate_sha256"] for candidate in data["candidates"]}
            differences = parsed["differences"]
            selected = [item for item in differences if item["assessment"] == "selected"]
            errors = []
            if parsed["candidate_set_sha256"] != data["candidate_set_sha256"] or parsed["selected_sha256"] not in candidates:
                errors.append("comparison changed its fixed candidate set")
            if {entry["candidate_sha256"] for entry in differences} != candidates or len(differences) != len(candidates):
                errors.append("comparison must describe every candidate exactly once")
            if len(selected) != 1 or selected[0]["candidate_sha256"] != parsed["selected_sha256"]:
                errors.append("comparison selection is inconsistent")
            if any(set(entry["evidence"]) - protocol.evidence_handles(self.request) for entry in differences):
                errors.append("comparison cites unknown evidence handles")
            return errors
        return []

    def _execute(self, specs):
        """All independent calls share one bounded pool; commits stay serial."""
        self._heartbeat()
        results = {}
        pending = {}
        ready = deque()
        cancelled = Event()
        started_at = time.monotonic()
        for step, data, round in specs:
            prompt = protocol.build_prompt(step, self.request, data, max_chars=self.limits.max_prompt_chars)
            ready.extend((step, data, round, prompt, slot) for slot in self.models.steps[step])
        pool = ThreadPoolExecutor(max_workers=self.models.max_parallel)
        try:
            while ready or pending:
                # Reserve attempts only when a worker is available. Pending
                # calls never include an unbounded executor queue, so stopping
                # a job cannot start fresh remote work while __exit__ waits.
                while ready and len(pending) < self.models.max_parallel:
                    self._heartbeat()
                    step, data, round, prompt, slot = ready.popleft()
                    identity = (step, slot)
                    try:
                        with psycopg.connect(self.database_url) as conn:
                            record, reused = store.begin_attempt(conn, **self._write_args(), plan=self.plan,
                                step=step, round=round, slot=slot, data=data, prompt=prompt,
                                model_config=self.models.config_for(step, slot), max_attempts=self.models.max_step_attempts)
                    except store.StepBudgetExhausted as exc:
                        # Other completed independent results still get saved.
                        results[identity] = {"status": "failed", "step": step, "slot": slot,
                                             "error": str(exc), "validation_errors": []}
                        continue
                    if reused:
                        results[identity] = record
                        self._emit("chapter_step_reused", step=step, model=record["model"])
                    else:
                        self._emit("chapter_step_started", step=step, model=record["model"], attempt=record["attempt"])
                        pending[pool.submit(self._invoke, step, slot, prompt, cancelled)] = (record, data)
                if not pending:
                    continue
                finished, _ = wait(pending, timeout=max(0.1, min(15, self.lease_seconds / 3)), return_when=FIRST_COMPLETED)
                self._heartbeat()
                for future in finished:
                    attempt, data = pending.pop(future)
                    raw, parsed, errors, receipt, status, error = future.result()
                    if status == "completed":
                        errors += self._semantic_errors(attempt["step"], parsed, data)
                        if errors:
                            status = "invalid"
                    with psycopg.connect(self.database_url) as conn:
                        record = store.finish_attempt(conn, **self._write_args(), attempt=attempt,
                            raw_text=raw, parsed=parsed, validation_errors=errors, receipt=receipt,
                            status=status, error=error)
                    results[(attempt["step"], attempt["slot"])] = record
                    self._emit("chapter_step_saved", step=attempt["step"], model=attempt["model"], status=status)
                if not finished:
                    self._emit("chapter_step_waiting", elapsed_seconds=int(time.monotonic() - started_at),
                               pending_steps=sorted({record["step"] for record, _ in pending.values()}))
        except BaseException:
            cancelled.set()
            for future in pending:
                future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            pool.shutdown(wait=True)
        return {step: [results[(step, slot)] for slot in self.models.steps[step]] for step, _data, _round in specs}

    def _group(self, step, data, round):
        return self._execute([(step, data, round)])[step]

    def _require_complete(self, records, step):
        if any(record["status"] == "failed" for record in records):
            raise PipelineFailure(f"{step}: model attempt failed; saved earlier steps will be reused")
        if any(record["status"] != "completed" for record in records):
            raise PipelineFailure(f"{step}: output contract failed; saved diagnostics are available")

    def _choose(self, records, step, round):
        self._require_complete(records, step)
        if len(records) == 1:
            return records[0]["parsed"], [], []
        candidates = [{"candidate_sha256": r["output_sha256"], "model": r["model"], "content": r["parsed"]} for r in records]
        data = {"step": step, "candidates": candidates, "candidate_set_sha256": sha256_json(candidates)}
        comparisons = self._group("comparison", data, round)
        if any(r["status"] == "failed" for r in comparisons):
            raise PipelineFailure("comparison model failed; missing responses are not agreement")
        decisions = {r["parsed"]["selected_sha256"] for r in comparisons if r["status"] == "completed"}
        unresolved = any(r["status"] != "completed" or any(d["assessment"] == "disputed" for d in r["parsed"]["differences"])
                         for r in comparisons) or len(decisions) != 1
        selected = next(iter(decisions)) if len(decisions) == 1 else records[0]["output_sha256"]
        chosen = next((r for r in records if r["output_sha256"] == selected), records[0])
        issues = [] if not unresolved else [_issue(
            f"{step} 的模型比较仍有实质分歧；当前为供审核的暂存稿，请查看所有候选。",
            target=step, identity=[step, round, [r["output_sha256"] for r in comparisons]])]
        for issue in issues:
            issue["comparison_disputed"] = True
        return chosen["parsed"], comparisons, issues

    def _validation(self, candidate):
        report = contract.validate_staged_candidate(self.request, candidate)
        return contract.flatten_staged_errors(report)

    def _save_draft(self, candidate, round, refs, issues, parent=None):
        with psycopg.connect(self.database_url) as conn:
            return store.save_draft(conn, **self._write_args(), plan=self.plan, candidate=candidate,
                round=round, history_refs=refs, issues=_dedupe_issues(issues), parent_sha256=parent)

    def _initial_draft(self):
        generated = self._execute([("translation", {}, 0), ("extraction", {}, 0)])
        translation, comparison_t, issues_t = self._choose(generated["translation"], "translation", 0)
        extraction, comparison_e, issues_e = self._choose(generated["extraction"], "extraction", 0)
        data = {"translation": translation, "extraction": extraction}
        links = self._group("linking", data, 0)
        linking, comparison_l, issues_l = self._choose(links, "linking", 0)
        candidate = protocol.assemble_candidate(self.request, translation, extraction, linking)
        related = generated["translation"] + generated["extraction"] + comparison_t + comparison_e + links + comparison_l
        # Include failed/interrupted attempts as history too; none count as a
        # completed candidate or a source of agreement.
        related_shas = {r["node_key"] for r in related}
        history_refs = [r["output_sha256"] for r in self._records()
                        if r.get("node_key") in related_shas]
        return self._save_draft(candidate, 0, history_refs, issues_t + issues_e + issues_l)

    def _history(self, draft, extra=None):
        saved = self._records()
        extras = extra or []
        node_keys = {r["node_key"] for r in extras if r.get("node_key")}
        # Preserve the earlier prefix exactly. Expand new nodes to include
        # their failed/interrupted attempts as well as the successful retry;
        # retain each old draft so opinion reversals can be compared to the
        # text actually reviewed, not inferred from a patch description.
        additional = [r["output_sha256"] for r in saved if r.get("node_key") in node_keys]
        additional.extend(r["output_sha256"] for r in extras)
        refs = list(dict.fromkeys([*draft["history_refs"], draft["output_sha256"], *additional]))
        records = store.resolve_history(saved, refs)
        return protocol.history_for_model(records), refs

    def _latest_review(self, draft):
        with psycopg.connect(self.database_url) as conn:
            row = conn.execute(
                """SELECT review_id FROM chronicle.review_items WHERE job_id = %s AND chunk_id = %s
                   AND payload->>'scope' = 'chapter_content' AND payload->>'candidate_sha256' = %s
                   AND payload->'step_output_sha256s' ? %s
                   ORDER BY created_at DESC, review_id DESC LIMIT 1""",
                (self.job_id, self.chunk_id, draft["candidate_sha256"], draft["output_sha256"]),
            ).fetchone()
            if row is None:
                return None
            saved = reviews.read_content_review(conn, row[0])
            # Equal text is not the same reviewed version: a later revision
            # can deliberately return to an earlier candidate with new
            # evidence/opinions. Only a gate containing this exact durable
            # draft may resume its decision (including a saved human patch).
            packet = saved["packet"]
            bound = [entry for entry in packet["history"]
                     if entry.get("output_sha256") == draft["output_sha256"]]
            if (packet["request_fingerprint"] != self.plan["request_fingerprint"]
                    or packet["pipeline_fingerprint"] != self.plan["pipeline_fingerprint"]
                    or len(bound) != 1 or bound[0].get("artifact_type") != store.DRAFT_TYPE
                    or bound[0].get("candidate") != draft["candidate"]):
                raise PersistenceConflict("chapter review does not bind the current draft and history")
            saved["review_id"] = str(row[0])
            saved["decision"] = reviews.get_content_decision(conn, row[0])
            return saved

    def _save_acceptance(self, draft, history, refs, decision):
        errors = self._validation(draft["candidate"])
        if errors:
            raise PersistenceConflict("cannot accept a mechanically invalid chapter: " + "; ".join(errors))
        # Only completed/failed response records belong to this receipt's
        # model-output set; the draft separately binds all attempt starts.
        known = {r["output_sha256"]: r for r in self._records()}
        step_refs = [ref for ref in refs if known[ref]["artifact_type"] == store.STEP_TYPE]
        value = {"schema": "chronicle.chapter-acceptance", "version": "0.1", "status": "accepted",
                 "chapter_id": self.request["chapter_id"], "request_fingerprint": self.plan["request_fingerprint"],
                 "pipeline_fingerprint": self.plan["pipeline_fingerprint"],
                 "candidate_sha256": draft["candidate_sha256"], "history_sha256": sha256_json(history),
                 "step_output_sha256s": step_refs, "decision": decision, "draft_sha256": draft["output_sha256"]}
        with psycopg.connect(self.database_url) as conn:
            record = store.append_output(conn, **self._write_args(), artifact_type=store.ACCEPTANCE_TYPE, payload=value)
        return {"outcome": "accepted", "candidate": draft["candidate"], "production_receipt": _payload(record)}

    def _gate(self, draft, report_records, issues, errors):
        history, refs = self._history(draft, report_records)
        with psycopg.connect(self.database_url) as conn:
            gate = reviews.freeze_content_review(conn, **self._write_args(), request=self.request,
                candidate=draft["candidate"], history=history, issues=_dedupe_issues(issues),
                validation_errors=errors, pipeline_fingerprint=self.plan["pipeline_fingerprint"],
                step_output_sha256s=refs)
        self._emit("chapter_content_review_required", review_id=gate["review_id"], issue_count=len(issues))
        return {"outcome": "needs_review", "review_id": gate["review_id"]}

    def _revised_draft(self, draft, patches, extra_records, issues):
        candidate = protocol.apply_patches(draft["candidate"], patches)
        generation = draft["round"] + 1
        extra = list(extra_records)
        # Upstream prose/entities/events/phases changing invalidates derived
        # links. Direct corrections to links/time metadata do not regenerate
        # the already-correct prose or extraction.
        if any((p["path"].startswith("/translation/") and p["path"].endswith("/text"))
               or p["path"].startswith(("/bundle/", "/person_states/phases")) for p in patches):
            translation = {"language": "zh-CN", "blocks": [{"block_id": b["block_id"], "text": b["text"]}
                           for b in candidate["translation"]["blocks"]]}
            extraction = {key: copy.deepcopy(candidate[key]) for key in (
                "chapter_id", "bundle", "mentions", "record_sources", "person_states", "warnings")}
            extraction["person_states"].pop("unit_phases", None)
            links = self._group("linking", {"translation": translation, "extraction": extraction}, generation)
            linking, comparisons, new_issues = self._choose(links, "linking", generation)
            candidate = protocol.assemble_candidate(self.request, translation, extraction, linking)
            extra += links + comparisons
            issues += new_issues
        _history, refs = self._history(draft, extra)
        return self._save_draft(candidate, generation, refs, issues, parent=draft["output_sha256"])

    def run(self):
        records = self._records()
        drafts = [r for r in records if r["artifact_type"] == store.DRAFT_TYPE]
        accepted = [r for r in records if r["artifact_type"] == store.ACCEPTANCE_TYPE]
        if accepted:
            if len(accepted) != 1:
                raise PersistenceConflict("chapter has conflicting content acceptances")
            saved = accepted[0]
            draft = next((r for r in drafts if r["output_sha256"] == saved["draft_sha256"]), None)
            if draft is None or draft["candidate_sha256"] != saved["candidate_sha256"] or self._validation(draft["candidate"]):
                raise PersistenceConflict("accepted chapter draft drift")
            return {"outcome": "accepted", "candidate": draft["candidate"], "production_receipt": _payload(saved)}
        draft = max(drafts, key=lambda r: r["round"]) if drafts else self._initial_draft()
        while True:
            self._heartbeat()
            gate = self._latest_review(draft)
            if gate:
                decision = gate["decision"]
                if decision is None:
                    return {"outcome": "needs_review", "review_id": gate["review_id"]}
                if decision["decision"] == "reject":
                    return {"outcome": "cancelled"}
                if decision["decision"] == "accept":
                    packet = gate["packet"]
                    return self._save_acceptance(draft, packet["history"], packet["step_output_sha256s"],
                        {"kind": "human", "review_id": gate["review_id"], "decision_sha256": decision["decision_sha256"]})
                # A human revision is a separate new draft; it never inherits
                # approval. Its subsequent model check sees every old opinion.
                packet = gate["packet"]
                with psycopg.connect(self.database_url) as conn:
                    note = store.append_output(conn, **self._write_args(), artifact_type=store.STEP_TYPE,
                        payload={"schema": "chronicle.chapter-step", "version": "0.1", "step": "human_repair",
                            "chapter_id": self.request["chapter_id"], "pipeline_fingerprint": self.plan["pipeline_fingerprint"],
                            "round": draft["round"] + 1, "status": "completed", "model": "human",
                            "parsed": {"patches": decision["patches"], "decision": decision},
                            "decision": decision, "validation_errors": [], "raw_text": None})
                refs = packet["step_output_sha256s"]
                prior = store.resolve_history(self._records(), refs)
                draft = self._revised_draft(draft, decision["patches"], prior + [note], packet["issues"])
                continue
            errors = self._validation(draft["candidate"])
            history, _refs = self._history(draft)
            prior_issues = _dedupe_issues(draft["issues"] + [_issue(error, identity=["validation", error]) for error in errors])
            data = {"candidate": draft["candidate"], "candidate_sha256": draft["candidate_sha256"],
                    "history": history, "history_sha256": sha256_json(history),
                    "previous_issues": prior_issues, "validation_errors": errors}
            reports = self._group("review", data, draft["round"])
            if any(r["status"] == "failed" for r in reports):
                raise PipelineFailure("review transport failed; it is not an approving opinion")
            all_issues = list(prior_issues)
            for record in reports:
                if record["status"] != "completed":
                    all_issues.append(_issue("复核返回的版本、意见覆盖或格式不合格，不能采用其通过结论。",
                        target="review", identity=record["output_sha256"]))
                if isinstance(record.get("parsed"), dict) and isinstance(record["parsed"].get("issues"), list):
                    for original in record["parsed"]["issues"]:
                        if isinstance(original, dict) and {"id", "type", "target", "message", "evidence", "represented"} <= original.keys():
                            item = copy.deepcopy(original)
                            item["model_issue_id"] = item["id"]
                            item["id"] = "opinion_" + sha256_json([record["output_sha256"], item["id"]])[:24]
                            item["model"] = record["model"]
                            all_issues.append(item)
            all_issues = _dedupe_issues(all_issues)
            comparison_disputed = any(issue.get("comparison_disputed") is True for issue in prior_issues)
            if not errors and not comparison_disputed and all(protocol.review_passes(r["parsed"], errors=r["validation_errors"])
                                  for r in reports if r["status"] == "completed") and all(r["status"] == "completed" for r in reports):
                history, refs = self._history(draft, reports)
                return self._save_acceptance(draft, history, refs,
                    {"kind": "ai", "review_output_sha256s": [r["output_sha256"] for r in reports]})
            repair_rounds = {r["round"] for r in self._records() if r.get("step") == "repair"}
            # A reserved/failed repair belongs to the current draft's round.
            # Resume that exact node (including its completed patch/linking)
            # before refusing to open another repair round for a newer draft.
            can_repair = draft["round"] in repair_rounds or len(repair_rounds) < self.models.max_repair_rounds
            if comparison_disputed or not can_repair or any(r["status"] != "completed" for r in reports):
                return self._gate(draft, reports, all_issues, errors)
            # A source ambiguity is a normal review branch, not a reason to
            # ask a model to invent an unqualified historical answer.
            if any(r["parsed"]["verdict"] == "needs_review" for r in reports):
                return self._gate(draft, reports, all_issues, errors)
            repair_history, _refs = self._history(draft, reports)
            repair_data = {"candidate": draft["candidate"], "candidate_sha256": draft["candidate_sha256"],
                "history": repair_history, "history_sha256": sha256_json(repair_history),
                "issues": all_issues, "validation_errors": errors,
                "patch_targets": protocol.patch_targets(draft["candidate"])}
            repairs = self._group("repair", repair_data, draft["round"])
            if any(r["status"] == "failed" for r in repairs):
                raise PipelineFailure("repair transport failed; previous candidates remain saved")
            if any(r["status"] != "completed" for r in repairs):
                return self._gate(draft, reports + repairs, all_issues + [_issue("局部修正不符合补丁规则。", target="repair")], errors)
            chosen, comparisons, comparison_issues = self._choose(repairs, "repair", draft["round"])
            if comparison_issues:
                return self._gate(draft, reports + repairs + comparisons, all_issues + comparison_issues, errors)
            draft = self._revised_draft(draft, chosen["patches"], reports + repairs + comparisons, all_issues)


def execute(database_url, **kwargs):
    try:
        return Runner(database_url, **kwargs).run()
    except PipelineHalted as exc:
        return {"outcome": exc.outcome}
