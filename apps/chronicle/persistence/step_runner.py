"""Shared durable execution primitives for Chronicle production steps.

The runner owns only execution mechanics: dependency barriers, bounded
parallelism, cancellation, model invocation fencing and the hand-off to an
append-only attempt/result store.  A caller supplies the business adapter for
prompt construction, parsing and semantic validation.  This keeps source,
translation and review meaning out of the reusable scheduler while allowing
future production documents to use the same recovery contract.
"""
from __future__ import annotations

import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from threading import Event
from typing import Any, Callable, Mapping, Sequence, TypedDict

from common import PersistenceError, sha256_json


class StepModelProfile(TypedDict, total=False):
    """Public, JSON-safe model profile passed to a step adapter."""

    model: str
    endpoint: str
    api_key_env: str
    timeout_seconds: float
    max_output_tokens: int
    max_response_bytes: int
    response_format: str


class StepAttempt(TypedDict, total=False):
    """Durable attempt-start fields shared by step stores."""

    artifact_type: str
    output_sha256: str
    node_key: str
    step: str
    round: int
    slot: str
    attempt: int
    model: str
    model_config: StepModelProfile
    prompt: str
    input: Any
    input_sha256: str
    status: str


class StepOutput(TypedDict, total=False):
    """Durable result fields shared by step stores."""

    artifact_type: str
    output_sha256: str
    attempt_sha256: str
    node_key: str
    step: str
    round: int
    slot: str
    attempt: int
    model: str
    raw_text: str | None
    parsed: Any
    validation_errors: list[str]
    receipt: dict[str, Any]
    status: str
    error: str | None


class StepAcceptanceRef(TypedDict, total=False):
    """Reference to a saved step output carried by an acceptance receipt."""

    output_sha256: str
    artifact_type: str
    step: str
    node_key: str
    status: str


@dataclass(frozen=True)
class StepDefinition:
    """Immutable execution policy for one logical step."""

    name: str
    dependencies: tuple[str, ...] = ()
    retryable: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise PersistenceError("step name must be a non-empty string")
        if any(not isinstance(item, str) or not item.strip() for item in self.dependencies):
            raise PersistenceError("step dependencies must be non-empty names")
        if self.name in self.dependencies:
            raise PersistenceError(f"step {self.name!r} cannot depend on itself")
        if len(set(self.dependencies)) != len(self.dependencies):
            raise PersistenceError(f"step {self.name!r} repeats a dependency")


@dataclass(frozen=True)
class StepSpec:
    """One invocation of a logical step in a generation/repair round.

    ``dependencies`` is optional so an adapter may execute a step whose input
    was already assembled by its caller.  When omitted, the runner uses the
    dependency list in the corresponding :class:`StepDefinition`.
    """

    step: str
    data: Any
    round: int = 0
    dependencies: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.step, str) or not self.step.strip():
            raise PersistenceError("step spec name must be a non-empty string")
        if not isinstance(self.round, int) or isinstance(self.round, bool) or self.round < 0:
            raise PersistenceError("step round must be a non-negative integer")
        if self.dependencies is not None:
            if any(not isinstance(item, str) or not item.strip() for item in self.dependencies):
                raise PersistenceError("step spec dependencies must be non-empty names")
            if self.step in self.dependencies:
                raise PersistenceError(f"step {self.step!r} cannot depend on itself")
            if len(set(self.dependencies)) != len(self.dependencies):
                raise PersistenceError(f"step {self.step!r} repeats a dependency")


@dataclass(frozen=True)
class StepInput:
    """The frozen identity of one model node.

    The identity includes every value that can change the response.  A saved
    successful result is therefore reusable only for the same pipeline,
    protocol prompt, input data, model profile and logical round.
    """

    pipeline_fingerprint: str
    step: str
    round: int
    slot: str
    data: Any
    prompt: str
    model_config: Mapping[str, Any]

    def fingerprint(self) -> str:
        return sha256_json({
            "pipeline_fingerprint": self.pipeline_fingerprint,
            "step": self.step,
            "round": self.round,
            "slot": self.slot,
            "data": self.data,
            "prompt": self.prompt,
            "model_config": self.model_config,
        })


class StepRunnerFailure(PersistenceError):
    """A durable step graph cannot produce a complete dependency frontier."""

    def __init__(self, message: str, *, results: Mapping[str, Any] | None = None):
        self.results = dict(results or {})
        super().__init__(message)


class StepDependencyCycle(StepRunnerFailure):
    """The supplied graph has no runnable frontier."""


