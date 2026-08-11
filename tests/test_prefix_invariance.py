"""Building through T+k must not change anything the build through T produced.

Spec §13 test 4: "build through T, rebuild through T+k; assert unchanged before T:
contract assignments, roll boundaries, 5-min bars, session IDs, seasonal profiles,
tercile thresholds, conditioner assignments, prevalence results, consumed-vintage
artifacts."

Phase 1 owns the first four. The remainder belong to later phases and are listed in
`test_deferred_prefix_invariance_targets` so they cannot be quietly forgotten.

Prefix invariance is **necessary but not sufficient** for causality — see
`tests/test_roll_causality.py`, which demonstrates a selector that is prefix invariant
and still leaks the future (spec §5.1 gate 4).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mnq_lab.spine.build import _collect_active_rows_sharded, _shard_to_frame
from mnq_lab.spine.calendar import trade_date_ids
from mnq_lab.spine.resample import resample_to_five_minutes
from mnq_lab.spine.rolls import build_causal_active_contract_map
from mnq_lab.spine.source import scan_source
from tests.conftest import SourceBuilder, session_grid
from mnq_lab.conditioners.scales.median import lower_median
from mnq_lab.core.weights import weighted_quantile
from mnq_lab.phase9 import (
    ARM_CODE_BY_LABEL,
    DECLARED_ARM_IDS,
    ELIGIBILITY_COLUMNS,
    PrevalenceInput,
    anchor_observation_keys,
    measure_prevalence,
)
from tests.phase7_pipeline_fixtures import synthetic_pipeline

NEAR = "MNQM1"
FAR = "MNQU1"
TIMES = ["17:00", "17:05", "23:00", "03:00", "08:30", "08:35", "12:00", "15:55"]

# Business days spanning a volume crossover, so at least one roll lies inside the prefix.
SESSIONS = [
    "2021-06-07", "2021-06-08", "2021-06-09", "2021-06-10", "2021-06-11",
    "2021-06-14", "2021-06-15", "2021-06-16", "2021-06-17", "2021-06-18",
]
PREFIX_LENGTH = 6
PREFIX = SESSIONS[:PREFIX_LENGTH]
BOUNDARY = PREFIX[-1]


def _write(path, trade_dates):
    """The near contract dominates until 2021-06-10, then the far one takes over."""
    builder = SourceBuilder()
    for trade_date in trade_dates:
        rolled = trade_date >= "2021-06-10"
        stamps = session_grid(trade_date, TIMES)
        builder.add_minutes(
            stamps, NEAR, volume=5 if rolled else 500, open_=12_000.0
        )
        builder.add_minutes(
            stamps, FAR, volume=900 if rolled else 3, open_=12_100.0
        )
    return builder.write(path)


def _pipeline(path, tmp_path, tag):
    scan = scan_source(path, chunksize=10_000, verbose=False)
    roll_map = build_causal_active_contract_map(
        scan.daily_volume, scan.first_year_by_symbol
    )
    symbols = sorted(scan.classification.retained)
    codes = {symbol: index for index, symbol in enumerate(symbols)}
    shards = _collect_active_rows_sharded(
        path, roll_map.active, codes, tmp_path / tag, 0.25, 10_000, verbose=False
    )
    frame = pd.concat(
        [_shard_to_frame(shard, symbols, 0.25) for shard in shards], ignore_index=True
    ).sort_values("timestamp", kind="stable").reset_index(drop=True)
    bars = resample_to_five_minutes(frame).bars
    bars["session_id"] = trade_date_ids(bars["timestamp"])
    return roll_map, bars


@pytest.fixture(scope="module")
def builds(tmp_path_factory):
    root = tmp_path_factory.mktemp("prefix")
    short = _write(root / "short.csv", PREFIX)
    long = _write(root / "long.csv", SESSIONS)
    return _pipeline(short, root, "short"), _pipeline(long, root, "long")


def test_contract_assignments_are_unchanged(builds):
    (short_map, _), (long_map, _) = builds
    for trade_date in PREFIX:
        assert short_map.active[trade_date] == long_map.active[trade_date], trade_date


def test_roll_boundaries_are_unchanged(builds):
    (short_map, _), (long_map, _) = builds
    short_rolls = [r for r in short_map.rolls if r.get("trigger_trade_date") in PREFIX]
    long_rolls = [r for r in long_map.rolls if r.get("trigger_trade_date") in PREFIX]
    assert short_rolls == long_rolls
    assert short_rolls, "the prefix contains no roll, so this assertion is vacuous"


def test_five_minute_bars_are_unchanged(builds):
    (_, short_bars), (_, long_bars) = builds
    cutoff = int(BOUNDARY.replace("-", ""))
    a = short_bars[short_bars["session_id"] <= cutoff].reset_index(drop=True)
    b = long_bars[long_bars["session_id"] <= cutoff].reset_index(drop=True)

    assert len(a) == len(b) > 0
    for column in (
        "timestamp", "open", "high", "low", "close", "volume", "symbol",
        "expected_1m_components", "observed_1m_components", "component_coverage_rate",
        "first_component_time", "last_component_time",
    ):
        np.testing.assert_array_equal(
            a[column].to_numpy(), b[column].to_numpy(), err_msg=column
        )


def test_session_ids_are_unchanged(builds):
    (_, short_bars), (_, long_bars) = builds
    cutoff = int(BOUNDARY.replace("-", ""))
    a = short_bars.loc[short_bars["session_id"] <= cutoff, "session_id"].to_numpy()
    b = long_bars.loc[long_bars["session_id"] <= cutoff, "session_id"].to_numpy()
    np.testing.assert_array_equal(a, b)


def test_negative_case_the_extension_is_not_empty(builds):
    """If the long build added nothing, every assertion above is vacuous."""
    (_, short_bars), (_, long_bars) = builds
    assert len(long_bars) > len(short_bars)
    (short_map, _), (long_map, _) = builds
    assert set(long_map.active) > set(short_map.active)


def test_negative_case_a_lookahead_normaliser_breaks_invariance(builds):
    """Demonstrate that this fixture *can* detect a prefix violation.

    A statistic normalised by the corpus total — a plausible-looking mistake — changes
    retroactively when new sessions arrive. The fixture must catch that.
    """
    (_, short_bars), (_, long_bars) = builds
    cutoff = int(BOUNDARY.replace("-", ""))

    def leaky(bars):
        window = bars[bars["session_id"] <= cutoff]
        return (window["volume"] / bars["volume"].sum()).to_numpy()

    assert not np.array_equal(leaky(short_bars), leaky(long_bars))


DEFERRED_TARGETS = [
    "consumed_vintage_artifacts",
]


@pytest.fixture(scope="module")
def phase7_builds():
    return synthetic_pipeline(123), synthetic_pipeline(125)


def test_seasonal_profiles_are_prefix_invariant(phase7_builds):
    short, long = phase7_builds
    short_sessions, short_scales, _, short_pipeline = short
    _, long_scales, _, long_pipeline = long
    cutoff = short_sessions[-1]
    for arm_id, short_table in short_pipeline.seasonal_profiles.items():
        long_rows = tuple(
            row
            for row in long_pipeline.seasonal_profiles[arm_id].rows
            if row.session_id <= cutoff
        )
        assert short_table.rows == long_rows
        assert all(
            dependency_session < row.session_id
            for row in short_table.rows
            for dependency_session, _ in row.dependency_keys
        )

    def leaky_corpus_profile(scale_table):
        values = np.asarray(
            [row.scale_value for row in scale_table.rows if row.scale_valid],
            dtype=np.float64,
        )
        return lower_median(values)

    primary = "primary_ewma78_permissive_expanding"
    assert leaky_corpus_profile(short_scales[primary]) != leaky_corpus_profile(
        long_scales[primary]
    )


def test_tercile_thresholds_are_prefix_invariant(phase7_builds):
    short, long = phase7_builds
    short_sessions, _, _, short_pipeline = short
    _, _, _, long_pipeline = long
    cutoff = short_sessions[-1]
    for arm_id, short_table in short_pipeline.threshold_tables.items():
        long_rows = tuple(
            row
            for row in long_pipeline.threshold_tables[arm_id].rows
            if row.session_id <= cutoff
        )
        assert short_table.rows == long_rows
        assert all(
            dependency_session < row.session_id
            for row in short_table.rows
            for dependency_session, _ in row.dependency_keys
        )

    def leaky_corpus_threshold(vol_table):
        values = np.asarray(
            [row.vol_rel for row in vol_table.rows if row.vol_rel_valid],
            dtype=np.float64,
        )
        weights = np.ones(values.size, dtype=np.float64)
        return (
            weighted_quantile(values, weights, 1.0 / 3.0),
            weighted_quantile(values, weights, 2.0 / 3.0),
        )

    primary = "primary_ewma78_permissive_expanding"
    assert leaky_corpus_threshold(
        short_pipeline.vol_rel_tables[primary]
    ) != leaky_corpus_threshold(long_pipeline.vol_rel_tables[primary])


def test_conditioner_assignments_are_prefix_invariant(phase7_builds):
    short, long = phase7_builds
    short_sessions, _, _, short_pipeline = short
    _, _, _, long_pipeline = long
    cutoff = short_sessions[-1]
    for arm_id, short_table in short_pipeline.assignment_tables.items():
        long_rows = tuple(
            row
            for row in long_pipeline.assignment_tables[arm_id].rows
            if row.session_id <= cutoff
        )
        assert short_table.rows == long_rows

    def backward_carry(table, prefix_length):
        assert table.rows[-1].category_code != -1
        carried = table.rows[-1].category_code
        return tuple(
            carried if row.category_code == -1 else row.category_code
            for row in table.rows[:prefix_length]
        )

    primary = "primary_ewma78_permissive_expanding"
    short_table = short_pipeline.assignment_tables[primary]
    long_table = long_pipeline.assignment_tables[primary]
    assert short_table.rows[-1].category_code != long_table.rows[-1].category_code
    assert backward_carry(short_table, len(short_table.rows)) != backward_carry(
        long_table, len(short_table.rows)
    )


def _phase9_input(size):
    local_labels = pd.date_range(
        "2021-06-07 08:30",
        periods=size,
        freq="5min",
        tz="America/Chicago",
    )
    labels = local_labels.tz_convert("UTC").to_numpy(dtype="datetime64[ns]").astype(
        np.int64
    )
    tau, buckets, phases = anchor_observation_keys(labels)
    state = np.ones(size, dtype=np.bool_)
    eligibility = []
    for name in ELIGIBILITY_COLUMNS:
        if name.endswith("h15"):
            values = state.copy()
        elif name.endswith("h30"):
            values = np.arange(size) < 5
        else:
            values = np.arange(size) < 2
        eligibility.append((name, np.asarray(values, dtype=np.bool_)))
    return PrevalenceInput(
        arm_id=np.full(size, DECLARED_ARM_IDS[0], dtype="U64"),
        session_id=np.full(size, 20210607, dtype=np.int32),
        ts_event_ns=labels,
        tau_ns=tau,
        observation_bucket_ct=buckets,
        session_phase=phases,
        category_code=np.asarray([0, 0, 1, 1, 0, 2, 2][:size], dtype=np.int8),
        assignment_status=np.full(size, "ok", dtype="U32"),
        reset_reason=np.full(size, "none", dtype="U16"),
        state_anchor=state,
        eligibility_columns=tuple(eligibility),
    )


@pytest.fixture(scope="module")
def phase9_builds():
    prefix_size = 4
    short = _phase9_input(prefix_size)
    long = _phase9_input(7)
    return prefix_size, short, long


def _prefix_event_columns(table, cutoff_tau_ns):
    mask = table.column("tau_ns") <= cutoff_tau_ns
    assert np.count_nonzero(mask) > 0
    return tuple((name, values[mask]) for name, values in table.columns)


def _assert_prefix_event_columns_equal(short_columns, long_columns):
    assert tuple(name for name, _ in short_columns) == tuple(
        name for name, _ in long_columns
    )
    for (name, short_values), (_, long_values) in zip(
        short_columns, long_columns
    ):
        np.testing.assert_array_equal(
            short_values, long_values, strict=True, err_msg=name
        )


def _with_corpus_normalized_state_contribution(columns, denominator):
    by_name = {name: values for name, values in columns}
    contribution = by_name["state_occurrence"].astype(np.float64) / denominator
    return (*columns, ("corpus_normalized_state_contribution", contribution))


def test_prevalence_results_are_prefix_invariant(phase9_builds):
    prefix_size, short, long = phase9_builds
    assert prefix_size > 0 and short.ts_event_ns.size == prefix_size
    assert long.ts_event_ns.size > prefix_size
    assert long.ts_event_ns[prefix_size:].size > 0
    np.testing.assert_array_equal(short.ts_event_ns, long.ts_event_ns[:prefix_size])

    short_result = measure_prevalence(
        short,
        declared_arm_ids=(DECLARED_ARM_IDS[0],),
    )
    extended_result = measure_prevalence(
        long,
        declared_arm_ids=(DECLARED_ARM_IDS[0],),
    )
    assert short_result.events.row_count == prefix_size
    assert extended_result.events.row_count == long.ts_event_ns.size
    assert extended_result.events.row_count > short_result.events.row_count
    assert not np.array_equal(
        short_result.summary.column("state_anchors"),
        extended_result.summary.column("state_anchors"),
    )

    cutoff = int(short.tau_ns[-1])
    short_columns = _prefix_event_columns(short_result.events, cutoff)
    extended_prefix_columns = _prefix_event_columns(extended_result.events, cutoff)
    assert short_columns[0][1].size == prefix_size
    assert extended_result.events.row_count - extended_prefix_columns[0][1].size > 0
    _assert_prefix_event_columns_equal(short_columns, extended_prefix_columns)


def test_negative_case_corpus_normalized_prevalence_breaks_prefix_invariance(
    phase9_builds,
):
    prefix_size, short, long = phase9_builds
    assert short.state_anchor.any()
    assert long.state_anchor[prefix_size:].any()
    short_result = measure_prevalence(
        short, declared_arm_ids=(DECLARED_ARM_IDS[0],)
    )
    extended_result = measure_prevalence(
        long, declared_arm_ids=(DECLARED_ARM_IDS[0],)
    )
    cutoff = int(short.tau_ns[-1])
    short_columns = _prefix_event_columns(short_result.events, cutoff)
    extended_prefix_columns = _prefix_event_columns(extended_result.events, cutoff)
    short_denominator = int(short_result.summary.column("n_anchors")[0])
    extended_denominator = int(extended_result.summary.column("n_anchors")[0])
    assert short_denominator == prefix_size
    assert extended_denominator == long.ts_event_ns.size
    leaky_short = _with_corpus_normalized_state_contribution(
        short_columns, short_denominator
    )
    leaky_extended_prefix = _with_corpus_normalized_state_contribution(
        extended_prefix_columns, extended_denominator
    )
    with pytest.raises(AssertionError):
        _assert_prefix_event_columns_equal(leaky_short, leaky_extended_prefix)


def test_declared_arm_codes_are_prefix_stable_and_observed_data_codes_are_not():
    primary = DECLARED_ARM_IDS[0]
    later_observed_arm = DECLARED_ARM_IDS[1]
    short_labels = np.asarray([primary, primary], dtype="U64")
    extended_labels = np.asarray(
        [primary, primary, later_observed_arm], dtype="U64"
    )
    declared_short = np.asarray(
        [ARM_CODE_BY_LABEL[str(value)] for value in short_labels], dtype=np.int8
    )
    declared_extended = np.asarray(
        [ARM_CODE_BY_LABEL[str(value)] for value in extended_labels], dtype=np.int8
    )
    _assert_prefix_event_columns_equal(
        (("arm_code", declared_short),),
        (("arm_code", declared_extended[: short_labels.size]),),
    )

    def observed_mapping(values):
        labels = tuple(sorted(set(values.tolist())))
        return {label: code for code, label in enumerate(labels)}

    short_map = observed_mapping(short_labels)
    extended_map = observed_mapping(extended_labels)
    assert short_map[primary] != extended_map[primary]
    data_derived_short = np.asarray(
        [short_map[str(value)] for value in short_labels], dtype=np.int8
    )
    data_derived_extended = np.asarray(
        [extended_map[str(value)] for value in extended_labels], dtype=np.int8
    )
    with pytest.raises(AssertionError):
        _assert_prefix_event_columns_equal(
            (("arm_code", data_derived_short),),
            (("arm_code", data_derived_extended[: short_labels.size]),),
        )


@pytest.mark.parametrize("target", DEFERRED_TARGETS)
def test_deferred_prefix_invariance_targets(target):
    """Registered as unimplemented so §13 test 4 is not silently under-covered.

    This target is produced in Phase 11. It remains a visible placeholder, not
    a passing check of the property.
    """
    pytest.xfail(f"{target} does not exist until a later phase (spec §15)")
