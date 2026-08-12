"""Primary raw-contrast evaluation by composing audited Phase 8 primitives."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np

from mnq_lab import SpineError
from mnq_lab.constants import load_completion_thresholds, load_constants
from mnq_lab.core.weights import weight_ess
from mnq_lab.phase10.adapter import FormalCorpus
from mnq_lab.phase10.contract import (
    PRIMARY_CONTRAST,
    PRIMARY_ESTIMAND,
    PRIMARY_HORIZON_MINUTES,
    PRIMARY_STATISTIC,
    load_phase10_contract,
)
from mnq_lab.phase8.contrasts import (
    SESSION_PHASES,
    VOLATILITY_STATES,
    CellKey,
    contrast_support,
    degenerate_baseline,
    prepare_weighted_quantile_ticks,
    support_masks,
    weighted_quantile_ticks,
    weighted_quantiles_ticks_prepared_batch_fast,
)
from mnq_lab.phase8.diagnostics import (
    status_decision,
)
from mnq_lab.phase8.estimands import _assigned_cell_masses


@dataclass(frozen=True)
class RawSurfaceEvaluation:
    contrasts: np.ndarray
    valid: np.ndarray
    statuses: np.ndarray
    target_n_anchors: np.ndarray
    target_n_sessions: np.ndarray
    target_weight_ess: np.ndarray
    baseline_n_anchors: np.ndarray
    baseline_n_sessions: np.ndarray
    baseline_weight_ess: np.ndarray
    yearly_contrasts: np.ndarray
    yearly_valid: np.ndarray


@dataclass(frozen=True)
class _CellWeights:
    cell: CellKey
    base_weights: np.ndarray
    assigned_mass: float
    n_anchors: int
    n_sessions: int
    max_anchor_share: float | None
    weight_cv: float | None


@dataclass(frozen=True)
class _ConditionWeights:
    weights: np.ndarray
    n_anchors: int
    n_sessions: int
    weight_ess: float | None
    cells: tuple[_CellWeights, ...]


@lru_cache(maxsize=1)
def _diagnostic_contract() -> tuple[float, float, int, int, float, float, float]:
    constants = load_constants()
    completion = load_completion_thresholds()[PRIMARY_HORIZON_MINUTES]
    return (
        completion,
        float(constants.get("completion", "max_imbalance_absolute")),
        int(constants.get("positivity", "min_baseline_anchors_per_stratum")),
        int(constants.get("positivity", "min_contributing_sessions")),
        float(constants.get("positivity", "max_single_anchor_weight_share")),
        float(constants.get("positivity", "max_weight_cv")),
        float(constants.get("positivity", "max_unsupported_target_mass")),
    )


def _state_names(codes: np.ndarray, valid: np.ndarray) -> np.ndarray:
    if codes.shape != valid.shape or codes.ndim != 2 or valid.dtype.kind != "b":
        raise SpineError("Phase 10 state code and validity matrices differ")
    if bool(np.any(valid & ((codes < 0) | (codes >= len(VOLATILITY_STATES))))):
        raise SpineError("Phase 10 valid state code is outside the imported encoding")
    names = np.full(codes.shape, VOLATILITY_STATES[0], dtype="<U4")
    for code, name in enumerate(VOLATILITY_STATES):
        names[valid & (codes == code)] = name
    return names


def _session_equal_values(group_ids: np.ndarray) -> tuple[np.ndarray, int]:
    labels = np.asarray(group_ids)
    if labels.ndim != 1 or labels.size == 0 or labels.dtype.kind not in ("i", "u"):
        raise SpineError("Phase 10 session labels lost their integer encoding")
    _, inverse, counts = np.unique(
        labels, return_inverse=True, return_counts=True
    )
    count_array = counts.astype(np.float64, copy=False)
    weights = (1.0 / (counts.size * count_array))[inverse]
    return weights, int(counts.size)


def _cell_weight_cache(
    *,
    session_ids: np.ndarray,
    phases: np.ndarray,
    states: np.ndarray,
    eligibility: np.ndarray,
) -> dict[CellKey, _CellWeights]:
    cache: dict[CellKey, _CellWeights] = {}
    for phase in SESSION_PHASES:
        for state in VOLATILITY_STATES:
            cell = CellKey(phase, state)
            mask = eligibility & (phases == phase) & (states == state)
            selected_sessions = session_ids[mask]
            anchor_count = int(selected_sessions.size)
            session_count = 0
            maximum_share = None
            weight_cv = None
            base_weights = np.zeros(session_ids.size, dtype=np.float64)
            if anchor_count:
                local, session_count = _session_equal_values(selected_sessions)
                base_weights[mask] = local
                maximum_share = float(np.max(local))
                weight_cv = float(
                    np.std(local, ddof=0, dtype=np.float64)
                    / np.mean(local, dtype=np.float64)
                )
            cache[cell] = _CellWeights(
                cell,
                base_weights,
                1.0,
                anchor_count,
                session_count,
                maximum_share,
                weight_cv,
            )
    return cache


def _fast_condition_weights(
    *,
    session_ids: np.ndarray,
    phases: np.ndarray,
    states: np.ndarray,
    eligibility: np.ndarray,
    cells: tuple[CellKey, ...],
    weighting: str,
    cache: dict[CellKey, _CellWeights] | None = None,
) -> _ConditionWeights:
    masks = tuple(
        eligibility
        & (phases == cell.phase)
        & (states == cell.volatility_state)
        for cell in cells
    )
    masses = _assigned_cell_masses(cells, masks, weighting)
    source = cache or _cell_weight_cache(
        session_ids=session_ids,
        phases=phases,
        states=states,
        eligibility=eligibility,
    )
    combined = np.zeros(session_ids.size, dtype=np.float64)
    union = np.zeros(session_ids.size, dtype=np.bool_)
    cell_rows: list[_CellWeights] = []
    for cell, mask, mass in zip(cells, masks, masses, strict=True):
        union |= mask
        base = source[cell]
        anchor_count = base.n_anchors
        session_count = base.n_sessions
        combined += base.base_weights * mass
        cell_rows.append(
            _CellWeights(
                cell,
                base.base_weights,
                float(mass),
                anchor_count,
                session_count,
                base.max_anchor_share,
                base.weight_cv,
            )
        )
    positive = combined > 0.0
    return _ConditionWeights(
        combined,
        int(np.count_nonzero(union)),
        int(np.unique(session_ids[union]).size),
        weight_ess(combined[positive]) if bool(np.any(positive)) else None,
        tuple(cell_rows),
    )


def _one_cell(
    *,
    values: np.ndarray,
    prepared_values: Any,
    session_ids: np.ndarray,
    years: np.ndarray,
    phases: np.ndarray,
    states: np.ndarray,
    active: np.ndarray,
    completed: np.ndarray,
    structural_fit: np.ndarray,
    target: CellKey,
    weighting: str,
    quantile_weights: list[np.ndarray] | None = None,
    cell_cache: dict[CellKey, _CellWeights] | None = None,
) -> tuple[int, bool, str, int, int, float, int, int, float]:
    eligible = completed & active
    support = contrast_support(target, PRIMARY_CONTRAST)
    target_weights = _fast_condition_weights(
        session_ids=session_ids,
        phases=phases,
        states=states,
        eligibility=eligible,
        cells=support.target_cells,
        weighting=weighting,
        cache=cell_cache,
    )
    baseline_weights = _fast_condition_weights(
        session_ids=session_ids,
        phases=phases,
        states=states,
        eligibility=eligible,
        cells=support.baseline_cells,
        weighting=weighting,
        cache=cell_cache,
    )
    masks = support_masks(phases, states, target, PRIMARY_CONTRAST)
    (
        completion_threshold,
        max_completion_imbalance,
        min_anchors,
        min_sessions,
        max_anchor_share,
        max_weight_cv,
        max_unsupported_mass,
    ) = _diagnostic_contract()
    structural = active & structural_fit
    target_structural = structural & masks.target
    baseline_structural = structural & masks.baseline
    target_structural_n = int(np.count_nonzero(target_structural))
    baseline_structural_n = int(np.count_nonzero(baseline_structural))
    target_completion = (
        None
        if target_structural_n == 0
        else int(np.count_nonzero(target_structural & completed))
        / target_structural_n
    )
    baseline_completion = (
        None
        if baseline_structural_n == 0
        else int(np.count_nonzero(baseline_structural & completed))
        / baseline_structural_n
    )
    completion_failed = (
        target_completion is None
        or target_completion < completion_threshold
        or baseline_completion is None
        or baseline_completion < completion_threshold
        or abs(target_completion - baseline_completion) > max_completion_imbalance
    )
    source_years = set(years[structural].tolist())
    if len(source_years) > 1:
        target_years = set(years[target_structural & completed].tolist())
        baseline_years = set(years[baseline_structural & completed].tolist())
        completion_failed = completion_failed or len(target_years) == 1 or len(baseline_years) == 1

    baseline_by_cell = {item.cell: item for item in baseline_weights.cells}
    positivity_failed = False
    unsupported_mass = 0.0
    total_mass = 0.0
    for cell in contrast_support(target, PRIMARY_CONTRAST).baseline_cells:
        cell_diagnostic = baseline_by_cell[cell]
        cell_mask = (
            eligible
            & (phases == cell.phase)
            & (states == cell.volatility_state)
        )
        cell_sessions = session_ids[cell_mask]
        anchor_count = int(cell_sessions.size)
        session_count = cell_diagnostic.n_sessions
        shortage = anchor_count < min_anchors or session_count < min_sessions
        mass = float(cell_diagnostic.assigned_mass)
        total_mass += mass
        if shortage:
            unsupported_mass += mass
            positivity_failed = True
        if anchor_count == 0 or cell_diagnostic.max_anchor_share is None:
            positivity_failed = True
            continue
        if (
            cell_diagnostic.max_anchor_share > max_anchor_share
            or cell_diagnostic.weight_cv is None
            or cell_diagnostic.weight_cv > max_weight_cv
        ):
            positivity_failed = True
    if total_mass <= 0.0 or unsupported_mass / total_mass > max_unsupported_mass:
        positivity_failed = True
    target_rows = np.flatnonzero(target_weights.weights > 0.0)
    baseline_rows = np.flatnonzero(baseline_weights.weights > 0.0)
    degenerate = False
    if target_rows.size and baseline_rows.size:
        degenerate = degenerate_baseline(
            tuple(target_rows),
            target_weights.weights[target_rows],
            tuple(baseline_rows),
            baseline_weights.weights[baseline_rows],
        )
    support_failed = (
        target_weights.n_anchors < min_anchors
        or target_weights.n_sessions == 0
        or baseline_weights.n_anchors < min_anchors
        or baseline_weights.n_sessions == 0
    )
    decision = status_decision(
        degenerate_baseline=degenerate,
        insufficient_anchors=support_failed,
        insufficient_completion=completion_failed,
        insufficient_overlap=positivity_failed,
    )
    contrast = 0
    valid = decision.status == "ok"
    if valid:
        if quantile_weights is None:
            target_tick = weighted_quantile_ticks(
                prepared_values, target_weights.weights, PRIMARY_STATISTIC
            )
            baseline_tick = weighted_quantile_ticks(
                prepared_values,
                baseline_weights.weights,
                PRIMARY_STATISTIC,
            )
            contrast = int(np.int64(target_tick) - np.int64(baseline_tick))
        else:
            quantile_weights.extend(
                (target_weights.weights, baseline_weights.weights)
            )
    return (
        contrast,
        valid,
        decision.status,
        target_weights.n_anchors,
        target_weights.n_sessions,
        float("nan") if target_weights.weight_ess is None else target_weights.weight_ess,
        baseline_weights.n_anchors,
        baseline_weights.n_sessions,
        float("nan") if baseline_weights.weight_ess is None else baseline_weights.weight_ess,
    )


def _surface_for_rows(
    *,
    values: np.ndarray,
    session_ids: np.ndarray,
    quarters: np.ndarray,
    years: np.ndarray,
    phases: np.ndarray,
    states: np.ndarray,
    active: np.ndarray,
    completed: np.ndarray,
    structural_fit: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[np.ndarray, ...]]:
    contract = load_phase10_contract()
    shape = (len(contract.weighting_planes), len(SESSION_PHASES), len(VOLATILITY_STATES))
    contrasts = np.zeros(shape, dtype=np.int64)
    valid = np.zeros(shape, dtype=np.bool_)
    statuses = np.full(shape, "", dtype="<U32")
    companions = tuple(np.zeros(shape, dtype=np.float64) for _ in range(6))
    prepared_values = prepare_weighted_quantile_ticks(values)
    cell_cache = _cell_weight_cache(
        session_ids=session_ids,
        phases=phases,
        states=states,
        eligibility=completed & active,
    )
    quantile_weights: list[np.ndarray] = []
    quantile_cells: list[tuple[int, int, int]] = []
    for plane, weighting in enumerate(contract.weighting_planes):
        for phase_index, phase in enumerate(SESSION_PHASES):
            for state_index, state in enumerate(VOLATILITY_STATES):
                result = _one_cell(
                    values=values,
                    prepared_values=prepared_values,
                    session_ids=session_ids,
                    years=years,
                    phases=phases,
                    states=states,
                    active=active,
                    completed=completed,
                    structural_fit=structural_fit,
                    target=CellKey(phase, state),
                    weighting=weighting,
                    quantile_weights=quantile_weights,
                    cell_cache=cell_cache,
                )
                contrasts[plane, phase_index, state_index] = result[0]
                valid[plane, phase_index, state_index] = result[1]
                statuses[plane, phase_index, state_index] = result[2]
                if result[1]:
                    quantile_cells.append((plane, phase_index, state_index))
                for companion, value in zip(companions, result[3:], strict=True):
                    companion[plane, phase_index, state_index] = value
    if quantile_weights:
        evaluated = weighted_quantiles_ticks_prepared_batch_fast(
            prepared_values,
            np.stack(quantile_weights),
            (PRIMARY_STATISTIC,),
        )[:, 0]
        for index, (plane, phase_index, state_index) in enumerate(quantile_cells):
            contrasts[plane, phase_index, state_index] = int(
                np.int64(evaluated[2 * index])
                - np.int64(evaluated[2 * index + 1])
            )
    return contrasts, valid, statuses, companions


def evaluate_primary_surface(
    corpus: FormalCorpus,
    state_codes: Any,
    state_valid: Any,
) -> RawSurfaceEvaluation:
    """Evaluate both frozen weighting planes and all yearly stability blocks."""
    codes = np.asarray(state_codes)
    active_matrix = np.asarray(state_valid)
    if codes.shape != corpus.state_codes.shape or active_matrix.shape != codes.shape:
        raise SpineError("Phase 10 reassigned state matrices differ from the corpus grid")
    states_matrix = _state_names(codes, active_matrix)
    width = corpus.observation_grid.size
    sessions = np.repeat(corpus.session_ids, width)
    quarters = np.repeat(corpus.calendar_quarters, width)
    years = np.repeat(corpus.calendar_years, width)
    phases = np.tile(corpus.phase_grid, corpus.session_ids.size)
    values = corpus.downward_excursion_ticks.reshape(-1)
    states = states_matrix.reshape(-1)
    active = active_matrix.reshape(-1)
    completed = corpus.outcome_valid.reshape(-1)
    structural_fit = corpus.window_fits_rth.reshape(-1)
    contrasts, valid, statuses, companions = _surface_for_rows(
        values=values,
        session_ids=sessions,
        quarters=quarters,
        years=years,
        phases=phases,
        states=states,
        active=active,
        completed=completed,
        structural_fit=structural_fit,
    )
    declared_years = tuple(dict.fromkeys(corpus.calendar_years.tolist()))
    yearly = np.zeros((len(declared_years), *contrasts.shape), dtype=np.int64)
    yearly_valid = np.zeros(yearly.shape, dtype=np.bool_)
    for year_index, year in enumerate(declared_years):
        keep = years == year
        year_contrasts, year_ok, _, _ = _surface_for_rows(
            values=values[keep],
            session_ids=sessions[keep],
            quarters=quarters[keep],
            years=years[keep],
            phases=phases[keep],
            states=states[keep],
            active=active[keep],
            completed=completed[keep],
            structural_fit=structural_fit[keep],
        )
        yearly[year_index] = year_contrasts
        yearly_valid[year_index] = year_ok
    return RawSurfaceEvaluation(
        contrasts,
        valid,
        statuses,
        companions[0].astype(np.int64),
        companions[1].astype(np.int64),
        companions[2],
        companions[3].astype(np.int64),
        companions[4].astype(np.int64),
        companions[5],
        yearly,
        yearly_valid,
    )
