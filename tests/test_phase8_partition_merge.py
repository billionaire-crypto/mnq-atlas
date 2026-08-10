"""Permanent collision and completion-order witnesses for Stage 1 merging."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from mnq_lab.phase8 import production
from mnq_lab.phase8.diagnostics import status_decision
from mnq_lab.phase8.preflight import BootstrapTermKey, build_term_support_record


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


def test_worker_deduplicates_support_sessions_before_retaining_partition():
    sessions = np.asarray([
        20240305, 20240102, 20240305, 20241118,
        20240102, 20241231, 20240704,
    ], dtype=np.int32)
    weights = np.asarray([0.5, 0.5, 0.25, 0.5, 0.25, 0.0, -0.5])

    compact = production._stable_unique_support_sessions(sessions, weights)
    raw = tuple(sessions[weights > 0.0])

    assert compact == (20240305, 20240102, 20241118)
    assert len(compact) == 3
    assert len(raw) == 5
    assert 20240704 not in compact
    # Negative controls: unordered or sorted uniqueness changes evidence.
    assert tuple(set(raw)) != compact
    assert tuple(sorted(set(raw))) != compact


def test_worker_deduplication_is_identical_to_parent_support_normalization():
    sessions = np.asarray([9, 2, 9, 5, 2, 5], dtype=np.int32)
    weights = np.ones(sessions.size, dtype=np.float64)
    key = BootstrapTermKey("contrast", ("declared",), "target")

    raw_record = build_term_support_record(
        key=key, session_ids=tuple(sessions), status="ok",
    )
    compact_record = build_term_support_record(
        key=key,
        session_ids=production._stable_unique_support_sessions(sessions, weights),
        status="ok",
    )

    assert compact_record == raw_record
    assert compact_record.session_ids == (9, 2, 5)
    # Negative control: a non-stable unique order changes the final record.
    reordered_record = build_term_support_record(
        key=key, session_ids=tuple(sorted(set(sessions))), status="ok",
    )
    assert reordered_record != raw_record


def test_contrast_partition_retains_unique_support_sessions_at_call_site(tmp_path):
    spec = production.declared_result_rows()[0]
    unique_sessions = np.asarray(
        [20200101 + index for index in range(30)], dtype=np.int32,
    )
    sessions = np.repeat(unique_sessions, 2)
    timestamps = np.arange(sessions.size, dtype=np.int64)
    arm = production.ArmFrame(
        arm_id=spec.arm_id,
        sessions=sessions.copy(),
        timestamps=timestamps.copy(),
        phases=np.full(sessions.size, "open"),
        states=np.full(sessions.size, "low"),
        active=np.ones(sessions.size, dtype=np.bool_),
        session_class=np.full(sessions.size, "regular"),
        data_quality=np.full(sessions.size, "ok"),
        holiday_adjacent=np.zeros(sessions.size, dtype=np.bool_),
        category_code=np.zeros(sessions.size, dtype=np.int16),
    )
    inputs = production.ProductionInputs(
        root=tmp_path,
        unit={
            "estimand": np.full(sessions.size, spec.path_estimand),
            "session_id": sessions,
            "ts_event_ns": timestamps,
            "horizon_minutes": np.full(
                sessions.size, spec.horizon_minutes, dtype=np.int16,
            ),
            "window_fits_rth": np.ones(sessions.size, dtype=np.bool_),
            "common_support": np.ones(sessions.size, dtype=np.bool_),
            "outcome_valid": np.ones(sessions.size, dtype=np.bool_),
            spec.outcome_name: np.arange(sessions.size, dtype=np.int32),
        },
        arms={spec.arm_id: arm},
        run_manifest={},
        unit_manifest={},
        phase7_manifest={},
        input_manifest_sha256=(),
    )

    partition = production._contrast_partition(inputs, ((0, spec),), {})

    census = partition.entries[0].census[0]
    assert census.support_sessions == tuple(unique_sessions)
    assert len(census.support_sessions) == 30
    assert partition.entries[0].row["n_anchors"] == 60
    # Negative control: reverting the production call site retains 60 values.
    assert census.support_sessions != tuple(sessions)


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


def test_stage1_pool_recycles_each_one_partition_worker(monkeypatch, tmp_path):
    """A worker retaining a returned 15-GiB heap is a named OOM witness."""
    captured = {}

    class FakePool:
        def __init__(
            self, *, processes, initializer, initargs, maxtasksperchild
        ):
            captured.update(
                processes=processes,
                initializer=initializer,
                initargs=initargs,
                maxtasksperchild=maxtasksperchild,
            )
            self.closed = False
            self.joined = False
            self.terminated = False

        def imap_unordered(self, function, partitions, *, chunksize):
            captured["function"] = function
            captured["chunksize"] = chunksize
            return iter(
                (index, _partition(index, 10 + index))
                for index, _ in enumerate(partitions)
            )

        def close(self):
            self.closed = True

        def join(self):
            self.joined = True

        def terminate(self):
            self.terminated = True

    fake_context = SimpleNamespace(Pool=FakePool)
    monkeypatch.setattr(
        "multiprocessing.get_context", lambda _method: fake_context
    )
    inputs = SimpleNamespace(
        root=tmp_path,
        run_manifest={},
        unit_manifest={},
        phase7_manifest={},
        input_manifest_sha256=(),
    )
    partitions = ((0, (object(),)), (1, (object(),)))
    completed = []

    results = production._run_contrast_partitions(
        inputs, partitions, None, process_start_method="spawn",
        completed_specs=0,
        on_complete=lambda index, result: completed.append((index, result)),
    )

    assert len(results) == 2
    assert captured["processes"] == 2
    assert captured["chunksize"] == 1
    assert captured["maxtasksperchild"] == 1
    assert completed == results


def test_post_contrast_inventory_rebuilds_worker_local_slice_cache(monkeypatch):
    """An extracted contrast worker leaves the parent slice cache empty."""
    expected = tuple(np.asarray([index]) for index in range(5))
    calls = []

    def fake_slice(inputs, path_estimand, horizon_minutes):
        calls.append((inputs, path_estimand, horizon_minutes))
        return expected

    monkeypatch.setattr(production, "_slice", fake_slice)
    inputs = object()
    cache = {}
    key = ("fully_labeled_1m_grid", 15)

    assert production._cached_slice(cache, inputs, key) is expected
    assert production._cached_slice(cache, inputs, key) is expected
    assert calls == [(inputs, "fully_labeled_1m_grid", 15)]


def test_contrast_invariant_cache_hoists_every_complete_identity(monkeypatch):
    sessions_a = np.asarray([20200102, 20200103], dtype=np.int32)
    sessions_b = np.asarray([20210401, 20210402], dtype=np.int32)
    timestamps = np.asarray([1, 2], dtype=np.int64)

    def arm(
        arm_id, *, active, session_class, data_quality,
        sessions=sessions_a,
    ):
        return production.ArmFrame(
            arm_id=arm_id, sessions=sessions, timestamps=timestamps,
            phases=np.asarray(["open", "close"]),
            states=np.asarray(["low", "high"]),
            active=np.asarray(active, dtype=np.bool_),
            session_class=np.asarray(session_class),
            data_quality=np.asarray(data_quality),
            holiday_adjacent=np.zeros(2, dtype=np.bool_),
            category_code=np.zeros(2, dtype=np.int16),
        )

    arm_a = arm(
        "arm-a", active=(True, True),
        session_class=("regular", "regular"), data_quality=("ok", "bad"),
    )
    arm_b = arm(
        "arm-b", active=(False, True),
        session_class=("early", "regular"), data_quality=("ok", "ok"),
    )
    valid = np.asarray([True, False])
    common = np.asarray([False, True])
    slice_a = ("path", 15)
    slice_b = ("path", 60)
    counters = {
        "quarters": 0, "ordinary": 0, "completed": 0,
        "eligible": 0, "years": 0, "verify": 0,
    }
    real = {
        "quarters": production._year_quarter,
        "ordinary": production._ordinary_mask,
        "completed": production._completed_mask,
        "eligible": production._eligible_mask,
        "years": production._calendar_years,
        "verify": production._verify_slice_arm_keys,
    }

    def counted(name):
        def wrapper(*args, **kwargs):
            counters[name] += 1
            return real[name](*args, **kwargs)
        return wrapper

    monkeypatch.setattr(production, "_year_quarter", counted("quarters"))
    monkeypatch.setattr(production, "_ordinary_mask", counted("ordinary"))
    monkeypatch.setattr(production, "_completed_mask", counted("completed"))
    monkeypatch.setattr(production, "_eligible_mask", counted("eligible"))
    monkeypatch.setattr(production, "_calendar_years", counted("years"))
    monkeypatch.setattr(production, "_verify_slice_arm_keys", counted("verify"))

    cache = production._ContrastInvariantCache()
    cache.verify(slice_a, sessions_a, timestamps, arm_a)
    cache.verify(slice_a, sessions_a, timestamps, arm_a)
    cache.verify(slice_a, sessions_a, timestamps, arm_b)
    quarters_a = cache.quarters(slice_a, sessions_a)
    assert cache.quarters(slice_a, sessions_a) is quarters_a
    quarters_b = cache.quarters(slice_b, sessions_b)
    slice_a_copy = ("path-copy", 15)
    sessions_a_copy = sessions_a.copy()
    quarters_a_copy = cache.quarters(slice_a_copy, sessions_a_copy)
    ordinary_a = cache.ordinary(arm_a)
    assert cache.ordinary(arm_a) is ordinary_a
    ordinary_b = cache.ordinary(arm_b)
    completed_a = cache.completed(slice_a, "horizon_specific", valid, common)
    assert cache.completed(slice_a, "horizon_specific", valid, common) is completed_a
    completed_b = cache.completed(slice_a, "common_support", valid, common)
    eligible_a = cache.eligible(slice_a, "horizon_specific", arm_a, completed_a)
    assert cache.eligible(
        slice_a, "horizon_specific", arm_a, completed_a
    ) is eligible_a
    eligible_b = cache.eligible(slice_a, "horizon_specific", arm_b, completed_a)
    years_a = cache.calendar_years(slice_a, sessions_a)
    assert cache.calendar_years(slice_a, sessions_a) is years_a
    years_b = cache.calendar_years(slice_b, sessions_b)
    years_a_copy = cache.calendar_years(slice_a_copy, sessions_a_copy)

    assert counters == {
        "quarters": 2, "ordinary": 2, "completed": 2,
        "eligible": 2, "years": 2, "verify": 2,
    }
    assert quarters_a_copy is quarters_a
    assert years_a_copy is years_a
    expected = (
        real["quarters"](sessions_a), real["quarters"](sessions_b),
        real["ordinary"](arm_a), real["ordinary"](arm_b),
        real["completed"](valid, common, "horizon_specific"),
        real["completed"](valid, common, "common_support"),
        real["eligible"](completed_a, arm_a),
        real["eligible"](completed_a, arm_b),
        real["years"](sessions_a), real["years"](sessions_b),
    )
    observed = (
        quarters_a, quarters_b, ordinary_a, ordinary_b,
        completed_a, completed_b, eligible_a, eligible_b, years_a, years_b,
    )
    for memoized, recomputed in zip(observed, expected, strict=True):
        np.testing.assert_array_equal(memoized, recomputed)
        assert memoized.flags.writeable is False

    # Negative controls: deleting each final key component aliases arrays that
    # are deliberately different in this fixture.
    assert not np.array_equal(quarters_a, quarters_b)  # missing horizon
    assert not np.array_equal(ordinary_a, ordinary_b)  # missing arm_id
    assert not np.array_equal(completed_a, completed_b)  # missing support_kind
    assert not np.array_equal(eligible_a, eligible_b)  # missing arm_id
    assert not np.array_equal(years_a, years_b)  # missing horizon

    mismatched = arm(
        "arm-mismatch", active=(True, True),
        session_class=("regular", "regular"), data_quality=("ok", "ok"),
        sessions=np.asarray([20200102, 20200104], dtype=np.int32),
    )
    # A verification set keyed only by slice would silently skip this check.
    for _ in range(2):
        with pytest.raises(production.SpineError, match="assignment keys differ"):
            cache.verify(slice_a, sessions_a, timestamps, mismatched)
    assert counters["verify"] == 4


def test_contrast_invariant_cache_rejects_changed_sessions_for_bound_slice():
    cache = production._ContrastInvariantCache()
    slice_key = ("path", 15)
    sessions = np.asarray([20200102, 20200103], dtype=np.int32)
    cache.quarters(slice_key, sessions)

    with pytest.raises(production.SpineError, match="slice sessions changed"):
        cache.quarters(slice_key, sessions.copy())


def test_contrast_invariant_cache_deduplicates_equal_session_content(
    monkeypatch,
):
    calls = {"quarters": 0, "years": 0}
    real_quarters = production._year_quarter
    real_years = production._calendar_years

    def quarters(session_ids):
        calls["quarters"] += 1
        return real_quarters(session_ids)

    def years(session_ids):
        calls["years"] += 1
        return real_years(session_ids)

    monkeypatch.setattr(production, "_year_quarter", quarters)
    monkeypatch.setattr(production, "_calendar_years", years)
    cache = production._ContrastInvariantCache()
    canonical = np.asarray([20200102, 20200403], dtype=np.int32)
    sessions = [canonical.copy() for _ in range(6)]
    slice_keys = [(f"path-{index}", 15) for index in range(6)]

    quarter_results = [
        cache.quarters(key, value)
        for key, value in zip(slice_keys, sessions, strict=True)
    ]
    year_results = [
        cache.calendar_years(key, value)
        for key, value in zip(slice_keys, sessions, strict=True)
    ]

    assert calls == {"quarters": 1, "years": 1}
    assert all(value is quarter_results[0] for value in quarter_results)
    assert all(value is year_results[0] for value in year_results)
    assert quarter_results[0].flags.writeable is False
    assert year_results[0].flags.writeable is False

    different = np.asarray([20210102, 20210403], dtype=np.int32)
    different_quarters = cache.quarters(("different", 15), different)
    different_years = cache.calendar_years(("different", 15), different)
    assert calls == {"quarters": 2, "years": 2}
    assert not np.array_equal(quarter_results[0], different_quarters)
    assert not np.array_equal(year_results[0], different_years)
