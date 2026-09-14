#!/usr/bin/env python3
"""The production entry for staged natural chapters and reviewed history.

Model steps use ChapterLimits and the global model timeout. The durable
claim/lease/retry loop lives in ingestion_worker; production never selects
chunk extraction, a second translation pass, or fake content.
"""

from __future__ import annotations

import threading
from typing import Mapping

import ingestion_worker as worker
import chapter_stage
from common import PersistenceError


def chapter_configs(
    env: Mapping[str, str] | None = None,
) -> tuple[chapter_stage.chapter_contract.ChapterLimits, object | None]:
    """Select the natural-chapter schema/profile/limits entry.

    Returns ``(limits, chapter_model)``. Limits honor the documented
    ``CHRONICLE_CHAPTER_*`` overrides; the provider follows the formal
    chapter entry (``CHRONICLE_CHAPTER_MODEL`` or
    ``CHRONICLE_CHAPTER_PIPELINE_CONFIG``). A missing
    provider is returned as ``None`` so the worker fails closed instead
    of faking chapters.
    """
    plain = dict(env) if env is not None else None
    limits = chapter_stage.chapter_limits_from_env(plain)
    model = chapter_stage.chapter_model_from_env(plain)
    return limits, model


def main(argv: list[str] | None = None) -> int:
    args = worker.build_parser().parse_args(argv)
    if args.lease_seconds < 1:
        raise PersistenceError("--lease-seconds must be a positive integer")
    if args.poll_interval <= 0:
        raise PersistenceError("--poll-interval must be positive")

    database_url = worker.database_url_from_env(args.database_url)
    worker_id = args.worker_id or worker.default_worker_id()
    source_dir = worker.source_dir_from_env(args.source_dir)
    chapter_limits, chapter_model = chapter_configs()
    chapter_stage.require_production_entry(
        source_dir=source_dir, chapter_model=chapter_model,
    )
    revision_source = worker.build_revision_source(database_url, source_dir)
    narrative_model = worker.narrative_stage.model_from_env()

    stop = threading.Event()
    worker.install_shutdown_handlers(stop)
    print(
        f"chronicle-worker: {worker_id} claiming from Chronicle PostgreSQL "
        f"(lease {args.lease_seconds}s), staged chapters from {source_dir} "
        f"(max_source_chars={chapter_limits.max_source_chars}, "
        f"max_prompt_chars={chapter_limits.max_prompt_chars})",
        flush=True,
    )
    tally = worker.run_forever(
        database_url,
        worker=worker_id,
        lease_seconds=args.lease_seconds,
        poll_interval=args.poll_interval,
        max_jobs=args.max_jobs,
        stop=stop,
        revision_source=revision_source,
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
