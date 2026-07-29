"""Completion accounting: per anchor × horizon window eligibility (spec §6, §10.2).

Phase 2 machinery only. Phase 3 runs this over the frozen S00 population and freezes
``min_completion_h15/h30/h60`` into the YAML with a ledger entry — that freezing is
deliberately NOT implemented here, and nothing in this module selects, ranks, or
thresholds anything.

Two estimands, exactly these names (§14 struck the rev-1–5 estimand names;
``tests/test_estimand_definition.py`` proves the struck spellings appear nowhere
in this package, including this docstring):

- ``fully_labeled_1m_grid`` — every required 5-min bar in the outcome window is
  present AND carries all five expected 1-min labels
  (``observed_1m_components == expected_1m_components == 5``). All five labels
  present proves every expected interval has an OHLCV row — not that the feed
  captured every trade (§6).
- ``observed_bar_path`` — every required 5-min bar is present in the source;
  1-minute coverage is NOT required. A bar built from three 1-min rows is rejected
  under ``fully_labeled_1m_grid`` and retained here, with the reduced coverage
  visible in ``n_fully_labeled_h*`` (§13 test 5's discriminating case). A window
  missing an entire 5-min bar is incomplete under BOTH estimands — an excursion
  across an absent interval would invent prices. The estimands differ exactly on
  1-minute coverage; that boundary choice is documented here and in
  docs/PHASE2.md.

Prevalence distinction (§10.2), kept structural in the output schema:

- ``state_anchor`` — the anchor bar exists, so a condition can be assigned
  causally at τ. Independent of every outcome window, so prevalence built on it
  is horizon-invariant by construction.
- ``outcome_eligible_<estimand>_h{Δ}`` — state anchor AND the window ``[τ, τ+Δ)``
  fits inside RTH AND the window is complete under the estimand.

Completion *rates* are reported over the structurally eligible population
(state anchors whose window fits RTH): including anchors whose window runs past
15:00 CT would fold the registered close-phase thinness (§4.2) into a number that
is supposed to measure data missingness.

Cell emission follows spec §16.4.5: every declared phase × horizon (and
year × horizon) cell is emitted with a ``status``, never dropped. ``n_anchors``
never appears without ``n_sessions`` and ``weight_ess`` beside it (§16.4.6);
``weight_ess`` is the weighting-layer statistic that arrives in Phase 4, so it is
reserved in the schema and carries NaN with ``status = "ok"`` — an honest "not
computed yet", not a claim.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from mnq_lab import SpineError
from mnq_lab.constants import load_constants
from mnq_lab.spine.seal import Corpus, assert_exploration_safe, store_path
from mnq_lab.spine.store import BarStore
from mnq_lab.spine.timemodel import (
    BAR_MINUTES,
    BAR_NS,
    STATUS_OK,
    TimeModel,
    assert_store_bar_seconds,
)

__all__ = [
    "ESTIMAND_FULLY_LABELED",
    "ESTIMAND_OBSERVED",
    "FULLY_LABELED_COMPONENTS",
    "anchor_outcome_completion",
    "completion_by_cell",
    "completion_by_year",
]

ESTIMAND_FULLY_LABELED = "fully_labeled_1m_grid"
ESTIMAND_OBSERVED = "observed_bar_path"

# "all five expected 1-min labels" (§6). Measured 2026-07-28: every bar in both
# built stores has expected_1m_components == 5, so the == 5 conjunct is currently
# redundant with observed == expected — it is kept so that a future store with
# boundary bars expecting fewer than five labels cannot silently qualify as
# "fully labeled" while carrying fewer than five.
FULLY_LABELED_COMPONENTS = 5

STATUS_CELL_OK = "ok"
STATUS_CELL_EMPTY = "no_structurally_eligible_anchors"


def anchor_outcome_completion(
    time_model: TimeModel,
    session_id: np.ndarray,
    ts_event_ns: np.ndarray,
    observed_1m_components: np.ndarray,
    expected_1m_components: np.ndarray,
) -> pd.DataFrame:
    """The declared anchor grid with per-horizon window completion, both estimands.

    One row per session × τ-gridpoint (emitted unconditionally, spec §16.4.5).
    Per declared horizon Δ, adds::

        window_fits_rth_h{Δ}                     τ + Δ ≤ rth_end (structural)
        n_required_h{Δ}                          Δ / 5, the full label grid
        n_present_h{Δ}                           required labels present in source
        n_fully_labeled_h{Δ}                     present with all five 1-min labels
        complete_fully_labeled_1m_grid_h{Δ}      n_fully_labeled == n_required
        complete_observed_bar_path_h{Δ}          n_present == n_required
        outcome_eligible_fully_labeled_1m_grid_h{Δ}
        outcome_eligible_observed_bar_path_h{Δ}  state anchor AND fits AND complete

    plus ``state_anchor`` (§10.2): the anchor bar exists; assignment at τ is
    possible regardless of any outcome window. The anchor bar's own completeness
    is NOT required (handoff §6.5 Ruling 1: the worked example lists only
    outcome-path bars as required).
    """
    labels = np.asarray(ts_event_ns)
    observed = np.asarray(observed_1m_components)
    expected = np.asarray(expected_1m_components)
    if not (labels.shape == observed.shape == expected.shape):
        raise SpineError("ts_event_ns and component columns must be aligned")
    if labels.size > 1 and int((np.diff(labels) <= 0).sum()):
        raise SpineError(
            "ts_event_ns must be strictly increasing; the spine emits one "
            "chronological active-contract chain"
        )

    grid = time_model.anchor_grid(session_id, labels)
    n_rows = len(grid)
    tau_ns = grid["tau_ns"].to_numpy(dtype=np.int64)
    tau_minute = grid["tau_ct_minute"].to_numpy(dtype=np.int32)
    state_anchor = (grid["status"] == STATUS_OK).to_numpy(dtype=bool)
    grid["state_anchor"] = state_anchor

    fully_labeled_bar = (observed == expected) & (
        expected == FULLY_LABELED_COMPONENTS
    )

    for horizon in time_model.horizons_minutes:
        k = horizon // BAR_MINUTES
        required = tau_ns[:, None] + (np.arange(k, dtype=np.int64) * BAR_NS)[None, :]
        flat = required.reshape(-1)
        idx = np.searchsorted(labels, flat)
        idx_clipped = np.minimum(idx, len(labels) - 1)
        present = (idx < len(labels)) & (labels[idx_clipped] == flat)
        fully = present & fully_labeled_bar[idx_clipped]

        n_present = present.reshape(n_rows, k).sum(axis=1).astype(np.int32)
        n_fully = fully.reshape(n_rows, k).sum(axis=1).astype(np.int32)
        fits = time_model.outcome_window_fits_rth(tau_minute, horizon)
        complete_fully = n_fully == k
        complete_observed = n_present == k

        grid[f"window_fits_rth_h{horizon}"] = fits
        grid[f"n_required_h{horizon}"] = np.full(n_rows, k, dtype=np.int32)
        grid[f"n_present_h{horizon}"] = n_present
        grid[f"n_fully_labeled_h{horizon}"] = n_fully
        grid[f"complete_{ESTIMAND_FULLY_LABELED}_h{horizon}"] = complete_fully
        grid[f"complete_{ESTIMAND_OBSERVED}_h{horizon}"] = complete_observed
        grid[f"outcome_eligible_{ESTIMAND_FULLY_LABELED}_h{horizon}"] = (
            state_anchor & fits & complete_fully
        )
        grid[f"outcome_eligible_{ESTIMAND_OBSERVED}_h{horizon}"] = (
            state_anchor & fits & complete_observed
        )

    return grid


def _summarise(frame: pd.DataFrame, group_mask: np.ndarray, horizon: int) -> dict:
    """One cell's counts and rates over its structurally eligible population."""
    rows = frame[group_mask]
    fits = rows[f"window_fits_rth_h{horizon}"].to_numpy(dtype=bool)
    state = rows["state_anchor"].to_numpy(dtype=bool)
    denominator = rows[state & fits]
    n_denom = len(denominator)
    n_fully = int(
        denominator[f"complete_{ESTIMAND_FULLY_LABELED}_h{horizon}"].sum()
    )
    n_observed = int(denominator[f"complete_{ESTIMAND_OBSERVED}_h{horizon}"].sum())
    return {
        "n_gridpoints": int(len(rows)),
        "n_state_anchors": int(state.sum()),
        "n_anchors": n_denom,  # structurally eligible: state anchor, window in RTH
        "n_sessions": int(denominator["session_id"].nunique()),
        "weight_ess": float("nan"),  # weighting arrives in Phase 4 (§7.2)
        f"n_complete_{ESTIMAND_FULLY_LABELED}": n_fully,
        f"n_complete_{ESTIMAND_OBSERVED}": n_observed,
        f"completion_rate_{ESTIMAND_FULLY_LABELED}": (
            n_fully / n_denom if n_denom else float("nan")
        ),
        f"completion_rate_{ESTIMAND_OBSERVED}": (
            n_observed / n_denom if n_denom else float("nan")
        ),
        "status": STATUS_CELL_OK if n_denom else STATUS_CELL_EMPTY,
    }


