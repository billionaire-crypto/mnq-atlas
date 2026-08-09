"""D33 / contract section 6: excluded sessions must disappear from Phase 7.

The v2 production run at commit e8542c1 applied the four-session D33 exclusion
to Unit O but not to Phase 7. Phase 7 kept all 1,009 sessions and 787,020
assignment rows, merely relabelling the 3,120 excluded rows
``excluded_unresolved_official_interruption``. Contract section 6 line 250
requires those rows to "disappear entirely".

The defect survived because ``_validate_phase7_tree`` compares the artifact
against ``product.row_counts``, which are computed from that same product: the
producer validated its output against itself, so a population defect was
structurally invisible. Every expectation here is therefore bound to the frozen
contract document or to an independently constructed input -- never to a
produced table.

Scope note, stated rather than implied: this repository has no multi-session
Phase 7 integration fixture (``_build_phase7_product`` rejects a two-session
synthetic store for unrelated state-diagnostic reasons). Corpus-scale exclusion
arithmetic is therefore enforced by the production tripwire below, exercised
here against constructed populations, not by an end-to-end unit test.
"""

from __future__ import annotations

from copy import deepcopy
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from mnq_lab import SpineError
from mnq_lab.production import first_exploration_run as run_module
from mnq_lab.production.first_exploration_run import (
    EXPECTED_RETAINED_ANCHOR_SCALE_ROWS,
    EXPECTED_RETAINED_GRID_ROWS,
    FROZEN_RELABELLED_ASSIGNMENT_ROWS,
    FROZEN_RETAINED_ASSIGNMENT_ROWS,
    FROZEN_RETAINED_SESSIONS,
    FROZEN_RETAINED_UNIT_O_ROWS,
    EXPECTED_RETAINED_SEASONAL_PROFILE_ROWS,
    EXPECTED_RETAINED_STATE_VALIDITY_ROWS,
    EXPECTED_RETAINED_THRESHOLD_ROWS,
    EXPECTED_RETAINED_VOL_REL_ROWS,
    _build_phase7_product,
    _enforce_frozen_phase7_counts,
    _enforce_frozen_unit_o_population,
    _validate_phase7_population_surfaces,
)
from mnq_lab.spine.exploration import validate_exploration_store
from tests.test_first_exploration_run import _calendar
from tests.unit_o_fixtures import (
    in_memory_store,
    schedule_for_store,
    synthetic_outcome_columns,
)

SESSION = 20210615
EXCLUDED = (20200309, 20200312, 20200316, 20200318)
CONTRACT = (
    Path(__file__).resolve().parents[1] / "docs" / "SESSION_AVAILABILITY_V2_CONTRACT.md"
)


def _store(tmp_path):
    columns = synthetic_outcome_columns("2021-06-15")
    store = in_memory_store(tmp_path / "exploration" / "bars_5m", columns)
    return store, validate_exploration_store(store)


# ---------------------------------------------------------------------------
# The exclusion reaches the Phase 7 population, not just its labels
# ---------------------------------------------------------------------------


def test_a_session_contributes_the_contract_declared_780_assignment_rows(tmp_path):
    """Contract section 6: each excluded session carries 780 assignment rows."""
    store, bars = _store(tmp_path)
    product = _build_phase7_product(
        store, bars, _calendar(SESSION), schedule_for_store(store)
    )

    assert product.row_counts["assignments"] == 780


def test_excluding_a_session_removes_its_rows_rather_than_relabelling_them(tmp_path):
    """The correction, and the negative control for it in one test.

    With the session retained the population is non-empty. With it excluded the
    population is empty and the pipeline fails closed -- it does not emit 780
    rows carrying an exclusion label, which is precisely what the audited v2
    artifact did.
    """
    store, bars = _store(tmp_path)
    retained = _build_phase7_product(
        store, bars, _calendar(SESSION), schedule_for_store(store)
    )
    assert retained.row_counts["assignments"] == 780

    with pytest.raises(SpineError, match="nonempty"):
        _build_phase7_product(
            store,
            bars,
            _calendar(SESSION),
            schedule_for_store(store, excluded=(SESSION,)),
        )


def test_schedule_table_is_required_and_fails_closed(tmp_path):
    store, bars = _store(tmp_path)
    for bad in (None, object(), {}, "schedule"):
        with pytest.raises(SpineError, match="canonical schedule table"):
            _build_phase7_product(store, bars, _calendar(SESSION), bad)


# ---------------------------------------------------------------------------
# The production tripwire
# ---------------------------------------------------------------------------


