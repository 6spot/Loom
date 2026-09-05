#!/usr/bin/env python3
"""Development-only C1-T13 worker runner for the frozen source fixture pack.

This runner changes no historical semantics and never bypasses Chronicle's
production pipeline. It only supplies larger deterministic model-input/prompt
budgets for the explicit fixture provider, whose responses are local/replayable
and do not have a real provider context-window constraint.

Production deployments must continue to use ``worker/ingestion_worker.py`` and
therefore keep the normal 8k segmentation/extraction fail-closed defaults until
a real provider's capability is configured and deployment-accepted.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHRONICLE = HERE.parent.parent
WORKER_DIR = CHRONICLE / "worker"
PERSISTENCE_DIR = CHRONICLE / "persistence"
for path in (str(WORKER_DIR), str(PERSISTENCE_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

import extraction  # noqa: E402
import ingestion_worker as worker  # noqa: E402
import model_provider  # noqa: E402
from common import PersistenceError  # noqa: E402
from segmentation import SegmentationConfig  # noqa: E402

DEFAULT_FIXTURE_MODEL_BUDGET_CHARS = 32000
PRODUCTION_DEFAULT_BUDGET_CHARS = 8000


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Chronicle C1-T13 source fixtures through the real durable worker"
    )
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--lease-seconds", type=int, default=300)
    parser.add_argument("--poll-interval", type=float, default=0.1)
    parser.add_argument("--max-jobs", type=int, required=True)
    parser.add_argument(
        "--model-budget-chars",
        "--max-input-chars",
        dest="model_budget_chars",
        type=int,
        default=DEFAULT_FIXTURE_MODEL_BUDGET_CHARS,
        help=(
            "fixture-only segmentation input + extraction prompt budget; "
            "does not change production defaults"
        ),
    )
    return parser


def fixture_configs(model_budget_chars: int) -> tuple[SegmentationConfig, extraction.ExtractionConfig]:
    """Return explicit development budgets for the replay-only model boundary."""
    if not isinstance(model_budget_chars, int) or isinstance(model_budget_chars, bool):
        raise PersistenceError("fixture model budget must be an integer")
    if model_budget_chars <= PRODUCTION_DEFAULT_BUDGET_CHARS:
        raise PersistenceError(
            "fixture model budget must be > 8000 so this runner cannot be "
            "mistaken for the production default path"
        )
    return (
        SegmentationConfig(max_input_chars=model_budget_chars),
        extraction.ExtractionConfig(max_prompt_chars=model_budget_chars),
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    fixture_pack = (os.environ.get("CHRONICLE_MODEL_FIXTURE_PACK") or "").strip()
    if not fixture_pack:
        raise PersistenceError(
            "C1-T13 fixture_worker requires explicit CHRONICLE_MODEL_FIXTURE_PACK"
        )

    database_url = worker.database_url_from_env()
    source_dir = worker.source_dir_from_env()
    if source_dir is None:
        raise PersistenceError(
            "C1-T13 fixture_worker requires CHRONICLE_SOURCE_DIR for real source ingestion"
        )
    revision_source = worker.build_revision_source(database_url, source_dir)
    extraction_model, presentation_model = model_provider.models_from_env()
    if extraction_model is None or presentation_model is None:
        raise PersistenceError(
            "C1-T13 fixture_worker requires both extraction and presentation fixture models"
        )
    if not str(getattr(extraction_model, "name", "")).startswith("fixture:"):
        raise PersistenceError("C1-T13 fixture_worker refuses a non-fixture extraction model")
    if not str(getattr(presentation_model, "name", "")).startswith("fixture:"):
        raise PersistenceError("C1-T13 fixture_worker refuses a non-fixture presentation model")

    segmentation_config, extraction_config = fixture_configs(args.model_budget_chars)
    stop = threading.Event()
    worker.install_shutdown_handlers(stop)
    print(
        "chronicle C1-T13 fixture worker: "
        f"worker={args.worker_id} "
        f"segmentation_input_chars={segmentation_config.max_input_chars} "
        f"extraction_prompt_chars={extraction_config.max_prompt_chars} "
        f"source_dir={source_dir}",
        flush=True,
    )
    tally = worker.run_forever(
        database_url,
        worker=args.worker_id,
        executor_factory=worker.StageExecutor,
        lease_seconds=args.lease_seconds,
        poll_interval=args.poll_interval,
        max_jobs=args.max_jobs,
        stop=stop,
        revision_source=revision_source,
        segmentation_config=segmentation_config,
        chunk_model=extraction_model,
        presentation_model=presentation_model,
        extraction_config=extraction_config,
        on_event=lambda event, payload: print(
            f"chronicle C1-T13 fixture worker: {event} {payload}", flush=True
        ),
    )
    print(f"chronicle C1-T13 fixture worker: shutdown {tally}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
