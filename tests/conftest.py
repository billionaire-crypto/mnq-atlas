"""Shared fixtures: a synthetic Databento-shaped source, and the real store if built.

Synthetic sources are used wherever a property can be proven on hand-built data, because
a test whose failure mode is "the 402 MB file changed" is not a test of the code. The
real store is used only for the gates, which are regression checks against it by
definition.
"""

from __future__ import annotations

import csv
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import pytest

from mnq_lab.constants import REPO_ROOT
from mnq_lab.spine.seal import Corpus, store_path
from mnq_lab.spine.store import BarStore

CT = "America/Chicago"

# --- free-space preflight ----------------------------------------------------
#
# Authorised in the re-audit 5 decision. Runs were dying partway through with
# OSError [Errno 28] / [WinError 112] because the volume holding pytest's
# temporary directory filled up, which produced failures that looked like test
# defects and made the suite unusable as a Stage 7 gate. Failing fast, before a
# single test runs, turns that into one clear message.
#
# This check NEVER deletes anything. Freeing space is a deliberate human act.
MIN_FREE_BYTES = 1536 * 1024 * 1024  # 1.5 GiB


def pytest_configure(config: pytest.Config) -> None:
    """Abort before collection when the temp volume lacks room for the run."""
    basetemp = getattr(config.option, "basetemp", None)
    target = Path(basetemp) if basetemp else Path(tempfile.gettempdir())
    # the directory may not exist yet; measure the nearest existing ancestor
    while not target.exists() and target != target.parent:
        target = target.parent
    free = shutil.disk_usage(target).free
    if free < MIN_FREE_BYTES:
        raise pytest.UsageError(
            f"Refusing to start: {free / 1024**3:.2f} GiB free on the volume holding "
            f"{target}, below the {MIN_FREE_BYTES / 1024**3:.2f} GiB minimum. "
            "A full run needs roughly 0.3 GiB of temporary space and previously "
            "failed mid-suite with 'no space left on device', which is "
            "indistinguishable from a real regression. Free space and re-run; "
            "nothing is deleted automatically."
        )
SOURCE_HEADER = [
    "ts_event",
    "rtype",
    "publisher_id",
    "instrument_id",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "symbol",
]


def ct(stamp: str) -> pd.Timestamp:
    """Exchange-local wall clock -> tz-aware UTC instant.

    Written out rather than hidden in a helper elsewhere because a worked example
    missing a timezone was one of the defects the spec's review rounds caught (§2).
    """
    return pd.Timestamp(stamp).tz_localize(CT).tz_convert("UTC")


@dataclass
class SourceBuilder:
    """Builds a minimal but schema-faithful Databento OHLCV-1m CSV."""

    rows: list[dict] = field(default_factory=list)

    def add(
        self,
        ct_stamp: str,
        symbol: str,
        *,
        volume: int,
        open_: float = 12000.0,
        high: float | None = None,
        low: float | None = None,
        close: float | None = None,
    ) -> "SourceBuilder":
        high = open_ + 1.0 if high is None else high
        low = open_ - 1.0 if low is None else low
        close = open_ + 0.25 if close is None else close
        self.rows.append(
            {
                "ts_event": ct(ct_stamp).strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
                "rtype": 33,
                "publisher_id": 1,
                "instrument_id": 8078,
                "open": f"{open_:.9f}",
                "high": f"{high:.9f}",
                "low": f"{low:.9f}",
                "close": f"{close:.9f}",
                "volume": int(volume),
                "symbol": symbol,
            }
        )
        return self

    def add_minutes(
        self,
        ct_stamps: list[str],
        symbol: str,
        *,
        volume: int,
        open_: float = 12000.0,
    ) -> "SourceBuilder":
        for stamp in ct_stamps:
            self.add(stamp, symbol, volume=volume, open_=open_)
        return self

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        ordered = sorted(self.rows, key=lambda row: (row["ts_event"], row["symbol"]))
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=SOURCE_HEADER)
            writer.writeheader()
            writer.writerows(ordered)
        return path


def session_grid(trade_date: str, times: list[str]) -> list[str]:
    """CT wall-clock stamps inside the Globex session for `trade_date`.

    A session runs 17:00 CT on the previous calendar day through 16:00 CT on
    `trade_date`. Times at or after 17:00 belong to the previous calendar day.
    """
    day = pd.Timestamp(trade_date).date()
    previous = day - pd.Timedelta(days=1)
    stamps = []
    for value in times:
        hour = int(value.split(":")[0])
        base = previous if hour >= 17 else day
        stamps.append(f"{base} {value}")
    return stamps