def _counts(
    *,
    grid: int = EXPECTED_RETAINED_GRID_ROWS,
    anchor_scales: int = EXPECTED_RETAINED_ANCHOR_SCALE_ROWS,
    assignments: int = FROZEN_RETAINED_ASSIGNMENT_ROWS,
    seasonal: int = EXPECTED_RETAINED_SEASONAL_PROFILE_ROWS,
    vol_rel: int = EXPECTED_RETAINED_VOL_REL_ROWS,
    thresholds: int = EXPECTED_RETAINED_THRESHOLD_ROWS,
    state_validity: int = EXPECTED_RETAINED_STATE_VALIDITY_ROWS,
):
    return {
        "declared_grid": grid,
        "anchor_scales": anchor_scales,
        "seasonal_profiles": seasonal,
        "vol_rel": vol_rel,
        "thresholds": thresholds,
        "assignments": assignments,
        "state_validity": state_validity,
    }


def _schedule(excluded):
    return SimpleNamespace(excluded_session_ids=tuple(excluded))


def test_tripwire_accepts_the_frozen_contract_population():
    _enforce_frozen_phase7_counts(
        _counts(),
        session_count=FROZEN_RETAINED_SESSIONS,
        relabelled_assignment_rows=FROZEN_RELABELLED_ASSIGNMENT_ROWS,
    )


def test_tripwire_kills_the_unit_o_only_mutant(tmp_path):
    """The exact defect that shipped: Unit O filtered, Phase 7 not.

    The excluded sessions are present and merely labelled. The guard must name
    them rather than pass.
    """
    store, bars = _store(tmp_path)
    retained = _build_phase7_product(
        store, bars, _calendar(SESSION), schedule_for_store(store)
    )
    with pytest.raises(SpineError, match="excluded sessions survived"):
        _validate_phase7_population_surfaces(retained, _schedule((SESSION,)))


def _surface_mutant(product, surface: str, excluded_session: int):
    pipeline_fields = {
        name: dict(getattr(product.pipeline, name))
        for name in (
            "seasonal_profiles",
            "vol_rel_tables",
            "threshold_tables",
            "assignment_tables",
        )
    }
    anchor_columns = dict(product.anchor_scale_columns)
    grid_session_ids = product.grid_session_ids
    completion_session_ids = product.completion_session_ids
    state_validity = product.state_validity
    completion_diagnostic = deepcopy(product.completion_diagnostic)
    row_counts = dict(product.row_counts)
    extra = SimpleNamespace(session_id=excluded_session)
    if surface == "declared grid":
        grid_session_ids = frozenset((*grid_session_ids, excluded_session))
    elif surface == "completion frame":
        completion_session_ids = frozenset(
            (*completion_session_ids, excluded_session)
        )
    elif surface == "anchor scales":
        anchor_columns["session_id"] = list(anchor_columns["session_id"]) + [
            excluded_session
        ]
        row_counts["anchor_scales"] += 1
    elif surface == "state validity":
        state_validity = SimpleNamespace(rows=tuple(state_validity.rows) + (extra,))
        row_counts["state_validity"] += 1
    elif surface == "completion diagnostic":
        completion_diagnostic["rows"][0]["source_session_count"] += 1
    else:
        field = {
            "seasonal profiles": "seasonal_profiles",
            "vol-rel tables": "vol_rel_tables",
            "threshold tables": "threshold_tables",
            "assignment tables": "assignment_tables",
        }[surface]
        key = next(iter(pipeline_fields[field]))
        table = pipeline_fields[field][key]
        pipeline_fields[field][key] = SimpleNamespace(rows=tuple(table.rows) + (extra,))
        row_name = {
            "seasonal profiles": "seasonal_profiles",
            "threshold tables": "thresholds",
            "assignment tables": "assignments",
        }.get(surface)
        if row_name is not None:
            row_counts[row_name] += 1
    return SimpleNamespace(
        grid_rows=product.grid_rows,
        grid_session_ids=grid_session_ids,
        completion_session_ids=completion_session_ids,
        anchor_scale_columns=anchor_columns,
        pipeline=SimpleNamespace(**pipeline_fields),
        state_validity=state_validity,
        completion_diagnostic=completion_diagnostic,
        row_counts=row_counts,
    )


@pytest.mark.parametrize(
    "surface",
    [
        "declared grid",
        "completion frame",
        "anchor scales",
        "seasonal profiles",
        "vol-rel tables",
        "threshold tables",
        "assignment tables",
        "state validity",
    ],
)
def test_each_phase7_surface_rejects_an_excluded_session(tmp_path, surface):
    store, bars = _store(tmp_path)
    product = _build_phase7_product(
        store, bars, _calendar(SESSION), schedule_for_store(store)
    )
    mutant = _surface_mutant(product, surface, 20200309)
    with pytest.raises(SpineError, match=rf"excluded sessions survived.*{surface}"):
        _validate_phase7_population_surfaces(mutant, _schedule((20200309,)))


