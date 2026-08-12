"""Synthetic-only witnesses for Slice 2 control and intervention plumbing.

No real corpus is loaded and no surface, p-value, rejection event, calibration
summary, or acceptance evidence is produced here.
"""

from __future__ import annotations

from dataclasses import replace
import inspect

import numpy as np
import pytest

from mnq_lab import SpineError
import mnq_lab.phase10.calibration_controls as controls_module
from mnq_lab.phase10.adapter import FormalCorpus, FormalJoinReconciliation
from mnq_lab.phase10.calibration_controls import (
    CALIBRATION_REPLICATIONS,
    PLANTED_EFFECT_LADDER,
    PLANTED_EFFECT_PHASES,
    CalibrationReplicationStreams,
    assert_planted_effect_invariants,
    calibration_replication_streams,
    freeze_intervention_inputs,
    generate_calibration_outer_control,
    plant_effect,
    plant_frozen_effect_ladder,
)
from mnq_lab.phase10.calibration_entropy import calibration_root_seed_sequence
from mnq_lab.phase10.mapping import (
    PermutedTrajectories,
    SessionMapping,
    apply_joint_mapping,
    spawn_session_mappings_from_seed_sequence,
)
from mnq_lab.phase8.contrasts import (
    VOLATILITY_STATES,
    CellKey,
    support_masks,
    tick_contrast,
)


def _readonly(values, dtype=None):
    result = np.array(values, dtype=dtype, copy=True)
    result.setflags(write=False)
    return result


def _fixture() -> tuple[FormalCorpus, PermutedTrajectories]:
    session_count = 40
    width = 5
    sessions = np.concatenate(
        (
            np.arange(20, dtype=np.int32) + 20200101,
            np.arange(20, dtype=np.int32) + 20210101,
        )
    )
    quarters = np.asarray(("2020Q1",) * 20 + ("2021Q1",) * 20)
    years = np.asarray((2020,) * 20 + (2021,) * 20, dtype=np.int32)
    phases = np.asarray(("open", "morning", "midday", "afternoon", "close"))
    row_axis = np.arange(session_count, dtype=np.int64)[:, np.newaxis]
    column_axis = np.arange(width, dtype=np.int64)[np.newaxis, :]
    state_codes = np.repeat((row_axis % 3).astype(np.int8), width, axis=1)
    state_codes[:, 0] = VOLATILITY_STATES.index("high")
    state_codes[:, 4] = VOLATILITY_STATES.index("low")
    state_valid = np.ones((session_count, width), dtype=np.bool_)
    state_valid[2, 1] = False
    state_valid[23, 2] = False
    outcome_valid = np.ones((session_count, width), dtype=np.bool_)
    outcome_valid[2, 3] = False
    outcome_valid[22, 1] = False
    window_fits = np.ones((session_count, width), dtype=np.bool_)
    window_fits[3, 2] = False
    outcomes = ((17 * row_axis + 11 * column_axis) % 401).astype(np.int32)
    reconciliation = FormalJoinReconciliation(
        verified_anchor_rows=session_count * width,
        verified_arm_rows=session_count * width,
        schedule_excluded_sessions=0,
        schedule_excluded_rows=0,
        active_sessions=session_count,
        regular_full_rth_sessions=session_count,
        holiday_adjacent_sessions_removed=0,
        truncated_sessions_removed=0,
        formal_sessions=session_count,
        formal_rows=session_count * width,
        anchors_per_session=width,
    )
    corpus = FormalCorpus(
        session_ids=_readonly(sessions, np.int32),
        calendar_quarters=_readonly(quarters),
        calendar_years=_readonly(years, np.int32),
        observation_grid=_readonly(("08:35", "09:05", "10:35", "12:35", "14:05")),
        phase_grid=_readonly(phases),
        ts_event_ns=_readonly(
            np.arange(session_count * width, dtype=np.int64).reshape(session_count, width)
        ),
        state_codes=_readonly(state_codes, np.int8),
        state_valid=_readonly(state_valid, np.bool_),
        downward_excursion_ticks=_readonly(outcomes, np.int32),
        outcome_valid=_readonly(outcome_valid, np.bool_),
        window_fits_rth=_readonly(window_fits, np.bool_),
        reconciliation=reconciliation,
        metadata={"effective_null_strata": "calendar_quarter_only"},
    )
    positions = np.concatenate(
        (
            np.roll(np.arange(20, dtype=np.intp), -1),
            np.roll(np.arange(20, 40, dtype=np.intp), -1),
        )
    )
    mapping = SessionMapping(
        recipient_session_ids=sessions.copy(),
        donor_session_ids=sessions[positions],
        donor_positions=positions,
        strata=quarters.copy(),
        usable=np.ones(session_count, dtype=np.bool_),
    )
    control = apply_joint_mapping(
        state_codes,
        state_valid,
        (outcome_valid, window_fits),
        mapping,
    )
    return corpus, control


