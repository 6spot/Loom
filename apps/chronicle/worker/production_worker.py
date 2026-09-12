#!/usr/bin/env python3
"""Production Chronicle worker entrypoint with one model-input budget authority.

The durable worker core stays in ``ingestion_worker.py``.  This deployment
entrypoint only derives the segmentation/extraction resource envelopes from one
provider-facing input budget so prompt growth and ContextState growth do not
require chasing duplicated magic numbers.

The current extraction prompt template is measured at worker startup.  Its
static/metadata/boundary overhead becomes the segmentation prompt reserve;
serialized ContextState and chunk text remain accounted separately by the
existing deterministic C1-T5 budget trimmer.  Extraction then enforces the same
budget against the final rendered prompt, fail-closed and without truncation.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Mapping

import ingestion_worker as worker
import chapter_stage as chapter_stage
from common import PersistenceError

DEFAULT_MODEL_INPUT_BUDGET_CHARS = 16384
CONTEXT_GROWTH_RESERVE_CHARS = 512
OUTPUT_HEADROOM_RESERVE_CHARS = 1500
PROMPT_SAFETY_MARGIN_CHARS = 512
MAX_SECTION_LABEL_RESERVE_CHARS = 120
MAX_DOCUMENT_TITLE_RESERVE_CHARS = 512


def model_input_budget_chars(env: Mapping[str, str] | None = None) -> int:
    """Return the single production prompt/input envelope in characters."""
    source = os.environ if env is None else env
    raw = (source.get("CHRONICLE_MODEL_INPUT_BUDGET_CHARS") or "").strip()
    if not raw:
        return DEFAULT_MODEL_INPUT_BUDGET_CHARS
    try:
        value = int(raw)
    except ValueError as exc:
        raise PersistenceError(
            "CHRONICLE_MODEL_INPUT_BUDGET_CHARS must be a positive integer"
        ) from exc
    if value < 1:
        raise PersistenceError(
            "CHRONICLE_MODEL_INPUT_BUDGET_CHARS must be a positive integer"
        )
    return value


def _compact_json_chars(value: object) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def measured_prompt_reserve_chars(
    *,
    boundary_context_chars: int = worker.SegmentationConfig().boundary_context_chars,
) -> int:
    """Measure current prompt overhead instead of guessing a fixed reserve.

    Chunk text and serialized ContextState are subtracted because C1-T5
    accounts for those actual values independently.  Section/document and
    boundary inputs are deliberately measured at conservative supported
    envelopes, then a small safety margin absorbs ordinary metadata growth.

    Any future prompt-template expansion automatically increases this reserve
    the next time the worker starts; no source/context truncation is introduced.
    """
    context = worker.segmentation.initial_context()
    chunk_text = "文"
    boundary = "界" * boundary_context_chars
    prompt = worker.extraction.build_extraction_prompt(
        chunk_text=chunk_text,
        section={
            "label": "節" * MAX_SECTION_LABEL_RESERVE_CHARS,
            "kind": "biography",
            "section_index": 999999,
        },
        document={
            "title": "題" * MAX_DOCUMENT_TITLE_RESERVE_CHARS,
            "verified_normalized_year": 208,
        },
        context_input=context,
        boundary_head=boundary,
        boundary_tail=boundary,
    )
    variable_chars = len(chunk_text) + _compact_json_chars(context)
    static_chars = len(prompt) - variable_chars
    if static_chars < 1:
        raise PersistenceError("measured extraction prompt overhead is invalid")
    return static_chars + PROMPT_SAFETY_MARGIN_CHARS


def production_configs(
    env: Mapping[str, str] | None = None,
) -> tuple[worker.SegmentationConfig, worker.extraction.ExtractionConfig]:
    """Build segmentation/extraction configs from one authoritative budget."""
    budget = model_input_budget_chars(env)
    prompt_reserve = measured_prompt_reserve_chars()
    reserved = (
        prompt_reserve
        + CONTEXT_GROWTH_RESERVE_CHARS
        + OUTPUT_HEADROOM_RESERVE_CHARS
    )
    if reserved >= budget:
        raise PersistenceError(
            "CHRONICLE_MODEL_INPUT_BUDGET_CHARS is too small for the current "
            f"Chronicle prompt contract: fixed/reserved envelope {reserved} >= "
            f"configured budget {budget}; increase the deployment budget or "
            "use a provider with a larger input window"
        )
    segmentation_config = worker.SegmentationConfig(
        max_input_chars=budget,
        reserved_prompt_chars=prompt_reserve,
        reserved_context_chars=CONTEXT_GROWTH_RESERVE_CHARS,
        reserved_output_chars=OUTPUT_HEADROOM_RESERVE_CHARS,
    )
    extraction_config = worker.extraction.ExtractionConfig(
        max_prompt_chars=budget,
    )
    return segmentation_config, extraction_config


def chapter_configs(
    env: Mapping[str, str] | None = None,
) -> tuple[chapter_stage.chapter_contract.ChapterLimits, object | None]:
    """Select the natural-chapter schema/profile/limits entry.

    Returns ``(limits, chapter_model)``. Limits honor the documented
    ``CHRONICLE_CHAPTER_*`` overrides; the provider follows the formal
    chapter entry (live ``CHRONICLE_CHAPTER_MODEL`` or explicit
    ``CHRONICLE_CHAPTER_FIXTURE_PACK`` test injection). A missing
    provider is returned as ``None`` so the worker fails closed instead
    of faking chapters.
    """
    plain = dict(env) if env is not None else None
    limits = chapter_stage.chapter_limits_from_env(plain)
    model = chapter_stage.chapter_model_from_env(plain)
    return limits, model


def main(argv: list[str] | None = None) -> int:
    """Run the normal durable worker with budget-coupled production configs."""
    args = worker.build_parser().parse_args(argv)
    if args.lease_seconds < 1:
        raise PersistenceError("--lease-seconds must be a positive integer")
    if args.poll_interval <= 0:
        raise PersistenceError("--poll-interval must be positive")

    database_url = worker.database_url_from_env(args.database_url)
    worker_id = args.worker_id or worker.default_worker_id()
    fail_plan = worker.parse_fail_plan(args.fail_stage)
    source_dir = worker.source_dir_from_env(args.source_dir)
    revision_source = (
        worker.build_revision_source(database_url, source_dir)
        if source_dir is not None
        else None
    )
    extraction_model, presentation_model = worker.model_provider.models_from_env()
    segmentation_config, extraction_config = production_configs()
    chapter_limits, chapter_model = chapter_configs()
    narrative_model = worker.narrative_stage.model_from_env()
    chapter_stage.require_production_entry(
        source_dir=source_dir,
        extraction_model=extraction_model,
        chapter_model=chapter_model,
    )

    stop = threading.Event()
    worker.install_shutdown_handlers(stop)

    if source_dir is not None:
        print(
            f"chronicle-worker: {worker_id} claiming from Chronicle PostgreSQL "
            f"(lease {args.lease_seconds}s) with real C1-T5 segmentation "
            f"from {source_dir}",
            flush=True,
        )
    else:
        print(
            f"chronicle-worker: {worker_id} claiming from Chronicle PostgreSQL "
            f"(lease {args.lease_seconds}s) with the deterministic fake "
            "executor (no --source-dir/CHRONICLE_SOURCE_DIR)",
            flush=True,
        )

    print(
        "chronicle-worker: unified model input budget "
        f"max={extraction_config.max_prompt_chars} "
        f"prompt_reserve={segmentation_config.reserved_prompt_chars} "
        f"context_growth_reserve={segmentation_config.reserved_context_chars} "
        f"output_headroom_reserve={segmentation_config.reserved_output_chars}",
        flush=True,
    )

    if extraction_model is not None or presentation_model is not None:
        print(
            "chronicle-worker: production model providers enabled "
            f"(extraction={getattr(extraction_model, 'name', 'off')}, "
            f"presentation={getattr(presentation_model, 'name', 'off')})",
            flush=True,
        )

    if chapter_model is not None:
        print(
            "chronicle-worker: natural-chapter pipeline enabled "
            f"(chapter_model={getattr(chapter_model, 'name', 'off')}, "
            f"max_source_chars={chapter_limits.max_source_chars}, "
            f"max_prompt_chars={chapter_limits.max_prompt_chars})",
            flush=True,
        )

    tally = worker.run_forever(
        database_url,
        worker=worker_id,
        executor_factory=lambda: worker.StageExecutor(fail_plan=dict(fail_plan)),
        lease_seconds=args.lease_seconds,
        poll_interval=args.poll_interval,
        max_jobs=args.max_jobs,
        stop=stop,
        revision_source=revision_source,
        segmentation_config=segmentation_config,
        chunk_model=extraction_model,
        presentation_model=presentation_model,
        extraction_config=extraction_config,
        chapter_model=chapter_model,
        chapter_limits=chapter_limits,
        narrative_model=narrative_model,
        on_event=lambda event, payload: print(
            f"chronicle-worker: {event} {payload}", flush=True
        ),
    )
    print(f"chronicle-worker: shutdown {tally}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
