"""Independent synthetic fixtures and semantic oracles for Unit O tests.

This module deliberately imports no production outcome module.  Expected clock
labels, dependency masks, and hand-computed excursions come from the ratified
Unit O contract, so production metadata cannot become its own oracle.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from mnq_lab.spine.store import BarStore, PIPELINE_VERSION, write_store
from tests.conftest import ct_ns, five_minute_times

MINUTE_NS = 60 * 1_000_000_000
BAR_NS = 5 * MINUTE_NS


def independent_required_labels(tau_ns: int, horizon_minutes: int) -> np.ndarray:
    return np.asarray(
        [tau_ns + offset * MINUTE_NS for offset in range(0, horizon_minutes, 5)],
        dtype=np.int64,
    )


def independent_semantic_masks(
    labels: np.ndarray,
    tau_ns: int,
    horizon_minutes: int,
    estimand: str,
) -> tuple[np.ndarray, np.ndarray]:
    future = independent_required_labels(tau_ns, horizon_minutes)
    bar_coordinates = np.concatenate(
        [np.asarray([tau_ns - BAR_NS], dtype=np.int64), future]
    )
    bar_mask = np.isin(labels, bar_coordinates)
    if estimand == "fully_labeled_1m_grid":
        component_mask = np.isin(labels, future)
    elif estimand == "observed_bar_path":
        component_mask = np.zeros(len(labels), dtype=bool)
    else:
        raise AssertionError(f"unknown test estimand {estimand!r}")
    return bar_mask, component_mask


def synthetic_outcome_columns(
    trade_date: str = "2021-06-15",
    *,
    missing: tuple[str, ...] = (),
    partial: dict[str, int] | None = None,
    expected_components: dict[str, int] | None = None,
    symbol_changes: dict[str, int] | None = None,
    session_changes: dict[str, int] | None = None,
    price_overrides: dict[str, tuple[int, int, int, int]] | None = None,
) -> dict[str, np.ndarray]:
    partial = partial or {}
    expected_components = expected_components or {}
    symbol_changes = symbol_changes or {}
    session_changes = session_changes or {}
    price_overrides = price_overrides or {}
    missing_set = set(missing)
    times = [
        value
        for value in five_minute_times("08:25", "15:00")
        if value not in missing_set
    ]
    labels = np.asarray(
        [ct_ns(f"{trade_date} {value}") for value in times], dtype=np.int64
    )
    session_default = int(trade_date.replace("-", ""))
    sessions = np.asarray(
        [session_changes.get(value, session_default) for value in times],
        dtype=np.int32,
    )
    expected = np.asarray(
        [expected_components.get(value, 5) for value in times], dtype=np.int8
    )
    observed = np.asarray(
        [partial.get(value, expected_components.get(value, 5)) for value in times],
        dtype=np.int8,
    )
    symbols = np.asarray(
        [symbol_changes.get(value, 0) for value in times], dtype=np.int16
    )

    ohlc = []
    for index, value in enumerate(times):
        center = 1_000 + index
        ohlc.append(price_overrides.get(value, (center, center + 2, center - 2, center)))
    open_ticks, high_ticks, low_ticks, close_ticks = (
        np.asarray(values, dtype=np.int32) for values in zip(*ohlc, strict=True)
    )
    return {
        "ts_event_ns": labels,
        "session_id": sessions,
        "symbol_code": symbols,
        "open_ticks": open_ticks,
        "high_ticks": high_ticks,
        "low_ticks": low_ticks,
        "close_ticks": close_ticks,
        "volume": np.full(len(times), 10, dtype=np.int64),
        "expected_1m_components": expected,
        "observed_1m_components": observed,
        "component_coverage_rate": observed.astype(np.float64)
        / expected.astype(np.float64),
        "rollover": np.zeros(len(times), dtype=bool),
    }


def combine_columns(*parts: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    return {
        name: np.concatenate([part[name] for part in parts])
        for name in parts[0]
    }


def in_memory_store(
    root: Path,
    columns: dict[str, np.ndarray],
    *,
    symbols: tuple[str, ...] = ("MNQM1", "MNQU1"),
) -> BarStore:
    return BarStore(
        root=root,
        manifest={
            "corpus": "exploration",
            "frequency": "5m",
            "bar_seconds": 300,
            "program_id": "mnq-atlas-001",
            "pipeline_version": PIPELINE_VERSION,
            "build_id": "synthetic-unit-o",
            "row_count": len(columns["ts_event_ns"]),
            "trade_date_first": int(np.min(columns["session_id"])),
            "trade_date_last": int(np.max(columns["session_id"])),
            "symbols": list(symbols),
            "columns": {name: {"dtype": str(value.dtype)} for name, value in columns.items()},
        },
        _columns=columns,
    )


def write_synthetic_store(
    data_root: Path,
    columns: dict[str, np.ndarray],
    *,
    symbols: tuple[str, ...] = ("MNQM1", "MNQU1"),
) -> BarStore:
    store_root = data_root / "exploration" / "bars_5m"
    session_ids = columns["session_id"]
    write_store(
        store_root,
        columns,
        metadata={
            "corpus": "exploration",
            "frequency": "5m",
            "bar_seconds": 300,
            "program_id": "mnq-atlas-001",
            "pipeline_version": PIPELINE_VERSION,
            "build_id": "synthetic-unit-o",
            "trade_date_first": int(np.min(session_ids)),
            "trade_date_last": int(np.max(session_ids)),
            "symbols": list(symbols),
        },
    )
    return BarStore.open(store_root)


def schedule_for_store(
    store,
    *,
    close_ct: int = 900,
    status: str = "full_rth",
    excluded: tuple[int, ...] = (),
) -> "SessionScheduleTable":
    """A full-RTH schedule covering exactly the sessions a synthetic store holds.

    D32 Stage 5: ``build_outcome_table`` now requires an explicit schedule and
    has no fallback close, so synthetic fixtures must supply one. Every session
    is declared 08:30-15:00 full RTH with no interruption and no exclusion, which
    reproduces the v1 fixed-close behaviour exactly -- so these tests keep
    measuring what they measured before, and any difference they show is a real
    difference rather than a change of fixture.
    """
    import numpy as np

    from mnq_lab.spine.accepted_calendar import CALENDAR_SHA256, CALENDAR_VERSION
    from mnq_lab.spine.availability import (
        SessionSchedule,
        build_session_schedule_table,
    )

    from mnq_lab.spine.availability import SessionExclusion

    sessions = sorted({int(value) for value in np.asarray(store.column("session_id"))})
    return build_session_schedule_table(
        (
            SessionSchedule(
                session_id=session,
                scheduled_rth_open_ct=510,
                scheduled_rth_close_ct=close_ct,
                scheduled_rth_status=status,
                structural_interruptions=(),
                timezone="America/Chicago",
                calendar_version=CALENDAR_VERSION,
                calendar_sha256=CALENDAR_SHA256,
                interruption_source_id=None,
            )
            for session in sessions
        ),
        exclusions=tuple(
            SessionExclusion(
                session_id=int(session),
                reason="excluded_unresolved_official_interruption",
                source_id="TEST",
                recorded_by_ruling="D33",
            )
            for session in excluded
        ),
    )
