"""Immutable acceptance receipts for historical narrative candidates.

The receipt is deliberately a small, content-addressed contract.  The
database stores the receipt verbatim beside its relational indexes; the
publication trigger is the final authority that a receipt is bound to the
current candidate and to the exact model/review evidence that produced it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from common import PersistenceError, sha256_json


SCHEMA = "chronicle.narrative-acceptance"
VERSION = "0.1"
POLICY_VERSION = "narrative-content-acceptance-v1"
ACCEPTANCE_TYPES = frozenset({"human", "policy_model_review"})
KINDS = frozenset({"facts", "prose"})


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise PersistenceError(f"{name} must be a lowercase SHA-256")
    return value


def _hashes(values: Any, name: str) -> list[str]:
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise PersistenceError(f"{name} must be a list of SHA-256 values")
    result = [_sha(value, name) for value in values]
    if len(result) != len(set(result)):
        raise PersistenceError(f"{name} must not contain duplicate hashes")
    return result


def build_receipt(
    *,
    job_id: Any,
    kind: str,
    acceptance_type: str,
    policy_version: str = POLICY_VERSION,
    input_sha256: str,
    candidate_sha256: str,
    content: dict[str, Any],
    pipeline_fingerprint: str | None,
    model_output_sha256s: list[str],
    model_opinion_sha256s: list[str],
    decision_reason: str,
    review_id: Any = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Create one auditable acceptance receipt.

    ``content`` is hashed here, rather than trusting a caller-provided draft
    hash.  Human and policy/model receipts share this exact shape so the read
    side has one acceptance boundary.
    """
    if kind not in KINDS:
        raise PersistenceError("narrative acceptance kind must be facts or prose")
    if acceptance_type not in ACCEPTANCE_TYPES:
        raise PersistenceError("narrative acceptance type is invalid")
    if not isinstance(policy_version, str) or not policy_version.strip():
        raise PersistenceError("narrative acceptance policy version is required")
    if not isinstance(content, dict):
        raise PersistenceError("narrative acceptance content must be an object")
    if not isinstance(decision_reason, str) or not decision_reason.strip():
        raise PersistenceError("narrative acceptance requires a rationale")
    if acceptance_type == "human" and review_id is None:
        raise PersistenceError("human narrative acceptance requires a review id")
    if acceptance_type == "policy_model_review" and review_id is not None:
        raise PersistenceError("automatic narrative acceptance cannot use a human review id")
    if acceptance_type == "policy_model_review" and not model_output_sha256s:
        raise PersistenceError("automatic narrative acceptance requires model outputs")
    if pipeline_fingerprint is not None and (
        not isinstance(pipeline_fingerprint, str) or not pipeline_fingerprint
    ):
        raise PersistenceError("pipeline fingerprint must be a nonempty string when supplied")

    body = {
        "schema": SCHEMA,
        "version": VERSION,
        "acceptance_type": acceptance_type,
        "policy_version": policy_version.strip(),
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
        "created_at": (created_at or datetime.now(timezone.utc)).isoformat(),
    }
    body["receipt_sha256"] = sha256_json(body)
    return body


def validate_receipt(receipt: dict[str, Any]) -> None:
    """Validate the self-addressed receipt before it crosses the DB boundary."""
    if not isinstance(receipt, dict) or receipt.get("schema") != SCHEMA:
        raise PersistenceError("invalid narrative acceptance receipt schema")
    if receipt.get("version") != VERSION or receipt.get("decision") != "accept":
        raise PersistenceError("invalid narrative acceptance receipt version or decision")
    required = (
        "acceptance_type", "policy_version", "job_id", "kind", "input_sha256",
        "candidate_sha256", "draft_sha256", "content_sha256", "decision_reason",
        "created_at", "receipt_sha256",
    )
    if any(key not in receipt for key in required):
        raise PersistenceError("narrative acceptance receipt is incomplete")
    if receipt.get("acceptance_type") not in ACCEPTANCE_TYPES or receipt.get("kind") not in KINDS:
        raise PersistenceError("narrative acceptance receipt has an invalid type")
    if not isinstance(receipt.get("job_id"), str) or not receipt["job_id"].strip():
        raise PersistenceError("narrative acceptance receipt has no job id")
    if not isinstance(receipt.get("policy_version"), str) or not receipt["policy_version"].strip():
        raise PersistenceError("narrative acceptance receipt has no policy version")
    if not isinstance(receipt.get("decision_reason"), str) or not receipt["decision_reason"].strip():
        raise PersistenceError("narrative acceptance receipt has no rationale")
    if not isinstance(receipt.get("created_at"), str) or not receipt["created_at"].strip():
        raise PersistenceError("narrative acceptance receipt has no creation time")
    _sha(receipt["input_sha256"], "input_sha256")
    _sha(receipt["candidate_sha256"], "candidate_sha256")
    _sha(receipt["draft_sha256"], "draft_sha256")
    _sha(receipt["content_sha256"], "content_sha256")
    _sha(receipt["receipt_sha256"], "receipt_sha256")
    _hashes(receipt.get("model_output_sha256s"), "model_output_sha256s")
    _hashes(receipt.get("model_opinion_sha256s"), "model_opinion_sha256s")
    if receipt["acceptance_type"] == "human" and not receipt.get("review_id"):
        raise PersistenceError("human narrative acceptance receipt has no review id")
    if receipt["acceptance_type"] == "policy_model_review" and receipt.get("review_id") is not None:
        raise PersistenceError("automatic narrative acceptance receipt has a review id")
    if receipt["acceptance_type"] == "policy_model_review":
        if not receipt["model_output_sha256s"]:
            raise PersistenceError("automatic narrative acceptance has no model outputs")
        if not isinstance(receipt.get("pipeline_fingerprint"), str) or not receipt["pipeline_fingerprint"]:
            raise PersistenceError("automatic narrative acceptance has no pipeline fingerprint")
    if receipt["draft_sha256"] != receipt["content_sha256"]:
        raise PersistenceError("narrative acceptance draft and content hashes differ")
    body = dict(receipt)
    body.pop("receipt_sha256")
    if sha256_json(body) != receipt["receipt_sha256"]:
        raise PersistenceError("narrative acceptance receipt hash mismatch")
