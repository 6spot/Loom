"""Chronicle durable staged ingestion worker package."""

try:
    from ingestion_worker import (
        DEFAULT_LEASE_SECONDS,
        DEFAULT_POLL_INTERVAL_SECONDS,
        WORKER_VERSION,
        JobRunner,
        default_worker_id,
        execute_job,
        run_forever,
        run_once,
    )
except ImportError:  # pragma: no cover - package-style import
    from .ingestion_worker import (
        DEFAULT_LEASE_SECONDS,
        DEFAULT_POLL_INTERVAL_SECONDS,
        WORKER_VERSION,
        JobRunner,
        default_worker_id,
        execute_job,
        run_forever,
        run_once,
    )

__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "WORKER_VERSION",
    "JobRunner",
    "default_worker_id",
    "execute_job",
    "run_forever",
    "run_once",
]
