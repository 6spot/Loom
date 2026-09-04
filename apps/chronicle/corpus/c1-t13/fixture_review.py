#!/usr/bin/env python3
"""Resolve C1-T13 development ReviewItems through the authenticated Studio API.

This is an acceptance harness, not identity authority.  It deliberately chooses
``uncertain`` for every resolution candidate so fixture development can exercise
the real human-review gate without pretending exact-name matching proves
historical identity.  The decisions remain durable/auditable ReviewItems, and
production deployments never run this script.
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import Any
from urllib import error, request


class AcceptanceError(RuntimeError):
    pass


def _auth(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {token}"


def _call(
    *, base_url: str, auth: str, method: str, path: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json", "Authorization": auth}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        headers["Content-Type"] = "application/json"
    req = request.Request(base_url.rstrip("/") + path, data=body, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=30) as response:
            raw = response.read()
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")[:1000]
        raise AcceptanceError(f"{method} {path} returned HTTP {exc.code}: {raw}") from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        raise AcceptanceError(f"{method} {path} failed: {exc}") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AcceptanceError(f"{method} {path} returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise AcceptanceError(f"{method} {path} returned a non-object JSON value")
    return value


def run(*, base_url: str, user: str, password: str) -> dict[str, Any]:
    auth = _auth(user, password)
    listing = _call(
        base_url=base_url,
        auth=auth,
        method="GET",
        path="/api/v1/studio/jobs/reviews?status=open&limit=200&offset=0",
    )
    reviews = listing.get("reviews")
    if not isinstance(reviews, list):
        raise AcceptanceError("review list response has no reviews array")

    resolved: list[dict[str, Any]] = []
    touched_jobs: set[str] = set()
    for review in reviews:
        if not isinstance(review, dict):
            raise AcceptanceError("review list contains a non-object item")
        review_id = review.get("review_id")
        job_id = review.get("job_id")
        allowed = review.get("allowed_decisions")
        if not isinstance(review_id, str) or not isinstance(job_id, str):
            raise AcceptanceError("review item is missing review_id/job_id")
        if review.get("scope") != "resolution":
            raise AcceptanceError(f"unexpected non-resolution open review {review_id}")
        if not isinstance(allowed, list) or "uncertain" not in allowed:
            raise AcceptanceError(f"review {review_id} does not allow conservative uncertain")
        response = _call(
            base_url=base_url,
            auth=auth,
            method="POST",
            path=f"/api/v1/studio/jobs/reviews/{review_id}/decision",
            payload={
                "decision": "uncertain",
                "confidence": 0.5,
                "rationale": (
                    "C1-T13 deterministic development fixture: retain candidate uncertainty; "
                    "fixture replay exercises the real review gate but does not claim human "
                    "historical identity adjudication."
                ),
            },
        )
        item = response.get("review")
        if not isinstance(item, dict) or item.get("status") != "resolved":
            raise AcceptanceError(f"review {review_id} did not become resolved")
        touched_jobs.add(job_id)
        resolved.append(
            {
                "review_id": review_id,
                "job_id": job_id,
                "link_kind": review.get("link_kind"),
                "candidate_id": review.get("candidate_id"),
                "decision": "uncertain",
            }
        )

    # Only resume jobs that are actually parked in needs_review and now have no
    # open review debt. Jobs with zero resolution candidates may already be
    # completed and are intentionally left alone.
    jobs_payload = _call(
        base_url=base_url,
        auth=auth,
        method="GET",
        path="/api/v1/studio/jobs?limit=100&offset=0",
    )
    jobs = jobs_payload.get("jobs")
    if not isinstance(jobs, list):
        raise AcceptanceError("job list response has no jobs array")
    resumed: list[str] = []
    for job in jobs:
        if not isinstance(job, dict) or job.get("status") != "needs_review":
            continue
        job_id = job.get("job_id")
        if not isinstance(job_id, str):
            raise AcceptanceError("needs_review job has no job_id")
        detail = _call(
            base_url=base_url,
            auth=auth,
            method="GET",
            path=f"/api/v1/studio/jobs/{job_id}",
        ).get("job")
        if not isinstance(detail, dict):
            raise AcceptanceError(f"job {job_id} detail is invalid")
        if int(detail.get("open_reviews") or 0) != 0:
            raise AcceptanceError(
                f"job {job_id} still has {detail.get('open_reviews')} open reviews; refusing resume"
            )
        resumed_job = _call(
            base_url=base_url,
            auth=auth,
            method="POST",
            path=f"/api/v1/studio/jobs/{job_id}/resume",
            payload={},
        ).get("job")
        if not isinstance(resumed_job, dict) or resumed_job.get("status") != "queued":
            raise AcceptanceError(f"job {job_id} did not return to queued on resume")
        resumed.append(job_id)

    remaining = _call(
        base_url=base_url,
        auth=auth,
        method="GET",
        path="/api/v1/studio/jobs/reviews?status=open&limit=200&offset=0",
    ).get("reviews")
    if remaining:
        raise AcceptanceError(f"open resolution review debt remains after fixture review: {len(remaining)}")

    return {
        "schema": "chronicle.c1-t13-fixture-review",
        "version": "0.1",
        "policy": "conservative-uncertain-v1",
        "resolved_reviews": resolved,
        "resolved_review_count": len(resolved),
        "jobs_with_review_candidates": sorted(touched_jobs),
        "resumed_jobs": resumed,
        "resumed_job_count": len(resumed),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--admin-user", required=True)
    parser.add_argument("--admin-password", required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = run(
        base_url=args.base_url,
        user=args.admin_user,
        password=args.admin_password,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
