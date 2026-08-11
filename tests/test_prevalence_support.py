"""Frozen-spec Test 14: prevalence support and episode boundaries."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from mnq_lab import SpineError
from mnq_lab.conditioners.status import AssignmentStatus, ResetReason
from mnq_lab.constants import REPO_ROOT
from mnq_lab.phase9 import (
    ARM_CODE_BY_LABEL,
    ASSIGNMENT_STATUS_CODE_BY_LABEL,
    DECLARED_ARM_IDS,
    ELIGIBILITY_COLUMNS,
    EVENT_CODE_LABELS,
    EVENT_COLUMNS,
    ESTIMANDS,
    HORIZONS,
    PHASE9_ARTIFACT_SCHEMA_VERSION,
    RESET_REASON_CODE_BY_LABEL,
    SESSION_PHASE_CODE_BY_LABEL,
    PrevalenceInput,
    PrevalenceTable,
    anchor_observation_keys,
    load_phase9_artifacts,
    measure_prevalence,
    state_anchor_counts_by_horizon,
    validate_horizon_support,
    write_phase9_artifacts,
)

ARM = DECLARED_ARM_IDS[0]
UNSUPPORTED_ARM = DECLARED_ARM_IDS[1]
CATEGORIES = ((0, "low"), (1, "mid"), (2, "high"))


def _utc_ns(local_label: str) -> int:
    return int(
        pd.Timestamp(local_label, tz="America/Chicago").tz_convert("UTC").value
    )


def _source(rows, eligibility=None) -> PrevalenceInput:
    labels = np.asarray([_utc_ns(row["label"]) for row in rows], dtype=np.int64)
    tau, buckets, phases = anchor_observation_keys(labels)
    state = np.asarray([row.get("state", True) for row in rows], dtype=np.bool_)
    supplied = {} if eligibility is None else eligibility
    eligibility_columns = tuple(
        (
            name,
            np.asarray(supplied.get(name, state), dtype=np.bool_),
        )
        for name in ELIGIBILITY_COLUMNS
    )
    return PrevalenceInput(
        arm_id=np.full(len(rows), ARM, dtype="U64"),
        session_id=np.asarray([row.get("session", 20210607) for row in rows], dtype=np.int32),
        ts_event_ns=labels,
        tau_ns=tau,
        observation_bucket_ct=buckets,
        session_phase=phases,
        category_code=np.asarray([row.get("category", 0) for row in rows], dtype=np.int8),
        assignment_status=np.asarray(
            [row.get("status", AssignmentStatus.OK.value) for row in rows], dtype="U32"
        ),
        reset_reason=np.asarray(
            [row.get("reset", ResetReason.NONE.value) for row in rows], dtype="U16"
        ),
        state_anchor=state,
        eligibility_columns=eligibility_columns,
    )


def _summary_value(result, category_code: int, column: str):
    codes = result.summary.column("category_code")
    positions = np.flatnonzero(codes == category_code)
    assert positions.size == 1
    return result.summary.column(column)[int(positions[0])].item()


def _episode_lengths(result, category_code: int) -> tuple[int, ...]:
    table = result.episode_lengths
    mask = (table.column("category_code") == category_code) & (
        table.column("episode_ordinal") >= 0
    )
    return tuple(int(value) for value in table.column("episode_length")[mask])


def _assert_episode_count(actual: int, expected: int, boundary: str) -> None:
    assert actual == expected, f"{boundary} boundary episode count differs"


def _mutant_episode_count(source: PrevalenceInput, omitted_term: str) -> int:
    """A named mutation that removes exactly one reset concept from the witness."""

    active_code = None
    count = 0
    previous = None
    for position in range(source.ts_event_ns.size):
        defined = bool(
            source.state_anchor[position]
            and source.assignment_status[position] == AssignmentStatus.OK.value
        )
        if not defined:
            if omitted_term != "warmup":
                active_code = None
            previous = position
            continue

        code = int(source.category_code[position])
        edge = previous is not None
        if edge and omitted_term != "warmup":
            edge = bool(
                source.state_anchor[previous]
                and source.assignment_status[previous] == AssignmentStatus.OK.value
            )
        if edge and omitted_term != "session":
            edge = source.session_id[previous] == source.session_id[position]
        if edge:
            edge = source.tau_ns[position] == source.tau_ns[previous] + 300_000_000_000
        if edge and omitted_term != "gap":
            edge = source.reset_reason[position] != ResetReason.GAP_RESET.value
        if edge and omitted_term != "roll":
            edge = source.reset_reason[position] != ResetReason.ROLL_RESET.value
        if edge and omitted_term == "phase":
            edge = source.session_phase[previous] == source.session_phase[position]

        if active_code is None or not edge or active_code != code:
            count += 1
        active_code = code
        previous = position
    return count


def _support_fixture() -> PrevalenceInput:
    rows = [
        {"label": f"2021-06-07 08:{minute:02d}"}
        for minute in (30, 35, 40, 45, 50)
    ]
    fully = {
        15: [True, True, True, True, True],
        30: [True, True, True, True, False],
        60: [True, True, False, False, False],
    }
    observed = {
        15: [True, True, True, True, True],
        30: [True, True, True, True, True],
        60: [True, True, True, True, False],
    }
    eligibility = {}
    for horizon in HORIZONS:
        eligibility[f"outcome_eligible_{ESTIMANDS[0]}_h{horizon}"] = fully[horizon]
        eligibility[f"outcome_eligible_{ESTIMANDS[1]}_h{horizon}"] = observed[horizon]
    return _source(rows, eligibility)


def test_a_state_anchor_counts_are_horizon_invariant_by_construction():
    source = _support_fixture()
    counts = state_anchor_counts_by_horizon(
        source.state_anchor, source.category_code == 0
    )
    assert counts == ((15, 5), (30, 5), (60, 5))
    result = measure_prevalence(
        source, declared_arm_ids=(ARM,), declared_categories=CATEGORIES
    )
    assert _summary_value(result, 0, "state_anchors") == 5


def test_a_negative_horizon_dependent_prevalence_is_rejected():
    bad_state_counts = ((15, 5), (30, 4), (60, 2))
    eligible = tuple(
        (estimand, ((15, 5), (30, 4), (60, 2))) for estimand in ESTIMANDS
    )
    with pytest.raises(SpineError, match="depends on outcome horizon"):
        validate_horizon_support(bad_state_counts, eligible)


def test_b_outcome_eligible_counts_shrink_by_horizon_for_each_estimand():
    result = measure_prevalence(
        _support_fixture(), declared_arm_ids=(ARM,), declared_categories=CATEGORIES
    )
    counts = []
    for estimand in ESTIMANDS:
        values = tuple(
            int(_summary_value(result, 0, f"outcome_eligible_{estimand}_h{horizon}"))
            for horizon in HORIZONS
        )
        assert all(left >= right for left, right in zip(values, values[1:]))
        counts.append((estimand, tuple(zip(HORIZONS, values))))
    validate_horizon_support(
        ((15, 5), (30, 5), (60, 5)),
        tuple(counts),
        require_strict_decrease=True,
    )


def test_b_negative_increasing_outcome_eligibility_is_rejected():
    increasing = ((15, 2), (30, 3), (60, 3))
    eligible = (
        (ESTIMANDS[0], increasing),
        (ESTIMANDS[1], ((15, 3), (30, 3), (60, 2))),
    )
    with pytest.raises(SpineError, match="increases with horizon"):
        validate_horizon_support(((15, 3), (30, 3), (60, 3)), eligible)


def test_c_episode_resets_at_session_boundary():
    source = _source(
        [
            {"label": "2021-06-07 08:30", "session": 20210607},
            {"label": "2021-06-07 08:35", "session": 20210608},
        ]
    )
    result = measure_prevalence(
        source, declared_arm_ids=(ARM,), declared_categories=CATEGORIES
    )
    _assert_episode_count(
        int(_summary_value(result, 0, "episodes")), 2, "session"
    )
    assert _episode_lengths(result, 0) == (1, 1)


def test_c_negative_missing_session_term_joins_the_runs_and_is_rejected():
    source = _source(
        [
            {"label": "2021-06-07 08:30", "session": 20210607},
            {"label": "2021-06-07 08:35", "session": 20210608},
        ]
    )
    joined = _mutant_episode_count(source, "session")
    assert joined == 1
    with pytest.raises(AssertionError, match="session boundary"):
        _assert_episode_count(joined, 2, "session")


def test_d_episode_resets_at_missing_interval_gap():
    source = _source(
        [
            {"label": "2021-06-07 08:30"},
            {"label": "2021-06-07 08:35", "reset": ResetReason.GAP_RESET.value},
        ]
    )
    result = measure_prevalence(
        source, declared_arm_ids=(ARM,), declared_categories=CATEGORIES
    )
    _assert_episode_count(int(_summary_value(result, 0, "episodes")), 2, "gap")


def test_d_negative_missing_gap_term_joins_the_runs_and_is_rejected():
    source = _source(
        [
            {"label": "2021-06-07 08:30"},
            {"label": "2021-06-07 08:35", "reset": ResetReason.GAP_RESET.value},
        ]
    )
    joined = _mutant_episode_count(source, "gap")
    assert joined == 1
    with pytest.raises(AssertionError, match="gap boundary"):
        _assert_episode_count(joined, 2, "gap")


def test_e_episode_resets_at_contract_roll():
    source = _source(
        [
            {"label": "2021-06-07 08:30"},
            {"label": "2021-06-07 08:35", "reset": ResetReason.ROLL_RESET.value},
        ]
    )
    result = measure_prevalence(
        source, declared_arm_ids=(ARM,), declared_categories=CATEGORIES
    )
    _assert_episode_count(int(_summary_value(result, 0, "episodes")), 2, "roll")


def test_e_negative_missing_roll_term_joins_the_runs_and_is_rejected():
    source = _source(
        [
            {"label": "2021-06-07 08:30"},
            {"label": "2021-06-07 08:35", "reset": ResetReason.ROLL_RESET.value},
        ]
    )
    joined = _mutant_episode_count(source, "roll")
    assert joined == 1
    with pytest.raises(AssertionError, match="roll boundary"):
        _assert_episode_count(joined, 2, "roll")


def test_f_episode_resets_at_warmup():
    source = _source(
        [
            {"label": "2021-06-07 08:30"},
            {
                "label": "2021-06-07 08:35",
                "category": -1,
                "status": AssignmentStatus.WARMUP.value,
            },
            {"label": "2021-06-07 08:40"},
        ]
    )
    result = measure_prevalence(
        source, declared_arm_ids=(ARM,), declared_categories=CATEGORIES
    )
    _assert_episode_count(
        int(_summary_value(result, 0, "episodes")), 2, "warmup"
    )
    assert _episode_lengths(result, 0) == (1, 1)


def test_f_negative_carrying_state_through_warmup_joins_runs_and_is_rejected():
    source = _source(
        [
            {"label": "2021-06-07 08:30"},
            {
                "label": "2021-06-07 08:35",
                "category": -1,
                "status": AssignmentStatus.WARMUP.value,
            },
            {"label": "2021-06-07 08:40"},
        ]
    )
    joined = _mutant_episode_count(source, "warmup")
    assert joined == 1
    with pytest.raises(AssertionError, match="warmup boundary"):
        _assert_episode_count(joined, 2, "warmup")


def test_g_episode_does_not_reset_at_session_phase_change():
    source = _source(
        [
            {"label": "2021-06-07 08:50"},
            {"label": "2021-06-07 08:55"},
        ]
    )
    assert tuple(source.session_phase) == ("open", "morning")
    result = measure_prevalence(
        source, declared_arm_ids=(ARM,), declared_categories=CATEGORIES
    )
    _assert_episode_count(int(_summary_value(result, 0, "episodes")), 1, "phase")
    assert _episode_lengths(result, 0) == (2,)


def test_g_negative_phase_term_oversegments_the_run_and_is_rejected():
    source = _source(
        [
            {"label": "2021-06-07 08:50"},
            {"label": "2021-06-07 08:55"},
        ]
    )
    split = _mutant_episode_count(source, "phase")
    assert split == 2
    with pytest.raises(AssertionError, match="phase boundary"):
        _assert_episode_count(split, 1, "phase")


def test_observation_time_keying_uses_bar_close_not_bar_open():
    label = np.asarray([_utc_ns("2021-06-07 08:30")], dtype=np.int64)
    tau, bucket, phase = anchor_observation_keys(label)
    assert tau[0] == label[0] + 300_000_000_000
    assert bucket.tolist() == ["08:35"]
    assert phase.tolist() == ["open"]
    assert bucket.tolist() != ["08:30"]


def test_every_declared_cell_and_required_support_companion_is_emitted():
    result = measure_prevalence(
        _source([{"label": "2021-06-07 08:30"}]),
        declared_arm_ids=(ARM, UNSUPPORTED_ARM),
        declared_categories=CATEGORIES,
    )
    assert result.summary.row_count == 6
    assert result.episode_lengths.row_count == 6
    names = tuple(name for name, _ in result.summary.columns)
    anchor_position = names.index("n_anchors")
    assert names[anchor_position : anchor_position + 3] == (
        "n_anchors",
        "n_sessions",
        "weight_ess",
    )
    unsupported = result.summary.column("arm_id") == UNSUPPORTED_ARM
    assert set(result.summary.column("status")[unsupported]) == {
        "unsupported_no_arm_rows"
    }
    assert np.isnan(result.summary.column("weight_ess")).all()
    assert set(result.summary.column("weight_ess_status")) == {
        "not_computed_in_phase9"
    }


def test_phase9_npy_store_round_trips_as_read_only_memory_maps(tmp_path):
    result = measure_prevalence(
        _support_fixture(), declared_arm_ids=(ARM,), declared_categories=CATEGORIES
    )
    root = tmp_path / "phase9"
    manifest = write_phase9_artifacts(
        root,
        (result.summary, result.episode_lengths, result.events),
        provenance={"fixture": "test_prevalence_support"},
        persist_events=True,
    )
    assert manifest["schema_version"] == PHASE9_ARTIFACT_SCHEMA_VERSION
    assert manifest["table_order"] == ["summary", "episode_lengths", "events"]
    assert manifest["events_persisted"] is True
    assert manifest["event_code_mappings"] == {
        column: [
            {"code": code, "label": label}
            for code, label in enumerate(labels)
        ]
        for column, labels in EVENT_CODE_LABELS.items()
    }
    payload = (root / "manifest.json").read_bytes()
    assert payload == (
        json.dumps(json.loads(payload), sort_keys=True, indent=2, ensure_ascii=True)
        + "\n"
    ).encode("utf-8")
    loaded = load_phase9_artifacts(root)
    assert all(isinstance(values, np.memmap) for table in loaded for _, values in table.columns)
    assert all(not values.flags.writeable for table in loaded for _, values in table.columns)
    for expected, actual in zip(
        (result.summary, result.episode_lengths, result.events), loaded
    ):
        for (expected_name, expected_values), (actual_name, actual_values) in zip(
            expected.columns, actual.columns
        ):
            assert expected_name == actual_name
            if expected_values.dtype.kind == "f":
                np.testing.assert_array_equal(expected_values, actual_values, strict=True)
            else:
                np.testing.assert_array_equal(expected_values, actual_values, strict=True)


def test_event_codes_follow_declared_vocabularies_and_exact_narrow_dtypes():
    result = measure_prevalence(
        _support_fixture(), declared_arm_ids=(ARM,), declared_categories=CATEGORIES
    )
    events = result.events
    assert events is not None
    assert events.column("arm_code").dtype == np.dtype("int8")
    assert events.column("session_phase_code").dtype == np.dtype("int8")
    assert events.column("assignment_status_code").dtype == np.dtype("int8")
    assert events.column("reset_reason_code").dtype == np.dtype("int8")
    assert set(events.column("arm_code")) == {ARM_CODE_BY_LABEL[ARM]}
    for source_name, code_name, mapping in (
        ("session_phase", "session_phase_code", SESSION_PHASE_CODE_BY_LABEL),
        ("assignment_status", "assignment_status_code", ASSIGNMENT_STATUS_CODE_BY_LABEL),
        ("reset_reason", "reset_reason_code", RESET_REASON_CODE_BY_LABEL),
    ):
        source_values = getattr(_support_fixture(), source_name)
        expected = np.asarray([mapping[str(value)] for value in source_values], dtype=np.int8)
        np.testing.assert_array_equal(events.column(code_name), expected, strict=True)
    assert sum(values.nbytes for _, values in events.columns) / events.row_count < 100


def test_event_closed_schema_rejects_wide_or_wrong_code_dtype():
    result = measure_prevalence(
        _support_fixture(), declared_arm_ids=(ARM,), declared_categories=CATEGORIES
    )
    assert result.events is not None
    columns = list(result.events.columns)
    position = EVENT_COLUMNS.index("arm_code")
    columns[position] = ("arm_code", columns[position][1].astype(np.int64))
    with pytest.raises(SpineError, match="events column 'arm_code' dtype"):
        PrevalenceTable("events", tuple(columns))


def test_events_are_computed_and_persisted_by_separate_explicit_controls(tmp_path):
    source = _support_fixture()
    with_events = measure_prevalence(
        source, declared_arm_ids=(ARM,), declared_categories=CATEGORIES
    )
    without_events = measure_prevalence(
        source,
        declared_arm_ids=(ARM,),
        declared_categories=CATEGORIES,
        compute_events=False,
    )
    assert with_events.events is not None
    assert without_events.events is None
    for expected, actual in (
        (with_events.summary, without_events.summary),
        (with_events.episode_lengths, without_events.episode_lengths),
    ):
        for (_, expected_values), (_, actual_values) in zip(expected.columns, actual.columns):
            np.testing.assert_array_equal(expected_values, actual_values, strict=True)

    root = tmp_path / "compact"
    manifest = write_phase9_artifacts(
        root,
        (with_events.summary, with_events.episode_lengths, with_events.events),
        provenance={},
    )
    assert manifest["events_persisted"] is False
    assert manifest["table_order"] == ["summary", "episode_lengths"]
    assert not (root / "events").exists()
    assert len(load_phase9_artifacts(root)) == 2


def test_explicit_event_persistence_requires_event_table(tmp_path):
    result = measure_prevalence(
        _support_fixture(),
        declared_arm_ids=(ARM,),
        declared_categories=CATEGORIES,
        compute_events=False,
    )
    with pytest.raises(SpineError, match="declared order"):
        write_phase9_artifacts(
            tmp_path / "missing-events",
            (result.summary, result.episode_lengths),
            provenance={},
            persist_events=True,
        )


def test_phase9_writer_refuses_overwrite(tmp_path):
    result = measure_prevalence(
        _support_fixture(), declared_arm_ids=(ARM,), declared_categories=CATEGORIES
    )
    root = tmp_path / "phase9"
    write_phase9_artifacts(
        root, (result.summary, result.episode_lengths, result.events), provenance={}
    )
    with pytest.raises(SpineError, match="must be absent"):
        write_phase9_artifacts(
            root,
            (result.summary, result.episode_lengths, result.events),
            provenance={},
        )


@pytest.mark.parametrize(
    "forbidden_root",
    (
        REPO_ROOT / "data" / "__phase9_forbidden_test__",
        REPO_ROOT / "data" / "exploration" / "__phase9_forbidden_test__",
        REPO_ROOT / "data" / "locked_confirmation" / "__phase9_forbidden_test__",
    ),
)
def test_phase9_writer_refuses_every_repository_data_destination(forbidden_root):
    assert not forbidden_root.exists()
    result = measure_prevalence(
        _support_fixture(), declared_arm_ids=(ARM,), declared_categories=CATEGORIES
    )
    with pytest.raises(SpineError, match="may not write under data"):
        write_phase9_artifacts(
            forbidden_root,
            (result.summary, result.episode_lengths, result.events),
            provenance={},
        )
    assert not forbidden_root.exists()
