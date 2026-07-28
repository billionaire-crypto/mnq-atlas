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

    total_rows = block["retained_rows"] + block["rejected_spread_rows"]
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

def gate_roll_causality(store: BarStore, manifest: dict[str, Any]) -> dict[str, Any]:
    """Gate 4, as observable on a built store.

    Two properties are checkable here:

      a. every roll's effective trade date is strictly after its trigger trade date, so
         no session's assignment consumed its own volume;
      b. each CME trade date carries exactly one contract in the built bars — the
         assignment is frozen for the whole Globex session and never recalculated at
         RTH.

    Neither is sufficient on its own. The decisive test is the synthetic two-version
    fixture diverging at 17:00 CT in `tests/test_roll_causality.py`; prefix invariance
    alone does not establish causality (spec §5.1 gate 4).
    """
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
        "note": (
            "observable properties only; the decisive 17:00 CT divergence fixture is "
            "tests/test_roll_causality.py"
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
