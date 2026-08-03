"""Descriptive four-cell interaction primitives for Phase 8."""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Real
from pathlib import Path
from typing import TYPE_CHECKING, Any, Hashable, Mapping

import numpy as np

from mnq_lab import SpineError
from mnq_lab.constants import load_constants
from mnq_lab.core.weights import session_equal_weights
from mnq_lab.phase8.contrasts import (
    OUTCOME_NAMES,
    SESSION_PHASES,
    VOLATILITY_STATES,
    CellKey,
    weighted_quantile_ticks,
)
from mnq_lab.phase8.inventory import (
    HORIZONS_MINUTES,
    PATH_ESTIMANDS,
    PRIMARY_ARM_ID,
    SUPPORT_KINDS,
)

if TYPE_CHECKING:
    from mnq_lab.phase8.uncertainty import (
        BootstrapInteractionRequest,
        BootstrapQuantileTerm,
    )

REFERENCE_PHASE = "midday"
REFERENCE_VOLATILITY_STATE = "mid"
REFERENCE_CELL = CellKey(REFERENCE_PHASE, REFERENCE_VOLATILITY_STATE)
INTERACTION_STATISTICS = ("q50", "q90")
INTERACTION_SUPPORT_KIND = "four_cell_common_sessions"
INTERACTION_POPULATION_ESTIMAND = "common_session_paired"
MIN_COMMON_SESSIONS = 20
MIN_CELL_ANCHORS = 30
DESCRIPTIVE_ONLY_LABEL = "DESCRIPTIVE ONLY - NO P-VALUE"

_INTERACTION_KEYS = ("reference_phase", "reference_vol", "support")
_INT32_INFO = np.iinfo(np.int32)

__all__ = [
    "DESCRIPTIVE_ONLY_LABEL",
    "INTERACTION_STATISTICS",
    "INTERACTION_SUPPORT_KIND",
    "INTERACTION_POPULATION_ESTIMAND",
    "MIN_CELL_ANCHORS",
    "MIN_COMMON_SESSIONS",
    "REFERENCE_CELL",
    "REFERENCE_PHASE",
    "REFERENCE_VOLATILITY_STATE",
    "FourCellSupport",
    "InteractionEvaluation",
    "InteractionResultRow",
    "InteractionRowSpec",
    "InteractionTermSupport",
    "assemble_interaction_rows",
    "build_four_cell_support",
    "declared_interaction_rows",
    "evaluate_interaction",
    "interaction_bootstrap_inputs",
    "interaction_cells",
]


@dataclass(frozen=True)
class InteractionTermSupport:
    cell: CellKey
    eligibility_mask: np.ndarray
    weights: np.ndarray
    n_anchors: int
    n_sessions: int
    weight_ess: float | None


@dataclass(frozen=True)
class FourCellSupport:
    target_cell: CellKey
    term_cells: tuple[CellKey, CellKey, CellKey, CellKey]
    retained_session_ids: tuple[Hashable, ...]
    n_common_sessions: int
    terms: tuple[
        InteractionTermSupport,
        InteractionTermSupport,
        InteractionTermSupport,
        InteractionTermSupport,
    ]


@dataclass(frozen=True)
class InteractionEvaluation:
    target_cell: CellKey
    statistic: str
    support: FourCellSupport
    completion_passes: tuple[
        tuple[CellKey, bool],
        tuple[CellKey, bool],
        tuple[CellKey, bool],
        tuple[CellKey, bool],
    ]
    support_breaches: tuple[str, ...]
    status: str
    status_flags: tuple[str, ...]
    term_quantiles_ticks: tuple[int, int, int, int] | None
    interaction_ticks: int | None
    interaction_valid: bool


