"""One-shot preregistered Phase 5 stochastic acceptance fixtures.

These tests must first execute only under the exact commands and seed schedules
recorded in ``docs/PHASE5_PREREGISTRATION.md``. They contain no module-scope RNG
construction, so collection alone does not consume either registered stream.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.constants import load_bootstrap_constants
from mnq_lab.core.bootstrap import (
    bootstrap_weighted_quantile_replicates,
    percentile_interval,
)
from mnq_lab.core.weights import (
    session_equal_weights,
    weighted_quantile,
)

COVERAGE_ROOT_ENTROPY = 34269753221940478235660674215598997415
AR1_ROOT_ENTROPY = 157484425038737148717780864763684278439
BOOTSTRAP_DRAWS = 999
CONFIDENCE_LEVEL = 0.95


def _loaded_primary_mean_block_groups() -> int:
    return load_bootstrap_constants()["mean_block_sessions_primary"]


@pytest.mark.skip(
    reason=(
        "one-shot executed 2026-07-30: 267/300 FAILED [277,292]; permanently "
        "recorded in docs/PHASE5_ACCEPTANCE_RECORD.md and D15; must never "
        "re-execute"
    )
)
def test_preregistered_synthetic_median_coverage_once():
    outer_count = 300
    session_count = 80
    rows_per_session = 4
    lower_coverage_count = 277
    upper_coverage_count = 292
    mean_block_groups = _loaded_primary_mean_block_groups()
    group_ids = np.repeat(
        np.arange(session_count, dtype=np.int64),
        rows_per_session,
    )
    baseline_weights, _ = session_equal_weights(group_ids)
    eligibility = np.ones(group_ids.size, dtype=bool)
    outer_sequences = np.random.SeedSequence(
        COVERAGE_ROOT_ENTROPY
    ).spawn(outer_count)
    coverage_count = 0

    for outer_sequence in outer_sequences:
        data_sequence, bootstrap_sequence = outer_sequence.spawn(2)
        data_rng = np.random.Generator(np.random.PCG64(data_sequence))
        bootstrap_rng = np.random.Generator(
            np.random.PCG64(bootstrap_sequence)
        )
        session_values = data_rng.standard_normal(session_count)
        values = np.repeat(session_values, rows_per_session)
        replicates = bootstrap_weighted_quantile_replicates(
            group_ids,
            baseline_weights,
            (values,),
            (eligibility,),
            (0.5,),
            BOOTSTRAP_DRAWS,
            mean_block_groups,
            bootstrap_rng,
        )[0]
        lower, upper = percentile_interval(
            replicates,
            CONFIDENCE_LEVEL,
        )
        coverage_count += int(lower <= 0.0 <= upper)

    evidence = {
        "acceptance_bounds_inclusive": [
            lower_coverage_count,
            upper_coverage_count,
        ],
        "coverage_count": coverage_count,
        "outer_replications": outer_count,
    }
    print("PHASE5_COVERAGE_RESULT=" + json.dumps(evidence, sort_keys=True))
    assert lower_coverage_count <= coverage_count <= upper_coverage_count


def _ar1_session_values(
    rng: np.random.Generator,
    session_count: int,
    rows_per_session: int,
) -> np.ndarray:
    innovations = rng.standard_normal((session_count, rows_per_session))
    values = np.empty_like(innovations)
    values[:, 0] = innovations[:, 0]
    for row_index in range(1, rows_per_session):
        values[:, row_index] = (
            0.8 * values[:, row_index - 1]
            + 0.6 * innovations[:, row_index]
        )
    return values.reshape(-1)


def _iid_row_bootstrap_median_replicates(
    values: np.ndarray,
    baseline_weights: np.ndarray,
    draws: int,
    rng: np.random.Generator,
) -> np.ndarray:
    row_count = values.size
    replicates = np.empty(draws, dtype=np.float64)
    for replicate_index in range(draws):
        selected_positions = rng.integers(
            row_count,
            size=row_count,
        )
        multiplicities = np.bincount(
            selected_positions,
            minlength=row_count,
        )
        row_weights = baseline_weights * multiplicities
        try:
            statistic = weighted_quantile(
                values,
                row_weights,
                0.5,
            )
        except SpineError as exc:
            raise SpineError(
                f"row-bootstrap replicate {replicate_index} failed: {exc}"
            ) from exc
        if not np.isfinite(statistic):
            raise SpineError(
                "row-bootstrap replicate "
                f"{replicate_index} produced a non-finite statistic"
            )
        replicates[replicate_index] = statistic
    return replicates


def test_preregistered_ar1_session_width_discriminator_once():
    outer_count = 24
    session_count = 64
    rows_per_session = 32
    row_count = session_count * rows_per_session
    minimum_median_ratio = 1.50
    minimum_directional_count = 20
    mean_block_groups = _loaded_primary_mean_block_groups()
    group_ids = np.repeat(
        np.arange(session_count, dtype=np.int64),
        rows_per_session,
    )
    baseline_weights, _ = session_equal_weights(group_ids)
    eligibility = np.ones(row_count, dtype=bool)
    outer_sequences = np.random.SeedSequence(AR1_ROOT_ENTROPY).spawn(
        outer_count
    )
    session_widths = np.empty(outer_count, dtype=np.float64)
    row_widths = np.empty(outer_count, dtype=np.float64)
    ratios = np.empty(outer_count, dtype=np.float64)

    for outer_index, outer_sequence in enumerate(outer_sequences):
        data_sequence, session_sequence, row_sequence = outer_sequence.spawn(3)
        data_rng = np.random.Generator(np.random.PCG64(data_sequence))
        session_rng = np.random.Generator(np.random.PCG64(session_sequence))
        row_rng = np.random.Generator(np.random.PCG64(row_sequence))
        values = _ar1_session_values(
            data_rng,
            session_count,
            rows_per_session,
        )
        session_replicates = bootstrap_weighted_quantile_replicates(
            group_ids,
            baseline_weights,
            (values,),
            (eligibility,),
            (0.5,),
            BOOTSTRAP_DRAWS,
            mean_block_groups,
            session_rng,
        )[0]
        row_replicates = _iid_row_bootstrap_median_replicates(
            values,
            baseline_weights,
            BOOTSTRAP_DRAWS,
            row_rng,
        )
        session_lower, session_upper = percentile_interval(
            session_replicates,
            CONFIDENCE_LEVEL,
        )
        row_lower, row_upper = percentile_interval(
            row_replicates,
            CONFIDENCE_LEVEL,
        )
        session_width = session_upper - session_lower
        row_width = row_upper - row_lower
        if (
            not np.isfinite(session_width)
            or not np.isfinite(row_width)
            or session_width <= 0.0
            or row_width <= 0.0
        ):
            raise SpineError(
                f"AR(1) outer replication {outer_index} produced "
                f"invalid widths {session_width!r}, {row_width!r}"
            )
        ratio = session_width / row_width
        if not np.isfinite(ratio) or ratio <= 0.0:
            raise SpineError(
                f"AR(1) outer replication {outer_index} produced "
                f"invalid width ratio {ratio!r}"
            )
        session_widths[outer_index] = session_width
        row_widths[outer_index] = row_width
        ratios[outer_index] = ratio

    median_ratio = weighted_quantile(
        ratios,
        np.ones(outer_count, dtype=np.float64),
        0.5,
    )
    directional_count = int(np.count_nonzero(session_widths > row_widths))
    evidence = {
        "directional_count": directional_count,
        "minimum_directional_count": minimum_directional_count,
        "minimum_median_ratio": minimum_median_ratio,
        "ratios": ratios.tolist(),
        "row_widths": row_widths.tolist(),
        "session_widths": session_widths.tolist(),
        "weighted_lower_median_ratio": median_ratio,
    }
    print("PHASE5_AR1_RESULT=" + json.dumps(evidence, sort_keys=True))
    assert median_ratio >= minimum_median_ratio
    assert directional_count >= minimum_directional_count
