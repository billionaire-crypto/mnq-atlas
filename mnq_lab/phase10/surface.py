"""Signed rook-connected coherence statistic for the frozen 5 by 3 lattice."""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Real
from typing import Any

import numpy as np

from mnq_lab import SpineError
from mnq_lab.phase8.contrasts import SESSION_PHASES, VOLATILITY_STATES
from mnq_lab.phase10.contract import load_phase10_contract


@dataclass(frozen=True)
class StandardizedSurfaces:
    scales: np.ndarray
    scale_valid: np.ndarray
    observed_z: np.ndarray
    observed_valid: np.ndarray
    null_z: np.ndarray
    null_valid: np.ndarray


@dataclass(frozen=True)
class SurfaceRegion:
    plane_index: int
    sign: str
    cells: tuple[tuple[int, int], ...]
    mean_z: float
    stability: float
    statistic: float


@dataclass(frozen=True)
class SurfaceStatistic:
    value: float
    regions: tuple[SurfaceRegion, ...]


def _numeric_array(values: Any, name: str) -> np.ndarray:
    array = np.asarray(values)
    if array.dtype.kind not in {"i", "u", "f"}:
        raise SpineError(f"{name} must be numeric")
    return array


def _bool_array(values: Any, name: str) -> np.ndarray:
    array = np.asarray(values)
    if array.dtype.kind != "b":
        raise SpineError(f"{name} must be boolean")
    return array


def shared_standardization(
    observed_raw: Any,
    observed_valid: Any,
    null_raw: Any,
    null_valid: Any,
) -> StandardizedSurfaces:
    """Apply one null-ensemble dispersion to observed and null contrasts."""
    observed = _numeric_array(observed_raw, "observed_raw")
    observed_ok = _bool_array(observed_valid, "observed_valid")
    null_values = _numeric_array(null_raw, "null_raw")
    null_ok = _bool_array(null_valid, "null_valid")
    lattice_shape = (len(SESSION_PHASES), len(VOLATILITY_STATES))
    if observed.ndim != 3 or observed.shape[1:] != lattice_shape:
        raise SpineError("observed contrast planes differ from the frozen lattice")
    if observed_ok.shape != observed.shape:
        raise SpineError("observed validity differs from observed contrasts")
    if null_values.ndim != 4 or null_values.shape[1:] != observed.shape:
        raise SpineError("null contrast planes differ from observed planes")
    if null_ok.shape != null_values.shape or null_values.shape[0] < 2:
        raise SpineError("null validity differs or has fewer than two replications")
    if not bool(np.isfinite(observed[observed_ok]).all()):
        raise SpineError("valid observed contrasts must be finite")
    if not bool(np.isfinite(null_values[null_ok]).all()):
        raise SpineError("valid null contrasts must be finite")

    scales = np.full(observed.shape, np.nan, dtype=np.float64)
    scale_ok = np.zeros(observed.shape, dtype=np.bool_)
    for plane in range(observed.shape[0]):
        for phase in range(lattice_shape[0]):
            for state in range(lattice_shape[1]):
                keep = null_ok[:, plane, phase, state]
                if int(np.count_nonzero(keep)) < 2:
                    continue
                scale = float(
                    np.std(
                        null_values[keep, plane, phase, state],
                        ddof=1,
                        dtype=np.float64,
                    )
                )
                if np.isfinite(scale) and scale > 0.0:
                    scales[plane, phase, state] = scale
                    scale_ok[plane, phase, state] = True

    observed_joint = observed_ok & scale_ok
    null_joint = null_ok & scale_ok[np.newaxis, :, :, :]
    observed_z = np.full(observed.shape, np.nan, dtype=np.float64)
    null_z = np.full(null_values.shape, np.nan, dtype=np.float64)
    observed_z[observed_joint] = observed[observed_joint] / scales[observed_joint]
    repeated_scales = np.broadcast_to(scales, null_values.shape)
    null_z[null_joint] = null_values[null_joint] / repeated_scales[null_joint]
    return StandardizedSurfaces(
        scales,
        scale_ok,
        observed_z,
        observed_joint,
        null_z,
        null_joint,
    )


