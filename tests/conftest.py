"""Shared fixtures: a synthetic Databento-shaped source, and the real store if built.

Synthetic sources are used wherever a property can be proven on hand-built data, because
a test whose failure mode is "the 402 MB file changed" is not a test of the code. The
real store is used only for the gates, which are regression checks against it by
definition.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import pytest

from mnq_lab.constants import REPO_ROOT
from mnq_lab.spine.seal import Corpus, store_path
from mnq_lab.spine.store import BarStore

CT = "America/Chicago"
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
            "Build it with:\n"
            "  python -m mnq_lab.spine.build --source-csv "
            '"C:\\Users\\kyawz\\Downloads\\GLBX-20260331-885WT5W7KA\\'
            'glbx-mdp3-20100606-20260329.ohlcv-1m.csv" --out data',
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
