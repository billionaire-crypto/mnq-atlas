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

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from mnq_lab import SpineError
from mnq_lab.production import first_exploration_run as run_module
from mnq_lab.production.first_exploration_run import (
    FROZEN_RELABELLED_ASSIGNMENT_ROWS,
    FROZEN_RETAINED_ASSIGNMENT_ROWS,
    FROZEN_RETAINED_SEASONAL_PROFILE_ROWS,
    FROZEN_RETAINED_SESSIONS,
    FROZEN_RETAINED_THRESHOLD_ROWS,
    FROZEN_RETAINED_UNIT_O_ROWS,
    _build_phase7_product,
    _enforce_frozen_phase7_population,
    _enforce_frozen_unit_o_population,
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


def _row(session_id: int, status: str = "ok"):
    return SimpleNamespace(session_id=session_id, data_quality_status=status)


def _population(
    *,
    sessions: int = FROZEN_RETAINED_SESSIONS,
    relabelled: int = FROZEN_RELABELLED_ASSIGNMENT_ROWS,
    assignments: int = FROZEN_RETAINED_ASSIGNMENT_ROWS,
    seasonal: int = FROZEN_RETAINED_SEASONAL_PROFILE_ROWS,
    thresholds: int = FROZEN_RETAINED_THRESHOLD_ROWS,
    extra_sessions: tuple[int, ...] = (),
):
    """A product shaped exactly as the enforcer reads it."""
    rows = [_row(30000000 + index) for index in range(sessions)]
    rows.extend(_row(session) for session in extra_sessions)
    rows.extend(_row(30000000, "scheduled_early_close") for _ in range(relabelled))
    return SimpleNamespace(
        pipeline=SimpleNamespace(assignment_tables={"primary": SimpleNamespace(rows=rows)}),
        row_counts={
            "assignments": assignments,
            "seasonal_profiles": seasonal,
            "thresholds": thresholds,
        },
    )


def _schedule(excluded):
    return SimpleNamespace(excluded_session_ids=tuple(excluded))


def test_tripwire_accepts_the_frozen_contract_population():
    _enforce_frozen_phase7_population(_population(), _schedule(EXCLUDED))


def test_tripwire_kills_the_unit_o_only_mutant():
    """The exact defect that shipped: Unit O filtered, Phase 7 not.

    The excluded sessions are present and merely labelled. The guard must name
    them rather than pass.
    """
    mutant = _population(extra_sessions=EXCLUDED)

    with pytest.raises(SpineError, match="excluded sessions survived"):
        _enforce_frozen_phase7_population(mutant, _schedule(EXCLUDED))


def test_tripwire_kills_a_relabelled_but_retained_excluded_session():
    rows = [_row(30000000 + i) for i in range(FROZEN_RETAINED_SESSIONS)]
    rows.extend(
        _row(session, "excluded_unresolved_official_interruption")
        for session in EXCLUDED
    )
    mutant = SimpleNamespace(
        pipeline=SimpleNamespace(assignment_tables={"a": SimpleNamespace(rows=rows)}),
        row_counts={
            "assignments": FROZEN_RETAINED_ASSIGNMENT_ROWS,
            "seasonal_profiles": FROZEN_RETAINED_SEASONAL_PROFILE_ROWS,
            "thresholds": FROZEN_RETAINED_THRESHOLD_ROWS,
        },
    )

    with pytest.raises(SpineError, match="disappear entirely"):
        _enforce_frozen_phase7_population(mutant, _schedule(EXCLUDED))


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"sessions": 1_009}, "distinct retained sessions"),
        ({"assignments": 787_020}, "assignment rows"),
        ({"seasonal": 393_510}, "seasonal profile rows"),
        ({"thresholds": 50_450}, "threshold rows"),
        ({"relabelled": 30_420}, "relabelled assignment rows"),
    ],
)
def test_tripwire_rejects_each_v1_shaped_count(kwargs, expected):
    """Every literal is load-bearing: the v1 value of each must halt the run."""
    with pytest.raises(SpineError, match=expected):
        _enforce_frozen_phase7_population(_population(**kwargs), _schedule(EXCLUDED))


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


def test_frozen_expectations_are_transcribed_from_the_contract_document():
    """Kills the 'derive expectations from the output' mutant structurally.

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
        "FROZEN_RETAINED_SEASONAL_PROFILE_ROWS",
        "FROZEN_RETAINED_THRESHOLD_ROWS",
        "FROZEN_RETAINED_UNIT_O_ROWS",
        "FROZEN_RELABELLED_ASSIGNMENT_ROWS",
    ):
        match = re.search(rf"^{name} = (.+)$", source, re.MULTILINE)
        assert match, name
        assert re.fullmatch(r"[\d_]+", match.group(1).strip()), (
            f"{name} must be an integer literal, got {match.group(1)!r}"
        )


def test_entry_point_resolves_the_schedule_table_exactly_once():
    """Contract requirement: one exclusion interpretation, not two loads."""
    source = Path(run_module.__file__).read_text(encoding="utf-8")
    body = source.split("def run_shakedown()", 1)[1]
    assert body.count("load_session_schedule_table()") == 1
    assert source.count("load_session_schedule_table()") == 1
