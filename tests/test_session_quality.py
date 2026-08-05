"""Stage 4 witnesses for the repaired Phase 7 session-quality vocabulary.

Every expected label is literal. The mutants at the end prove the witnesses
discriminate: each flips a single precedence or predicate in the classifier and
must be caught.
"""

from __future__ import annotations

import pytest

from mnq_lab import SpineError
from mnq_lab.spine.accepted_calendar import (
    CALENDAR_SHA256,
    CALENDAR_VERSION,
    SCHEMA_VERSION,
    CalendarRow,
    load_accepted_calendar,
)
from mnq_lab.spine.availability import (
    EXCLUSION_REGISTRY_SHA256,
    SessionExclusion,
    build_session_schedule_table,
    load_session_exclusions,
    load_session_schedule_table,
)
from mnq_lab.spine.session_quality import (
    SESSION_QUALITY_STATUSES,
    STATUS_EXCLUDED,
    STATUS_MID_SESSION_GAP,
    STATUS_NO_SCHEDULED_RTH,
    STATUS_OK,
    STATUS_REGISTERED_INTERRUPTION,
    STATUS_SCHEDULED_EARLY_CLOSE,
    STATUS_UNRESOLVED_EARLY_TERMINATION,
    classify_session_quality,
)

MARCH = (20200309, 20200312, 20200316, 20200318)
UNRESOLVED = (20200228, 20200630)
NO_RTH_SESSION = 20210402


def _row(trade_date, *, session_class="regular", status="full_rth",
         open_ct="08:30", close_ct="15:00"):
    if status in {"no_scheduled_rth", "full_exchange_holiday"}:
        open_ct = close_ct = ""
    return CalendarRow(
        trade_date=trade_date, market="CME_GLOBEX_EQUITY_INDEX_FUTURES",
        session_class=session_class, scheduled_rth_status=status,
        scheduled_rth_open_ct=open_ct, scheduled_rth_close_ct=close_ct,
        raw_exchange_open_ct="17:00", raw_exchange_close_ct="16:00",
        holiday_adjacent=False, source_event_id="TEST", source_label="TEST",
        source_as_of="2026-08-05", calendar_version=CALENDAR_VERSION,
        schema_version=SCHEMA_VERSION,
    )


def _classify(row, table, *, no_rth=False, early=False, gap=False):
    return classify_session_quality(
        session_id=row.trade_date, calendar_row=row,
        observed_no_rth_bars=no_rth, observed_rth_ended_early=early,
        observed_mid_rth_gap=gap, schedule_table=table,
    )


REAL = load_session_schedule_table()
CAL = load_accepted_calendar()


# --------------------------------------------------------------- vocabulary


def test_vocabulary_is_closed_and_ordered_by_precedence():
    assert SESSION_QUALITY_STATUSES == (
        STATUS_EXCLUDED,
        STATUS_NO_SCHEDULED_RTH,
        STATUS_REGISTERED_INTERRUPTION,
        STATUS_MID_SESSION_GAP,
        STATUS_SCHEDULED_EARLY_CLOSE,
        STATUS_UNRESOLVED_EARLY_TERMINATION,
        STATUS_OK,
    )
    assert len(set(SESSION_QUALITY_STATUSES)) == len(SESSION_QUALITY_STATUSES)
    # the collapsing v1 label is gone
    assert "unresolved_truncated_session" not in SESSION_QUALITY_STATUSES


# ------------------------------------------------------- required witnesses


def test_the_four_march_sessions_are_excluded_not_truncated():
    """D33. They carry a mid-session gap, NOT an early termination."""
    for session in MARCH:
        row = CAL.lookup(session)
        assert row.session_class == "regular"          # calendar v1 untouched
        assert row.scheduled_rth_status == "full_rth"
        assert _classify(row, REAL, gap=True) == STATUS_EXCLUDED


def test_february_and_june_remain_unresolved_early_terminations():
    """They are NOT excluded and NOT reclassified as structural."""
    for session in UNRESOLVED:
        row = CAL.lookup(session)
        assert REAL.is_excluded(session) is False
        assert _classify(row, REAL, early=True) == STATUS_UNRESOLVED_EARLY_TERMINATION


