"""The four fail-closed gates (spec §5.1).

    1. Rebuilt roll list == the verified 28-roll fixture (finding C)
    2. Rebuilt 5-min bars row-for-row identical to `data/mnq_active_5m_3y.csv`
    3. Symbol classification — every retained symbol matches the outright rule, every
       rejected symbol matches an explicit spread rule, exact counts in the manifest
    4. Roll causality — session d's contract fixed entirely from volumes through
       completed session d-1, and frozen for the whole Globex session

"On any gate failure: STOP. Locate the first mismatching session, classify the cause ...
Never bridge two data definitions." Every function here raises `SpineError` on failure
and returns a report on success. None of them accepts a tolerance, and none may be given
one — see .claude/skills/gate-diagnosis.

Gate 2's oracle is the locked-confirmation tier (docs/DISCREPANCIES.md D6). This module
is one of only three permitted to reference it, and it does so to validate the build, not
on behalf of any exploratory analysis.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from mnq_lab import SpineError
from mnq_lab.constants import REPO_ROOT, load_spine_constants
from mnq_lab.core.units import to_quanta
from mnq_lab.spine.rolls import build_causal_active_contract_map
from mnq_lab.spine.seal import Corpus, store_path
from mnq_lab.spine.store import BarStore
from mnq_lab.spine.symbols import OUTRIGHT_PATTERN, SPREAD_PATTERN

__all__ = [
    "ROLL_FIXTURE_PATH",
    "REFERENCE_5M_CSV",
    "gate_roll_list_equality",
    "gate_five_minute_equality",
    "gate_symbol_classification",
    "gate_roll_causality",
    "run_all_gates",
]

ROLL_FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "mnq_active_5m_3y.csv.manifest.json"

# The 5-minute regression oracle is 17 MB and is not committed (repository policy).
REFERENCE_5M_CSV = Path(
    r"C:\Users\kyawz\Documents\Codex\2026-07-27\role-context-you-are-an-elite"
    r"\data\mnq_active_5m_3y.csv"
)

EXPECTED_ROLL_COUNT = 28  # spec §3 finding C


# --- gate 1 -------------------------------------------------------------------------

def gate_roll_list_equality(
    rebuilt_rolls: list[dict[str, Any]],
    fixture_path: Path = ROLL_FIXTURE_PATH,
) -> dict[str, Any]:
    """Gate 1: the rebuilt causal roll list must equal the verified fixture exactly."""
    if not fixture_path.is_file():
        raise SpineError(
            f"roll fixture not found at {fixture_path}. Gate 1 cannot be skipped; "
            "restore the fixture rather than bypassing the gate (spec §5.1)."
        )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))["rolls"]

    if len(fixture) != EXPECTED_ROLL_COUNT:
        raise SpineError(
            f"the fixture itself has {len(fixture)} rolls, not {EXPECTED_ROLL_COUNT} "
            "(spec §3 finding C). The oracle is wrong, not the build."
        )
    if len(rebuilt_rolls) != len(fixture):
        raise SpineError(
            f"GATE 1 FAILED: rebuilt roll list has {len(rebuilt_rolls)} entries, "
            f"fixture has {len(fixture)}. Classify the cause before changing anything "
            "(roll mapping / source revision)."
        )

    for index, (built, expected) in enumerate(zip(rebuilt_rolls, fixture)):
        if built != expected:
            differing = sorted(
                key
                for key in set(built) | set(expected)
                if built.get(key) != expected.get(key)
            )
            raise SpineError(
                f"GATE 1 FAILED at roll {index} "
                f"(effective {expected.get('effective_trade_date')}): fields "
                f"{differing} differ.\n  rebuilt : {built}\n  fixture : {expected}"
            )

    return {
        "gate": "roll_list_equality",
        "status": "pass",
        "roll_count": len(rebuilt_rolls),
        "first_effective": rebuilt_rolls[0]["effective_trade_date"],
        "last_effective": rebuilt_rolls[-1]["effective_trade_date"],
    }


# --- gate 2 -------------------------------------------------------------------------

def _load_reference_five_minute(path: Path, tick_size: float) -> pd.DataFrame:
    if not path.is_file():
        raise SpineError(
            f"Gate 2 reference CSV not found at {path}. The gate cannot be skipped."
        )
    frame = pd.read_csv(
        path,
        dtype={
            "open": "float64",
            "high": "float64",
            "low": "float64",
            "close": "float64",
            "volume": "int64",
            "symbol": "string",
        },
    )
    timestamp = pd.to_datetime(frame["ts_event"], utc=True, errors="raise")
    return pd.DataFrame(
        {
            "ts_event_ns": timestamp.to_numpy(dtype="datetime64[ns]").astype(np.int64),
            "open_ticks": to_quanta(frame["open"].to_numpy(), tick_size, name="ref open"),
            "high_ticks": to_quanta(frame["high"].to_numpy(), tick_size, name="ref high"),
            "low_ticks": to_quanta(frame["low"].to_numpy(), tick_size, name="ref low"),
            "close_ticks": to_quanta(
                frame["close"].to_numpy(), tick_size, name="ref close"
            ),
            "volume": frame["volume"].to_numpy(dtype=np.int64),
            "symbol": frame["symbol"].astype(str).to_numpy(),
            "rollover": frame["rollover"].astype(str).str.lower().eq("true").to_numpy(),
        }
    )


def gate_five_minute_equality(
    store: BarStore, reference_csv: Path = REFERENCE_5M_CSV
) -> dict[str, Any]:
    """Gate 2: row-for-row identity with the reference CSV.

    Compared over the **whole reference file, with no date filter** (D2), so the
    comparison window cannot be narrowed to make the gate pass.
    """
    constants = load_spine_constants()
    reference = _load_reference_five_minute(reference_csv, constants.tick_size)
    built_symbols = store.symbol_series().astype(str)

    if store.n_rows != len(reference):
        raise SpineError(
            f"GATE 2 FAILED: rebuilt store has {store.n_rows} rows, reference has "
            f"{len(reference)}. Locate the first missing or extra timestamp and "
            "classify the cause (missing bars / duplicates / roll mapping) before "
            "changing anything."
        )

    checks = {
        "ts_event_ns": np.asarray(store["ts_event_ns"]),
        "open_ticks": np.asarray(store["open_ticks"]),
        "high_ticks": np.asarray(store["high_ticks"]),
        "low_ticks": np.asarray(store["low_ticks"]),
        "close_ticks": np.asarray(store["close_ticks"]),
        "volume": np.asarray(store["volume"]),
        "rollover": np.asarray(store["rollover"]),
    }
    for name, built in checks.items():
        expected = reference[name].to_numpy()
        mismatch = built != expected
        if mismatch.any():
            offset = int(np.flatnonzero(mismatch)[0])
            stamp = pd.Timestamp(int(reference["ts_event_ns"].iloc[offset]), tz="UTC")
            raise SpineError(
                f"GATE 2 FAILED: column {name!r} first differs at row {offset} "
                f"({stamp.isoformat()}): rebuilt {built[offset]!r}, reference "
                f"{expected[offset]!r}. Total differing rows: {int(mismatch.sum())}. "
                "Stop and classify the cause; do not add a tolerance (spec §16.6)."
            )

    symbol_mismatch = built_symbols != reference["symbol"].to_numpy()
    if symbol_mismatch.any():
        offset = int(np.flatnonzero(symbol_mismatch)[0])
        stamp = pd.Timestamp(int(reference["ts_event_ns"].iloc[offset]), tz="UTC")
        raise SpineError(
            f"GATE 2 FAILED: contract differs at row {offset} ({stamp.isoformat()}): "
            f"rebuilt {built_symbols[offset]!r}, reference "
            f"{reference['symbol'].iloc[offset]!r} — cause is roll mapping."
        )

    return {
        "gate": "five_minute_equality",
        "status": "pass",
        "rows_compared": int(len(reference)),
        "columns_compared": sorted([*checks, "symbol"]),
        "reference_csv": str(reference_csv),
    }


# --- gate 3 -------------------------------------------------------------------------

def gate_symbol_classification(manifest: dict[str, Any]) -> dict[str, Any]:
    """Gate 3: the recorded classification is an exhaustive, exact partition.

    Spec §14 struck "assert ~1.6% spread rows". This checks membership and exact
    counts, never a proportion.
    """
    block = manifest.get("symbol_classification")
    if not block:
        raise SpineError("GATE 3 FAILED: manifest carries no symbol_classification")

    retained = block["retained_symbols"]
    rejected = block["rejected_spread_symbols"]

    bad_retained = [s for s in retained if not OUTRIGHT_PATTERN.fullmatch(s)]
    if bad_retained:
        raise SpineError(
            f"GATE 3 FAILED: retained symbols do not match the outright rule "
            f"{OUTRIGHT_PATTERN.pattern!r}: {sorted(bad_retained)[:10]}"
        )
    bad_rejected = [s for s in rejected if not SPREAD_PATTERN.fullmatch(s)]
    if bad_rejected:
        raise SpineError(
            f"GATE 3 FAILED: rejected symbols do not match the spread rule "
            f"{SPREAD_PATTERN.pattern!r}: {sorted(bad_rejected)[:10]}"
        )
    overlap = set(retained) & set(rejected)
    if overlap:
        raise SpineError(f"GATE 3 FAILED: symbols in both classes: {sorted(overlap)}")

    # Every recorded aggregate is RECOMPUTED from the listed partition, never trusted.
    # Audit finding M1 (2026-07-28): the previous version accepted a manifest whose
    # distinct_symbol_count said 999 and whose row totals disagreed with the per-symbol
    # lists, because it compared recorded numbers against each other instead of against
    # the lists. Limitation, stated honestly: the per-symbol row values themselves are
    # only verifiable at scan time against the source; this gate verifies that every
    # aggregate is consistent with the lists and that the lists cover the source total.
    if block["retained_symbol_count"] != len(retained):
        raise SpineError(
            f"GATE 3 FAILED: retained_symbol_count is {block['retained_symbol_count']} "
            f"but {len(retained)} symbols are listed"
        )
    if block["rejected_spread_symbol_count"] != len(rejected):
        raise SpineError(
            "GATE 3 FAILED: rejected_spread_symbol_count is "
            f"{block['rejected_spread_symbol_count']} but {len(rejected)} are listed"
        )
    recomputed_distinct = len(retained) + len(rejected)
    if block["distinct_symbol_count"] != recomputed_distinct:
        raise SpineError(
            f"GATE 3 FAILED: distinct_symbol_count is {block['distinct_symbol_count']} "
            f"but the lists contain {recomputed_distinct} symbols"
        )
    recomputed_retained_rows = sum(int(count) for count in retained.values())
    if block["retained_rows"] != recomputed_retained_rows:
        raise SpineError(
            f"GATE 3 FAILED: retained_rows is {block['retained_rows']} but the listed "
            f"per-symbol counts sum to {recomputed_retained_rows}"
        )
    recomputed_rejected_rows = sum(int(count) for count in rejected.values())
    if block["rejected_spread_rows"] != recomputed_rejected_rows:
        raise SpineError(
            f"GATE 3 FAILED: rejected_spread_rows is {block['rejected_spread_rows']} "
            f"but the listed per-symbol counts sum to {recomputed_rejected_rows}"
        )

    total_rows = recomputed_retained_rows + recomputed_rejected_rows
    source_rows = manifest["source"]["rows"]
    if total_rows != source_rows:
        raise SpineError(
            f"GATE 3 FAILED: classification covers {total_rows} rows but the source has "
            f"{source_rows}. The partition is not exhaustive — {source_rows - total_rows} "
            "rows are unaccounted for."
        )

    return {
        "gate": "symbol_classification",
        "status": "pass",
        "retained_symbol_count": block["retained_symbol_count"],
        "rejected_spread_symbol_count": block["rejected_spread_symbol_count"],
        "distinct_symbol_count": block["distinct_symbol_count"],
        "retained_rows": block["retained_rows"],
        "rejected_spread_rows": block["rejected_spread_rows"],
    }


# --- gate 4 -------------------------------------------------------------------------

def _causality_fixture(session_d_flips: bool) -> dict[tuple[str, str], int]:
    """Per-session volume aggregates for the two-version Gate 4 fixture.

    `daily_volume` is keyed by CME trade date, and a trade date's aggregate covers its
    whole Globex session beginning 17:00 CT — so making session d's aggregate wholly
    different IS the spec's "diverge from 17:00 CT at the start of session d" at this
    layer. (The CSV-level 17:00 CT divergence, including the overnight-volume subtlety,
    is additionally proven in tests/test_roll_causality.py.)
    """
    near, far = "MNQM1", "MNQU1"
    sessions = ["2021-06-08", "2021-06-09", "2021-06-10", "2021-06-11"]
    session_d = "2021-06-10"
    volumes: dict[tuple[str, str], int] = {}
    for trade_date in sessions:
        flipped = session_d_flips and trade_date == session_d
        volumes[(trade_date, near)] = 2 if flipped else 500
        volumes[(trade_date, far)] = 20_000 if flipped else 3
    return volumes


def _run_causality_fixture() -> dict[str, Any]:
    """Execute the real selector on the two-version fixture. Raises on any breach.

    Audit finding H1 (2026-07-28): the previous version of this gate checked only
    observable store properties, so `python -m mnq_lab.spine.gates` could report Gate 4
    passed without ever executing the decisive fixture. This function closes that gap:
    it calls `rolls.build_causal_active_contract_map` — the same function `build.py`
    imports — directly.

    Three assertions, each load-bearing:
      1. session d's assignment is identical across the two versions (causality);
      2. session d+1's assignment DIFFERS across versions (the divergence actually
         reaches the map — without this, 1 passes vacuously on an inert fixture);
      3. a deliberately leaky same-day selector produces DIFFERENT session-d
         assignments on the same fixture (the fixture can detect the defect it exists
         to detect — a gate that cannot fail is worse than no gate).
    """
    near, far = "MNQM1", "MNQU1"
    session_d, session_after = "2021-06-10", "2021-06-11"
    first_year = {near: 2021, far: 2021}

    baseline = build_causal_active_contract_map(
        _causality_fixture(session_d_flips=False), first_year
    ).active
    flipped = build_causal_active_contract_map(
        _causality_fixture(session_d_flips=True), first_year
    ).active

    if baseline[session_d] != flipped[session_d] or baseline[session_d] != near:
        raise SpineError(
            f"GATE 4 FAILED: the selector assigned {flipped[session_d]!r} to session "
            f"{session_d} when that session's own volume flipped ({baseline[session_d]!r} "
            "without the flip). Session d's contract consumed session d's volume — the "
            "selection is not causal (spec §5.1 gate 4)."
        )
    if baseline[session_after] == flipped[session_after]:
        raise SpineError(
            "GATE 4 FAILED (fixture inert): session d's flipped volume did not change "
            f"session {session_after}'s assignment, so the fixture cannot distinguish "
            "a causal selector from a non-causal one and the check above proved nothing."
        )

    def _leaky(volumes: dict[tuple[str, str], int]) -> str:
        by_day: dict[str, dict[str, int]] = {}
        for (trade_date, symbol), volume in volumes.items():
            by_day.setdefault(trade_date, {})[symbol] = volume
        day = by_day[session_d]
        return max(day, key=lambda symbol: day[symbol])

    leaky_baseline = _leaky(_causality_fixture(session_d_flips=False))
    leaky_flipped = _leaky(_causality_fixture(session_d_flips=True))
    if leaky_baseline == leaky_flipped:
        raise SpineError(
            "GATE 4 FAILED (self-check): a same-day selector was NOT caught by this "
            "fixture, so the fixture has no detection power and Gate 4 is vacuous."
        )

    return {
        "fixture_session_d": session_d,
        "session_d_assignment": near,
        "divergence_reached_next_session": [
            baseline[session_after],
            flipped[session_after],
        ],
        "leaky_selector_detected": True,
    }


def gate_roll_causality(store: BarStore, manifest: dict[str, Any]) -> dict[str, Any]:
    """Gate 4: roll causality, tested directly (spec §5.1 gate 4).

    Three layers, all required:

      a. the synthetic two-version fixture executed against the real selector
         (`_run_causality_fixture`) — the decisive test;
      b. every roll's effective trade date is strictly after its trigger trade date, so
         no recorded roll consumed the session it applies to;
      c. each CME trade date carries exactly one contract in the built bars — the
         assignment is frozen for the whole Globex session and never recalculated at
         RTH.

    Scope, stated honestly: layer (a) certifies the selector in `mnq_lab.spine.rolls`,
    which is the function `build.py` imports. If a build bypassed that module entirely,
    this gate would not see it — Gate 1's fixture equality and the full CSV-path test in
    `tests/test_roll_causality.py` are the guards on that flank.
    """
    fixture_report = _run_causality_fixture()

    for roll in manifest["rolls"]:
        trigger = roll.get("trigger_trade_date")
        effective = roll.get("effective_trade_date")
        if trigger is None:
            continue  # post_expiry_guard rolls use the public contract calendar
        if effective is None or effective <= trigger:
            raise SpineError(
                f"GATE 4 FAILED: roll {roll} takes effect on {effective!r}, which is "
                f"not strictly after its trigger session {trigger!r}. The selection "
                "consumed the session it applies to."
            )

    session_ids = np.asarray(store["session_id"])
    symbol_codes = np.asarray(store["symbol_code"])
    order = np.lexsort((symbol_codes, session_ids))
    sorted_sessions = session_ids[order]
    sorted_codes = symbol_codes[order]

    # Within a session (adjacent rows sharing a session id), the contract must never
    # change. Sorting by (session, code) puts any second contract adjacent to the first.
    same_session = sorted_sessions[1:] == sorted_sessions[:-1]
    code_changed = sorted_codes[1:] != sorted_codes[:-1]
    violation = same_session & code_changed
    if violation.any():
        offset = int(np.flatnonzero(violation)[0])
        raise SpineError(
            f"GATE 4 FAILED: trade date {int(sorted_sessions[offset])} carries more "
            f"than one contract (codes {int(sorted_codes[offset])} and "
            f"{int(sorted_codes[offset + 1])}). The active contract was recalculated "
            "inside a Globex session."
        )

    return {
        "gate": "roll_causality",
        "status": "pass",
        "sessions_checked": int(len(np.unique(session_ids))),
        "rolls_checked": len(manifest["rolls"]),
        "selector_fixture": fixture_report,
        "note": (
            "certifies the selector in mnq_lab.spine.rolls plus store observables; the "
            "full CSV-path 17:00 CT fixture is tests/test_roll_causality.py"
        ),
    }


# --- runner -------------------------------------------------------------------------

def run_all_gates(
    out_root: Path | str,
    *,
    reference_csv: Path = REFERENCE_5M_CSV,
    fixture_path: Path = ROLL_FIXTURE_PATH,
) -> dict[str, Any]:
    out_root = Path(out_root)
    locked_5m = BarStore.open(store_path(out_root, Corpus.LOCKED_CONFIRMATION, "5m"))
    exploration_5m = BarStore.open(store_path(out_root, Corpus.EXPLORATION, "5m"))

    locked_5m.verify_hashes()
    exploration_5m.verify_hashes()

    manifest = locked_5m.manifest
    results = [
        gate_roll_list_equality(manifest["rolls"], fixture_path),
        gate_five_minute_equality(locked_5m, reference_csv),
        gate_symbol_classification(manifest),
        gate_roll_causality(exploration_5m, manifest),
    ]
    return {"status": "pass", "gates": results}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the four fail-closed spine gates.")
    parser.add_argument("--store", type=Path, default=REPO_ROOT / "data")
    parser.add_argument("--reference-csv", type=Path, default=REFERENCE_5M_CSV)
    args = parser.parse_args()
    print(json.dumps(run_all_gates(args.store, reference_csv=args.reference_csv), indent=2))


if __name__ == "__main__":
    main()