class StepRunner:
    """Run step specs through injected protocol and persistence adapters.

    The persistence callbacks are intentionally narrow.  They can wrap the
    existing ``IngestionJob``/``ingestion_outputs`` store, an in-memory unit
    test store, or a later production document without making the scheduler
    aware of a database schema.
    """

    def __init__(
        self,
        *,
        definitions: Mapping[str, StepDefinition],
        model_slots: Callable[[str], Sequence[str]],
        model_for: Callable[[str, str], Any],
        model_config: Callable[[str, str], Mapping[str, Any]],
        build_prompt: Callable[[str, Any], str],
        parse: Callable[[str, str], tuple[Any, list[str]]],
        semantic_errors: Callable[[str, Any, Any], list[str]],
        begin_attempt: Callable[..., tuple[dict[str, Any], bool]],
        finish_attempt: Callable[..., dict[str, Any]],
        retry_prompt: Callable[[str, dict[str, Any]], str] | None,
        heartbeat: Callable[[], None],
        max_parallel: int,
        max_attempts: int,
        max_response_chars: int | None,
        wait_timeout_seconds: float,
        preparation_exceptions: tuple[type[BaseException], ...] = (),
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
        event_prefix: str = "step",
    ) -> None:
        if not definitions:
            raise PersistenceError("step runner requires at least one definition")
        if not isinstance(max_parallel, int) or isinstance(max_parallel, bool) or max_parallel < 1:
            raise PersistenceError("step runner max_parallel must be a positive integer")
        if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or max_attempts < 1:
            raise PersistenceError("step runner max_attempts must be a positive integer")
        if not isinstance(wait_timeout_seconds, (int, float)) or wait_timeout_seconds <= 0:
            raise PersistenceError("step runner wait timeout must be positive")
        if not callable(retry_prompt) and retry_prompt is not None:
            raise PersistenceError("step runner retry_prompt must be callable or None")
        self.definitions = dict(definitions)
        for name, definition in self.definitions.items():
            if name != definition.name:
                raise PersistenceError(f"step definition key {name!r} disagrees with its name")
        self.model_slots = model_slots
        self.model_for = model_for
        self.model_config = model_config
        self.build_prompt = build_prompt
        self.parse = parse
        self.semantic_errors = semantic_errors
        self.begin_attempt = begin_attempt
        self.finish_attempt = finish_attempt
        self.retry_prompt = retry_prompt
        self.heartbeat = heartbeat
        self.max_parallel = max_parallel
        self.max_attempts = max_attempts
        self.max_response_chars = max_response_chars
        self.wait_timeout_seconds = float(wait_timeout_seconds)
        self.preparation_exceptions = preparation_exceptions
        self.on_event = on_event
        self.event_prefix = event_prefix.strip("_") or "step"

    def _emit(self, event: str, **values: Any) -> None:
        if self.on_event is not None:
            self.on_event(f"{self.event_prefix}_{event}", values)

    def _definition(self, step: str) -> StepDefinition:
        try:
            return self.definitions[step]
        except KeyError as exc:
            raise PersistenceError(f"step {step!r} has no execution definition") from exc

    def _invoke(self, step: str, slot: str, prompt: str, cancelled: Event):
        """Invoke one provider without giving it database or source authority."""
        started = time.monotonic()
        try:
            model = self.model_for(step, slot)
            if cancelled.is_set():
                raise RuntimeError("model attempt cancelled before dispatch")
            observed = getattr(model, "complete_with_receipt", None)
            if callable(observed):
                raw, receipt = observed(prompt, cancelled=cancelled.is_set)
            else:
                raw = model.complete(prompt)
                receipt = {
                    "status": "completed",
                    "model": getattr(model, "name", None),
                    "usage": None,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "http_attempts": None,
                    "injected_provider": True,
                }
            if not isinstance(receipt, dict):
                receipt = {
                    "status": "completed",
                    "model": getattr(model, "name", None),
                    "usage": None,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                }
            if not isinstance(raw, str):
                return "", receipt, ["model returned a non-text value"], "invalid", None
            if self.max_response_chars is not None and len(raw) > self.max_response_chars:
                return raw, receipt, ["model text exceeds response character limit"], "invalid", None
            return raw, receipt, [], "ready", None
        except Exception as exc:  # provider-neutral; only safe metadata is persisted
            raw = getattr(exc, "raw_text", "")
            receipt = getattr(exc, "receipt", None)
            if not isinstance(raw, str):
                raw = ""
            if not isinstance(receipt, dict):
                receipt = {"usage": None, "elapsed_seconds": round(time.monotonic() - started, 3)}
            if type(exc).__name__ == "ModelProviderError":
                return raw, receipt, [], "failed", str(exc)
            return "", receipt, [], "failed", f"model adapter failed ({type(exc).__name__})"

    def _invoke_and_validate(self, step: str, slot: str, prompt: str, data: Any, cancelled: Event):
        raw, receipt, transport_errors, transport_status, error = self._invoke(
            step, slot, prompt, cancelled
        )
        if transport_status in ("invalid", "failed"):
            parsed = None
            errors = list(transport_errors)
            status = transport_status
            return raw, parsed, errors, receipt, status, error
        # The parser is deliberately called here, after the transport has
        # proved that it returned complete text.  A partial response never
        # becomes a successful or agreeing candidate.
        try:
            parsed, errors = self.parse(step, raw)
            if not errors:
                errors = self.semantic_errors(step, parsed, data)
        except Exception as exc:
            # Adapter defects or malformed parser input still have a durable
            # terminal record. Do not leave a started attempt looking as if
            # it may safely be reused after a worker crash.
            return raw, None, [f"step adapter failed ({type(exc).__name__})"], receipt, "invalid", None
        return raw, parsed, errors, receipt, "invalid" if errors else "completed", None

    @staticmethod
    def _record(record: Mapping[str, Any], *, step: str, slot: str) -> dict[str, Any]:
        value = dict(record)
        value.setdefault("step", step)
        value.setdefault("slot", slot)
        return value

    @staticmethod
    def _dependency_names(spec: StepSpec, definition: StepDefinition) -> tuple[str, ...]:
        return spec.dependencies if spec.dependencies is not None else definition.dependencies

    def execute(self, specs: Sequence[StepSpec]) -> dict[str, list[dict[str, Any]]]:
        """Execute a finite graph and return one final record per model slot.

        A dependency is considered satisfied only after every configured slot
        for that logical step has a completed saved result.  Missing dependency
        names are treated as external inputs already assembled by the caller;
        this lets a chapter adapter run its selection/review phases separately
        while the same runner still enforces a full A/B/C graph in one call.
        """
        normalized = tuple(specs)
        if not normalized:
            return {}
        if any(not isinstance(spec, StepSpec) for spec in normalized):
            raise PersistenceError("step runner expects StepSpec values")
        names = [spec.step for spec in normalized]
        if len(names) != len(set(names)):
            raise PersistenceError("one step runner execution cannot contain duplicate logical steps")
        definitions = {spec.step: self._definition(spec.step) for spec in normalized}
        slots_by_step: dict[str, tuple[str, ...]] = {}
        for spec in normalized:
            slots = tuple(self.model_slots(spec.step))
            if not slots:
                raise PersistenceError(f"step {spec.step!r} has no model slots")
            if len(slots) != len(set(slots)):
                raise PersistenceError(f"step {spec.step!r} repeats a model slot")
            slots_by_step[spec.step] = slots
        pending = {spec.step: spec for spec in normalized}
        known = set(pending)
        statuses: dict[str, str] = {}
        active: dict[str, set[str]] = {}
        records: dict[str, dict[str, dict[str, Any]]] = {name: {} for name in names}
        ready: deque[tuple[StepSpec, str]] = deque()
        running: dict[Future, tuple[StepSpec, str, str, dict[str, Any]]] = {}
        preparation_errors: list[str] = []
        cancelled = Event()
        pool = ThreadPoolExecutor(max_workers=self.max_parallel)
        started_at = time.monotonic()

        def result_view() -> dict[str, list[dict[str, Any]]]:
            view: dict[str, list[dict[str, Any]]] = {}
            for spec in normalized:
                slots = slots_by_step[spec.step]
                view[spec.step] = [records[spec.step][slot] for slot in slots if slot in records[spec.step]]
            return view

        def finish_group(step: str) -> None:
            if active.get(step):
                return
            active.pop(step, None)
            values = list(records[step].values())
            statuses[step] = "completed" if values and all(item.get("status") == "completed" for item in values) else "failed"

        def mark_preparation_failure(spec: StepSpec, slot: str, message: str) -> None:
            records[spec.step][slot] = {
                "step": spec.step,
                "slot": slot,
                "round": spec.round,
                "status": "failed",
                "preparation_error": message,
            }
            preparation_errors.append(f"{spec.step}/{slot}: {message}")
            active[spec.step].discard(slot)
            finish_group(spec.step)

        def dependency_state(spec: StepSpec) -> tuple[bool, str | None]:
            dependencies = self._dependency_names(spec, definitions[spec.step])
            failed = next((dep for dep in dependencies if statuses.get(dep) == "failed"), None)
            if failed is not None:
                return False, failed
            # A dependency not in this invocation is an already assembled
            # input.  In-graph dependencies must be completed first.
            waiting = [dep for dep in dependencies if dep in known and statuses.get(dep) != "completed"]
            return not waiting, None

        def schedule_frontier() -> bool:
            changed = False
            for step, spec in list(pending.items()):
                ready_for_step, failed_dependency = dependency_state(spec)
                if failed_dependency is not None:
                    pending.pop(step)
                    active[step] = set()
                    for slot in slots_by_step[step]:
                        mark_preparation_failure(spec, slot, f"dependency {failed_dependency} did not complete")
                    changed = True
                    continue
                if not ready_for_step:
                    continue
                pending.pop(step)
                slots = slots_by_step[step]
                active[step] = set(slots)
                ready.extend((spec, slot) for slot in slots)
                changed = True
            return changed

        try:
            while pending or active or ready or running:
                schedule_frontier()

                while ready and len(running) < self.max_parallel:
                    spec, slot = ready.popleft()
                    definition = definitions[spec.step]
                    try:
                        base_prompt = self.build_prompt(spec.step, spec.data)
                        config = self.model_config(spec.step, slot)
                        attempt, reused = self.begin_attempt(
                            step=spec.step,
                            round=spec.round,
                            slot=slot,
                            data=spec.data,
                            prompt=base_prompt,
                            model_config=config,
                            max_attempts=self.max_attempts,
                            retryable=definition.retryable,
                            retry_prompt=self.retry_prompt,
                        )
                    except self.preparation_exceptions as exc:
                        mark_preparation_failure(spec, slot, str(exc))
                        continue
                    if reused:
                        saved = self._record(attempt, step=spec.step, slot=slot)
                        records[spec.step][slot] = saved
                        active[spec.step].discard(slot)
                        self._emit("reused", step=spec.step, model=saved.get("model"), slot=slot)
                        finish_group(spec.step)
                        continue
                    actual_prompt = attempt.get("prompt", base_prompt)
                    self._emit(
                        "started",
                        step=spec.step,
                        model=attempt.get("model"),
                        slot=slot,
                        attempt=attempt.get("attempt"),
                    )
                    future = pool.submit(
                        self._invoke_and_validate,
                        spec.step,
                        slot,
                        actual_prompt,
                        spec.data,
                        cancelled,
                    )
                    running[future] = (spec, slot, base_prompt, attempt)

                if not running:
                    if pending:
                        # No dependency is externally missing at this point;
                        # the remaining graph is cyclic or references a step
                        # that can never reach completed.
                        remaining = ", ".join(sorted(pending))
                        raise StepDependencyCycle(f"step dependency graph has no runnable frontier: {remaining}")
                    continue

                finished, _ = wait(
                    tuple(running),
                    timeout=self.wait_timeout_seconds,
                    return_when=FIRST_COMPLETED,
                )
                self.heartbeat()
                for future in finished:
                    spec, slot, _base_prompt, attempt = running.pop(future)
                    raw, parsed, errors, receipt, status, error = future.result()
                    if status == "completed" and errors:
                        status = "invalid"
                    saved = self.finish_attempt(
                        attempt=attempt,
                        raw_text=raw,
                        parsed=parsed,
                        validation_errors=errors,
                        receipt=receipt,
                        status=status,
                        error=error,
                    )
                    saved = self._record(saved, step=spec.step, slot=slot)
                    records[spec.step][slot] = saved
                    self._emit("saved", step=spec.step, model=saved.get("model"), slot=slot, status=status)
                    definition = definitions[spec.step]
                    if (
                        status == "invalid"
                        and definition.retryable
                        and attempt.get("attempt", self.max_attempts) < self.max_attempts
                    ):
                        # The saved invalid result remains in the audit history;
                        # the store consumes the next attempt for this exact
                        # input/profile node and attaches its correction prompt.
                        ready.appendleft((spec, slot))
                    else:
                        active[spec.step].discard(slot)
                        finish_group(spec.step)
                if not finished:
                    self._emit(
                        "waiting",
                        elapsed_seconds=int(time.monotonic() - started_at),
                        pending_steps=sorted({spec.step for spec, _slot, _prompt, _attempt in running.values()}),
                    )
        except BaseException:
            cancelled.set()
            for future in running:
                future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            pool.shutdown(wait=True)

        output = result_view()
        if preparation_errors:
            raise StepRunnerFailure(
                "; ".join(preparation_errors) + "; saved earlier steps will be reused",
                results=output,
            )
        # A saved failed/invalid result is a meaningful business input for
        # callers such as review gates: they must retain the objection rather
        # than turn it into an implicit transport exception.  A dependent
        # frontier is blocked above and does raise through preparation_errors.
        return output


__all__ = [
    "StepDefinition",
    "StepDependencyCycle",
    "StepInput",
    "StepAcceptanceRef",
    "StepAttempt",
    "StepModelProfile",
    "StepOutput",
    "StepRunner",
    "StepRunnerFailure",
    "StepSpec",
]
