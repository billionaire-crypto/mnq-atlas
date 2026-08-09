"""Phase 8 operator progress reporting.

The first Step 7 production attempt ran 3 h 07 min emitting nothing, so a
stalled run and a working run were indistinguishable and diagnosis required
attaching a sampling profiler to a live process. D30 authorizes a progress
indicator carrying an index, a count and an elapsed time only.

The prohibition on leaking a measured value is enforced STRUCTURALLY, not by
convention. There is no API on this module that accepts free text, an array,
or any scientific quantity:

* ``phase`` accepts a name that must be a member of :data:`PHASE_NAMES`, a
  frozen allowlist of fixed literals, and an integer total.
* ``advance`` accepts an integer count and nothing else.
* every emitted field is derived from those integers and from the clock.

There is therefore no code path by which a tick, quantile, contrast, interval
endpoint, session identifier or cell result can reach a progress line --
including via exception text, because no exception object is ever accepted.
"""

from __future__ import annotations

import sys
import threading
import time
from datetime import datetime, timezone
from numbers import Integral
from pathlib import Path
from typing import IO, Any, Sequence

from mnq_lab import SpineError

PHASE_CONTRASTS = "contrasts"
PHASE_DAY_TYPES = "day_types"
PHASE_INTERACTIONS = "interactions"
PHASE_BOOTSTRAP_PLANS = "bootstrap_plans"
PHASE_BOOTSTRAP_CHUNKS = "bootstrap_chunks"
PHASE_ARTIFACTS = "artifacts"

PHASE_NAMES = frozenset({
    PHASE_CONTRASTS,
    PHASE_DAY_TYPES,
    PHASE_INTERACTIONS,
    PHASE_BOOTSTRAP_PLANS,
    PHASE_BOOTSTRAP_CHUNKS,
    PHASE_ARTIFACTS,
})

# A moving phase must produce a line well inside the 30 second requirement.
EMIT_INTERVAL_SECONDS = 10.0

_PENDING = "pending"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _builtin_nonnegative_int(value: object, field: str) -> int:
    """Accept counts only; never invoke user-defined integer conversion."""
    if type(value) is not int or value < 0:
        raise SpineError(
            f"Phase 8 progress {field} must be a non-negative built-in integer"
        )
    return value


class _PhaseProgress:
    """Progress for one phase. Accepts an item count and nothing else."""

    __slots__ = (
        "_sink", "_name", "_total", "_started", "_last_emit",
        "_emitted_done", "_count", "_lock", "_stop", "_thread",
        "_failure",
    )

    def __init__(self, sink: "ProgressSink", name: str, total: int) -> None:
        self._sink = sink
        self._name = name
        self._total = _builtin_nonnegative_int(total, "total")
        self._started = time.perf_counter()
        self._last_emit = 0.0
        self._emitted_done = -1
        self._count = 0
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._failure: Exception | None = None
        self._sink._register_phase(self)
        with self._lock:
            self._emit(0)
        if self._total == 0:
            self._stop.set()
            self._sink._phase_finished(self)
        elif self._sink._has_streams:
            self._thread = threading.Thread(
                target=self._heartbeat,
                name=f"phase8-progress-{name}",
                daemon=True,
            )
            self._thread.start()

    def _emit(self, done: int) -> None:
        elapsed = time.perf_counter() - self._started
        rate = done / elapsed if elapsed > 0.0 and done > 0 else 0.0
        remaining = (self._total - done) / rate if rate > 0.0 else -1.0
        percent = 100.0 * done / self._total if self._total else 100.0
        eta = f"{remaining:.0f}s" if remaining >= 0.0 else _PENDING
        self._sink._write(
            f"{_timestamp()} phase={self._name} done={done} total={self._total} "
            f"pct={percent:.1f} rate={rate:.2f}/s elapsed={elapsed:.1f}s eta={eta}"
        )
        self._last_emit = elapsed
        self._emitted_done = done

    def _heartbeat(self) -> None:
        """Emit the current count even while one item is still running."""
        while not self._stop.wait(EMIT_INTERVAL_SECONDS):
            with self._lock:
                if self._stop.is_set():
                    return
                try:
                    self._emit(self._count)
                except Exception as exc:  # surfaced on the next foreground call
                    self._failure = exc
                    self._stop.set()
                    return

    def _raise_heartbeat_failure(self) -> None:
        if self._failure is not None:
            raise SpineError("Phase 8 progress heartbeat output failed") from self._failure

    def _join_thread(self) -> None:
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(1.0, EMIT_INTERVAL_SECONDS + 1.0))

    def close(self) -> None:
        """Stop this phase without falsely reporting it complete."""
        self._stop.set()
        self._join_thread()
        self._sink._phase_finished(self)

    def advance(self, done: int) -> None:
        """Report ``done`` items complete. Emits on interval or on completion.

        ``done`` must be a BUILT-IN int. ``int(done)`` is deliberately not
        used: it would invoke ``__int__`` on an arbitrary object, which is a
        route for a value-bearing type to reach a progress line. A bool is
        rejected for the same reason -- it is not an item count. The count
        must not go backwards and must not exceed the declared total, so a
        miscounted phase fails closed rather than reporting a false position.

        An integer-like argument is a programming error inside this package
        and raises SpineError. Anything that is not even integer-like never
        belonged here at all and raises TypeError.
        """
        completed = False
        with self._lock:
            self._raise_heartbeat_failure()
            if type(done) is not int:
                integer_like = (
                    isinstance(done, Integral)
                    or hasattr(done, "__index__")
                    or hasattr(done, "__int__")
                )
                message = (
                    "Phase 8 progress count must be a built-in integer, "
                    f"got {type(done).__name__}"
                )
                if integer_like:
                    raise SpineError(message)
                raise TypeError(message)
            if done == self._count:
                return
            if done < self._count:
                raise SpineError(
                    "Phase 8 progress count must be monotonic; "
                    f"{done} follows {self._count}"
                )
            if done > self._total:
                raise SpineError(
                    "Phase 8 progress count cannot exceed the phase total "
                    f"{self._total}, got {done}"
                )
            self._count = done
            elapsed = time.perf_counter() - self._started
            if done >= self._total or (
                elapsed - self._last_emit
            ) >= EMIT_INTERVAL_SECONDS:
                self._emit(done)
            if done >= self._total:
                self._stop.set()
                completed = True
        if completed:
            self._join_thread()
            self._sink._phase_finished(self)


