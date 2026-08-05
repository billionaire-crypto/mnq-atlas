"""The accepted immutable CME equity-index calendar, in the neutral layer.

Moved here from ``mnq_lab/conditioners/calendar.py`` at Stage 3 of the D32/D33
repair. The outcome layer needs per-session scheduled closes and must not import
``conditioners`` (spec responsibility boundaries), so the single canonical loader
lives in ``spine`` and ``conditioners.calendar`` re-exports it. There is one
implementation, not two.

The loader accepts no caller path and verifies the byte-pinned SHA-256, so no
consumer can substitute a different calendar.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType

from mnq_lab import SpineError
from mnq_lab.constants import REPO_ROOT

__all__ = [
    "CALENDAR_SHA256",
    "CALENDAR_VERSION",
    "SCHEMA_VERSION",
    "CalendarRow",
    "CalendarTable",
    "load_accepted_calendar",
]

CALENDAR_SHA256 = "b86e112c16112bf11a6a548ca8b3f21d28a08f90442b4dde84098f9d3f6eb069"
CALENDAR_VERSION = "mnq-cme-equity-index-calendar-v1"
SCHEMA_VERSION = "cme-equity-index-session-calendar-v1"
_CALENDAR_PATH = (
    REPO_ROOT
    / "mnq_lab"
    / "spine"
    / "calendar_inputs"
    / "cme_equity_index_v1"
    / "cme_equity_index_sessions_20190506_20230329_v1.json"
)
_COLUMNS = (
    "trade_date",
    "market",
    "session_class",
    "scheduled_rth_status",
    "scheduled_rth_open_ct",
    "scheduled_rth_close_ct",
    "raw_exchange_open_ct",
    "raw_exchange_close_ct",
    "holiday_adjacent",
    "source_event_id",
    "source_label",
    "source_as_of",
    "calendar_version",
    "schema_version",
)
_SESSION_CLASSES = {
    "regular",
    "scheduled_early_close",
    "full_exchange_holiday",
    "unscheduled_closure",
}
_RTH_STATUSES = {
    "full_rth",
    "shortened_rth",
    "no_scheduled_rth",
    "full_exchange_holiday",
}


@dataclass(frozen=True)
class CalendarRow:
    trade_date: int
    market: str
    session_class: str
    scheduled_rth_status: str
    scheduled_rth_open_ct: str
    scheduled_rth_close_ct: str
    raw_exchange_open_ct: str
    raw_exchange_close_ct: str
    holiday_adjacent: bool
    source_event_id: str
    source_label: str
    source_as_of: str
    calendar_version: str
    schema_version: str

    def __post_init__(self) -> None:
        if type(self.trade_date) is not int or not 20100101 <= self.trade_date <= 20991231:
            raise SpineError("calendar trade_date must be an int32-like YYYYMMDD")
        if self.market != "CME_GLOBEX_EQUITY_INDEX_FUTURES":
            raise SpineError("calendar market is not CME Globex equity-index futures")
        if self.session_class not in _SESSION_CLASSES:
            raise SpineError(f"unknown calendar session_class {self.session_class!r}")
        if self.scheduled_rth_status not in _RTH_STATUSES:
            raise SpineError(
                f"unknown calendar scheduled_rth_status {self.scheduled_rth_status!r}"
            )
        if type(self.holiday_adjacent) is not bool:
            raise SpineError("calendar holiday_adjacent must be bool")
        if self.calendar_version != CALENDAR_VERSION or self.schema_version != SCHEMA_VERSION:
            raise SpineError("calendar row version differs from the accepted input")
        for name in ("source_event_id", "source_label", "source_as_of"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise SpineError(f"calendar {name} must be nonempty")

        times = (
            self.scheduled_rth_open_ct,
            self.scheduled_rth_close_ct,
            self.raw_exchange_open_ct,
            self.raw_exchange_close_ct,
        )
        if self.session_class == "full_exchange_holiday":
            if self.scheduled_rth_status != "full_exchange_holiday" or any(times):
                raise SpineError("full holiday calendar row has inconsistent times/status")
        elif self.scheduled_rth_status == "no_scheduled_rth":
            if self.scheduled_rth_open_ct or self.scheduled_rth_close_ct:
                raise SpineError("no-scheduled-RTH row must have empty RTH times")
            if not self.raw_exchange_open_ct or not self.raw_exchange_close_ct:
                raise SpineError("active calendar row must retain raw exchange times")
        else:
            if not all(times):
                raise SpineError("active RTH calendar row must have all time fields")

    @property
    def seasonal_reference_eligible(self) -> bool:
        return self.session_class not in {
            "full_exchange_holiday",
            "scheduled_early_close",
        }


@dataclass(frozen=True)
class CalendarTable:
    rows: tuple[CalendarRow, ...]

    def __post_init__(self) -> None:
        if not self.rows:
            raise SpineError("calendar table must be nonempty")
        dates = [row.trade_date for row in self.rows]
        if dates != sorted(dates) or len(set(dates)) != len(dates):
            raise SpineError("calendar trade dates must be unique and strictly ordered")
        object.__setattr__(
            self,
            "_by_date",
            MappingProxyType({row.trade_date: row for row in self.rows}),
        )

    @property
    def first_trade_date(self) -> int:
        return self.rows[0].trade_date

    @property
    def last_trade_date(self) -> int:
        return self.rows[-1].trade_date

    def lookup(self, trade_date: int) -> CalendarRow | None:
        if type(trade_date) is not int:
            raise SpineError("calendar lookup trade_date must be a built-in int")
        row = self._by_date.get(trade_date)
        if row is None and self.first_trade_date <= trade_date <= self.last_trade_date:
            raise SpineError(f"accepted calendar is missing in-range trade date {trade_date}")
        return row


def _canonical_bytes(value) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    ).encode("utf-8")


@lru_cache(maxsize=1)
def load_accepted_calendar() -> CalendarTable:
    """Load only the byte-pinned accepted calendar; accepts no caller path."""
    payload = _CALENDAR_PATH.read_bytes()
    if hashlib.sha256(payload).hexdigest() != CALENDAR_SHA256:
        raise SpineError("accepted calendar SHA-256 differs from the ratified input")
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpineError(f"accepted calendar is not canonical UTF-8 JSON: {exc}") from exc
    if payload != _canonical_bytes(document):
        raise SpineError("accepted calendar JSON bytes are not canonical")
    if tuple(document.get("columns", ())) != _COLUMNS:
        raise SpineError("accepted calendar column order differs from the contract")
    if document.get("calendar_version") != CALENDAR_VERSION:
        raise SpineError("accepted calendar version differs from the contract")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise SpineError("accepted calendar schema differs from the contract")
    raw_rows = document.get("rows")
    if not isinstance(raw_rows, list):
        raise SpineError("accepted calendar rows must be a list")
    try:
        rows = tuple(
            CalendarRow(**dict(zip(_COLUMNS, values, strict=True)))
            for values in raw_rows
        )
    except (TypeError, ValueError) as exc:
        raise SpineError(f"accepted calendar row shape is invalid: {exc}") from exc
    table = CalendarTable(rows)
    if table.first_trade_date != 20190506 or table.last_trade_date != 20230329:
        raise SpineError("accepted calendar coverage differs from the ratified range")
    if len(table.rows) != 1018:
        raise SpineError("accepted calendar must contain exactly 1,018 weekday rows")
    return table
