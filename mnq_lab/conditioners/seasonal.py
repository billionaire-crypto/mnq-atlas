"""Frozen causal seasonal profiles over strictly prior completed sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from types import MappingProxyType
from zoneinfo import ZoneInfo

import numpy as np

from mnq_lab import SpineError
from mnq_lab.conditioners.calendar import (
    CALENDAR_SHA256,
    CALENDAR_VERSION,
    CalendarTable,
)
from mnq_lab.conditioners.scales.median import lower_median
from mnq_lab.conditioners.status import SeasonalStatus
from mnq_lab.spine.timemodel import BAR_NS, TimeModel

__all__ = [
    "RTH_BUCKETS",
    "ScaleAnchorRow",
    "ScaleAnchorTable",
    "SeasonalProfileRow",
    "SeasonalProfileTable",
    "build_seasonal_profiles",
    "scale_anchor_row",
]

CT = ZoneInfo("America/Chicago")
RTH_BUCKET_MINUTES = tuple(range(8 * 60 + 30, 15 * 60, 5))
RTH_BUCKETS = tuple(f"{minute // 60:02d}:{minute % 60:02d}" for minute in RTH_BUCKET_MINUTES)
SEASONAL_WARMUP_SESSIONS = 60
SEASONAL_MIN_BUCKET_OBS = 30
SEASONAL_SHRINK_K = 30


@lru_cache(maxsize=1)
def _time_model() -> TimeModel:
    return TimeModel.from_constants()


def _bucket_and_phase(tau_ns: int) -> tuple[str, str]:
    if type(tau_ns) is not int:
        raise SpineError("tau_ns must be a built-in int")
    value = datetime.fromtimestamp(tau_ns / 1_000_000_000, tz=UTC).astimezone(CT)
    if value.second or value.microsecond or value.minute % 5:
        raise SpineError("anchor observation time must lie on the five-minute grid")
    minute = value.hour * 60 + value.minute
    model = _time_model()
    if not model.rth_start_minute <= minute < model.rth_end_minute:
        raise SpineError("scale anchor observation time is outside the RTH state grid")
    phase = str(model.phase_of(np.asarray([minute], dtype=np.int32))[0])
    if not phase:
        raise SpineError("scale anchor has no frozen session phase")
    return f"{value.hour:02d}:{value.minute:02d}", phase


def _phase_for_bucket(bucket: str) -> str:
    try:
        hour, minute = (int(part) for part in bucket.split(":"))
    except (ValueError, AttributeError) as exc:
        raise SpineError(f"invalid observation bucket {bucket!r}") from exc
    total = hour * 60 + minute
    phase = str(_time_model().phase_of(np.asarray([total], dtype=np.int32))[0])
    if not phase:
        raise SpineError(f"bucket {bucket!r} is outside the frozen phase grid")
    return phase


@dataclass(frozen=True)
class ScaleAnchorRow:
    arm_id: str
    session_id: int
    ts_event_ns: int
    tau_ns: int
    observation_bucket_ct: str
    session_phase: str
    scale_stage: str
    scale_value: float
    scale_valid: bool
    data_quality_status: str

    def __post_init__(self) -> None:
        if not isinstance(self.arm_id, str) or not self.arm_id:
            raise SpineError("scale anchor arm_id must be nonempty")
        if type(self.session_id) is not int:
            raise SpineError("scale anchor session_id must be a built-in int")
        if type(self.ts_event_ns) is not int or type(self.tau_ns) is not int:
            raise SpineError("scale anchor timestamps must be built-in integers")
        if self.tau_ns != self.ts_event_ns + int(BAR_NS):
            raise SpineError("scale anchor tau must equal ts_event plus five minutes")
        bucket, phase = _bucket_and_phase(self.tau_ns)
        if self.observation_bucket_ct != bucket or self.session_phase != phase:
            raise SpineError("scale anchor bucket/phase differs from observation time")
        if self.scale_stage not in {"ewma", "mad"}:
            raise SpineError("scale anchor stage must be ewma or mad")
        if type(self.scale_valid) is not bool:
            raise SpineError("scale_valid must be bool")
        if not isinstance(self.scale_value, float) or not np.isfinite(self.scale_value):
            raise SpineError("scale_value must be a finite float")
        if self.scale_value < 0.0:
            raise SpineError("scale_value cannot be negative")
        if not self.scale_valid and self.scale_value != 0.0:
            raise SpineError("undefined scale rows must store numeric zero")
        if self.scale_value == 0.0:
            object.__setattr__(self, "scale_value", 0.0)
        if not isinstance(self.data_quality_status, str) or not self.data_quality_status:
            raise SpineError("data_quality_status must be nonempty")


def scale_anchor_row(
    *,
    arm_id: str,
    session_id: int,
    ts_event_ns: int,
    scale_stage: str,
    scale_value: float,
    scale_valid: bool,
    data_quality_status: str = "ok",
) -> ScaleAnchorRow:
    tau_ns = int(ts_event_ns) + int(BAR_NS)
    bucket, phase = _bucket_and_phase(tau_ns)
    return ScaleAnchorRow(
        arm_id,
        int(session_id),
        int(ts_event_ns),
        tau_ns,
        bucket,
        phase,
        scale_stage,
        float(scale_value),
        bool(scale_valid),
        data_quality_status,
    )


@dataclass(frozen=True)
class ScaleAnchorTable:
    arm_id: str
    rows: tuple[ScaleAnchorRow, ...]

    def __post_init__(self) -> None:
        if not self.rows:
            raise SpineError("scale anchor table must be nonempty")
        if any(row.arm_id != self.arm_id for row in self.rows):
            raise SpineError("scale anchor table mixes arm identifiers")
        keys = [(row.session_id, row.tau_ns) for row in self.rows]
        if keys != sorted(keys) or len(set(keys)) != len(keys):
            raise SpineError("scale anchor rows must be unique and ordered by session/tau")


@dataclass(frozen=True)
class SeasonalProfileRow:
    arm_id: str
    session_id: int
    observation_bucket_ct: str
    session_phase: str
    qualifying_prior_sessions: int
    bucket_n: int
    bucket_median: float
    bucket_median_valid: bool
    phase_session_median: float
    phase_session_median_valid: bool
    shrink_weight: float
    seasonal_profile: float
    seasonal_valid: bool
    seasonal_status: SeasonalStatus
    calendar_version: str
    calendar_sha256: str
    dependency_keys: tuple[tuple[int, str], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.seasonal_status, SeasonalStatus):
            raise SpineError("seasonal_status must use the closed vocabulary")
        if self.observation_bucket_ct not in RTH_BUCKETS:
            raise SpineError("seasonal row bucket is outside the frozen grid")
        if self.session_phase != _phase_for_bucket(self.observation_bucket_ct):
            raise SpineError("seasonal row phase differs from its bucket")
        if type(self.qualifying_prior_sessions) is not int or type(self.bucket_n) is not int:
            raise SpineError("seasonal counts must be built-in integers")
        if not 0 <= self.bucket_n <= self.qualifying_prior_sessions:
            raise SpineError("seasonal bucket count exceeds qualifying sessions")
        for name in (
            "bucket_median",
            "phase_session_median",
            "shrink_weight",
            "seasonal_profile",
        ):
            value = getattr(self, name)
            if not isinstance(value, float) or not np.isfinite(value) or value < 0.0:
                raise SpineError(f"seasonal {name} must be finite and nonnegative")
        if not 0.0 <= self.shrink_weight <= 1.0:
            raise SpineError("seasonal shrink weight must be inside [0,1]")
        if self.seasonal_valid != (self.seasonal_status is SeasonalStatus.OK):
            raise SpineError("seasonal status and validity disagree")
        if not self.seasonal_valid and self.seasonal_profile != 0.0:
            raise SpineError("undefined seasonal rows must store numeric zero")
        if self.seasonal_status is SeasonalStatus.OK:
            if self.qualifying_prior_sessions < SEASONAL_WARMUP_SESSIONS:
                raise SpineError("defined seasonal row has insufficient history")
            if self.bucket_median_valid != (self.bucket_n > 0):
                raise SpineError("defined seasonal bucket median validity/count disagree")
            if not self.phase_session_median_valid:
                raise SpineError("defined seasonal row lacks its phase fallback")
        elif self.bucket_median_valid or self.phase_session_median_valid:
            raise SpineError("undefined seasonal row cannot expose a usable median")
        if self.calendar_version != CALENDAR_VERSION or self.calendar_sha256 != CALENDAR_SHA256:
            raise SpineError("seasonal row calendar identity differs from accepted input")
        if self.dependency_keys != tuple(sorted(set(self.dependency_keys))):
            raise SpineError("seasonal dependency keys must be unique and ordered")
        if any(session >= self.session_id for session, _ in self.dependency_keys):
            raise SpineError("seasonal dependency includes current or future session")


@dataclass(frozen=True)
class SeasonalProfileTable:
    arm_id: str
    rows: tuple[SeasonalProfileRow, ...]

    def __post_init__(self) -> None:
        if not self.rows:
            raise SpineError("seasonal profile table must be nonempty")
        keys = [
            (row.session_id, RTH_BUCKETS.index(row.observation_bucket_ct))
            for row in self.rows
        ]
        if keys != sorted(keys) or len(set(keys)) != len(keys):
            raise SpineError("seasonal rows must be unique and canonically ordered")
        if any(row.arm_id != self.arm_id for row in self.rows):
            raise SpineError("seasonal profile table mixes arm identifiers")
        object.__setattr__(
            self,
            "_by_key",
            MappingProxyType(
                {
                    (row.session_id, row.observation_bucket_ct): row
                    for row in self.rows
                }
            ),
        )

    def lookup(self, session_id: int, bucket: str) -> SeasonalProfileRow:
        try:
            return self._by_key[(session_id, bucket)]
        except KeyError as exc:
            raise SpineError(f"seasonal profile key is absent: {(session_id, bucket)!r}") from exc


def _profile_value(
    bucket_values: tuple[float, ...],
    phase_medians: tuple[float, ...],
    qualifying_count: int,
) -> tuple[float, bool, float, bool, float, float, bool, SeasonalStatus]:
    if qualifying_count < SEASONAL_WARMUP_SESSIONS:
        return 0.0, False, 0.0, False, 0.0, 0.0, False, SeasonalStatus.WARMUP
    if not phase_medians:
        return (
            0.0,
            False,
            0.0,
            False,
            0.0,
            0.0,
            False,
            SeasonalStatus.SEASONAL_FALLBACK_UNAVAILABLE,
        )
    phase_median = float(lower_median(np.asarray(phase_medians, dtype=np.float64)))
    if bucket_values:
        bucket_median = float(lower_median(np.asarray(bucket_values, dtype=np.float64)))
        bucket_valid = True
    else:
        bucket_median = 0.0
        bucket_valid = False
    n = len(bucket_values)
    if n >= SEASONAL_MIN_BUCKET_OBS:
        weight = 1.0
        profile = bucket_median
    elif n > 0:
        weight = float(np.float64(n) / np.float64(n + SEASONAL_SHRINK_K))
        profile = float(
            np.float64(
                np.float64(weight * bucket_median)
                + np.float64(np.float64(1.0 - weight) * phase_median)
            )
        )
    else:
        weight = 0.0
        profile = phase_median
    if not np.isfinite(profile) or profile < 0.0:
        raise SpineError("seasonal profile is negative or non-finite")
    if profile == 0.0:
        profile = 0.0
    return (
        bucket_median,
        bucket_valid,
        phase_median,
        True,
        weight,
        profile,
        True,
        SeasonalStatus.OK,
    )


def build_seasonal_profiles(
    scales: ScaleAnchorTable,
    current_sessions: tuple[int, ...],
    completed_sessions: frozenset[int],
    calendar: CalendarTable,
) -> SeasonalProfileTable:
    """Build all 78 causal profiles per requested current session."""
    if not isinstance(scales, ScaleAnchorTable) or not isinstance(calendar, CalendarTable):
        raise SpineError("seasonal builder requires validated scale and calendar tables")
    if (
        not current_sessions
        or tuple(sorted(current_sessions)) != current_sessions
        or len(set(current_sessions)) != len(current_sessions)
        or any(type(value) is not int for value in current_sessions)
    ):
        raise SpineError("current_sessions must be nonempty unique ascending built-in ints")
    if not isinstance(completed_sessions, frozenset) or any(
        type(value) is not int for value in completed_sessions
    ):
        raise SpineError("completed_sessions must be a frozenset of built-in ints")

    by_session_phase: dict[tuple[int, str], list[ScaleAnchorRow]] = {}
    by_session_bucket: dict[tuple[int, str], ScaleAnchorRow] = {}
    for row in scales.rows:
        by_session_phase.setdefault((row.session_id, row.session_phase), []).append(row)
        by_session_bucket[(row.session_id, row.observation_bucket_ct)] = row

    output: list[SeasonalProfileRow] = []
    ordered_completed = tuple(sorted(completed_sessions))
    for current_session in current_sessions:
        current_calendar = calendar.lookup(current_session)
        phase_context: dict[
            str, tuple[list[int], list[float], list[tuple[int, str]]]
        ] = {}
        if current_calendar is not None:
            for phase in _time_model().phase_names:
                prior_sessions: list[int] = []
                phase_medians: list[float] = []
                phase_dependency_keys: list[tuple[int, str]] = []
                for prior in ordered_completed:
                    if prior >= current_session:
                        break
                    prior_calendar = calendar.lookup(prior)
                    if (
                        prior_calendar is None
                        or not prior_calendar.seasonal_reference_eligible
                    ):
                        continue
                    phase_rows = [
                        row
                        for row in by_session_phase.get((prior, phase), ())
                        if row.scale_valid
                    ]
                    if not phase_rows:
                        continue
                    prior_sessions.append(prior)
                    phase_medians.append(
                        float(
                            lower_median(
                                np.asarray(
                                    [row.scale_value for row in phase_rows],
                                    dtype=np.float64,
                                )
                            )
                        )
                    )
                    phase_dependency_keys.extend(
                        (row.session_id, row.observation_bucket_ct)
                        for row in phase_rows
                    )
                phase_context[phase] = (
                    prior_sessions,
                    phase_medians,
                    phase_dependency_keys,
                )
        for bucket in RTH_BUCKETS:
            phase = _phase_for_bucket(bucket)
            if current_calendar is None:
                output.append(
                    SeasonalProfileRow(
                        scales.arm_id,
                        current_session,
                        bucket,
                        phase,
                        0,
                        0,
                        0.0,
                        False,
                        0.0,
                        False,
                        0.0,
                        0.0,
                        False,
                        SeasonalStatus.CALENDAR_CLASSIFICATION_MISSING,
                        CALENDAR_VERSION,
                        CALENDAR_SHA256,
                        (),
                    )
                )
                continue

            prior_sessions, phase_medians, phase_dependency_keys = phase_context[phase]

            bucket_rows = [
                by_session_bucket[(prior, bucket)]
                for prior in prior_sessions
                if (prior, bucket) in by_session_bucket
                and by_session_bucket[(prior, bucket)].scale_valid
            ]
            bucket_values = tuple(row.scale_value for row in bucket_rows)
            calculated = _profile_value(
                bucket_values,
                tuple(phase_medians),
                len(prior_sessions),
            )
            # Every bucket member is already a member of the emitted phase
            # fallback support, so the phase identity set is the exact union.
            dependencies = tuple(sorted(set(phase_dependency_keys)))
            output.append(
                SeasonalProfileRow(
                    scales.arm_id,
                    current_session,
                    bucket,
                    phase,
                    len(prior_sessions),
                    len(bucket_rows),
                    calculated[0],
                    calculated[1],
                    calculated[2],
                    calculated[3],
                    calculated[4],
                    calculated[5],
                    calculated[6],
                    calculated[7],
                    CALENDAR_VERSION,
                    CALENDAR_SHA256,
                    dependencies,
                )
            )
    return SeasonalProfileTable(scales.arm_id, tuple(output))