class ProgressSink:
    """Writes progress lines to every configured stream, flushed immediately.

    Sealed against subclassing. Overriding ``_write`` or ``banner`` would be a
    route to place an arbitrary string, and therefore a measured value, into
    an operator log.
    """

    __slots__ = (
        "_streams", "_phases", "_phases_lock", "_write_lock", "_closed",
    )

    def __init_subclass__(cls, **kwargs: Any) -> None:
        del cls, kwargs
        raise TypeError("ProgressSink cannot be subclassed")

    def __init__(self, streams: Sequence[IO[str]] = ()) -> None:
        object.__setattr__(self, "_streams", tuple(streams))
        object.__setattr__(self, "_phases", set())
        object.__setattr__(self, "_phases_lock", threading.RLock())
        object.__setattr__(self, "_write_lock", threading.RLock())
        object.__setattr__(self, "_closed", threading.Event())

    def __setattr__(self, name: str, value: object) -> None:
        del value
        raise AttributeError(f"sealed Phase 8 ProgressSink attribute: {name}")

    @property
    def _has_streams(self) -> bool:
        return bool(self._streams)

    def _register_phase(self, phase: _PhaseProgress) -> None:
        with self._phases_lock:
            if self._closed.is_set():
                raise SpineError("Phase 8 progress sink is closed")
            self._phases.add(phase)

    def _phase_finished(self, phase: _PhaseProgress) -> None:
        with self._phases_lock:
            self._phases.discard(phase)

    def _write(self, line: str) -> None:
        with self._write_lock:
            if self._closed.is_set():
                return
            for stream in self._streams:
                stream.write(line + "\n")
                stream.flush()

    def close(self) -> None:
        """Stop every heartbeat before its streams are closed."""
        self._closed.set()
        with self._phases_lock:
            phases = tuple(self._phases)
        for phase in phases:
            phase.close()

    def banner(
        self,
        *,
        contrast_rows: int,
        day_type_rows: int,
        interaction_rows: int,
        bootstrap_workers: int,
        stage1_workers: int,
        aggregate_memory_ceiling_bytes: int,
        distinct_bootstrap_terms: int | None = None,
        resume: bool = False,
        external_checkpoint: bool = False,
    ) -> None:
        """Record the fixed totals and operating parameters at startup.

        ``distinct_bootstrap_terms`` is not knowable until Stage 1 completes,
        so it is reported as ``pending`` here and the measured count is
        emitted by :meth:`realized_terms` immediately afterwards. It is never
        invented or hardcoded.
        """
        contrast_rows = _builtin_nonnegative_int(contrast_rows, "contrast_rows")
        day_type_rows = _builtin_nonnegative_int(day_type_rows, "day_type_rows")
        interaction_rows = _builtin_nonnegative_int(
            interaction_rows, "interaction_rows"
        )
        bootstrap_workers = _builtin_nonnegative_int(
            bootstrap_workers, "bootstrap_workers"
        )
        stage1_workers = _builtin_nonnegative_int(stage1_workers, "stage1_workers")
        aggregate_memory_ceiling_bytes = _builtin_nonnegative_int(
            aggregate_memory_ceiling_bytes, "aggregate_memory_ceiling_bytes"
        )
        if not isinstance(resume, bool) or not isinstance(external_checkpoint, bool):
            raise SpineError("Phase 8 progress resume facts must be built-in booleans")
        terms = (
            _PENDING
            if distinct_bootstrap_terms is None
            else _builtin_nonnegative_int(
                distinct_bootstrap_terms, "distinct_bootstrap_terms"
            )
        )
        self._write(
            f"{_timestamp()} phase=startup contrast_rows={contrast_rows} "
            f"day_type_rows={day_type_rows} interaction_rows={interaction_rows} "
            f"bootstrap_workers={bootstrap_workers} stage1_workers={stage1_workers} "
            f"aggregate_memory_ceiling_bytes={aggregate_memory_ceiling_bytes} "
            f"resume={int(resume)} external_checkpoint={int(external_checkpoint)} "
            f"distinct_bootstrap_terms={terms}"
        )

    def realized_terms(self, distinct_bootstrap_terms: int) -> None:
        """Emit the measured distinct term count once Stage 1 has finished."""
        distinct_bootstrap_terms = _builtin_nonnegative_int(
            distinct_bootstrap_terms, "distinct_bootstrap_terms"
        )
        self._write(
            f"{_timestamp()} phase=startup "
            f"distinct_bootstrap_terms={distinct_bootstrap_terms}"
        )

    def phase(self, name: str, total: int) -> _PhaseProgress:
        if type(name) is not str or name not in PHASE_NAMES:
            raise SpineError(f"undeclared Phase 8 progress phase: {name!r}")
        return _PhaseProgress(self, name, total)