def completion_by_cell(
    completion_frame: pd.DataFrame, time_model: TimeModel
) -> pd.DataFrame:
    """Completion rates per declared phase × horizon cell — every cell emitted.

    Row order is the declared phase order × declared horizon order, never a
    measured value (§11 canonical order).
    """
    records = []
    phases = completion_frame["phase"].to_numpy(dtype=object)
    for phase in time_model.phase_names:
        for horizon in time_model.horizons_minutes:
            cell = {"phase": phase, "horizon_minutes": horizon}
            cell.update(_summarise(completion_frame, phases == phase, horizon))
            records.append(cell)
    return pd.DataFrame.from_records(records)


def completion_by_year(
    completion_frame: pd.DataFrame, time_model: TimeModel
) -> pd.DataFrame:
    """Completion rates per calendar year × horizon — the §6 selection confound.

    §16.5 item 6: measure completion by year FIRST, and say so loudly if it
    varies. Emitted for every year present in the input, in chronological order.
    """
    years = (
        completion_frame["session_id"].to_numpy(dtype=np.int64) // 10_000
    ).astype(np.int32)
    # Audit finding L-1 (2026-07-28): iterating np.unique(years) emits only the
    # years PRESENT, so a corpus spanning 2021 and 2023 silently omitted 2022's
    # three cells. Spec §16.4.5 requires every declared cell with a status; the
    # declared year axis is the contiguous span, so an absent year is emitted as
    # an empty cell rather than vanishing.
    records = []
    for year in range(int(years.min()), int(years.max()) + 1):
        for horizon in time_model.horizons_minutes:
            cell = {"year": int(year), "horizon_minutes": horizon}
            cell.update(_summarise(completion_frame, years == year, horizon))
            records.append(cell)
    return pd.DataFrame.from_records(records)