def _seed_state(sequence: np.random.SeedSequence) -> tuple:
    state = sequence.state
    entropy = state["entropy"]
    if isinstance(entropy, int):
        entropy = (entropy,)
    return (
        tuple(entropy),
        tuple(state["spawn_key"]),
        state["pool_size"],
        state["n_children_spawned"],
    )


def _assert_stream_contract(producer) -> None:
    observed = (producer(7), producer(2), producer(7))
    for requested, streams in zip((7, 2, 7), observed, strict=True):
        expected_root = calibration_root_seed_sequence()
        expected_replication = expected_root.spawn(CALIBRATION_REPLICATIONS)[requested]
        expected_control, expected_ensemble = expected_replication.spawn(2)
        expected_rng = np.random.Generator(np.random.PCG64(expected_control))
        assert streams.replication_index == requested
        assert streams.control_spawn_key == (requested, 0)
        assert streams.ensemble_spawn_key == (requested, 1)
        assert isinstance(streams.control_rng.bit_generator, np.random.PCG64)
        assert streams.control_rng.bit_generator.state == expected_rng.bit_generator.state
        assert _seed_state(streams.ensemble_root) == _seed_state(expected_ensemble)
        assert streams.ensemble_root.n_children_spawned == 0
    assert observed[0].control_rng.bit_generator.state == observed[2].control_rng.bit_generator.state
    assert observed[0].ensemble_root is not observed[2].ensemble_root


def test_replication_streams_are_exact_fresh_index_coordinates():
    assert tuple(inspect.signature(calibration_replication_streams).parameters) == (
        "replication_index",
    )
    _assert_stream_contract(calibration_replication_streams)


@pytest.mark.parametrize(
    "mutant",
    (
        "deployment_root",
        "swapped_roles",
        "call_order",
        "philox",
        "wrong_index",
        "consumed_ensemble",
        "cached_ensemble",
    ),
)
def test_stream_mutants_fail_the_positive_contract(mutant):
    shared_root = calibration_root_seed_sequence()
    cached = None

    def producer(index):
        nonlocal cached
        if mutant == "cached_ensemble" and cached is not None:
            return cached
        if mutant == "deployment_root":
            root = np.random.SeedSequence((20260728,))
            replication = root.spawn(CALIBRATION_REPLICATIONS)[index]
        elif mutant == "call_order":
            replication = shared_root.spawn(1)[0]
        else:
            replication = calibration_root_seed_sequence().spawn(
                CALIBRATION_REPLICATIONS
            )[index]
        first, second = replication.spawn(2)
        control_child, ensemble_root = (
            (second, first) if mutant == "swapped_roles" else (first, second)
        )
        bit_generator = (
            np.random.Philox(control_child)
            if mutant == "philox"
            else np.random.PCG64(control_child)
        )
        if mutant == "consumed_ensemble":
            ensemble_root.spawn(1)
        result = CalibrationReplicationStreams(
            index + 1 if mutant == "wrong_index" else index,
            control_child.spawn_key,
            ensemble_root.spawn_key,
            np.random.Generator(bit_generator),
            ensemble_root,
        )
        if mutant == "cached_ensemble":
            cached = result
        return result

    with pytest.raises(AssertionError):
        _assert_stream_contract(producer)