def test_scheduled_early_close_is_structural_not_an_anomaly():
    """Its early end is explained by the schedule, so it is not 'unresolved'."""
    row = _row(20191129, session_class="scheduled_early_close",
               status="shortened_rth", close_ct="12:00")
    table = build_session_schedule_table([_sched(row)])
    assert _classify(row, table, early=True) == STATUS_SCHEDULED_EARLY_CLOSE


def test_no_scheduled_rth_session():
    row = CAL.lookup(NO_RTH_SESSION)
    assert row.scheduled_rth_status == "no_scheduled_rth"
    assert _classify(row, REAL, no_rth=True) == STATUS_NO_SCHEDULED_RTH


def test_ordinary_session_is_ok():
    row = CAL.lookup(20200306)
    assert _classify(row, REAL) == STATUS_OK


def test_mid_session_gap_outranks_a_scheduled_early_close():
    """An early close explains an early END, never a hole in the middle."""
    row = _row(20191129, session_class="scheduled_early_close",
               status="shortened_rth", close_ct="12:00")
    table = build_session_schedule_table([_sched(row)])
    assert _classify(row, table, early=True, gap=True) == STATUS_MID_SESSION_GAP


def test_registered_interruption_outranks_an_observed_gap():
    """A sourced interruption explains the gap; the label says so."""
    from mnq_lab.spine.availability import SessionSchedule, StructuralInterruption

    sched = SessionSchedule(
        session_id=20991230, scheduled_rth_open_ct=510, scheduled_rth_close_ct=900,
        scheduled_rth_status="full_rth",
        structural_interruptions=(StructuralInterruption(
            start_ct_minute=700, end_ct_minute=715,
            reason="registered_interruption", source_id="SYNTHETIC"),),
        timezone="America/Chicago", calendar_version=CALENDAR_VERSION,
        calendar_sha256=CALENDAR_SHA256, interruption_source_id="SYNTHETIC",
    )
    table = build_session_schedule_table([sched])
    row = _row(20991230)
    assert _classify(row, table, gap=True) == STATUS_REGISTERED_INTERRUPTION


def test_exclusion_outranks_everything():
    row = _row(20991231)
    table = build_session_schedule_table(
        [_sched(row)],
        exclusions=(SessionExclusion(
            session_id=20991231,
            reason="excluded_unresolved_official_interruption",
            source_id="TEST", recorded_by_ruling="D33"),),
    )
    assert _classify(row, table, early=True, gap=True) == STATUS_EXCLUDED


def _sched(row):
    from mnq_lab.spine.availability import SessionSchedule

    no_rth = row.scheduled_rth_status in {"no_scheduled_rth", "full_exchange_holiday"}
    to_min = lambda t: int(t[:2]) * 60 + int(t[3:])
    return SessionSchedule(
        session_id=row.trade_date,
        scheduled_rth_open_ct=None if no_rth else to_min(row.scheduled_rth_open_ct),
        scheduled_rth_close_ct=None if no_rth else to_min(row.scheduled_rth_close_ct),
        scheduled_rth_status=row.scheduled_rth_status,
        structural_interruptions=(), timezone="America/Chicago",
        calendar_version=CALENDAR_VERSION, calendar_sha256=CALENDAR_SHA256,
        interruption_source_id=None,
    )


# ------------------------------------------------------------- fails closed


def test_contradictions_fail_closed():
    row = _row(20200306)
    with pytest.raises(SpineError):          # schedule says RTH, no bars seen
        _classify(row, REAL, no_rth=True)
    no_rth_row = CAL.lookup(NO_RTH_SESSION)
    with pytest.raises(SpineError):          # no RTH, yet RTH anomaly flagged
        _classify(no_rth_row, REAL, early=True)


