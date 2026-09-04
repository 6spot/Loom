"""Pure C1-T10 tests for the browser-safe Studio job projection."""

from __future__ import annotations

import unittest

from studio_jobs import _studio_job_projection


class StudioJobProjectionTests(unittest.TestCase):
    def test_chunk_run_projection_excludes_verbatim_model_artifacts(self) -> None:
        detail = {
            "job_id": "job-1",
            "revision_id": "rev-1",
            "status": "failed",
            "attempt": 1,
            "max_attempts": 3,
            "lease_owner": None,
            "lease_expires_at": None,
            "checkpoint": {"internal": "do not expose"},
            "error": "validation failed",
            "created_at": "2026-09-04T00:00:00+00:00",
            "updated_at": "2026-09-04T00:01:00+00:00",
            "open_reviews": 0,
            "stages": [
                {
                    "stage": "extract",
                    "status": "failed",
                    "attempt": 1,
                    "checkpoint": {"provider_secret": "secret"},
                    "error": "validation failed",
                    "started_at": None,
                    "finished_at": None,
                }
            ],
            "chunks": [
                {
                    "chunk_id": "chunk-1",
                    "section_id": "section-1",
                    "chunk_index": 7,
                    "status": "failed",
                    "attempt": 1,
                    "max_attempts": 3,
                    "source_start": 100,
                    "source_end": 180,
                    "source_sha256": "a" * 64,
                    "content_sha256": "b" * 64,
                    "runs": [
                        {
                            "run_id": "run-1",
                            "attempt": 1,
                            "status": "failed",
                            "worker": "worker-a",
                            "error": "grounding failure",
                            "started_at": None,
                            "finished_at": None,
                            "checkpoint": {
                                "extraction_version": "c1t6-v1",
                                "contract_version": "0.2",
                                "prompt_version": "c1t6-prompt-v1",
                                "model_version": "gpt-luna",
                                "attempt_count": 1,
                                "accepted": False,
                                "authoritative": False,
                                "prompt": "SECRET VERBATIM PROMPT",
                                "raw_response": "SECRET MODEL RESPONSE",
                                "candidate": {"claims": ["secret candidate"]},
                                "request_meta": {"hidden": "context"},
                                "attempts": [
                                    {
                                        "kind": "initial",
                                        "prompt": "SECRET VERBATIM PROMPT",
                                        "prompt_sha256": "c" * 64,
                                        "raw_response": "SECRET MODEL RESPONSE",
                                        "raw_response_sha256": "d" * 64,
                                        "candidate": {"secret": True},
                                        "parse_error": None,
                                        "validation": {
                                            "passed": False,
                                            "errors": {"grounding": ["evidence not exact"]},
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
            "reviews": [
                {
                    "review_id": "review-1",
                    "kind": "quality_flag",
                    "status": "open",
                    "chunk_id": "chunk-1",
                    "payload": {"private": "review payload belongs to T11"},
                    "created_at": None,
                    "resolved_at": None,
                }
            ],
            "outputs": [],
        }

        projected = _studio_job_projection(detail)
        text = repr(projected)
        self.assertNotIn("SECRET VERBATIM PROMPT", text)
        self.assertNotIn("SECRET MODEL RESPONSE", text)
        self.assertNotIn("secret candidate", text)
        self.assertNotIn("provider_secret", text)
        self.assertNotIn("review payload", text)
        self.assertNotIn("checkpoint", projected)
        self.assertNotIn("checkpoint", projected["stages"][0])

        meta = projected["chunks"][0]["runs"][0]["meta"]
        self.assertEqual(meta["model_version"], "gpt-luna")
        self.assertEqual(meta["prompt_version"], "c1t6-prompt-v1")
        self.assertEqual(meta["attempts"][0]["prompt_sha256"], "c" * 64)
        self.assertEqual(meta["attempts"][0]["raw_response_sha256"], "d" * 64)
        self.assertFalse(meta["attempts"][0]["validation"]["passed"])


if __name__ == "__main__":
    unittest.main()
