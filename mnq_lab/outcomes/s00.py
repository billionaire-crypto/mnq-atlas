"""Deterministic S00 completion atlas and threshold-candidate derivation.

Phase 3 only. This module consumes the exploration store, the frozen constants,
and Phase 2 completion accounting. It writes a canonical threshold-input artifact
and derives candidate completion thresholds; it does not edit the constants,
create a ledger entry, or compute any S01A/Phase 4 result.

The quantile convention was ratified by Opus 5 before implementation and is
recorded in ``docs/PHASE3_PREREGISTRATION.md``:

    s00_p05(h) = inf{x : (1/5) sum_p 1[c(p,h) <= x] >= 0.05}
                 = min_p c(p,h)

All arithmetic used for the floor is exact integer arithmetic over completion
counts. Empty, missing, duplicate, extra, non-finite, or wrong-estimand cells
fail closed rather than being dropped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from fractions import Fraction
from numbers import Integral
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from mnq_lab import SpineError
from mnq_lab.constants import Constants, load_constants
from mnq_lab.outcomes.completion import (
    ESTIMAND_FULLY_LABELED,
    ESTIMAND_OBSERVED,
    anchor_outcome_completion,
    completion_by_cell,
)
from mnq_lab.spine.seal import Corpus, assert_exploration_safe, store_path
from mnq_lab.spine.store import BarStore
from mnq_lab.spine.timemodel import TimeModel, assert_store_bar_seconds

__all__ = [
    "ARTIFACT_FILENAME",
    "ARTIFACT_SCHEMA_VERSION",
    "FROZEN_HORIZONS",
    "FROZEN_PHASES",
    "QUANTILE_CONVENTION",
    "build_s00_payload",
    "canonical_artifact_bytes",
    "derive_threshold_candidates",
    "write_s00_artifact",
]

ARTIFACT_FILENAME = "s00_threshold_input_v1.json"
ARTIFACT_SCHEMA_VERSION = "s00-completion-atlas-1"
QUANTILE_CONVENTION = "discrete_inverse_cdf_equal_phase_weights"
WEIGHT_ESS_STATUS = "not_computed_until_phase_4"

FROZEN_PHASES = ("open", "morning", "midday", "afternoon", "close")
FROZEN_HORIZONS = (15, 30, 60)

STATUS_OK = "ok"
MIN_COMPLETION_PERCENT = 90
PERCENT_SCALE = 100


def _plain_int(value: Any, field: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise SpineError(f"S00 {field} must be an integer, got {value!r}")
    return int(value)


def _validate_axes(
    phase_names: Iterable[str], horizons_minutes: Iterable[int]
) -> tuple[tuple[str, ...], tuple[int, ...]]:
    phases = tuple(phase_names)
    horizons = tuple(
        _plain_int(value, "horizon_minutes") for value in horizons_minutes
    )
    if phases != FROZEN_PHASES:
        raise SpineError(
            f"S00 requires the exact frozen phase order {FROZEN_PHASES}, got {phases}"
        )
    if horizons != FROZEN_HORIZONS:
        raise SpineError(
            f"S00 requires the exact frozen horizon order {FROZEN_HORIZONS}, "
            f"got {horizons}"
        )
    return phases, horizons


def _validated_cell_records(
    table: pd.DataFrame,
    phase_names: Iterable[str],
    horizons_minutes: Iterable[int],
    *,
    estimand: str,
) -> tuple[
    tuple[str, ...],
    tuple[int, ...],
    dict[tuple[str, int], dict[str, Any]],
]:
    if estimand != ESTIMAND_FULLY_LABELED:
        raise SpineError(
            "S00 threshold input must use fully_labeled_1m_grid; "
            f"wrong estimand {estimand!r} was requested"
        )
    phases, horizons = _validate_axes(phase_names, horizons_minutes)
    required_columns = {
        "phase",
        "horizon_minutes",
        "n_anchors",
        f"n_complete_{estimand}",
        f"completion_rate_{estimand}",
        "status",
    }
    missing_columns = sorted(required_columns - set(table.columns))
    if missing_columns:
        raise SpineError(f"S00 threshold table is missing columns {missing_columns}")

    expected_pairs = [(phase, horizon) for phase in phases for horizon in horizons]
    expected_set = set(expected_pairs)
    records: dict[tuple[str, int], dict[str, Any]] = {}
    for record in table.to_dict(orient="records"):
        phase = record["phase"]
        if not isinstance(phase, str):
            raise SpineError(f"S00 phase must be a string, got {phase!r}")
        horizon = _plain_int(record["horizon_minutes"], "horizon_minutes")
        pair = (phase, horizon)
        if pair in records:
            raise SpineError(f"S00 threshold table contains duplicate cell {pair}")
        records[pair] = record

    extras = [pair for pair in records if pair not in expected_set]
    if extras:
        raise SpineError(f"S00 threshold table contains extra cells {extras}")
    missing = [pair for pair in expected_pairs if pair not in records]
    if missing:
        raise SpineError(f"S00 threshold table is missing declared cells {missing}")

    complete_column = f"n_complete_{estimand}"
    rate_column = f"completion_rate_{estimand}"
    for pair in expected_pairs:
        record = records[pair]
        if record["status"] != STATUS_OK:
            raise SpineError(
                f"S00 cell {pair} has status {record['status']!r}; every declared "
                "phase rate must be defined before threshold derivation"
            )
        denominator = _plain_int(record["n_anchors"], f"{pair}.n_anchors")
        numerator = _plain_int(record[complete_column], f"{pair}.{complete_column}")
        if denominator <= 0:
            raise SpineError(
                f"S00 cell {pair} has zero structurally eligible anchors; its "
                "completion rate is undefined and cannot be skipped"
            )
        if numerator < 0 or numerator > denominator:
            raise SpineError(
                f"S00 cell {pair} has invalid completion counts "
                f"{numerator}/{denominator}"
            )
        rate = record[rate_column]
        if isinstance(rate, (bool, np.bool_)) or not isinstance(
            rate, (int, float, np.integer, np.floating)
        ):
            raise SpineError(f"S00 cell {pair} has non-numeric rate {rate!r}")
        rate_float = float(rate)
        if not np.isfinite(rate_float):
            raise SpineError(
                f"S00 cell {pair} has non-finite completion rate {rate!r}"
            )
        exact_float = numerator / denominator
        if rate_float != exact_float:
            raise SpineError(
                f"S00 cell {pair} rate {rate_float!r} does not equal its exact "
                f"count ratio {numerator}/{denominator}"
            )

    return phases, horizons, records


def derive_threshold_candidates(
    table: pd.DataFrame,
    phase_names: Iterable[str],
    horizons_minutes: Iterable[int],
    *,
    estimand: str = ESTIMAND_FULLY_LABELED,
) -> list[dict[str, Any]]:
    """Derive one inverse-CDF p05 and threshold candidate per horizon.

    All five phase cells have equal mass. With q=0.05 the first empirical-CDF
    jump is at least 1/5, so the inverse CDF is the minimum exact phase fraction.
    The function validates the complete declared grid before computing anything.
    """
    phases, horizons, records = _validated_cell_records(
        table, phase_names, horizons_minutes, estimand=estimand
    )
    complete_column = f"n_complete_{estimand}"

    candidates: list[dict[str, Any]] = []
    for horizon in horizons:
        phase_fractions = []
        for phase in phases:
            record = records[(phase, horizon)]
            numerator = _plain_int(record[complete_column], complete_column)
            denominator = _plain_int(record["n_anchors"], "n_anchors")
            phase_fractions.append((phase, Fraction(numerator, denominator)))

        p05 = min(fraction for _, fraction in phase_fractions)
        attaining_phases = [
            phase for phase, fraction in phase_fractions if fraction == p05
        ]
        raw_percent = (PERCENT_SCALE * p05.numerator) // p05.denominator
        threshold_percent = max(MIN_COMPLETION_PERCENT, raw_percent)
        candidates.append(
            {
                "horizon_minutes": horizon,
                "s00_p05_numerator": p05.numerator,
                "s00_p05_denominator": p05.denominator,
                "s00_p05_decimal": float(p05),
                "s00_p05_attaining_phases": attaining_phases,
                "raw_threshold": raw_percent / PERCENT_SCALE,
                "min_completion_candidate": (
                    threshold_percent / PERCENT_SCALE
                ),
            }
        )
    return candidates


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _date_string(session_id: int) -> str:
    text = f"{session_id:08d}"
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def _required_manifest_value(manifest: dict[str, Any], key: str) -> Any:
    if key not in manifest:
        raise SpineError(f"exploration manifest is missing required field {key!r}")
    return manifest[key]


def _session_flag_census(flags: pd.DataFrame, n_sessions: int) -> dict[str, int]:
    required = {
        "observed_short_session",
        "observed_rth_ended_early",
        "observed_no_rth_bars",
        "observed_mid_rth_gap",
        "calendar_early_close",
    }
    missing = sorted(required - set(flags.columns))
    if missing:
        raise SpineError(f"session flags are missing required columns {missing}")
    if len(flags) != n_sessions:
        raise SpineError(
            f"session flag rows {len(flags)} do not match source sessions {n_sessions}"
        )
    calendar = flags["calendar_early_close"]
    if not (calendar == "unknown").all():
        raise SpineError(
            "calendar_early_close must remain 'unknown' for every S00 session"
        )
    ended = flags["observed_rth_ended_early"].to_numpy(dtype=bool)
    no_rth = flags["observed_no_rth_bars"].to_numpy(dtype=bool)
    gap = flags["observed_mid_rth_gap"].to_numpy(dtype=bool)
    if np.any(ended & no_rth):
        raise SpineError(
            "observed_rth_ended_early and observed_no_rth_bars must be disjoint"
        )
    return {
        "n_sessions": n_sessions,
        "n_observed_short_session": int(
            flags["observed_short_session"].sum()
        ),
        "n_observed_rth_ended_early": int(ended.sum()),
        "n_observed_no_rth_bars": int(no_rth.sum()),
        "n_observed_mid_rth_gap": int(gap.sum()),
        "n_observed_rth_ended_early_and_mid_rth_gap": int((ended & gap).sum()),
        "n_calendar_early_close_unknown": int((calendar == "unknown").sum()),
    }


def _artifact_rows(table: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for record in table.to_dict(orient="records"):
        row = {
            "phase": str(record["phase"]),
            "horizon_minutes": _plain_int(
                record["horizon_minutes"], "horizon_minutes"
            ),
            "n_gridpoints": _plain_int(record["n_gridpoints"], "n_gridpoints"),
            "n_state_anchors": _plain_int(
                record["n_state_anchors"], "n_state_anchors"
            ),
            "n_anchors": _plain_int(record["n_anchors"], "n_anchors"),
            "n_sessions": _plain_int(record["n_sessions"], "n_sessions"),
            "weight_ess": None,
            "weight_ess_status": WEIGHT_ESS_STATUS,
            f"n_complete_{ESTIMAND_FULLY_LABELED}": _plain_int(
                record[f"n_complete_{ESTIMAND_FULLY_LABELED}"],
                f"n_complete_{ESTIMAND_FULLY_LABELED}",
            ),
            f"completion_rate_{ESTIMAND_FULLY_LABELED}": float(
                record[f"completion_rate_{ESTIMAND_FULLY_LABELED}"]
            ),
            f"n_complete_{ESTIMAND_OBSERVED}": _plain_int(
                record[f"n_complete_{ESTIMAND_OBSERVED}"],
                f"n_complete_{ESTIMAND_OBSERVED}",
            ),
            f"completion_rate_{ESTIMAND_OBSERVED}": float(
                record[f"completion_rate_{ESTIMAND_OBSERVED}"]
            ),
            "status": str(record["status"]),
        }
        rows.append(row)
    return rows


def build_s00_payload(
    store_root: Path | str, constants: Constants | None = None
) -> dict[str, Any]:
    """Build the complete in-memory S00 artifact from the exploration store."""
    frozen = constants if constants is not None else load_constants()
    time_model = TimeModel.from_constants(frozen)
    phases, horizons = _validate_axes(
        time_model.phase_names, time_model.horizons_minutes
    )

    if frozen.get("estimands", "path") != ESTIMAND_FULLY_LABELED:
        raise SpineError(
            "S00 requires estimands.path = fully_labeled_1m_grid"
        )
    source_population = frozen.get("completion", "source_population")
    if not isinstance(source_population, dict):
        raise SpineError("completion.source_population must be a mapping")
    if frozen.get("completion", "source_population", "rth_only") is not True:
        raise SpineError("S00 requires completion.source_population.rth_only = true")
    if (
        frozen.get(
            "completion", "source_population", "include_holidays_flagged"
        )
        is not True
    ):
        raise SpineError(
            "S00 requires holidays/short sessions to remain included and flagged"
        )
    if (
        frozen.get("completion", "source_population", "include_thin_cells")
        is not True
    ):
        raise SpineError("S00 requires thin cells to remain included")
    declared_dates = frozen.get("completion", "source_population", "years")
    if declared_dates != ["2019-05-05", "2023-03-29"]:
        raise SpineError(
            "S00 requires the frozen inclusive population bounds "
            "2019-05-05 through 2023-03-29"
        )

    exploration_path = assert_exploration_safe(
        store_path(Path(store_root), Corpus.EXPLORATION, "5m")
    )
    exploration = BarStore.open(exploration_path)
    assert_store_bar_seconds(exploration.manifest)

    sessions = np.asarray(exploration["session_id"])
    labels = np.asarray(exploration["ts_event_ns"])
    observed = np.asarray(exploration["observed_1m_components"])
    expected = np.asarray(exploration["expected_1m_components"])
    unique_sessions = np.unique(sessions)
    if unique_sessions.size == 0:
        raise SpineError("S00 exploration store contains no sessions")

    declared_start = int(declared_dates[0].replace("-", ""))
    declared_end = int(declared_dates[1].replace("-", ""))
    actual_first = int(unique_sessions[0])
    actual_last = int(unique_sessions[-1])
    if actual_first < declared_start or actual_last > declared_end:
        raise SpineError(
            f"S00 exploration sessions {actual_first}..{actual_last} fall outside "
            f"declared bounds {declared_start}..{declared_end}"
        )

    frame = anchor_outcome_completion(
        time_model, sessions, labels, observed, expected
    )
    n_sessions = int(unique_sessions.size)
    if frame["session_id"].nunique() != n_sessions:
        raise SpineError("S00 anchor grid did not retain every exploration session")
    table = completion_by_cell(frame, time_model)
    candidates = derive_threshold_candidates(
        table, phases, horizons, estimand=ESTIMAND_FULLY_LABELED
    )
    flags = time_model.session_flags(sessions, labels)
    census = _session_flag_census(flags, n_sessions)

    manifest_path = exploration.root / "manifest.json"
    manifest = exploration.manifest
    manifest_first = _plain_int(
        _required_manifest_value(manifest, "trade_date_first"),
        "manifest.trade_date_first",
    )
    manifest_last = _plain_int(
        _required_manifest_value(manifest, "trade_date_last"),
        "manifest.trade_date_last",
    )
    if (manifest_first, manifest_last) != (actual_first, actual_last):
        raise SpineError(
            "exploration manifest trade-date bounds do not match session_id data"
        )

    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "program_id": frozen.get("program_id"),
        "spec_version": frozen.get("spec_version"),
        "study": "S00",
        "tier": Corpus.EXPLORATION.value,
        "source_population": {
            "declared_start_inclusive": declared_dates[0],
            "declared_end_inclusive": declared_dates[1],
            "actual_first_session": _date_string(actual_first),
            "actual_last_session": _date_string(actual_last),
            "n_sessions": n_sessions,
            "n_gridpoints": int(len(frame)),
            "rth_only": True,
            "include_holidays_and_short_sessions_flagged": True,
            "include_thin_cells": True,
            "calendar_early_close_status": "unknown",
        },
        "store_provenance": {
            "build_id": _required_manifest_value(manifest, "build_id"),
            "pipeline_version": _required_manifest_value(
                manifest, "pipeline_version"
            ),
            "bar_seconds": _plain_int(
                _required_manifest_value(manifest, "bar_seconds"),
                "manifest.bar_seconds",
            ),
            "row_count": _plain_int(
                _required_manifest_value(manifest, "row_count"),
                "manifest.row_count",
            ),
            "manifest_sha256": _sha256_file(manifest_path),
        },
        "path_estimand": ESTIMAND_FULLY_LABELED,
        "observed_path_estimand_role": "diagnostic_only",
        "quantile": {
            "name": "s00_p05",
            "q_numerator": 1,
            "q_denominator": 20,
            "convention": QUANTILE_CONVENTION,
            "phase_weights": "equal",
            "all_five_phase_cells_required": True,
        },
        "threshold_rule": frozen.get("completion", "rule"),
        "session_flag_census": census,
        "rows": _artifact_rows(table),
        "candidates": candidates,
    }


def canonical_artifact_bytes(payload: dict[str, Any]) -> bytes:
    """Strict, stable JSON bytes; non-finite floats are refused."""
    try:
        text = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise SpineError(f"S00 artifact is not strict canonical JSON: {exc}") from exc
    return (text + "\n").encode("utf-8")


def write_s00_artifact(payload: dict[str, Any], output_path: Path | str) -> dict[str, Any]:
    """Write the exact canonical bytes and return their path, size, and SHA-256."""
    resolved = assert_exploration_safe(output_path)
    data = canonical_artifact_bytes(payload)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_bytes(data)
    return {
        "path": str(resolved),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _run(store_root: Path, output_path: Path | None = None) -> dict[str, Any]:
    payload = build_s00_payload(store_root)
    output = (
        output_path
        if output_path is not None
        else store_root / Corpus.EXPLORATION.value / "s00" / ARTIFACT_FILENAME
    )
    artifact = write_s00_artifact(payload, output)
    return {"artifact": artifact, "payload": payload}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build the deterministic S00 completion atlas from exploration data "
            "and derive threshold candidates. Does not edit the YAML or run S01A."
        )
    )
    parser.add_argument("--store", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = _run(args.store, args.output)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