def test_bad_inputs_fail_closed():
    row = _row(20200306)
    with pytest.raises(SpineError):
        classify_session_quality(session_id=20200307, calendar_row=row,
                                 observed_no_rth_bars=False, observed_rth_ended_early=False,
                                 observed_mid_rth_gap=False, schedule_table=REAL)
    with pytest.raises(SpineError):
        classify_session_quality(session_id=20200306, calendar_row=row,
                                 observed_no_rth_bars=0, observed_rth_ended_early=False,
                                 observed_mid_rth_gap=False, schedule_table=REAL)
    with pytest.raises(SpineError):
        classify_session_quality(session_id=20200306, calendar_row=row,
                                 observed_no_rth_bars=False, observed_rth_ended_early=False,
                                 observed_mid_rth_gap=False, schedule_table=object())


def test_no_outcome_value_can_reach_the_classifier():
    import inspect

    params = set(inspect.signature(classify_session_quality).parameters)
    assert params == {
        "session_id", "calendar_row", "observed_no_rth_bars",
        "observed_rth_ended_early", "observed_mid_rth_gap", "schedule_table",
    }
    forbidden = {"excursion", "ticks", "outcome", "quantile", "contrast",
                 "interval", "vol_rel", "scale_value", "category"}
    assert forbidden.isdisjoint(params)


# ------------------------------------------------------------- the registry


def test_exclusion_registry_is_byte_pinned_and_holds_exactly_the_four():
    records = load_session_exclusions()
    assert tuple(r.session_id for r in records) == MARCH
    assert {r.reason for r in records} == {"excluded_unresolved_official_interruption"}
    assert {r.recorded_by_ruling for r in records} == {"D33"}
    assert REAL.excluded_session_ids == MARCH
    assert len(EXCLUSION_REGISTRY_SHA256) == 64


def test_calendar_v1_still_classifies_the_four_as_regular_full_rth():
    """Exclusion is a separate registry, never a calendar edit."""
    for session in MARCH:
        row = CAL.lookup(session)
        assert (row.session_class, row.scheduled_rth_status) == ("regular", "full_rth")


# ------------------------------------------------------------------ mutants


def test_mutant_exclusion_ranked_below_gap_would_mislabel_the_march_sessions():
    """If exclusion did not outrank the gap check, the four become gaps."""
    def mutant(row, table, gap):
        if gap:
            return STATUS_MID_SESSION_GAP
        return STATUS_EXCLUDED if table.is_excluded(row.trade_date) else STATUS_OK

    row = CAL.lookup(20200309)
    assert _classify(row, REAL, gap=True) == STATUS_EXCLUDED
    assert mutant(row, REAL, True) == STATUS_MID_SESSION_GAP
    assert _classify(row, REAL, gap=True) != mutant(row, REAL, True)


def test_mutant_early_close_ranked_above_gap_would_swallow_the_gap():
    row = _row(20191129, session_class="scheduled_early_close",
               status="shortened_rth", close_ct="12:00")
    table = build_session_schedule_table([_sched(row)])

    def mutant(r, gap):
        if r.session_class == "scheduled_early_close":
            return STATUS_SCHEDULED_EARLY_CLOSE
        return STATUS_MID_SESSION_GAP if gap else STATUS_OK

    assert _classify(row, table, early=True, gap=True) == STATUS_MID_SESSION_GAP
    assert mutant(row, True) == STATUS_SCHEDULED_EARLY_CLOSE
    assert _classify(row, table, early=True, gap=True) != mutant(row, True)


def test_mutant_v1_collapsing_label_disagrees_on_four_of_the_six():
    """The v1 rule called all six 'truncated'. v2 splits them 4/2."""
    def v1(row, no_rth, early, gap):
        anomalous = no_rth or early or gap
        return ("unresolved_truncated_session"
                if row.session_class == "regular" and anomalous else "ok")

    for session in MARCH:
        row = CAL.lookup(session)
        assert v1(row, False, False, True) == "unresolved_truncated_session"
        assert _classify(row, REAL, gap=True) == STATUS_EXCLUDED
    for session in UNRESOLVED:
        row = CAL.lookup(session)
        assert v1(row, False, True, False) == "unresolved_truncated_session"
        assert _classify(row, REAL, early=True) == STATUS_UNRESOLVED_EARLY_TERMINATION