class _TrackingReplication:
    def __init__(self, sequence, calls):
        self._sequence = sequence
        self._calls = calls

    def spawn(self, count):
        self._calls.append(count)
        return self._sequence.spawn(count)


class _TrackingRoot:
    def __init__(self):
        self._sequence = calibration_root_seed_sequence()
        self.calls = []
        self.replication_calls = []

    def spawn(self, count):
        self.calls.append(count)
        return [
            _TrackingReplication(child, self.replication_calls)
            for child in self._sequence.spawn(count)
        ]


def _assert_batch_spawn_calls(root_calls, replication_calls):
    assert root_calls == [CALIBRATION_REPLICATIONS]
    assert replication_calls == [2]


def test_replication_roots_are_spawned_in_one_frozen_batch(monkeypatch):
    tracker = _TrackingRoot()
    monkeypatch.setattr(
        controls_module,
        "calibration_root_seed_sequence",
        lambda: tracker,
    )
    calibration_replication_streams(7)
    _assert_batch_spawn_calls(tracker.calls, tracker.replication_calls)


def test_sequential_spawn_one_mutant_fails_the_positive_batch_assertion():
    with pytest.raises(AssertionError):
        _assert_batch_spawn_calls([1] * CALIBRATION_REPLICATIONS, [2])