# --- CLI ---------------------------------------------------------------------------

def _run(store_root: Path) -> dict:
    exploration = BarStore.open(
        assert_exploration_safe(store_path(store_root, Corpus.EXPLORATION, "5m"))
    )
    # Audit M-5: consume the store's own declared bar duration rather than
    # assuming this engine's five minutes matches it.
    assert_store_bar_seconds(exploration.manifest)
    time_model = TimeModel.from_constants(load_constants())
    frame = anchor_outcome_completion(
        time_model,
        np.asarray(exploration["session_id"]),
        np.asarray(exploration["ts_event_ns"]),
        np.asarray(exploration["observed_1m_components"]),
        np.asarray(exploration["expected_1m_components"]),
    )
    return {
        "store": str(exploration.root),
        "n_sessions": int(frame["session_id"].nunique()),
        "n_gridpoints": int(len(frame)),
        "by_cell": completion_by_cell(frame, time_model).to_dict(orient="records"),
        "by_year": completion_by_year(frame, time_model).to_dict(orient="records"),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Completion accounting over the exploration store (spec §6). "
        "Reports rates; freezes nothing (thresholds are Phase 3, with a ledger entry)."
    )
    parser.add_argument("--store", required=True, type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(_run(args.store), indent=2))


if __name__ == "__main__":
    main()