def _neighbors(cell: tuple[int, int]) -> tuple[tuple[int, int], ...]:
    row, column = cell
    candidates = (
        (row - 1, column),
        (row + 1, column),
        (row, column - 1),
        (row, column + 1),
    )
    return tuple(
        (next_row, next_column)
        for next_row, next_column in candidates
        if 0 <= next_row < len(SESSION_PHASES)
        and 0 <= next_column < len(VOLATILITY_STATES)
    )


def _components(mask: np.ndarray) -> tuple[tuple[tuple[int, int], ...], ...]:
    remaining = {
        (row, column)
        for row in range(mask.shape[0])
        for column in range(mask.shape[1])
        if bool(mask[row, column])
    }
    output: list[tuple[tuple[int, int], ...]] = []
    for start_row in range(mask.shape[0]):
        for start_column in range(mask.shape[1]):
            start = (start_row, start_column)
            if start not in remaining:
                continue
            remaining.remove(start)
            queue = [start]
            group: list[tuple[int, int]] = []
            while queue:
                current = queue.pop(0)
                group.append(current)
                for neighbor in _neighbors(current):
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        queue.append(neighbor)
            output.append(tuple(group))
    return tuple(output)


def _region_stability(
    cells: tuple[tuple[int, int], ...],
    sign: str,
    plane_index: int,
    yearly_raw: np.ndarray,
    yearly_valid: np.ndarray,
) -> float:
    retained = 0
    for year_index in range(yearly_raw.shape[0]):
        if not all(
            bool(yearly_valid[year_index, plane_index, row, column])
            for row, column in cells
        ):
            continue
        mean = float(
            np.mean(
                [
                    yearly_raw[year_index, plane_index, row, column]
                    for row, column in cells
                ],
                dtype=np.float64,
            )
        )
        if (sign == "positive" and mean > 0.0) or (
            sign == "negative" and mean < 0.0
        ):
            retained += 1
    return retained / yearly_raw.shape[0]


def coherence_statistic(
    z_values: Any,
    z_valid: Any,
    yearly_raw: Any,
    yearly_valid: Any,
) -> SurfaceStatistic:
    """Compute one joint maximum over signed regions in both weighting planes."""
    z = _numeric_array(z_values, "z_values")
    valid = _bool_array(z_valid, "z_valid")
    years = _numeric_array(yearly_raw, "yearly_raw")
    year_ok = _bool_array(yearly_valid, "yearly_valid")
    lattice_shape = (len(SESSION_PHASES), len(VOLATILITY_STATES))
    if z.ndim != 3 or z.shape[1:] != lattice_shape or valid.shape != z.shape:
        raise SpineError("surface values differ from the frozen lattice")
    if years.ndim != 4 or years.shape[1:] != z.shape or years.shape[0] == 0:
        raise SpineError("yearly contrasts differ from the surface planes")
    if year_ok.shape != years.shape:
        raise SpineError("yearly validity differs from yearly contrasts")
    if not bool(np.isfinite(z[valid]).all()) or not bool(np.isfinite(years[year_ok]).all()):
        raise SpineError("valid surface inputs must be finite")
    contract = load_phase10_contract()
    regions: list[SurfaceRegion] = []
    joint_value = 0.0
    for plane in range(z.shape[0]):
        declarations = (
            ("positive", valid[plane] & (z[plane] > contract.positive_threshold)),
            ("negative", valid[plane] & (z[plane] < contract.negative_threshold)),
        )
        for sign, mask in declarations:
            for cells in _components(mask):
                mean_z = float(
                    np.mean([z[plane, row, column] for row, column in cells])
                )
                stability = _region_stability(
                    cells, sign, plane, years, year_ok
                )
                directed_mean = mean_z if sign == "positive" else -mean_z
                value = float(np.sqrt(len(cells)) * directed_mean * stability)
                regions.append(
                    SurfaceRegion(
                        plane,
                        sign,
                        cells,
                        mean_z,
                        stability,
                        value,
                    )
                )
                joint_value = max(joint_value, value)
    return SurfaceStatistic(joint_value, tuple(regions))
