"""Session data-quality classification (Stage 4 of the D32/D33 repair).

Phase 7 v1 collapsed every anomaly on a regular session into one label,
``unresolved_truncated_session`` (``production/first_exploration_run.py``). That
label asserted the whole day was truncated. Measurement shows it was applied to
two genuinely different situations: two sessions whose trading ends early and
never resumes, and four sessions with a temporary intraday gap after which
trading resumes normally. Calling the second kind "truncated" is a claim the
evidence does not support.

This module replaces that single label with a closed, declared vocabulary that
separates *structural* causes (known from the schedule or a registered ruling)
from *observed* anomalies (seen in the data and unexplained).

Measured partition of the 1,009 exploration sessions before this change:

    regular / full_rth              , no flags      970   -> ok
    scheduled_early_close/shortened , ended_early    32   -> scheduled_early_close
    regular / full_rth              , mid_gap         4   -> excluded (D33)
    regular / full_rth              , ended_early     2   -> observed early termination
    scheduled_early_close/no_rth    , no_rth_bars     1   -> no_scheduled_rth

The groups are disjoint, so no session in the current corpus exercises more than
one branch. The precedence below is still declared and tested, because a future
corpus may.

No outcome value participates. The classifier never sees an excursion, a tick, a
quantile or an interval, and its signature makes that structural.
"""

from __future__ import annotations

from mnq_lab import SpineError
from mnq_lab.spine.accepted_calendar import CalendarRow
from mnq_lab.spine.availability import SessionScheduleTable

__all__ = [
    "SESSION_QUALITY_STATUSES",
    "STATUS_EXCLUDED",
    "STATUS_MID_SESSION_GAP",
    "STATUS_NO_SCHEDULED_RTH",
    "STATUS_OK",
    "STATUS_REGISTERED_INTERRUPTION",
    "STATUS_SCHEDULED_EARLY_CLOSE",
    "STATUS_UNRESOLVED_EARLY_TERMINATION",
    "classify_session_quality",
]

STATUS_EXCLUDED = "excluded_unresolved_official_interruption"
STATUS_NO_SCHEDULED_RTH = "no_scheduled_rth"
STATUS_REGISTERED_INTERRUPTION = "registered_structural_interruption"
STATUS_MID_SESSION_GAP = "observed_unexplained_mid_session_gap"
STATUS_SCHEDULED_EARLY_CLOSE = "scheduled_early_close"
STATUS_UNRESOLVED_EARLY_TERMINATION = "observed_unresolved_early_termination"
STATUS_OK = "ok"

# Canonical order == the precedence the classifier applies.
SESSION_QUALITY_STATUSES = (
    STATUS_EXCLUDED,
    STATUS_NO_SCHEDULED_RTH,
    STATUS_REGISTERED_INTERRUPTION,
    STATUS_MID_SESSION_GAP,
    STATUS_SCHEDULED_EARLY_CLOSE,
    STATUS_UNRESOLVED_EARLY_TERMINATION,
    STATUS_OK,
)

_NO_RTH_STATUSES = frozenset({"no_scheduled_rth", "full_exchange_holiday"})


def classify_session_quality(
    *,
    session_id: int,
    calendar_row: CalendarRow,
    observed_no_rth_bars: bool,
    observed_rth_ended_early: bool,
    observed_mid_rth_gap: bool,
    schedule_table: SessionScheduleTable,
) -> str:
    """Classify one session. Structural causes outrank observed anomalies.

    Precedence, and why each rank sits where it does:

    1. ``excluded`` -- a D33 exclusion removes the session from the population
       entirely, so nothing else about it is worth classifying.
    2. ``no_scheduled_rth`` -- there was no RTH to truncate or interrupt.
    3. ``registered_structural_interruption`` -- an authoritative interruption
       explains a gap. None is registered today; the branch exists so that a
       future record does not need a new vocabulary.
    4. ``observed_unexplained_mid_session_gap`` -- ABOVE scheduled_early_close on
       purpose. An early close explains a session ending early; it does not
       explain a hole in the middle of one. Ranking the schedule higher would let
       a scheduled close swallow an unexplained gap.
    5. ``scheduled_early_close`` -- the early end is explained by the schedule, so
       it is a structural fact and not an anomaly.
    6. ``observed_unresolved_early_termination`` -- trading ends early on a day
       with no scheduled reason. This is the honest "we do not know" case.
    7. ``ok``.

    Fails closed on contradictions rather than choosing a plausible label.
    """
    if type(session_id) is not int:
        raise SpineError("session_id must be a built-in int")
    if not isinstance(calendar_row, CalendarRow):
        raise SpineError("session quality requires one accepted CalendarRow")
    if calendar_row.trade_date != session_id:
        raise SpineError(
            f"calendar row {calendar_row.trade_date} does not describe session {session_id}"
        )
    if not isinstance(schedule_table, SessionScheduleTable):
        raise SpineError("session quality requires a canonical SessionScheduleTable")
    for name, value in (
        ("observed_no_rth_bars", observed_no_rth_bars),
        ("observed_rth_ended_early", observed_rth_ended_early),
        ("observed_mid_rth_gap", observed_mid_rth_gap),
    ):
        if type(value) is not bool:
            raise SpineError(f"{name} must be a built-in bool")

    has_scheduled_rth = calendar_row.scheduled_rth_status not in _NO_RTH_STATUSES

    # Contradiction: the schedule says RTH exists but not one RTH bar was seen,
    # or the schedule says there is no RTH yet bars were observed. Either way the
    # calendar and the data disagree; that is a discrepancy to report, not to label.
    if has_scheduled_rth and observed_no_rth_bars:
        raise SpineError(
            f"session {session_id}: schedule declares RTH "
            f"({calendar_row.scheduled_rth_status}) but no RTH bar was observed"
        )
    if not has_scheduled_rth and (observed_rth_ended_early or observed_mid_rth_gap):
        raise SpineError(
            f"session {session_id}: schedule declares no RTH but observed-RTH "
            "anomaly flags are set"
        )

    if schedule_table.is_excluded(session_id):
        return STATUS_EXCLUDED
    if not has_scheduled_rth:
        return STATUS_NO_SCHEDULED_RTH
    if schedule_table.lookup(session_id).structural_interruptions:
        return STATUS_REGISTERED_INTERRUPTION
    if observed_mid_rth_gap:
        return STATUS_MID_SESSION_GAP
    if calendar_row.session_class == "scheduled_early_close":
        return STATUS_SCHEDULED_EARLY_CLOSE
    if observed_rth_ended_early:
        return STATUS_UNRESOLVED_EARLY_TERMINATION
    return STATUS_OK