def test_default_rng_call_is_unreachable(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("default_rng witness was reached")

    monkeypatch.setattr(np.random, "default_rng", forbidden)
    _assert_stream_contract(calibration_replication_streams)
    with pytest.raises(AssertionError, match="default_rng witness was reached"):
        np.random.default_rng(0)


def test_outer_control_uses_control_child_and_corpus_quarters_only():
    corpus, _ = _fixture()
    assert tuple(inspect.signature(generate_calibration_outer_control).parameters) == (
        "corpus",
        "replication_index",
    )
    observed = generate_calibration_outer_control(corpus, 5)
    expected_streams = calibration_replication_streams(5)
    expected = controls_module.generate_session_mapping(
        corpus.session_ids,
        corpus.calendar_quarters,
        expected_streams.control_rng,
    )
    for name in (
        "recipient_session_ids",
        "donor_session_ids",
        "donor_positions",
        "strata",
        "usable",
    ):
        np.testing.assert_array_equal(getattr(observed, name), getattr(expected, name))
    np.testing.assert_array_equal(observed.strata, corpus.calendar_quarters)


def test_internal_ensemble_root_is_fresh_and_naturally_rederived():
    corpus, _ = _fixture()
    first = calibration_replication_streams(5).ensemble_root
    second = calibration_replication_streams(5).ensemble_root
    short = spawn_session_mappings_from_seed_sequence(
        corpus.session_ids,
        corpus.calendar_quarters,
        2,
        root_sequence=first,
    )
    repeated = spawn_session_mappings_from_seed_sequence(
        corpus.session_ids,
        corpus.calendar_quarters,
        2,
        root_sequence=second,
    )
    for left, right in zip(short, repeated, strict=True):
        np.testing.assert_array_equal(left.donor_positions, right.donor_positions)
    with pytest.raises(SpineError, match="fresh and unconsumed"):
        spawn_session_mappings_from_seed_sequence(
            corpus.session_ids,
            corpus.calendar_quarters,
            1,
            root_sequence=first,
        )


def test_wrong_outer_strata_mutant_fails_the_positive_assertion():
    corpus, _ = _fixture()
    streams = calibration_replication_streams(5)
    mutant = controls_module.generate_session_mapping(
        corpus.session_ids,
        corpus.calendar_years,
        streams.control_rng,
    )
    with pytest.raises(AssertionError):
        np.testing.assert_array_equal(mutant.strata, corpus.calendar_quarters)


def _assert_effect_contract(corpus, control, result, magnitude):
    snapshot = freeze_intervention_inputs(corpus, control)
    assert_planted_effect_invariants(
        corpus,
        control,
        snapshot,
        magnitude,
        result,
    )


def _assert_frozen_public_api(
    stream_function,
    outer_function,
    effect_function,
    ladder_function,
    ladder,
    target_phases,
):
    assert tuple(inspect.signature(stream_function).parameters) == (
        "replication_index",
    )
    assert tuple(inspect.signature(outer_function).parameters) == (
        "corpus",
        "replication_index",
    )
    assert ladder == (10, 30, 60)
    assert all(type(value) is int for value in ladder)
    assert target_phases == ("morning", "midday", "afternoon")
    signature = inspect.signature(effect_function)
    assert tuple(signature.parameters) == ("corpus", "control", "magnitude_ticks")
    assert signature.parameters["magnitude_ticks"].default is inspect.Parameter.empty
    assert tuple(inspect.signature(ladder_function).parameters) == (
        "corpus",
        "control",
    )


def test_ladder_and_explicit_intervention_api_are_frozen():
    _assert_frozen_public_api(
        calibration_replication_streams,
        generate_calibration_outer_control,
        plant_effect,
        plant_frozen_effect_ladder,
        PLANTED_EFFECT_LADDER,
        PLANTED_EFFECT_PHASES,
    )


def test_public_api_and_constant_mutants_fail_the_positive_assertions():
    def stream_override(replication_index, root=None):
        return None

    def strata_override(corpus, replication_index, strata=None):
        return None

    def magnitude_default(corpus, control, magnitude_ticks=10):
        return None

    def ladder_override(corpus, control, ladder=None):
        return None

    mutants = (
        (stream_override, generate_calibration_outer_control, plant_effect, plant_frozen_effect_ladder, PLANTED_EFFECT_LADDER, PLANTED_EFFECT_PHASES),
        (calibration_replication_streams, strata_override, plant_effect, plant_frozen_effect_ladder, PLANTED_EFFECT_LADDER, PLANTED_EFFECT_PHASES),
        (calibration_replication_streams, generate_calibration_outer_control, magnitude_default, plant_frozen_effect_ladder, PLANTED_EFFECT_LADDER, PLANTED_EFFECT_PHASES),
        (calibration_replication_streams, generate_calibration_outer_control, plant_effect, ladder_override, PLANTED_EFFECT_LADDER, PLANTED_EFFECT_PHASES),
        (calibration_replication_streams, generate_calibration_outer_control, plant_effect, plant_frozen_effect_ladder, (10, 30, 61), PLANTED_EFFECT_PHASES),
        (calibration_replication_streams, generate_calibration_outer_control, plant_effect, plant_frozen_effect_ladder, (10, 30, 60.0), PLANTED_EFFECT_PHASES),
        (calibration_replication_streams, generate_calibration_outer_control, plant_effect, plant_frozen_effect_ladder, PLANTED_EFFECT_LADDER, ("open", *PLANTED_EFFECT_PHASES)),
    )
    for mutant in mutants:
        with pytest.raises(AssertionError):
            _assert_frozen_public_api(*mutant)


def test_effect_shifts_exactly_the_complete_valid_target_conjunction():
    corpus, control = _fixture()
    original = corpus.downward_excursion_ticks.copy()
    result = plant_effect(corpus, control, 10)
    _assert_effect_contract(corpus, control, result, 10)
    np.testing.assert_array_equal(corpus.downward_excursion_ticks, original)
    assert not result.outcomes.flags.writeable
    assert not result.modification_mask.flags.writeable


@pytest.mark.parametrize(
    "mutant",
    (
        "omit_outcome_valid",
        "omit_control_valid",
        "use_corpus_valid",
        "include_open",
        "outcome_subset",
    ),
)
def test_mask_mutants_fail_the_named_positive_checker(mutant):
    corpus, control = _fixture()
    snapshot = freeze_intervention_inputs(corpus, control)
    high_code = VOLATILITY_STATES.index("high")
    phases = np.isin(corpus.phase_grid, PLANTED_EFFECT_PHASES)[np.newaxis, :]
    if mutant == "omit_outcome_valid":
        mask = (control.state_codes == high_code) & phases & control.state_valid
    elif mutant == "omit_control_valid":
        mask = (control.state_codes == high_code) & phases & corpus.outcome_valid
    elif mutant == "use_corpus_valid":
        mask = (
            (control.state_codes == high_code)
            & phases
            & corpus.outcome_valid
            & corpus.state_valid
        )
    elif mutant == "include_open":
        expanded = np.isin(
            corpus.phase_grid,
            ("open", *PLANTED_EFFECT_PHASES),
        )[np.newaxis, :]
        mask = (
            (control.state_codes == high_code)
            & expanded
            & corpus.outcome_valid
            & control.state_valid
        )
    else:
        mask = snapshot.modification_mask.copy()
        selected_values = snapshot.outcomes[mask]
        cutoff = np.quantile(selected_values, 0.90)
        mask &= snapshot.outcomes >= cutoff
    mutant_snapshot = replace(snapshot, modification_mask=_readonly(mask, np.bool_))
    with pytest.raises(SpineError, match="exact conjunction"):
        assert_planted_effect_invariants(
            corpus,
            control,
            mutant_snapshot,
            10,
            None,
        )


def _assert_high_code_is_derived(corpus, control):
    snapshot = freeze_intervention_inputs(corpus, control)
    expected = (
        (control.state_codes == controls_module.VOLATILITY_STATES.index("high"))
        & np.isin(corpus.phase_grid, PLANTED_EFFECT_PHASES)[np.newaxis, :]
        & corpus.outcome_valid
        & control.state_valid
    )
    np.testing.assert_array_equal(snapshot.modification_mask, expected)


def test_high_code_is_derived_from_the_canonical_mapping(monkeypatch):
    corpus, control = _fixture()
    reordered = ("high", "low", "mid")
    monkeypatch.setattr(controls_module, "VOLATILITY_STATES", reordered)
    _assert_high_code_is_derived(corpus, control)


def test_literal_high_code_mutant_fails_the_positive_assertion(monkeypatch):
    corpus, control = _fixture()
    monkeypatch.setattr(controls_module, "VOLATILITY_STATES", ("high", "low", "mid"))
    literal_mask = (
        (control.state_codes == 2)
        & np.isin(corpus.phase_grid, PLANTED_EFFECT_PHASES)[np.newaxis, :]
        & corpus.outcome_valid
        & control.state_valid
    )
    with pytest.raises(AssertionError):
        expected = (
            (control.state_codes == controls_module.VOLATILITY_STATES.index("high"))
            & np.isin(corpus.phase_grid, PLANTED_EFFECT_PHASES)[np.newaxis, :]
            & corpus.outcome_valid
            & control.state_valid
        )
        np.testing.assert_array_equal(literal_mask, expected)


def _assert_widened_addition(add_function):
    original = np.asarray([[7, 11]], dtype=np.int32)
    before = original.copy()
    shifted = add_function(original, np.asarray([[True, False]]), 10)
    assert shifted.dtype == np.dtype(np.int64)
    np.testing.assert_array_equal(original, before)
    np.testing.assert_array_equal(shifted, np.asarray([[17, 11]], dtype=np.int64))


def test_effect_arithmetic_widens_before_addition_and_preserves_source():
    _assert_widened_addition(controls_module._shift_in_int64)


def test_direct_int32_addition_mutant_fails_the_positive_assertion():
    def direct_add(outcomes, mask, magnitude):
        result = outcomes.copy()
        result[mask] += magnitude
        return result

    with pytest.raises(AssertionError):
        _assert_widened_addition(direct_add)


def _assert_precast_bounds_guard(add_function):
    values = np.asarray([[np.iinfo(np.int32).max - 5]], dtype=np.int32)
    try:
        add_function(values, np.asarray([[True]]), 10)
    except SpineError as exc:
        assert "outside signed int32" in str(exc)
        return
    raise AssertionError("pre-cast signed int32 bounds guard did not fire")


def test_effect_bounds_are_checked_before_int32_cast():
    _assert_precast_bounds_guard(controls_module._shift_in_int64)


def test_missing_precast_bounds_mutant_fails_the_positive_assertion():
    def no_guard(outcomes, mask, magnitude):
        widened = outcomes.astype(np.int64, copy=True)
        widened[mask] += magnitude
        return widened

    with pytest.raises(AssertionError):
        _assert_precast_bounds_guard(no_guard)


def test_each_target_cell_requires_support_in_each_represented_year():
    corpus, control = _fixture()
    state_valid = control.state_valid.copy()
    rows = corpus.calendar_years == 2021
    columns = corpus.phase_grid == "morning"
    state_valid[np.ix_(rows, columns)] = False
    mutant_control = replace(control, state_valid=state_valid)
    snapshot = freeze_intervention_inputs(corpus, mutant_control)
    with pytest.raises(
        SpineError,
        match="phase=morning, volatility_state=high, calendar_year=2021",
    ):
        assert_planted_effect_invariants(
            corpus,
            mutant_control,
            snapshot,
            10,
            None,
        )


def test_selected_and_unselected_value_mutants_fail_the_named_checker():
    corpus, control = _fixture()
    result = plant_effect(corpus, control, 10)
    snapshot = freeze_intervention_inputs(corpus, control)
    selected = np.argwhere(result.modification_mask)[0]
    unselected = np.argwhere(~result.modification_mask)[0]
    wrong_selected = result.outcomes.copy()
    wrong_selected[tuple(selected)] -= 1
    wrong_selected.setflags(write=False)
    with pytest.raises(SpineError, match="declared magnitude"):
        assert_planted_effect_invariants(
            corpus,
            control,
            snapshot,
            10,
            replace(result, outcomes=wrong_selected),
        )
    wrong_unselected = result.outcomes.copy()
    wrong_unselected[tuple(unselected)] += 1
    wrong_unselected.setflags(write=False)
    with pytest.raises(SpineError, match="outside the modification mask"):
        assert_planted_effect_invariants(
            corpus,
            control,
            snapshot,
            10,
            replace(result, outcomes=wrong_unselected),
        )


def test_source_mask_identifier_and_axis_mutants_fail_the_named_checker():
    corpus, control = _fixture()
    snapshot = freeze_intervention_inputs(corpus, control)
    cases = (
        (replace(corpus, outcome_valid=_readonly(~corpus.outcome_valid)), control, "outcome validity"),
        (replace(corpus, window_fits_rth=_readonly(~corpus.window_fits_rth)), control, "structural fit"),
        (corpus, replace(control, state_valid=~control.state_valid), "state validity"),
        (corpus, replace(control, state_codes=np.roll(control.state_codes, 1, axis=0)), "state codes"),
        (replace(corpus, observation_grid=_readonly(np.roll(corpus.observation_grid, 1))), control, "observation grid"),
        (replace(corpus, phase_grid=_readonly(np.roll(corpus.phase_grid, 1))), control, "phases"),
        (replace(corpus, ts_event_ns=_readonly(corpus.ts_event_ns + 1)), control, "timestamps"),
        (replace(corpus, state_codes=_readonly(np.roll(corpus.state_codes, 1, axis=0))), control, "corpus state codes"),
        (replace(corpus, state_valid=_readonly(~corpus.state_valid)), control, "corpus state validity"),
        (replace(corpus, downward_excursion_ticks=_readonly(corpus.downward_excursion_ticks + 1, np.int32)), control, "control outcomes"),
        (replace(corpus, calendar_years=_readonly(corpus.calendar_years + 1)), control, "calendar years"),
        (replace(corpus, calendar_quarters=_readonly(np.roll(corpus.calendar_quarters, 1))), control, "calendar quarters"),
    )
    for mutant_corpus, mutant_control, message in cases:
        with pytest.raises(SpineError, match=message):
            assert_planted_effect_invariants(
                mutant_corpus,
                mutant_control,
                snapshot,
                10,
                None,
            )


def test_session_id_mutant_fails_closed_before_intervention():
    corpus, control = _fixture()
    mutated_ids = corpus.session_ids.copy()
    mutated_ids[0] += 1
    mutant = replace(corpus, session_ids=_readonly(mutated_ids))
    snapshot = freeze_intervention_inputs(corpus, control)
    with pytest.raises(SpineError, match="recipients differ"):
        assert_planted_effect_invariants(mutant, control, snapshot, 10, None)


def test_writable_corpus_and_direct_write_mutants_fail_closed():
    corpus, control = _fixture()
    writable = corpus.downward_excursion_ticks.copy()
    mutant = replace(corpus, downward_excursion_ticks=writable)
    with pytest.raises(SpineError, match="became writeable"):
        freeze_intervention_inputs(mutant, control)
    with pytest.raises(ValueError, match="read-only"):
        corpus.downward_excursion_ticks[0, 0] += 10


def test_intervention_input_guard_mutants_reach_the_real_guards(monkeypatch):
    corpus, control = _fixture()
    wrong_mapping_ids = control.mapping.recipient_session_ids.copy()
    wrong_mapping_ids[0] += 1
    wrong_mapping = replace(
        control.mapping,
        recipient_session_ids=wrong_mapping_ids,
    )
    invalid_codes = control.state_codes.copy()
    invalid_codes[0, 0] = len(VOLATILITY_STATES)
    cases = (
        (lambda: freeze_intervention_inputs(None, control), "FormalCorpus"),
        (lambda: freeze_intervention_inputs(corpus, None), "control-assigned"),
        (
            lambda: freeze_intervention_inputs(
                replace(corpus, outcome_valid=_readonly(corpus.outcome_valid[:, :-1])),
                control,
            ),
            "outcome arrays",
        ),
        (
            lambda: freeze_intervention_inputs(
                replace(corpus, window_fits_rth=_readonly(corpus.window_fits_rth[:, :-1])),
                control,
            ),
            "structural-fit",
        ),
        (
            lambda: freeze_intervention_inputs(
                corpus,
                replace(control, state_codes=control.state_codes[:, :-1]),
            ),
            "state arrays",
        ),
        (
            lambda: freeze_intervention_inputs(
                corpus,
                replace(control, state_valid=control.state_valid.astype(np.int8)),
            ),
            "must be boolean",
        ),
        (
            lambda: freeze_intervention_inputs(
                replace(corpus, phase_grid=_readonly(corpus.phase_grid[:-1])),
                control,
            ),
            "phase grid",
        ),
        (
            lambda: freeze_intervention_inputs(
                replace(corpus, session_ids=_readonly(corpus.session_ids[:-1])),
                control,
            ),
            "session ids",
        ),
        (
            lambda: freeze_intervention_inputs(
                replace(corpus, calendar_years=_readonly(corpus.calendar_years[:-1])),
                control,
            ),
            "calendar years",
        ),
        (
            lambda: freeze_intervention_inputs(
                replace(corpus, calendar_quarters=_readonly(corpus.calendar_quarters[:-1])),
                control,
            ),
            "calendar quarters",
        ),
        (
            lambda: freeze_intervention_inputs(
                corpus,
                replace(control, mapping=wrong_mapping),
            ),
            "recipients differ",
        ),
        (
            lambda: freeze_intervention_inputs(
                replace(
                    corpus,
                    downward_excursion_ticks=_readonly(
                        corpus.downward_excursion_ticks,
                        np.int64,
                    ),
                ),
                control,
            ),
            "signed int32",
        ),
        (
            lambda: freeze_intervention_inputs(
                replace(
                    corpus,
                    outcome_valid=_readonly(corpus.outcome_valid, np.int8),
                ),
                control,
            ),
            "must be boolean",
        ),
        (
            lambda: freeze_intervention_inputs(
                corpus,
                replace(control, state_codes=invalid_codes),
            ),
            "outside the canonical encoding",
        ),
    )
    for invoke, message in cases:
        with pytest.raises((SpineError, TypeError), match=message):
            invoke()
    monkeypatch.setattr(
        controls_module,
        "PLANTED_EFFECT_PHASES",
        ("morning", "undeclared"),
    )
    with pytest.raises(SpineError, match="outside the canonical phase axis"):
        freeze_intervention_inputs(corpus, control)


def test_magnitude_and_result_guard_mutants_reach_the_named_checker():
    corpus, control = _fixture()
    snapshot = freeze_intervention_inputs(corpus, control)
    result = plant_effect(corpus, control, 10)
    for invalid in (True, 10.0, 0, -1):
        with pytest.raises(SpineError, match="positive built-in integer"):
            assert_planted_effect_invariants(
                corpus,
                control,
                snapshot,
                invalid,
                None,
            )
    wrong_mask = result.modification_mask.copy()
    wrong_mask[0, 0] = ~wrong_mask[0, 0]
    wrong_mask.setflags(write=False)
    int64_outcomes = result.outcomes.astype(np.int64)
    int64_outcomes.setflags(write=False)
    short_outcomes = result.outcomes[:, :-1].copy()
    short_outcomes.setflags(write=False)
    writable_outcomes = result.outcomes.copy()
    writable_mask = result.modification_mask.copy()
    cases = (
        (object(), "undeclared type"),
        (replace(result, magnitude_ticks=11), "metadata differs"),
        (replace(result, modification_mask=wrong_mask), "result mask differs"),
        (replace(result, outcomes=int64_outcomes), "signed int32 storage"),
        (replace(result, outcomes=short_outcomes), "frozen outcome shape"),
        (replace(result, outcomes=writable_outcomes), "must be read-only"),
        (replace(result, modification_mask=writable_mask), "must be read-only"),
    )
    for mutant, message in cases:
        with pytest.raises(SpineError, match=message):
            assert_planted_effect_invariants(
                corpus,
                control,
                snapshot,
                10,
                mutant,
            )


def test_frozen_ladder_members_are_independent_not_accumulated():
    corpus, control = _fixture()
    results = plant_frozen_effect_ladder(corpus, control)
    assert tuple(result.magnitude_ticks for result in results) == PLANTED_EFFECT_LADDER
    for magnitude, result in zip(PLANTED_EFFECT_LADDER, results, strict=True):
        _assert_effect_contract(corpus, control, result, magnitude)
    accumulated = results[2].outcomes.copy()
    accumulated[results[2].modification_mask] += PLANTED_EFFECT_LADDER[1]
    accumulated.setflags(write=False)
    mutant = replace(results[2], outcomes=accumulated)
    with pytest.raises(SpineError, match="declared magnitude"):
        _assert_effect_contract(corpus, control, mutant, PLANTED_EFFECT_LADDER[2])


def _assert_uniform_synthetic_contrast_shift(corpus, control, result, magnitude):
    phases = np.tile(corpus.phase_grid, corpus.session_ids.size)
    names = np.full(control.state_codes.shape, "low", dtype="<U4")
    for code, name in enumerate(VOLATILITY_STATES):
        names[control.state_valid & (control.state_codes == code)] = name
    states = names.reshape(-1)
    eligible = (corpus.outcome_valid & control.state_valid).reshape(-1)
    before = corpus.downward_excursion_ticks.reshape(-1)
    after = result.outcomes.reshape(-1)
    for phase in PLANTED_EFFECT_PHASES:
        masks = support_masks(
            phases,
            states,
            CellKey(phase, "high"),
            "vol_effect_given_phase",
        )
        target = masks.target & eligible
        baseline = masks.baseline & eligible
        before_contrast = tick_contrast(
            before[target],
            np.ones(np.count_nonzero(target)),
            before[baseline],
            np.ones(np.count_nonzero(baseline)),
            "q90",
        )
        after_contrast = tick_contrast(
            after[target],
            np.ones(np.count_nonzero(target)),
            after[baseline],
            np.ones(np.count_nonzero(baseline)),
            "q90",
        )
        assert (
            after_contrast.contrast_ticks - before_contrast.contrast_ticks
            == magnitude
        )


def test_uniform_synthetic_shift_moves_raw_target_contrast_exactly():
    corpus, control = _fixture()
    magnitude = 10
    result = plant_effect(corpus, control, magnitude)
    _assert_uniform_synthetic_contrast_shift(corpus, control, result, magnitude)


def test_wrong_uniform_shift_fails_the_positive_contrast_assertion():
    corpus, control = _fixture()
    result = plant_effect(corpus, control, 9)
    with pytest.raises(AssertionError):
        _assert_uniform_synthetic_contrast_shift(corpus, control, result, 10)