_ACTIVE: ProgressSink = ProgressSink(())
_OPENED: list[IO[str]] = []
_CONFIGURED = False


def get_sink() -> ProgressSink:
    return _ACTIVE


def is_configured() -> bool:
    """Return whether an operator-visible sink has been explicitly installed."""
    return _CONFIGURED


def configure(
    *, log_path: Path | None = None, stdout: bool = True,
    extra_streams: Sequence[IO[str]] = (),
) -> ProgressSink:
    """Install a sink writing to stdout and a dedicated real log file."""
    global _ACTIVE, _CONFIGURED
    extra_streams = tuple(extra_streams)
    if not stdout and log_path is None and not extra_streams:
        raise SpineError("Phase 8 progress configuration requires a visible stream")
    reset()
    streams: list[IO[str]] = []
    if stdout:
        streams.append(sys.stdout)
    if log_path is not None:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a", encoding="utf-8", buffering=1)
        _OPENED.append(handle)
        streams.append(handle)
    streams.extend(extra_streams)
    _ACTIVE = ProgressSink(streams)
    _CONFIGURED = True
    return _ACTIVE


def reset() -> None:
    """Restore the silent default and close anything this module opened."""
    global _ACTIVE, _CONFIGURED
    _ACTIVE.close()
    _ACTIVE = ProgressSink(())
    _CONFIGURED = False
    while _OPENED:
        handle = _OPENED.pop()
        try:
            handle.close()
        except OSError:
            pass


__all__ = [
    "EMIT_INTERVAL_SECONDS",
    "PHASE_ARTIFACTS",
    "PHASE_BOOTSTRAP_CHUNKS",
    "PHASE_BOOTSTRAP_PLANS",
    "PHASE_CONTRASTS",
    "PHASE_DAY_TYPES",
    "PHASE_INTERACTIONS",
    "PHASE_NAMES",
    "ProgressSink",
    "configure",
    "get_sink",
    "is_configured",
    "reset",
]
