"""Permanent collision and completion-order witnesses for Stage 1 merging."""

from __future__ import annotations

import numpy as np
import pytest

from mnq_lab.phase8 import production
from mnq_lab.phase8.diagnostics import status_decision


class _ConstantDigest:
    def update(self, _payload):
        return None

    def hexdigest(self):
        return "c" * 64


def _constant_sha256(*_args, **_kwargs):
    return _ConstantDigest()


def _ok():
    return status_decision(
        degenerate_baseline=False,
        insufficient_anchors=False,
        insufficient_completion=False,
        insufficient_overlap=False,
    )


def _partition(index, value):
    rows = np.asarray([0, 1], dtype=np.int32)
    values = np.asarray([value, value + 1], dtype=np.int32)
    weights = np.asarray([0.5, 0.5], dtype=np.float64)
    local = production._TermRegistry()
    handle = local.register_payload(rows, values, weights, "q50")
    entry = production._ContrastEntry(
        index=index,
        row={"row_id": f"declared-{index}"},
        census=(),
        request=(f"declared-{index}", handle, None, _ok()),
    )
    payloads = {
        recipe.term_id: (
            recipe.eligible_rows,
            recipe.eligible_values,
            recipe.eligible_weights,
            recipe.statistic,
        )
        for recipe in local.recipes
    }
    return production._ContrastPartition((entry,), payloads)


def _snapshot(merged):
    return (
        tuple(row["row_id"] for row in merged.rows),
        tuple(
            (
                recipe.term_id,
                recipe.support_digest,
                recipe.eligible_rows.tobytes(),
                recipe.eligible_values.tobytes(),
                recipe.eligible_weights.tobytes(),
                recipe.statistic,
            )
            for recipe in merged.registry.recipes
        ),
        tuple(
            (request.request_id, request.target_term_id, request.baseline_term_id)
            for request in merged.requests
        ),
        merged.census,
    )


def test_central_merge_survives_partition_local_digest_collision(
    monkeypatch,
):
    monkeypatch.setattr(production.hashlib, "sha256", _constant_sha256)
    first = _partition(0, 10)
    second = _partition(1, 20)
    assert next(iter(first.payloads)) == next(iter(second.payloads))

    merged = production._merge_contrast_partitions((first, second))

    assert len(merged.registry.recipes) == 2
    assert tuple(recipe.term_id[2] for recipe in merged.registry.recipes) == (0, 1)
    assert tuple(request.target_term_id[2] for request in merged.requests) == (0, 1)
    assert merged.registry.recipes[0].eligible_values.tobytes() != (
        merged.registry.recipes[1].eligible_values.tobytes()
    )


def test_reversed_completion_and_shuffled_payload_maps_are_byte_identical(
    monkeypatch,
):
    monkeypatch.setattr(production.hashlib, "sha256", _constant_sha256)
    first = _partition(0, 10)
    second = _partition(1, 20)
    shuffled_first = production._ContrastPartition(
        first.entries, dict(reversed(tuple(first.payloads.items())))
    )

    declared = _snapshot(
        production._merge_contrast_partitions((first, second))
    )
    reversed_completion = _snapshot(
        production._merge_contrast_partitions((second, shuffled_first))
    )
    assert reversed_completion == declared


def test_old_worker_identifier_map_is_a_discriminating_negative_control(
    monkeypatch,
):
    monkeypatch.setattr(production.hashlib, "sha256", _constant_sha256)
    first = _partition(0, 10)
    second = _partition(1, 20)
    old_style = {
        handle: payload
        for part in (first, second)
        for handle, payload in part.payloads.items()
    }
    assert len(old_style) == 1
    assert len(
        production._merge_contrast_partitions((first, second)).registry.recipes
    ) == 2
