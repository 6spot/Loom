"""Chronicle durable ingestion worker package (C1-T4)."""

try:
    from ingestion_worker import (
        CHUNK_BEARING_STAGE,
        DEFAULT_LEASE_SECONDS,
        DEFAULT_POLL_INTERVAL_SECONDS,
        FAKE_CHUNKS_PER_JOB,
        WORKER_VERSION,
        JobRunner,
        StageExecutionError,
        StageExecutor,
        default_worker_id,
        execute_job,
        run_forever,
        run_once,
    )
except ImportError:  # pragma: no cover - package-style import
    from .ingestion_worker import (
        CHUNK_BEARING_STAGE,
        DEFAULT_LEASE_SECONDS,
        DEFAULT_POLL_INTERVAL_SECONDS,
        FAKE_CHUNKS_PER_JOB,
        WORKER_VERSION,
        JobRunner,
        StageExecutionError,
        StageExecutor,
        default_worker_id,
        execute_job,
        run_forever,
        run_once,
    )

__all__ = [
    "CHUNK_BEARING_STAGE",
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "FAKE_CHUNKS_PER_JOB",
    "WORKER_VERSION",
    "JobRunner",
    "StageExecutionError",
    "StageExecutor",
    "default_worker_id",
    "execute_job",
    "run_forever",
    "run_once",
]
