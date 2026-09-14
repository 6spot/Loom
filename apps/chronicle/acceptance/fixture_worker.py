"""Test adapter for the frozen R2/R3 browser fixtures, never a production CLI.

The gates exercise the shared durable worker library with their local HTTP
fixtures. Current production accepts staged 0.4 only. Retire this adapter when
C3-T01 migrates the browser gates to the current staged fixture contract.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from gate_runtime import GateError


def require_fixture_config(env: Mapping[str, str]) -> None:
    if env.get("CHRONICLE_CHAPTER_MODEL") not in {
        "fixture:gate-r2:reading-chapter", "fixture:gate-r3:person-state-chapter",
    }:
        raise GateError("browser fixture worker requires an explicit R2/R3 fixture model")
    if env.get("CHRONICLE_NARRATIVE_MODEL", "") not in {"", "gate-fixture:narrative"}:
        raise GateError("browser fixture worker refuses live narrative models")
    if any(env.get(key) for key in (
        "CHRONICLE_CHAPTER_PIPELINE_CONFIG", "CHRONICLE_CHAPTER_FIXTURE_PACK",
        "CHRONICLE_MODEL_FIXTURE_PACK",
    )):
        raise GateError("browser fixture worker refuses alternate model configurations")
    endpoint = urlsplit(env.get("CHRONICLE_MODEL_ENDPOINT", ""))
    if (endpoint.scheme != "http" or endpoint.hostname not in {
        "localhost", "127.0.0.1", "host.docker.internal",
    } or endpoint.username is not None or endpoint.password is not None):
        raise GateError("browser fixture worker requires the local gate HTTP provider")


def main(argv: list[str] | None = None) -> int:
    require_fixture_config(os.environ)
    worker_dir = Path(__file__).resolve().parents[1] / "worker"
    sys.path.insert(0, str(worker_dir))
    import ingestion_worker as worker
    import chapter_stage

    args = worker.build_parser().parse_args(argv)
    if args.lease_seconds < 1 or args.poll_interval <= 0:
        raise GateError("fixture worker lease and polling intervals must be positive")
    database_url = worker.database_url_from_env(args.database_url)
    source_dir = worker.source_dir_from_env(args.source_dir)
    if source_dir is None:
        raise GateError("browser fixture worker requires the uploaded source directory")
    stop = threading.Event()
    worker.install_shutdown_handlers(stop)
    worker.run_forever(
        database_url,
        worker=args.worker_id or worker.default_worker_id(),
        lease_seconds=args.lease_seconds,
        poll_interval=args.poll_interval,
        max_jobs=args.max_jobs,
        stop=stop,
        revision_source=worker.build_revision_source(database_url, source_dir),
        chapter_model=chapter_stage.chapter_model_from_env(),
        chapter_limits=chapter_stage.chapter_limits_from_env(),
        narrative_model=worker.narrative_stage.model_from_env(),
        on_event=lambda event, payload: print(
            f"chronicle-fixture-worker: {event} {payload}", flush=True,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
