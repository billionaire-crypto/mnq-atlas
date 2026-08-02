"""Independent Phase 7 dependency-mask constructors frozen before estimators."""

from __future__ import annotations

import numpy as np


def ewma_semantic_mask(size: int, segment_start: int, anchor: int) -> np.ndarray:
    if not 0 <= segment_start <= anchor < size:
        raise ValueError("invalid EWMA mask bounds")
    mask = np.zeros(size, dtype=np.bool_)
    mask[segment_start : anchor + 1] = True
    return mask


def mad_semantic_mask(size: int, segment_start: int, anchor: int) -> np.ndarray:
    first = anchor - 78
    if not 0 <= segment_start <= first <= anchor < size:
        raise ValueError("MAD requires exactly 79 bars inside one segment")
    mask = np.zeros(size, dtype=np.bool_)
    mask[first : anchor + 1] = True
    return mask


def composite_row_mask(size: int, required_indices: tuple[int, ...]) -> np.ndarray:
    if not required_indices or len(set(required_indices)) != len(required_indices):
        raise ValueError("required indices must be nonempty and unique")
    if min(required_indices) < 0 or max(required_indices) >= size:
        raise ValueError("required index outside coordinate support")
    mask = np.zeros(size, dtype=np.bool_)
    mask[np.asarray(required_indices, dtype=np.intp)] = True
    return mask

