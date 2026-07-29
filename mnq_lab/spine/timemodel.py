"""The clock-window engine: τ derivation, anchors, phases, session flags (spec §4).

This module is market-aware — anchors, RTH, session phases, and short sessions are
exchange concepts, so they live in ``spine/`` beside the calendar, never in ``core/``
(spec §16.3). The market-free event-time arithmetic it builds on is
``mnq_lab.core.causality``.

Time model (spec §4.1) and the two rulings recorded in docs/PHASE2_HANDOFF.md §6.5
(logged as docs/DISCREPANCIES.md D11):

- ``τ = bar label + 5 minutes`` — the bar label is the OPEN (finding E); τ is the
  instant the bar's close is observed. Every time-of-day decision keys on τ,
  **never** on the label.
- **Ruling 1**: an anchor is eligible when ``rth_start ≤ τ < rth_end`` in
  observation-time CT, half-open. The 08:25-labeled bar (overnight data, τ = 08:30)
  IS the first open-phase anchor; the 14:55-labeled bar (τ = 15:00) is NOT an
  anchor. The full declared τ-grid is emitted per session; a missing anchor bar
  yields the gridpoint with ``status = "anchor_bar_missing"``, never a silent
  absence (spec §16.4.5).
- **Ruling 2**: no CME calendar exists in this repository, and inventing one is
  worse than declaring the gap (§9.2, §14). Short sessions carry data-derived
  flags with honest names (``observed_short_session``); whether a shortening was
  *scheduled* is unknown, not false — the ``calendar_early_close`` column is the
  constant string ``"unknown"`` until a versioned CME calendar table arrives with
  a ledger entry.

Every wall-clock rule is computed in exchange-local time via tz conversion, never
via a fixed UTC offset — 08:30 CT is a different UTC instant across DST
transitions. Horizon arithmetic uses physical minutes; ``anchor_grid`` proves per
session that no UTC-offset change falls inside RTH (US DST switches at 02:00
local), so wall-clock and physical arithmetic agree exactly where this engine
operates, and it fails closed if that ever stops holding.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from mnq_lab import SpineError
from mnq_lab.constants import Constants, load_constants
from mnq_lab.core.causality import interval_end_ns
from mnq_lab.spine.calendar import session_ids_to_strings, trade_date_ids
from mnq_lab.spine.vendored import CME_TIMEZONE

__all__ = [
    "BAR_MINUTES",
    "BAR_SECONDS",
    "STATUS_OK",
    "STATUS_ANCHOR_BAR_MISSING",
    "TimeModel",
    "assert_store_bar_seconds",
]

# The spine's study bars are 5-minute bars (spec §4.1; the store is bars_5m). This is
# a structural property of the store, not an analysis constant, which is why it is not
# in analysis_constants_v1.yaml. It is not merely asserted: `assert_store_bar_seconds`
# checks the store manifest's declared `bar_seconds`, and `TimeModel._assert_bar_grid`
# checks the observed label stride (audit M-5 — divisibility alone cannot tell a
# 5-minute store from a 10-minute one).
BAR_MINUTES = 5
BAR_SECONDS = BAR_MINUTES * 60
BAR_NS = BAR_SECONDS * 1_000_000_000
MINUTE_NS = 60 * 1_000_000_000

STATUS_OK = "ok"
STATUS_ANCHOR_BAR_MISSING = "anchor_bar_missing"

# Ruling 2 three-state semantics: the calendar truth is unknown, not false.
CALENDAR_EARLY_CLOSE_UNKNOWN = "unknown"


def assert_store_bar_seconds(manifest: dict) -> None:
    """Refuse a store whose declared bar duration is not this engine's.

    Audit finding M-5 (2026-07-28): `BAR_MINUTES = 5` was justified as "structural
    to the store" but nothing consumed the store's own declaration of it. The
    Phase 1 manifest carries `bar_seconds`; this consumes it, so a store built at
    another frequency is rejected at the door rather than producing a τ-grid that
    is half `anchor_bar_missing`.
    """
    declared = manifest.get("bar_seconds")
    if declared is None:
        raise SpineError(
            "store manifest declares no bar_seconds; refusing to assume "
            f"{BAR_SECONDS}s bars (audit M-5)"
        )
    # Round-2 audit finding M-4 (2026-07-28): comparing int(declared) truncated
    # 300.9 to 300 and coerced "300", so malformed declarations passed a check
    # whose entire job is exactness. The manifest is written with a JSON integer;
    # anything else is a corrupt or foreign manifest, not a value to repair.
    if isinstance(declared, bool) or not isinstance(declared, (int, np.integer)):
        raise SpineError(
            f"store manifest bar_seconds is {declared!r} "
            f"({type(declared).__name__}); it must be a plain integer. A float or "
            "string here means the manifest was not written by this pipeline "
            "(round-2 audit M-4)."
        )
    if int(declared) != BAR_SECONDS:
        raise SpineError(
            f"store declares bar_seconds={int(declared)} but this engine is built "
            f"for {BAR_SECONDS}s bars. The τ-grid and every horizon are expressed "
            f"in {BAR_MINUTES}-minute bars; running it against another frequency "
            "would silently mis-key every anchor. Stop and report (spec §16.6)."
        )


def _parse_ct_minutes(value: str, name: str) -> int:
    try:
        hours, minutes = value.split(":")
        total = int(hours) * 60 + int(minutes)
    except (ValueError, AttributeError) as exc:
        raise SpineError(f"{name} must be 'HH:MM', got {value!r}") from exc
    if not 0 <= total < 24 * 60:
        raise SpineError(f"{name}={value!r} is outside the day")
    return total


@dataclass(frozen=True)
class TimeModel:
    """RTH bounds, session phases, and horizons — all consumed from the frozen YAML.

    Nothing here defaults: a missing constant raises in ``Constants.get`` (spec §12),
    and a YAML whose phases do not tile RTH, or whose bounds sit off the 5-minute bar
    grid, refuses to construct. The Phase 1 re-audit proved a divergent
    ``rth_start_ct`` built byte-identical data because nothing consumed it; this
    class is the consumer, and ``tests/test_time_and_timezone.py`` proves a divergent
    YAML now changes anchor output.
    """

    session_tz: str
    rth_start_minute: int
    rth_end_minute: int
    phase_names: tuple[str, ...]
    phase_starts: tuple[int, ...]  # minutes-of-day CT, same order as phase_names
    phase_ends: tuple[int, ...]
    horizons_minutes: tuple[int, ...]

    @classmethod
    def from_constants(cls, constants: Constants | None = None) -> "TimeModel":
        constants = constants if constants is not None else load_constants()

        session_tz = constants.get("time", "session_tz")
        # Audit M2 pattern: the vendored session runtime hardcodes America/Chicago.
        # A YAML declaring a different zone would bucket under one rule while the
        # spine filtered under another. Fail closed; changing the zone requires a
        # new pipeline version with a ledger entry.
        if session_tz != CME_TIMEZONE:
            raise SpineError(
                f"time.session_tz is {session_tz!r} but the spine's session runtime "
                f"implements {CME_TIMEZONE!r}; refusing to bucket under a different "
                "zone than the data was built with (audit M2)."
            )

        rth_start = _parse_ct_minutes(constants.get("time", "rth_start_ct"), "time.rth_start_ct")
        rth_end = _parse_ct_minutes(constants.get("time", "rth_end_ct"), "time.rth_end_ct")
        if rth_start >= rth_end:
            raise SpineError(f"rth_start_ct must precede rth_end_ct, got {rth_start} >= {rth_end}")
        for name, minute in (("rth_start_ct", rth_start), ("rth_end_ct", rth_end)):
            if minute % BAR_MINUTES != 0:
                raise SpineError(
                    f"time.{name} = minute {minute} is off the {BAR_MINUTES}-minute bar "
                    "grid; the τ-grid would not align with bar labels"
                )

        phases = constants.get("session_phases")
        if not isinstance(phases, dict) or not phases:
            raise SpineError("session_phases must be a nonempty mapping")
        names, starts, ends = [], [], []
        for phase_name, bounds in phases.items():
            if not (isinstance(bounds, list) and len(bounds) == 2):
                raise SpineError(f"session_phases.{phase_name} must be [start, end]")
            names.append(str(phase_name))
            starts.append(_parse_ct_minutes(bounds[0], f"session_phases.{phase_name}[0]"))
            ends.append(_parse_ct_minutes(bounds[1], f"session_phases.{phase_name}[1]"))
        # Phases must tile RTH exactly — contiguous, half-open, no gap, no overlap
        # (spec §4.2). This is validated at construction, not assumed from the test
        # suite, so a divergent YAML cannot construct a phase table at all.
        if starts[0] != rth_start:
            raise SpineError(
                f"first phase starts at minute {starts[0]}, RTH starts at {rth_start}; "
                "phases must tile RTH exactly (spec §4.2)"
            )
        if ends[-1] != rth_end:
            raise SpineError(
                f"last phase ends at minute {ends[-1]}, RTH ends at {rth_end}; "
                "phases must tile RTH exactly (spec §4.2)"
            )
        # Audit finding M-2 (2026-07-28): checking only "each end == the next start"
        # accepts a BACKWARDS phase (e.g. morning = [10:30, 09:00]), which still
        # chains but silently overlaps its neighbours and empties itself of anchors.
        # Every phase must have positive duration and the whole boundary sequence
        # must be strictly increasing, or the table does not tile RTH.
        for name, start, end in zip(names, starts, ends):
            if start >= end:
                raise SpineError(
                    f"phase {name!r} spans [{start}, {end}) minutes, which is empty "
                    "or backwards; phases must tile RTH exactly (spec §4.2)"
                )
        for i in range(len(names) - 1):
            if ends[i] != starts[i + 1]:
                raise SpineError(
                    f"phase {names[i]!r} ends at minute {ends[i]} but {names[i+1]!r} "
                    f"starts at {starts[i+1]}; phases must be contiguous (spec §4.2)"
                )
        # No separate monotonicity check: positive duration (start < end) plus
        # contiguity (end_i == start_{i+1}) already force the boundary sequence
        # strictly increasing. A first draft of the M-2 fix asserted monotonicity
        # again anyway — a check that could never fire, which is worse than no
        # check (§16.7) — and it was removed once proven unreachable.

        horizons = constants.get("horizons_minutes")
        if not isinstance(horizons, list) or not horizons:
            raise SpineError("horizons_minutes must be a nonempty list")
        for horizon in horizons:
            if not isinstance(horizon, int) or horizon <= 0 or horizon % BAR_MINUTES != 0:
                raise SpineError(
                    f"horizon {horizon!r} is not a positive multiple of {BAR_MINUTES} minutes"
                )

        return cls(
            session_tz=session_tz,
            rth_start_minute=rth_start,
            rth_end_minute=rth_end,
            phase_names=tuple(names),
            phase_starts=tuple(starts),
            phase_ends=tuple(ends),
            horizons_minutes=tuple(int(h) for h in horizons),
        )

    # --- τ derivation and CT bucketing ---------------------------------------------

    def observation_times_ns(self, ts_event_ns: np.ndarray) -> np.ndarray:
        """τ for each bar: label + bar length. The label is the OPEN (finding E)."""
        return interval_end_ns(ts_event_ns, BAR_NS)

    def ct_minute_of_day(self, instant_ns: np.ndarray) -> np.ndarray:
        """Exchange-local wall-clock minute of day for UTC-nanosecond instants.

        Computed by tz conversion, never a fixed UTC offset — the same CT wall
        minute is a different UTC instant either side of a DST transition. Fails
        closed on instants off the minute grid: a 5-minute-bar τ with seconds in
        it means the store is corrupt, not that rounding is wanted.
        """
        instants = np.asarray(instant_ns)
        if instants.dtype != np.int64:
            raise SpineError(
                f"instant_ns must be int64 UTC nanoseconds, got {instants.dtype} "
                "(pandas 3.0 emits datetime64[us] unless forced to ns)"
            )
        if instants.size and int((instants % MINUTE_NS != 0).sum()):
            raise SpineError("instants off the minute grid; the store is misaligned")
        local = pd.DatetimeIndex(
            pd.to_datetime(instants, unit="ns", utc=True)
        ).tz_convert(self.session_tz)
        return (local.hour * 60 + local.minute).to_numpy(dtype=np.int32)

    # --- anchor eligibility and phases (Ruling 1) ----------------------------------

    def anchor_eligible(self, tau_ct_minute: np.ndarray) -> np.ndarray:
        """Ruling 1: eligible iff ``rth_start ≤ τ < rth_end``, on τ — never the label."""
        minutes = np.asarray(tau_ct_minute)
        return (minutes >= self.rth_start_minute) & (minutes < self.rth_end_minute)

    def phase_of(self, tau_ct_minute: np.ndarray) -> np.ndarray:
        """Phase name for each τ minute; ``""`` where no phase contains τ.

        Half-open ``[start, end)`` per phase (spec §4.2). τ = 15:00 lies in no
        phase — which is exactly why the 14:55-labeled bar is not an anchor.
        """
        minutes = np.asarray(tau_ct_minute)
        out = np.full(minutes.shape, "", dtype=object)
        for name, start, end in zip(self.phase_names, self.phase_starts, self.phase_ends):
            out[(minutes >= start) & (minutes < end)] = name
        return out

    def outcome_window_fits_rth(
        self, tau_ct_minute: np.ndarray, horizon_minutes: int
    ) -> np.ndarray:
        """Whether ``[τ, τ+Δ)`` lies inside RTH: ``τ + Δ ≤ rth_end``.

        Wall-clock arithmetic is valid here because ``anchor_grid`` proves no
        UTC-offset change occurs inside RTH for any built session.
        """
        if horizon_minutes not in self.horizons_minutes:
            raise SpineError(
                f"horizon {horizon_minutes} is not a declared horizon "
                f"{list(self.horizons_minutes)} (analysis_constants_v1.yaml)"
            )
        minutes = np.asarray(tau_ct_minute)
        return minutes + horizon_minutes <= self.rth_end_minute

    # --- the declared τ-grid (Ruling 1, spec §16.4.5) ------------------------------

    def tau_grid_ct_minutes(self) -> np.ndarray:
        """The declared τ-grid: every eligible observation minute, e.g. 08:30…14:55."""
        return np.arange(self.rth_start_minute, self.rth_end_minute, BAR_MINUTES, dtype=np.int32)

    def _localize_session_minutes(
        self, session_dates: np.ndarray, ct_minutes: np.ndarray
    ) -> np.ndarray:
        """UTC int64 ns instants for (session trade date × CT wall minute) pairs.

        ``tz_localize`` with ``ambiguous="raise"``/``nonexistent="raise"``: RTH
        minutes are never inside a US DST fold (transitions happen 02:00 local),
        so any ambiguity means the inputs are wrong and the build must stop.
        """
        naive = (
            pd.DatetimeIndex(pd.to_datetime(session_dates, format="%Y-%m-%d"))
            + pd.to_timedelta(ct_minutes, unit="m")
        ).as_unit("ns")
        localized = naive.tz_localize(
            self.session_tz, ambiguous="raise", nonexistent="raise"
        )
        return localized.tz_convert("UTC").asi8

    # --- fail-closed input guards (extracted so each is directly testable) ---------

    def _assert_bar_grid(self, labels: np.ndarray) -> None:
        """Labels must lie on the bar grid AND actually have the bar's stride.

        Audit finding M-5 (2026-07-28): divisibility alone does not identify the
        bar duration — a 10- or 15-minute store is also divisible by five
        minutes, and would silently produce a τ-grid where every second gridpoint
        reports ``anchor_bar_missing``. So the smallest positive gap between
        consecutive labels is checked against the bar duration.

        Scope, weakened per the round-2 audit adjudication: this is a fail-closed
        *frequency check*, not a reliable inference of the bar duration. A
        genuine 5-minute store so sparse that no two adjacent bars sit 5 minutes
        apart would be refused with a wrong-frequency diagnostic — it errs toward
        refusal, never toward silently accepting the wrong stride. The
        authoritative declaration is the manifest's ``bar_seconds``, consumed by
        ``assert_store_bar_seconds`` wherever a store (rather than a raw array)
        is available.
        """
        if labels.size and int((labels % BAR_NS != 0).sum()):
            raise SpineError(
                f"store labels off the {BAR_MINUTES}-minute grid; anchor grid "
                "construction requires aligned 5-minute bars"
            )
        if labels.size < 2:
            return
        gaps = np.diff(labels)
        if int((gaps <= 0).sum()):
            raise SpineError(
                "ts_event_ns must be strictly increasing; the spine emits one "
                "chronological active-contract chain"
            )
        stride = int(gaps.min())
        if stride != BAR_NS:
            raise SpineError(
                f"smallest gap between consecutive labels is {stride / 6e10:g} "
                f"minutes, but this engine is built for {BAR_MINUTES}-minute bars. "
                "Refusing to infer the bar duration: a 10- or 15-minute store is "
                "also divisible by 5 minutes and would silently drop half the "
                "τ-grid (audit M-5). Pass a 5-minute store, or re-derive the "
                "engine's bar duration explicitly."
            )

    def _assert_no_offset_change_inside_rth(self, session_dates: np.ndarray) -> None:
        """No UTC-offset change may fall inside RTH on any session.

        Horizon arithmetic elsewhere adds *physical* minutes to τ while phase and
        eligibility logic uses *wall-clock* minutes. The two agree only while the
        UTC offset is constant across RTH. US DST switches at 02:00 local, so this
        holds for every CME session — but it is a load-bearing assumption, so it
        is proven per session rather than asserted in a comment.
        """
        rth_span_ns = np.int64((self.rth_end_minute - self.rth_start_minute) * MINUTE_NS)
        bounds_ns = self._localize_session_minutes(
            np.repeat(session_dates, 2),
            np.tile(
                np.asarray([self.rth_start_minute, self.rth_end_minute]),
                len(session_dates),
            ),
        ).reshape(len(session_dates), 2)
        offset_shifted = bounds_ns[:, 1] - bounds_ns[:, 0] != rth_span_ns
        if int(offset_shifted.sum()):
            bad = np.asarray(session_dates)[offset_shifted]
            raise SpineError(
                f"UTC offset changes inside RTH for sessions {bad[:5].tolist()}; "
                "wall-clock horizon arithmetic is invalid there. Stop and report "
                "(spec §16.6) — do not fall back to physical-time buckets."
            )

    def _assert_sessions_own_their_bars(
        self, sessions: np.ndarray, labels: np.ndarray
    ) -> None:
        """Every bar's ``session_id`` must equal its own CME trade date.

        Audit finding M-6 (2026-07-28): anchor and outcome presence are matched by
        exact UTC instant across the whole input, without pairing on
        ``session_id``. That is sound only because a UTC instant belongs to
        exactly one CME session — true of the built stores (independently
        verified: zero timestamp-to-session-ID mismatches), but an assumption
        about the *input*, not a property enforced by this module. So it is
        enforced here, once, using the spine's own trade-date rule.
        """
        if labels.size == 0:
            return
        derived = trade_date_ids(
            pd.Series(pd.to_datetime(labels, unit="ns", utc=True))
        )
        mismatched = derived != np.asarray(sessions, dtype=np.int32)
        if int(mismatched.sum()):
            first = int(np.flatnonzero(mismatched)[0])
            raise SpineError(
                f"{int(mismatched.sum())} bar(s) carry a session_id that is not "
                f"their CME trade date; first at index {first}: label "
                f"{pd.Timestamp(int(labels[first]), unit='ns', tz='UTC')} is trade "
                f"date {int(derived[first])} but is labelled {int(sessions[first])}. "
                "Exact-instant presence matching would attribute one session's bar "
                "to another (audit M-6)."
            )

    def anchor_grid(
        self, session_id: np.ndarray, ts_event_ns: np.ndarray
    ) -> pd.DataFrame:
        """The full declared anchor grid for every session present in the input.

        One row per session × τ-gridpoint, emitted unconditionally: a session with
        no 08:25 bar still has the τ = 08:30 row, with
        ``status = "anchor_bar_missing"`` (spec §16.4.5 — never a silent absence).

        Columns: ``session_id`` int32, ``tau_ct_minute`` int32, ``tau_ns`` int64
        UTC, ``anchor_label_ns`` int64 UTC (the bar whose close is observed at τ,
        label = τ − 5 min), ``phase`` str, ``status`` str.

        Validation order matters and is deliberate (audit findings M-4, M-5, M-6):
        the intra-RTH offset guard runs BEFORE the τ-grid is localized, because a
        session whose offset changes inside RTH also has nonexistent or ambiguous
        grid minutes, and localizing the grid first would raise an anonymous
        pandas ``ValueError`` instead of this module's diagnostic. The
        session-ownership check runs after the offset guard because it applies the
        CME trade-date rule, which is meaningful only for a CME session calendar.
        """
        sessions = np.asarray(session_id)
        labels = np.asarray(ts_event_ns)
        if labels.dtype != np.int64:
            raise SpineError(f"ts_event_ns must be int64, got {labels.dtype}")
        if sessions.shape != labels.shape:
            raise SpineError("session_id and ts_event_ns must be aligned")
        self._assert_bar_grid(labels)

        unique_sessions = np.unique(sessions).astype(np.int32)
        session_dates = session_ids_to_strings(unique_sessions)
        grid = self.tau_grid_ct_minutes()
        n_sessions, n_grid = len(unique_sessions), len(grid)

        self._assert_no_offset_change_inside_rth(session_dates)
        self._assert_sessions_own_their_bars(sessions, labels)

        tau_ns = self._localize_session_minutes(
            np.repeat(session_dates, n_grid), np.tile(grid, n_sessions)
        )
        anchor_label_ns = tau_ns - np.int64(BAR_NS)
        present = np.isin(anchor_label_ns, labels)
        status = np.where(present, STATUS_OK, STATUS_ANCHOR_BAR_MISSING)
        tau_minutes = np.tile(grid, n_sessions)

        return pd.DataFrame(
            {
                "session_id": np.repeat(unique_sessions, n_grid),
                "tau_ct_minute": tau_minutes.astype(np.int32),
                "tau_ns": tau_ns,
                "anchor_label_ns": anchor_label_ns,
                "phase": self.phase_of(tau_minutes),
                "status": status,
            }
        )

    # --- data-derived session flags (Ruling 2) -------------------------------------

    def session_flags(
        self, session_id: np.ndarray, ts_event_ns: np.ndarray
    ) -> pd.DataFrame:
        """Per-session, data-derived RTH shape flags. No calendar claims.

        ``observed_no_rth_bars`` — the session has **no** RTH bar at all, so it
        never started as far as this data shows. Audit adjudication (2026-07-28):
        such a session was previously flagged ``observed_rth_ended_early``, which
        is a claim the data does not support — a session that never started did
        not end early. It is now its own state, mutually exclusive with
        ``observed_rth_ended_early``. Exactly one exploration session
        (20210402) is in this state.

        ``observed_rth_ended_early`` — some RTH bars exist AND the trailing end of
        the RTH label grid is missing: the last observed RTH bar ends before
        ``rth_end``. A scheduled early close, a feed outage, and a vendor gap all
        produce the same flag; that uncertainty is intentional (Ruling 2) and is
        why the name says *observed*, never *official*.

        ``observed_mid_rth_gap`` — at least one RTH label is missing strictly
        before the last observed one. Truncated-end and mid-session-gap sessions
        are therefore distinguished: a session missing 10:00–10:25 but trading to
        15:00 gaps without ending early, and vice versa. A session can be both.

        ``observed_short_session`` — alias of ``observed_rth_ended_early``: the
        session's RTH, as observed in data, is short *but nonempty*.

        ``last_rth_bar_end_ct_minute`` — CT minute at which the last observed RTH
        bar ends, or the sentinel ``-1`` when ``observed_no_rth_bars``. Consumers
        ranking sessions by this value must exclude the sentinel; it is not an
        early end.

        ``calendar_early_close`` — the constant ``"unknown"``: whether any
        shortening was scheduled cannot be known without a versioned CME calendar
        table, which does not exist in this repository. Unknown is not false.
        Formal calendar-dependent exclusion (null strata, seasonal profile) stays
        fail-closed/deferred until that table arrives with a ledger entry.
        """
        sessions = np.asarray(session_id)
        labels = np.asarray(ts_event_ns)
        if labels.dtype != np.int64:
            raise SpineError(f"ts_event_ns must be int64, got {labels.dtype}")
        if sessions.shape != labels.shape:
            raise SpineError("session_id and ts_event_ns must be aligned")
        # Found while preparing the round-2 audit: the round-1 M-6 fix guarded
        # anchor_grid but left this method's identical exact-instant matching
        # unguarded — the same borrow-across-sessions defect through another door.
        # Same guards, same order, both entry points.
        self._assert_bar_grid(labels)
        self._assert_sessions_own_their_bars(sessions, labels)

        unique_sessions = np.unique(sessions).astype(np.int32)
        session_dates = session_ids_to_strings(unique_sessions)
        # RTH bar labels: [rth_start, rth_end), same stride as the τ-grid.
        label_grid = np.arange(
            self.rth_start_minute, self.rth_end_minute, BAR_MINUTES, dtype=np.int32
        )
        n_sessions, n_grid = len(unique_sessions), len(label_grid)
        expected_ns = self._localize_session_minutes(
            np.repeat(session_dates, n_grid), np.tile(label_grid, n_sessions)
        )
        present = np.isin(expected_ns, labels).reshape(n_sessions, n_grid)

        observed = present.sum(axis=1).astype(np.int32)
        missing = np.int32(n_grid) - observed
        # Consecutive missing labels at the END of the grid: cumprod over the
        # reversed presence-complement stays 1 exactly while the tail is missing.
        trailing = (
            np.cumprod(~present[:, ::-1], axis=1).sum(axis=1).astype(np.int32)
        )
        interior = missing - trailing
        no_rth = observed == 0
        # A session with no RTH bars did not "end early" — it never started.
        ended_early = (trailing > 0) & ~no_rth
        last_end_minute = np.where(
            no_rth,
            np.int32(-1),
            self.rth_end_minute - BAR_MINUTES * trailing,
        ).astype(np.int32)

        return pd.DataFrame(
            {
                "session_id": unique_sessions,
                "n_rth_bars_expected": np.full(n_sessions, n_grid, dtype=np.int32),
                "n_rth_bars_observed": observed,
                "n_rth_bars_missing_trailing": trailing,
                "n_rth_bars_missing_interior": interior,
                "last_rth_bar_end_ct_minute": last_end_minute,
                "observed_no_rth_bars": no_rth,
                "observed_rth_ended_early": ended_early,
                "observed_mid_rth_gap": interior > 0,
                "observed_short_session": ended_early,
                "calendar_early_close": np.full(
                    n_sessions, CALENDAR_EARLY_CLOSE_UNKNOWN, dtype=object
                ),
            }
        )