@dataclass(frozen=True)
class InteractionRowSpec:
    arm_id: str
    outcome_name: str
    path_estimand: str
    support_kind: str
    horizon_minutes: int
    population_estimand: str
    statistic: str
    target_cell: CellKey

    def __post_init__(self) -> None:
        if self.arm_id != PRIMARY_ARM_ID:
            raise SpineError("interaction rows belong only to the primary arm")
        if self.outcome_name not in OUTCOME_NAMES:
            raise SpineError("interaction outcome is outside the frozen inventory")
        if self.path_estimand not in PATH_ESTIMANDS:
            raise SpineError("interaction path estimand is outside the frozen inventory")
        if self.support_kind not in SUPPORT_KINDS:
            raise SpineError("interaction support kind is outside the frozen inventory")
        if self.horizon_minutes not in HORIZONS_MINUTES:
            raise SpineError("interaction horizon is outside the frozen inventory")
        if self.population_estimand != INTERACTION_POPULATION_ESTIMAND:
            raise SpineError(
                "interaction population estimand must be common_session_paired"
            )
        if self.statistic not in INTERACTION_STATISTICS:
            raise SpineError("interaction statistic must be exactly q50 and q90")
        if not isinstance(self.target_cell, CellKey):
            raise SpineError("interaction target must be a declared CellKey")

    @property
    def structurally_degenerate(self) -> bool:
        return (
            self.target_cell.phase == REFERENCE_PHASE
            or self.target_cell.volatility_state == REFERENCE_VOLATILITY_STATE
        )


@dataclass(frozen=True)
class InteractionResultRow:
    spec: InteractionRowSpec
    reference_cell: CellKey
    interaction_ticks: int | None
    interaction_valid: bool
    common_n_sessions: int | None
    cell_anchor_counts: tuple[tuple[CellKey, int], ...]
    cell_session_counts: tuple[tuple[CellKey, int], ...]
    cell_weight_ess: tuple[tuple[CellKey, float | None], ...]
    completion_diagnostics: tuple[tuple[CellKey, bool], ...]
    status: str
    status_flags: tuple[str, ...]
    panel_label: str


def _validate_contract(constants_path: Path | None) -> None:
    constants = load_constants(constants_path)
    interaction = constants.get("interaction")
    if not isinstance(interaction, dict) or tuple(interaction) != _INTERACTION_KEYS:
        actual = tuple(interaction) if isinstance(interaction, dict) else ()
        raise SpineError(
            f"interaction constants must contain exactly {_INTERACTION_KEYS}; "
            f"found {actual}"
        )
    expected = {
        "reference_phase": REFERENCE_PHASE,
        "reference_vol": REFERENCE_VOLATILITY_STATE,
        "support": INTERACTION_SUPPORT_KIND,
    }
    if interaction != expected:
        raise SpineError("interaction constants differ from the Phase 8 contract")
    positivity = constants.get("positivity")
    if not isinstance(positivity, dict):
        raise SpineError("interaction adequacy requires the frozen positivity constants")
    if (
        positivity.get("min_baseline_anchors_per_stratum") != MIN_CELL_ANCHORS
        or positivity.get("min_contributing_sessions") != MIN_COMMON_SESSIONS
    ):
        raise SpineError("interaction adequacy thresholds differ from the contract")


def interaction_cells(
    target: CellKey,
) -> tuple[CellKey, CellKey, CellKey, CellKey]:
    """Return the four algebraic terms in fixed difference-in-differences order."""
    if not isinstance(target, CellKey):
        raise SpineError("interaction target must be a declared CellKey")
    return (
        target,
        CellKey(target.phase, REFERENCE_VOLATILITY_STATE),
        CellKey(REFERENCE_PHASE, target.volatility_state),
        REFERENCE_CELL,
    )


