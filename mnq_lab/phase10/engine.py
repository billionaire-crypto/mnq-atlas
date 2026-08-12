"""Composition of mapping, raw surfaces, standardization, coherence, and p-value."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from mnq_lab import SpineError
from mnq_lab.phase10.adapter import FormalCorpus
from mnq_lab.phase10.contract import artifact_metadata, load_phase10_contract
from mnq_lab.phase10.evaluation import RawSurfaceEvaluation, evaluate_primary_surface
from mnq_lab.phase10.mapping import apply_joint_mapping, spawn_session_mappings
from mnq_lab.phase10.pvalue import permutation_pvalue
from mnq_lab.phase10.surface import (
    SurfaceRegion,
    coherence_statistic,
    shared_standardization,
)


@dataclass(frozen=True)
class NullSurfaceBatch:
    observed: RawSurfaceEvaluation
    null_contrasts: np.ndarray
    null_valid: np.ndarray
    null_yearly_contrasts: np.ndarray
    null_yearly_valid: np.ndarray
    observed_statistic: float
    observed_regions: tuple[SurfaceRegion, ...]
    null_statistics: np.ndarray


@dataclass(frozen=True)
class FormalTestResult:
    p_value: float
    observed_statistic: float
    observed_regions: tuple[SurfaceRegion, ...]
    null_statistics: np.ndarray
    metadata: dict[str, Any]


def evaluate_null_surfaces(
    corpus: FormalCorpus,
    replications: int,
    progress: Callable[[int], None] | None = None,
) -> NullSurfaceBatch:
    """Evaluate a complete fixed-size null batch without computing a p-value."""
    mappings = spawn_session_mappings(
        corpus.session_ids, corpus.calendar_quarters, replications
    )
    observed = evaluate_primary_surface(corpus, corpus.state_codes, corpus.state_valid)
    shape = (replications, *observed.contrasts.shape)
    year_shape = (replications, *observed.yearly_contrasts.shape)
    null_contrasts = np.zeros(shape, dtype=np.int64)
    null_valid = np.zeros(shape, dtype=np.bool_)
    null_yearly = np.zeros(year_shape, dtype=np.int64)
    null_yearly_valid = np.zeros(year_shape, dtype=np.bool_)
    for index, mapping in enumerate(mappings):
        reassigned = apply_joint_mapping(
            corpus.state_codes,
            corpus.state_valid,
            (corpus.outcome_valid, corpus.window_fits_rth),
            mapping,
        )
        evaluated = evaluate_primary_surface(
            corpus, reassigned.state_codes, reassigned.state_valid
        )
        null_contrasts[index] = evaluated.contrasts
        null_valid[index] = evaluated.valid
        null_yearly[index] = evaluated.yearly_contrasts
        null_yearly_valid[index] = evaluated.yearly_valid
        if progress is not None:
            progress(index + 1)
    standardized = shared_standardization(
        observed.contrasts,
        observed.valid,
        null_contrasts,
        null_valid,
    )
    observed_surface = coherence_statistic(
        standardized.observed_z,
        standardized.observed_valid,
        observed.yearly_contrasts,
        observed.yearly_valid,
    )
    null_statistics = np.empty(replications, dtype=np.float64)
    for index in range(replications):
        null_statistics[index] = coherence_statistic(
            standardized.null_z[index],
            standardized.null_valid[index],
            null_yearly[index],
            null_yearly_valid[index],
        ).value
    return NullSurfaceBatch(
        observed,
        null_contrasts,
        null_valid,
        null_yearly,
        null_yearly_valid,
        observed_surface.value,
        observed_surface.regions,
        null_statistics,
    )


def run_formal_test(corpus: FormalCorpus, replications: int) -> FormalTestResult:
    """Run only the frozen final count; development and benchmark paths return no p-value."""
    contract = load_phase10_contract()
    if replications != contract.permutations_final:
        raise SpineError(
            "formal p-value requires exactly inference.permutations_final replications"
        )
    batch = evaluate_null_surfaces(corpus, replications)
    return FormalTestResult(
        permutation_pvalue(batch.observed_statistic, batch.null_statistics),
        batch.observed_statistic,
        batch.observed_regions,
        batch.null_statistics.copy(),
        artifact_metadata(),
    )