def test_completion_diagnostic_is_bound_to_retained_sessions(tmp_path):
    store, bars = _store(tmp_path)
    product = _build_phase7_product(
        store, bars, _calendar(SESSION), schedule_for_store(store)
    )
    mutant = _surface_mutant(product, "completion diagnostic", 20200309)
    with pytest.raises(SpineError, match="completion diagnostic describes"):
        _validate_phase7_population_surfaces(mutant, schedule_for_store(store))


def test_state_validity_threshold_series_is_bound_to_threshold_rows(tmp_path):
    store, bars = _store(tmp_path)
    product = _build_phase7_product(
        store, bars, _calendar(SESSION), schedule_for_store(store)
    )
    rows = list(product.state_validity.rows)
    position = next(
        index
        for index, row in enumerate(rows)
        if row.metric == "threshold_drift"
        and row.detail in {"lower_threshold_series", "upper_threshold_series"}
    )
    del rows[position]
    mutant = SimpleNamespace(
        grid_rows=product.grid_rows,
        grid_session_ids=product.grid_session_ids,
        completion_session_ids=product.completion_session_ids,
        anchor_scale_columns=product.anchor_scale_columns,
        pipeline=product.pipeline,
        state_validity=SimpleNamespace(rows=tuple(rows)),
        completion_diagnostic=product.completion_diagnostic,
        row_counts={**product.row_counts, "state_validity": len(rows)},
    )
    with pytest.raises(SpineError, match="threshold series differs"):
        _validate_phase7_population_surfaces(mutant, schedule_for_store(store))


@pytest.mark.parametrize(
    "counts,session_count,relabelled,expected",
    [
        (_counts(grid=78_702), FROZEN_RETAINED_SESSIONS, FROZEN_RELABELLED_ASSIGNMENT_ROWS, "declared grid rows"),
        (_counts(anchor_scales=393_510), FROZEN_RETAINED_SESSIONS, FROZEN_RELABELLED_ASSIGNMENT_ROWS, "anchor scale rows"),
        (_counts(assignments=787_020), FROZEN_RETAINED_SESSIONS, FROZEN_RELABELLED_ASSIGNMENT_ROWS, "assignment rows"),
        (_counts(seasonal=393_510), FROZEN_RETAINED_SESSIONS, FROZEN_RELABELLED_ASSIGNMENT_ROWS, "seasonal profile rows"),
        (_counts(vol_rel=393_510), FROZEN_RETAINED_SESSIONS, FROZEN_RELABELLED_ASSIGNMENT_ROWS, "vol-rel rows"),
        (_counts(thresholds=50_450), FROZEN_RETAINED_SESSIONS, FROZEN_RELABELLED_ASSIGNMENT_ROWS, "threshold rows"),
        (_counts(state_validity=107_505), FROZEN_RETAINED_SESSIONS, FROZEN_RELABELLED_ASSIGNMENT_ROWS, "state-validity rows"),
        (_counts(), 1_009, FROZEN_RELABELLED_ASSIGNMENT_ROWS, "distinct retained sessions"),
        (_counts(), FROZEN_RETAINED_SESSIONS, 30_420, "relabelled assignment rows"),
    ],
)
def test_tripwire_rejects_each_v1_shaped_count(
    counts, session_count, relabelled, expected
):
    """Every literal is load-bearing: the v1 value of each must halt the run."""
    with pytest.raises(SpineError, match=expected):
        _enforce_frozen_phase7_counts(
            counts,
            session_count=session_count,
            relabelled_assignment_rows=relabelled,
        )


def test_unit_o_tripwire_accepts_only_the_frozen_row_count():
    _enforce_frozen_unit_o_population(FROZEN_RETAINED_UNIT_O_ROWS)
    for wrong in (
        FROZEN_RETAINED_UNIT_O_ROWS - 1,
        FROZEN_RETAINED_UNIT_O_ROWS + 1,
        472_212,  # the v1 count
    ):
        with pytest.raises(SpineError, match="section 6 tripwire"):
            _enforce_frozen_unit_o_population(wrong)


# ---------------------------------------------------------------------------
# The expectations are the contract's, not the artifact's
# ---------------------------------------------------------------------------


def test_contract_literals_are_transcribed_from_the_contract_document():
    """Kills the 'derive contract expectations from the output' mutant.

    If a constant were ever recomputed from a produced artifact it would drift
    from the frozen contract and this fails. The contract file is the authority.
    """
    text = CONTRACT.read_text(encoding="utf-8")

    def declared(pattern: str) -> int:
        match = re.search(pattern, text)
        assert match, f"contract no longer declares {pattern!r}"
        return int(match.group(1).replace(",", ""))

    assert FROZEN_RETAINED_ASSIGNMENT_ROWS == declared(r"787,020 → ([\d,]+)")
    assert FROZEN_RETAINED_SESSIONS == declared(r"1,009 → ([\d,]+)")
    assert FROZEN_RETAINED_UNIT_O_ROWS == declared(r"472,212 → ([\d,]+)")
    assert FROZEN_RELABELLED_ASSIGNMENT_ROWS == declared(
        r"\*\*([\d,]+)\*\* retained assignment rows"
    )