def _one_dimensional(values: Any, name: str) -> np.ndarray:
    try:
        array = np.asarray(values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpineError(f"{name} cannot be converted to an array: {exc}") from exc
    if array.ndim != 1:
        raise SpineError(f"{name} must be one-dimensional, got ndim={array.ndim}")
    return array


def _session_labels(values: Any) -> tuple[Hashable, ...]:
    array = _one_dimensional(values, "session_ids")
    labels: list[Hashable] = []
    for index, raw in enumerate(array):
        label = raw.item() if isinstance(raw, np.generic) else raw
        if isinstance(label, (bool, np.bool_)) or label is None:
            raise SpineError(f"session_ids contains an invalid label at index {index}")
        if isinstance(label, Real):
            try:
                finite = np.isfinite(float(label))
            except (TypeError, ValueError, OverflowError):
                finite = False
            if not finite:
                raise SpineError(
                    f"session_ids contains a non-finite label at index {index}"
                )
        elif not isinstance(label, (str, bytes)):
            raise SpineError(
                "session_ids labels must be finite numbers, strings, or bytes"
            )
        try:
            hash(label)
        except TypeError as exc:
            raise SpineError(
                f"session_ids contains an unhashable label at index {index}"
            ) from exc
        labels.append(label)
    return tuple(labels)


def _label_vector(values: Any, name: str, declared: tuple[str, ...]) -> np.ndarray:
    array = _one_dimensional(values, name)
    for index, value in enumerate(array):
        if not isinstance(value, (str, np.str_)) or value not in declared:
            raise SpineError(f"{name} contains an undeclared label at index {index}")
    return array


def _bool_vector(values: Any, name: str) -> np.ndarray:
    array = _one_dimensional(values, name)
    if array.dtype.kind != "b":
        raise SpineError(f"{name} must be a one-dimensional bool array")
    return array.astype(np.bool_, copy=False)


def _ordered_unique(values: tuple[Hashable, ...]) -> tuple[Hashable, ...]:
    seen: set[Hashable] = set()
    ordered: list[Hashable] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return tuple(ordered)


def _readonly(values: np.ndarray) -> np.ndarray:
    copied = values.copy()
    copied.setflags(write=False)
    return copied


def build_four_cell_support(
    session_ids: Any,
    session_phases: Any,
    volatility_states: Any,
    eligible: Any,
    target: CellKey,
    *,
    constants_path: Path | None = None,
) -> FourCellSupport:
    """Retain only sessions contributing eligible anchors to all four cells."""
    _validate_contract(constants_path)
    cells = interaction_cells(target)
    if len(set(cells)) != 4:
        raise SpineError("degenerate interaction rows do not build four-cell support")
    labels = _session_labels(session_ids)
    phases = _label_vector(session_phases, "session_phases", SESSION_PHASES)
    states = _label_vector(
        volatility_states, "volatility_states", VOLATILITY_STATES
    )
    eligible_mask = _bool_vector(eligible, "eligible")
    if not labels:
        raise SpineError("four-cell support requires a nonempty aligned frame")
    if len({len(labels), phases.size, states.size, eligible_mask.size}) != 1:
        raise SpineError("all four-cell support vectors must have equal length")

    cell_masks = tuple(
        eligible_mask & (phases == cell.phase) & (states == cell.volatility_state)
        for cell in cells
    )
    cell_session_sets = tuple(
        {labels[index] for index in np.flatnonzero(mask)} for mask in cell_masks
    )
    common_sessions = set.intersection(*cell_session_sets)
    retained_sessions = tuple(
        label for label in _ordered_unique(labels) if label in common_sessions
    )
    retained_set = set(retained_sessions)
    retained_mask = np.fromiter(
        (label in retained_set for label in labels),
        dtype=np.bool_,
        count=len(labels),
    )

    terms: list[InteractionTermSupport] = []
    for cell, cell_mask in zip(cells, cell_masks, strict=True):
        mask = cell_mask & retained_mask
        row_indices = np.flatnonzero(mask)
        weights = np.zeros(len(labels), dtype=np.float64)
        if row_indices.size:
            local_labels = tuple(labels[index] for index in row_indices)
            local_weights, diagnostics = session_equal_weights(local_labels)
            if diagnostics.contributing_group_count != len(retained_sessions):
                raise SpineError("four-cell terms do not share one session set")
            weights[row_indices] = local_weights
            ess: float | None = diagnostics.weight_ess
            n_sessions = diagnostics.contributing_group_count
        else:
            ess = None
            n_sessions = 0
        terms.append(
            InteractionTermSupport(
                cell=cell,
                eligibility_mask=_readonly(mask.astype(np.bool_, copy=False)),
                weights=_readonly(weights),
                n_anchors=int(row_indices.size),
                n_sessions=n_sessions,
                weight_ess=ess,
            )
        )
    return FourCellSupport(
        target_cell=target,
        term_cells=cells,
        retained_session_ids=retained_sessions,
        n_common_sessions=len(retained_sessions),
        terms=tuple(terms),
    )


def _tick_vector(values: Any, expected_size: int) -> np.ndarray:
    array = _one_dimensional(values, "interaction tick values")
    if array.size != expected_size:
        raise SpineError("interaction values must align to the complete support frame")
    if array.dtype.kind != "i":
        raise SpineError("interaction values must be signed integer ticks")
    if bool(np.any(array < _INT32_INFO.min) or np.any(array > _INT32_INFO.max)):
        raise SpineError("interaction ticks must remain within int32 storage range")
    return array


def _completion_passes(
    cells: tuple[CellKey, CellKey, CellKey, CellKey],
    values: Mapping[CellKey, bool],
) -> tuple[
    tuple[CellKey, bool],
    tuple[CellKey, bool],
    tuple[CellKey, bool],
    tuple[CellKey, bool],
]:
    if not isinstance(values, Mapping) or tuple(values) != cells:
        raise SpineError("completion diagnostics must follow structural cell order")
    result = tuple((cell, values[cell]) for cell in cells)
    if any(type(passed) is not bool for _, passed in result):
        raise SpineError("cell completion decisions must be built-in bool values")
    return result


def evaluate_interaction(
    values: Any,
    support: FourCellSupport,
    completion_passes: Mapping[CellKey, bool],
    statistic: Any,
) -> InteractionEvaluation:
    """Evaluate adequacy and, only when adequate, the raw-tick interaction."""
    if not isinstance(support, FourCellSupport):
        raise SpineError("interaction support must be FourCellSupport")
    if statistic not in INTERACTION_STATISTICS:
        raise SpineError("interaction statistic must be exactly q50 and q90")
    ticks = _tick_vector(values, support.terms[0].eligibility_mask.size)
    completions = _completion_passes(support.term_cells, completion_passes)
    breaches: list[str] = []
    if support.n_common_sessions < MIN_COMMON_SESSIONS:
        breaches.append("fewer_than_20_common_sessions")
    for term in support.terms:
        if term.n_anchors < MIN_CELL_ANCHORS:
            breaches.append(
                f"cell_below_30_anchors:{term.cell.phase}:{term.cell.volatility_state}"
            )
    for cell, passed in completions:
        if not passed:
            breaches.append(
                f"cell_failed_completion:{cell.phase}:{cell.volatility_state}"
            )
    if breaches:
        return InteractionEvaluation(
            target_cell=support.target_cell,
            statistic=statistic,
            support=support,
            completion_passes=completions,
            support_breaches=tuple(breaches),
            status="insufficient_interaction_support",
            status_flags=("insufficient_interaction_support",),
            term_quantiles_ticks=None,
            interaction_ticks=None,
            interaction_valid=False,
        )

    quantiles = tuple(
        weighted_quantile_ticks(
            ticks[term.eligibility_mask],
            term.weights[term.eligibility_mask],
            statistic,
        )
        for term in support.terms
    )
    interaction = int(
        np.int64(quantiles[0])
        - np.int64(quantiles[1])
        - np.int64(quantiles[2])
        + np.int64(quantiles[3])
    )
    return InteractionEvaluation(
        target_cell=support.target_cell,
        statistic=statistic,
        support=support,
        completion_passes=completions,
        support_breaches=(),
        status="ok",
        status_flags=(),
        term_quantiles_ticks=quantiles,
        interaction_ticks=interaction,
        interaction_valid=True,
    )


def interaction_bootstrap_inputs(
    request_id: Hashable,
    values: Any,
    evaluation: InteractionEvaluation,
) -> tuple[
    tuple[
        BootstrapQuantileTerm,
        BootstrapQuantileTerm,
        BootstrapQuantileTerm,
        BootstrapQuantileTerm,
    ],
    BootstrapInteractionRequest,
]:
    """Translate one adequate interaction into the shared Section 11 engine."""
    if not isinstance(evaluation, InteractionEvaluation):
        raise SpineError("bootstrap interaction requires an InteractionEvaluation")
    if evaluation.status != "ok" or not evaluation.interaction_valid:
        raise SpineError("bootstrap accepts only ok interaction evaluations")
    ticks = _tick_vector(
        values, evaluation.support.terms[0].eligibility_mask.size
    )
    from mnq_lab.phase8.uncertainty import (
        BootstrapInteractionRequest,
        BootstrapQuantileTerm,
    )

    terms = tuple(
        BootstrapQuantileTerm(
            (
                request_id,
                "interaction_term",
                index,
                term.cell.phase,
                term.cell.volatility_state,
                evaluation.statistic,
            ),
            ticks,
            term.eligibility_mask,
            term.weights,
            evaluation.statistic,
        )
        for index, term in enumerate(evaluation.support.terms)
    )
    request = BootstrapInteractionRequest(
        request_id,
        tuple(term.term_id for term in terms),
        evaluation.status,
    )
    return terms, request


def declared_interaction_rows() -> tuple[InteractionRowSpec, ...]:
    """Return the complete primary-arm interaction inventory in literal order."""
    return tuple(
        InteractionRowSpec(
            PRIMARY_ARM_ID,
            outcome,
            path_estimand,
            support_kind,
            horizon,
            population_estimand,
            statistic,
            CellKey(phase, state),
        )
        for outcome in OUTCOME_NAMES
        for path_estimand in PATH_ESTIMANDS
        for support_kind in SUPPORT_KINDS
        for horizon in HORIZONS_MINUTES
        for population_estimand in (INTERACTION_POPULATION_ESTIMAND,)
        for statistic in INTERACTION_STATISTICS
        for phase in SESSION_PHASES
        for state in VOLATILITY_STATES
    )


def assemble_interaction_rows(
    declared: Any,
    evaluation_by_spec: Mapping[InteractionRowSpec, InteractionEvaluation],
) -> tuple[InteractionResultRow, ...]:
    """Emit every declared row, requiring evidence for all nonreference cells."""
    if not isinstance(declared, tuple) or any(
        not isinstance(spec, InteractionRowSpec) for spec in declared
    ):
        raise SpineError("declared interaction cells must be an immutable spec tuple")
    if len(set(declared)) != len(declared):
        raise SpineError("declared interaction cells contain a duplicate")
    if not isinstance(evaluation_by_spec, Mapping):
        raise SpineError("interaction evaluations must be a mapping")
    expected = {spec for spec in declared if not spec.structurally_degenerate}
    supplied = set(evaluation_by_spec)
    missing = expected - supplied
    if missing:
        raise SpineError(f"missing declared interaction cell: {next(iter(missing))!r}")
    extras = supplied - expected
    if extras:
        raise SpineError(f"undeclared interaction cell: {next(iter(extras))!r}")

    rows: list[InteractionResultRow] = []
    for spec in declared:
        if spec.structurally_degenerate:
            rows.append(
                InteractionResultRow(
                    spec=spec,
                    reference_cell=REFERENCE_CELL,
                    interaction_ticks=None,
                    interaction_valid=False,
                    common_n_sessions=None,
                    cell_anchor_counts=(),
                    cell_session_counts=(),
                    cell_weight_ess=(),
                    completion_diagnostics=(),
                    status="degenerate_baseline",
                    status_flags=("degenerate_baseline",),
                    panel_label=DESCRIPTIVE_ONLY_LABEL,
                )
            )
            continue
        evaluation = evaluation_by_spec[spec]
        if not isinstance(evaluation, InteractionEvaluation):
            raise SpineError("interaction cell evidence has the wrong type")
        if (
            evaluation.target_cell != spec.target_cell
            or evaluation.statistic != spec.statistic
        ):
            raise SpineError("interaction evidence key differs from its declared cell")
        terms = evaluation.support.terms
        rows.append(
            InteractionResultRow(
                spec=spec,
                reference_cell=REFERENCE_CELL,
                interaction_ticks=evaluation.interaction_ticks,
                interaction_valid=evaluation.interaction_valid,
                common_n_sessions=evaluation.support.n_common_sessions,
                cell_anchor_counts=tuple(
                    (term.cell, term.n_anchors) for term in terms
                ),
                cell_session_counts=tuple(
                    (term.cell, term.n_sessions) for term in terms
                ),
                cell_weight_ess=tuple(
                    (term.cell, term.weight_ess) for term in terms
                ),
                completion_diagnostics=evaluation.completion_passes,
                status=evaluation.status,
                status_flags=evaluation.status_flags,
                panel_label=DESCRIPTIVE_ONLY_LABEL,
            )
        )
    return tuple(rows)