@pytest.fixture
def source_builder() -> SourceBuilder:
    return SourceBuilder()


# --- synthetic 5-min session arrays for the Phase 2 time-model tests ----------------

def ct_ns(stamp: str) -> int:
    """Exchange-local wall clock -> int64 UTC nanoseconds."""
    return int(ct(stamp).value)


def five_minute_times(start: str, end_exclusive: str) -> list[str]:
    """'HH:MM' labels every 5 minutes in [start, end_exclusive)."""
    to_minutes = lambda v: int(v[:2]) * 60 + int(v[3:])  # noqa: E731
    return [
        f"{m // 60:02d}:{m % 60:02d}"
        for m in range(to_minutes(start), to_minutes(end_exclusive), 5)
    ]


def synthetic_session_bars(
    trade_date: str,
    *,
    missing: tuple[str, ...] = (),
    partial: dict[str, int] | None = None,
    expected_components: dict[str, int] | None = None,
    first_label: str = "08:25",
    last_label_exclusive: str = "15:00",
):
    """5-min-bar arrays for one session, shaped like the bars_5m store columns.

    Returns ``(session_id, ts_event_ns, observed_1m, expected_1m)`` covering CT
    labels ``[first_label, last_label_exclusive)`` — by default 08:25 (the bar
    whose close is the first eligible τ = 08:30 under handoff §6.5 Ruling 1)
    through 14:55. ``missing`` drops labels entirely; ``partial`` maps a label to
    an ``observed_1m_components`` count below five; ``expected_components`` maps a
    label to an ``expected_1m_components`` count below five, which is what
    distinguishes the two conjuncts of the fully-labeled criterion (audit M-3 —
    every fixture previously set expected = 5, so dropping the `== 5` conjunct
    was undetectable).
    """
    import numpy as np

    partial = partial or {}
    expected_components = expected_components or {}
    times = [t for t in five_minute_times(first_label, last_label_exclusive)
             if t not in set(missing)]
    ts = np.asarray([ct_ns(f"{trade_date} {t}") for t in times], dtype=np.int64)
    session = np.full(len(times), int(trade_date.replace("-", "")), dtype=np.int32)
    expected = np.asarray(
        [expected_components.get(t, 5) for t in times], dtype=np.int8
    )
    observed = np.asarray(
        [partial.get(t, expected_components.get(t, 5)) for t in times], dtype=np.int8
    )
    return session, ts, observed, expected


# --- the real build, when present --------------------------------------------------

REAL_STORE_ROOT = REPO_ROOT / "data"


def _require_real_store(corpus: Corpus, frequency: str) -> BarStore:
    """Open a real store, or FAIL the test — never skip.

    Audit finding H2 (2026-07-28): with `data/` absent (it is git-ignored), the suite
    previously skipped all 63 real-store tests and exited green, so a clean checkout
    could receive a passing pytest run without a single Phase 1 acceptance gate
    executing against real artifacts. That is a fallback path around a gate
    (spec §16.4.3). The stores are a Phase 1 deliverable; their absence is a failure
    of the thing under test, not an environmental excuse.
    """
    path = store_path(REAL_STORE_ROOT, corpus, frequency)
    if not (path / "manifest.json").is_file():
        pytest.fail(
            f"Phase 1 acceptance requires the built store at {path} and it is absent. "
            "Real-store gates fail closed rather than skip (audit H2; spec §16.4.3). "
            "The canonical store is sealed against the pre-Phase-3 YAML; a direct "
            "build with the current YAML creates different provenance and is expected "
            "to fail the pinned manifest tests. Restore the preserved sealed artifact "
            "or follow docs/SEALED_STORE_REBUILD.md for the limits and procedure of a "
            "disposable scientific reconstruction.",
            pytrace=False,
        )
    return BarStore.open(path)


@pytest.fixture(scope="session")
def exploration_5m() -> BarStore:
    return _require_real_store(Corpus.EXPLORATION, "5m")


@pytest.fixture(scope="session")
def exploration_1m() -> BarStore:
    return _require_real_store(Corpus.EXPLORATION, "1m")


@pytest.fixture(scope="session")
def locked_5m() -> BarStore:
    return _require_real_store(Corpus.LOCKED_CONFIRMATION, "5m")
