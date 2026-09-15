"""Immutable acceptance receipts for person-history products.

This mirrors the C3-T06 receipt shape used by source-corroboration narratives
but keeps a separate product vocabulary and database table.  The distinction
is intentional: a person's summary/prose is not a main-history candidate and
must not become publishable through a cast or widened generic table.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from common import PersistenceError, sha256_json

SCHEMA = "chronicle.person-history-acceptance"
VERSION = "0.1"
POLICY_VERSION = "person-history-content-acceptance-v1"
ACCEPTANCE_TYPES = frozenset({"human", "policy_model_review"})
KINDS = frozenset({"summary", "prose"})


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise PersistenceError(f"{name} must be a lowercase SHA-256")
    return value


def _hashes(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise PersistenceError(f"{name} must be a list of SHA-256 values")
    result = [_sha(item, name) for item in value]
    if len(result) != len(set(result)):
        raise PersistenceError(f"{name} must not contain duplicate hashes")
    return result


def build_receipt(
    *,
    job_id: Any,
    kind: str,
    acceptance_type: str,
    input_sha256: str,
    candidate_sha256: str,
    content: dict[str, Any],
    pipeline_fingerprint: str | None,
    model_output_sha256s: list[str],
    model_opinion_sha256s: list[str],
    decision_reason: str,
    review_id: Any = None,
    reviewed_conclusion_ids: list[str] | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    if kind not in KINDS:
        raise PersistenceError("person-history acceptance kind must be summary or prose")
    if acceptance_type not in ACCEPTANCE_TYPES:
        raise PersistenceError("person-history acceptance type is invalid")
    if not isinstance(content, dict):
        raise PersistenceError("person-history acceptance content must be an object")
    if not isinstance(decision_reason, str) or not decision_reason.strip():
        raise PersistenceError("person-history acceptance requires a rationale")
    if acceptance_type == "human" and review_id is None:
        raise PersistenceError("human person-history acceptance requires a review id")
    if acceptance_type == "policy_model_review" and review_id is not None:
        raise PersistenceError("automatic person-history acceptance cannot use a human review id")
    if acceptance_type == "policy_model_review" and not model_output_sha256s:
        raise PersistenceError("automatic person-history acceptance requires model outputs")
    reviewed_conclusion_ids = list(reviewed_conclusion_ids or [])
    if (
        not reviewed_conclusion_ids
        or any(not isinstance(item, str) or not item for item in reviewed_conclusion_ids)
        or len(reviewed_conclusion_ids) != len(set(reviewed_conclusion_ids))
    ):
        raise PersistenceError("reviewed person-history conclusion ids must be a nonempty unique string list")
    if pipeline_fingerprint is not None and (not isinstance(pipeline_fingerprint, str) or not pipeline_fingerprint):
        raise PersistenceError("person-history pipeline fingerprint must be nonempty when supplied")
    body = {
        "schema": SCHEMA,
        "version": VERSION,
        "acceptance_type": acceptance_type,
        "policy_version": POLICY_VERSION,
        "job_id": str(job_id),
        "kind": kind,
        "input_sha256": _sha(input_sha256, "input_sha256"),
        "candidate_sha256": _sha(candidate_sha256, "candidate_sha256"),
        "draft_sha256": sha256_json(content),
        "content_sha256": sha256_json(content),
        "pipeline_fingerprint": pipeline_fingerprint,
        "model_output_sha256s": _hashes(model_output_sha256s, "model_output_sha256s"),
        "model_opinion_sha256s": _hashes(model_opinion_sha256s, "model_opinion_sha256s"),
        "decision": "accept",
        "decision_reason": decision_reason.strip(),
        "review_id": str(review_id) if review_id is not None else None,
        "reviewed_conclusion_ids": reviewed_conclusion_ids,
        "created_at": (created_at or datetime.now(timezone.utc)).isoformat(),
    }
    body["receipt_sha256"] = sha256_json(body)
    return body


def validate_receipt(receipt: dict[str, Any]) -> None:
    if not isinstance(receipt, dict) or receipt.get("schema") != SCHEMA:
        raise PersistenceError("invalid person-history acceptance receipt schema")
    if receipt.get("version") != VERSION or receipt.get("decision") != "accept":
        raise PersistenceError("invalid person-history acceptance receipt version or decision")
    required = (
        "acceptance_type", "policy_version", "job_id", "kind", "input_sha256",
        "candidate_sha256", "draft_sha256", "content_sha256", "decision_reason",
        "created_at", "receipt_sha256", "pipeline_fingerprint",
        "model_output_sha256s", "model_opinion_sha256s", "review_id",
        "reviewed_conclusion_ids",
    )
    if any(key not in receipt for key in required):
        raise PersistenceError("person-history acceptance receipt is incomplete")
    if receipt.get("acceptance_type") not in ACCEPTANCE_TYPES or receipt.get("kind") not in KINDS:
        raise PersistenceError("person-history acceptance receipt has an invalid type")
    if not isinstance(receipt.get("job_id"), str) or not receipt["job_id"].strip():
        raise PersistenceError("person-history acceptance receipt has no job id")
    if not isinstance(receipt.get("policy_version"), str) or receipt["policy_version"] != POLICY_VERSION:
        raise PersistenceError("person-history acceptance receipt has an invalid policy version")
    if not isinstance(receipt.get("decision_reason"), str) or not receipt["decision_reason"].strip():
        raise PersistenceError("person-history acceptance receipt has no rationale")
    _sha(receipt["input_sha256"], "input_sha256")
    _sha(receipt["candidate_sha256"], "candidate_sha256")
    _sha(receipt["draft_sha256"], "draft_sha256")
    _sha(receipt["content_sha256"], "content_sha256")
    _sha(receipt["receipt_sha256"], "receipt_sha256")
    _hashes(receipt["model_output_sha256s"], "model_output_sha256s")
    _hashes(receipt["model_opinion_sha256s"], "model_opinion_sha256s")
    if (
        not isinstance(receipt["reviewed_conclusion_ids"], list)
        or not receipt["reviewed_conclusion_ids"]
        or any(not isinstance(item, str) or not item for item in receipt["reviewed_conclusion_ids"])
        or len(receipt["reviewed_conclusion_ids"]) != len(set(receipt["reviewed_conclusion_ids"]))
    ):
        raise PersistenceError("reviewed person-history conclusion ids must be a nonempty unique string list")
    if receipt["acceptance_type"] == "human" and not receipt.get("review_id"):
        raise PersistenceError("human person-history acceptance has no review id")
    if receipt["acceptance_type"] == "policy_model_review" and receipt.get("review_id") is not None:
        raise PersistenceError("automatic person-history acceptance has a review id")
    if receipt["acceptance_type"] == "policy_model_review":
        if not receipt["model_output_sha256s"]:
            raise PersistenceError("automatic person-history acceptance has no model outputs")
        if not isinstance(receipt.get("pipeline_fingerprint"), str) or not receipt["pipeline_fingerprint"]:
            raise PersistenceError("automatic person-history acceptance has no pipeline fingerprint")
    if receipt["draft_sha256"] != receipt["content_sha256"]:
        raise PersistenceError("person-history draft and content hashes differ")
    body = dict(receipt)
    body.pop("receipt_sha256")
    if sha256_json(body) != receipt["receipt_sha256"]:
        raise PersistenceError("person-history acceptance receipt hash mismatch")


__all__ = [
    "ACCEPTANCE_TYPES",
    "KINDS",
    "POLICY_VERSION",
    "SCHEMA",
    "VERSION",
    "build_receipt",
    "validate_receipt",
]