def test_mechanical_population_literals_follow_the_registered_shapes():
    """The remaining literals are consequences, not contract quotations."""
    assert EXPECTED_RETAINED_GRID_ROWS == 78 * FROZEN_RETAINED_SESSIONS
    assert EXPECTED_RETAINED_ANCHOR_SCALE_ROWS == 5 * EXPECTED_RETAINED_GRID_ROWS
    assert EXPECTED_RETAINED_SEASONAL_PROFILE_ROWS == (
        5 * EXPECTED_RETAINED_GRID_ROWS
    )
    assert EXPECTED_RETAINED_VOL_REL_ROWS == 5 * EXPECTED_RETAINED_GRID_ROWS
    assert EXPECTED_RETAINED_THRESHOLD_ROWS == 10 * 5 * FROZEN_RETAINED_SESSIONS
    assert FROZEN_RETAINED_ASSIGNMENT_ROWS == 10 * EXPECTED_RETAINED_GRID_ROWS
    # Ten arms, five phases, five corpus years and the fixed diagnostic
    # inventories. Only the two threshold-series rows vary per session.
    fixed_rows = (
        10 * 5 * (4 + 3)
        + 10 * 5
        + 10 * 5 * (9 + 1)
        + 9 * 5 * (4 * 4 + 3)
        + 10 * 5 * 2
        + 10 * 5
        + 10 * 5 * 4 * 2
        + 10 * 5
        + 10 * 5 * 5 * 17
    )
    assert EXPECTED_RETAINED_STATE_VALIDITY_ROWS == (
        2 * EXPECTED_RETAINED_THRESHOLD_ROWS + fixed_rows
    )


def test_the_four_excluded_sessions_are_the_contract_registry():
    text = CONTRACT.read_text(encoding="utf-8")
    for session in EXCLUDED:
        assert f"`{session}`" in text, session


def test_frozen_constants_are_literals_not_computed():
    """No frozen expectation may be a function of anything at import time."""
    source = Path(run_module.__file__).read_text(encoding="utf-8")
    for name in (
        "FROZEN_RETAINED_SESSIONS",
        "FROZEN_RETAINED_ASSIGNMENT_ROWS",
        "FROZEN_RETAINED_UNIT_O_ROWS",
        "FROZEN_RELABELLED_ASSIGNMENT_ROWS",
        "EXPECTED_RETAINED_GRID_ROWS",
        "EXPECTED_RETAINED_ANCHOR_SCALE_ROWS",
        "EXPECTED_RETAINED_SEASONAL_PROFILE_ROWS",
        "EXPECTED_RETAINED_VOL_REL_ROWS",
        "EXPECTED_RETAINED_THRESHOLD_ROWS",
        "EXPECTED_RETAINED_STATE_VALIDITY_ROWS",
    ):
        match = re.search(rf"^{name} = (.+)$", source, re.MULTILINE)
        assert match, name
        assert re.fullmatch(r"[\d_]+", match.group(1).strip()), (
            f"{name} must be an integer literal, got {match.group(1)!r}"
        )


def test_grid_and_completion_frame_carry_the_same_exclusion_filter():
    """Regression: the first corrected run halted because only one was filtered.

    ``completion_frame`` is the declared anchor grid recomputed from the full
    bar series, so it must be filtered alongside ``grid``. Filtering one and not
    the other leaves the state diagnostics keyed to a population the assignment
    tables no longer contain, which halts inside build_state_validity_panel
    with a message naming neither the exclusion nor the frame.
    """
    source = Path(run_module.__file__).read_text(encoding="utf-8")
    body = source.split("def _build_phase7_product", 1)[1].split("\ndef ", 1)[0]
    anchors = source.split("def _anchor_products", 1)[1].split("\ndef ", 1)[0]

    assert "completion_frame = completion_frame[keep]" in body
    assert "grid = grid[keep]" in anchors
    # and the guard that makes a future divergence say so immediately
    assert "different populations" in body


def test_entry_point_resolves_the_schedule_table_exactly_once():
    """Contract requirement: one exclusion interpretation, not two loads."""
    source = Path(run_module.__file__).read_text(encoding="utf-8")
    body = source.split("def run_shakedown()", 1)[1]
    assert body.count("load_session_schedule_table()") == 1
    assert source.count("load_session_schedule_table()") == 1
