"""Count real Phase 8 bootstrap evaluations without emitting result values."""

from __future__ import annotations

import hashlib
import json

import numpy as np

from mnq_lab.constants import REPO_ROOT
from mnq_lab.core.weights import session_equal_weights
from mnq_lab.ledger.ratification import require_ratified_unit_o
from mnq_lab.phase8.contrasts import (
    OUTCOME_NAMES,
    SESSION_PHASES,
    VOLATILITY_STATES,
    CellKey,
)
from mnq_lab.phase8.estimands import ESTIMAND_NAMES, build_estimand_weights
from mnq_lab.phase8.interactions import build_four_cell_support
from mnq_lab.phase8.inventory import (
    ALTERNATIVE_ARM_IDS,
    CONTRAST_WEIGHTINGS,
    HORIZONS_MINUTES,
    PATH_ESTIMANDS,
    PRIMARY_ARM_ID,
    SUPPORT_KINDS,
)


def _column(root, manifest, table_root, name):
    return np.load(
        root / table_root / manifest["columns"][name]["file"],
        mmap_mode="r",
        allow_pickle=False,
    )


def _quarter_labels(session_ids: np.ndarray) -> np.ndarray:
    years = session_ids // 10_000
    months = (session_ids // 100) % 100
    quarters = ((months - 1) // 3) + 1
    return np.char.add(
        np.char.add(years.astype("<U4"), np.asarray("Q")),
        quarters.astype("<U1"),
    )


class _EvaluationCounter:
    def __init__(self) -> None:
        self._digests: set[bytes] = set()

    def add(
        self,
        values: np.ndarray,
        weights: np.ndarray,
    ) -> None:
        rows = np.flatnonzero(weights > 0.0)
        if rows.size == 0:
            return
        digest = hashlib.sha256()
        for array in (rows, values[rows], weights[rows]):
            digest.update(str(array.dtype).encode("ascii"))
            digest.update(np.asarray(array.shape, dtype=np.int64).tobytes())
            digest.update(array.tobytes(order="C"))
        self._digests.add(digest.digest())

    def __len__(self) -> int:
        return len(self._digests)


def _condition_terms(
    counter: _EvaluationCounter,
    values_by_outcome: tuple[np.ndarray, np.ndarray],
    result,
) -> None:
    for values in values_by_outcome:
        counter.add(values, result.target.weights)
        if result.baseline is not None:
            counter.add(values, result.baseline.weights)


def main() -> None:
    root = REPO_ROOT / "data/exploration/derived/phase7-unit-o-first-run-v1"
    require_ratified_unit_o(root)
    unit = json.loads((root / "unit_o/manifest.json").read_text(encoding="utf-8"))
    phase7 = json.loads((root / "phase7/manifest.json").read_text(encoding="utf-8"))
    assignments = phase7["tables"]["assignments"]
    unit_column = lambda name: _column(root, unit, "unit_o", name)
    assignment_column = lambda name: _column(
        root, assignments, "phase7", name
    )

    unit_estimand = unit_column("estimand")
    unit_horizon = unit_column("horizon_minutes")
    unit_sessions = unit_column("session_id")
    unit_valid = unit_column("outcome_valid")
    unit_common = unit_column("common_support")
    unit_values = {name: unit_column(name) for name in OUTCOME_NAMES}

    assignment_arms = assignment_column("arm_id")
    assignment_sessions = assignment_column("session_id")
    assignment_status = assignment_column("assignment_status")
    assignment_phases = assignment_column("session_phase")
    assignment_states = assignment_column("category_name")
    assignment_class = assignment_column("calendar_session_class")
    assignment_quality = assignment_column("data_quality_status")
    assignment_holiday_adjacent = assignment_column("holiday_adjacent")

    arm_data = {}
    for arm_id in (PRIMARY_ARM_ID, *ALTERNATIVE_ARM_IDS):
        mask = assignment_arms == arm_id
        sessions = np.asarray(assignment_sessions[mask])
        states = np.asarray(assignment_states[mask]).copy()
        active = np.asarray(assignment_status[mask] == "ok")
        states[~active] = "low"
        arm_data[arm_id] = (
            sessions,
            np.asarray(assignment_phases[mask]),
            states,
            active,
            np.asarray(assignment_class[mask]),
            np.asarray(assignment_quality[mask]),
            np.asarray(assignment_holiday_adjacent[mask]),
        )

    reference_sessions = arm_data[PRIMARY_ARM_ID][0]
    quarters = _quarter_labels(reference_sessions)
    cells = tuple(
        CellKey(phase, state)
        for phase in SESSION_PHASES
        for state in VOLATILITY_STATES
    )
    counter = _EvaluationCounter()

    for path_estimand in PATH_ESTIMANDS:
        for horizon in HORIZONS_MINUTES:
            unit_slice = (unit_estimand == path_estimand) & (
                unit_horizon == horizon
            )
            sessions = np.asarray(unit_sessions[unit_slice])
            if not np.array_equal(sessions, reference_sessions):
                raise RuntimeError("Unit O and Phase 7 term-count keys differ")
            values_by_outcome = tuple(
                np.asarray(unit_values[name][unit_slice], dtype=np.int32)
                for name in OUTCOME_NAMES
            )
            primary = arm_data[PRIMARY_ARM_ID]
            phases, states, active = primary[1], primary[2], primary[3]
            ordinary = (
                (primary[4] == "regular")
                & (primary[5] == "ok")
            )
            for support_kind in SUPPORT_KINDS:
                completed = np.asarray(
                    (unit_valid if support_kind == "horizon_specific" else unit_common)[
                        unit_slice
                    ],
                    dtype=np.bool_,
                )
                eligible = completed & active
                for target in cells:
                    for estimand_name in ESTIMAND_NAMES:
                        absolute = build_estimand_weights(
                            estimand_name=estimand_name,
                            session_ids=sessions,
                            calendar_quarters=quarters,
                            session_phases=phases,
                            volatility_states=states,
                            outcome_eligible=eligible,
                            ordinary_full_length=ordinary,
                            target=target,
                            contrast_name="absolute_distribution",
                            contrast_weighting="not_applicable",
                        )
                        _condition_terms(counter, values_by_outcome, absolute)
                        for contrast_name in (
                            "phase_effect_given_vol",
                            "vol_effect_given_phase",
                            "cell_vs_complement",
                            "cell_vs_population",
                        ):
                            for weighting in CONTRAST_WEIGHTINGS:
                                result = build_estimand_weights(
                                    estimand_name=estimand_name,
                                    session_ids=sessions,
                                    calendar_quarters=quarters,
                                    session_phases=phases,
                                    volatility_states=states,
                                    outcome_eligible=eligible,
                                    ordinary_full_length=ordinary,
                                    target=target,
                                    contrast_name=contrast_name,
                                    contrast_weighting=weighting,
                                )
                                _condition_terms(
                                    counter, values_by_outcome, result
                                )

                day_types = np.full(sessions.size, "regular", dtype="<U21")
                day_types[primary[6]] = "holiday_adjacent"
                day_types[primary[4] == "scheduled_early_close"] = (
                    "scheduled_early_close"
                )
                for day_type in (
                    "scheduled_early_close",
                    "holiday_adjacent",
                    "regular",
                ):
                    day_mask = eligible & (day_types == day_type)
                    weights = np.zeros(sessions.size, dtype=np.float64)
                    if bool(np.any(day_mask)):
                        weights[day_mask], _ = session_equal_weights(
                            sessions[day_mask]
                        )
                    for values in values_by_outcome:
                        counter.add(values, weights)

                for target in cells:
                    if target.phase == "midday" or target.volatility_state == "mid":
                        continue
                    interaction = build_four_cell_support(
                        sessions,
                        phases,
                        states,
                        eligible,
                        target,
                    )
                    if interaction.n_common_sessions < 20 or any(
                        term.n_anchors < 30 for term in interaction.terms
                    ):
                        continue
                    for term in interaction.terms:
                        for values in values_by_outcome:
                            counter.add(values, term.weights)

    unit_slice = (unit_estimand == "fully_labeled_1m_grid") & (
        unit_horizon == 30
    )
    survival_values = np.asarray(
        unit_values["downward_excursion_ticks"][unit_slice], dtype=np.int32
    )
    survival_completed = np.asarray(unit_valid[unit_slice], dtype=np.bool_)
    for arm_id in ALTERNATIVE_ARM_IDS:
        sessions, phases, states, active, session_class, quality, _ = arm_data[
            arm_id
        ]
        ordinary = (session_class == "regular") & (quality == "ok")
        eligible = survival_completed & active
        for target in cells:
            for weighting in CONTRAST_WEIGHTINGS:
                result = build_estimand_weights(
                    estimand_name="prospective_cell",
                    session_ids=sessions,
                    calendar_quarters=quarters,
                    session_phases=phases,
                    volatility_states=states,
                    outcome_eligible=eligible,
                    ordinary_full_length=ordinary,
                    target=target,
                    contrast_name="vol_effect_given_phase",
                    contrast_weighting=weighting,
                )
                counter.add(survival_values, result.target.weights)
                counter.add(survival_values, result.baseline.weights)

    print(f"realized_distinct_evaluations={len(counter)}")


if __name__ == "__main__":
    main()
