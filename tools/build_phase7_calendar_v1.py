"""Build and adversarially validate the MNQ Atlas calendar candidate.

This one-time extractor is governed by ratified U10/U11.  It requires explicit
source, dependency, repository, and output roots; importing the module performs
no extraction and does not require pandas-market-calendars at runtime.  The
tool does not authorize any Phase 7 computation.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import platform
import shutil
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
PMC_ROOT = ROOT / "pandas_market_calendars-v5.4.0"
REPO = Path(r"C:\mnq-atlas")
STORE = REPO / "data" / "exploration" / "bars_5m"
OUT = ROOT / "canonical_json_candidate_v1_cli"
RAW_OUT = OUT / "raw_source_provenance"
EXTRACTION_SITE_PACKAGES = ROOT / "venv" / "Lib" / "site-packages"
np: Any = None
pd: Any = None

START = date(2019, 5, 5)
END = date(2023, 3, 29)
TZ_NAME = "America/Chicago"
TZ = ZoneInfo(TZ_NAME)
MARKET = "CME_GLOBEX_EQUITY_INDEX_FUTURES"
SOURCE_LABEL = "pandas-market-calendars:CME Globex Equities"
SOURCE_VERSION = "5.4.0"
SOURCE_COMMIT = "275890784073a3a3a347e4f05f4dc986456e6a75"
SOURCE_AS_OF = f"v{SOURCE_VERSION}@{SOURCE_COMMIT}"
CALENDAR_VERSION = "mnq-cme-equity-index-calendar-v1"
SCHEMA_VERSION = "cme-equity-index-session-calendar-v1"

TABLE_NAME = "cme_equity_index_sessions_20190506_20230329_v1.json"
MANIFEST_NAME = "cme_equity_index_sessions_20190506_20230329_v1.manifest.json"
REPORT_NAME = "cme_equity_index_sessions_20190506_20230329_v1.acceptance.json"
SOURCE_INDEX_NAME = "pandas_market_calendars_v5.4.0.source_index.json"
DEPENDENCY_LOCK_NAME = "extraction_environment.lock.json"
DISCREPANCIES_SHA256 = (
    "68325d575bd5a480fa23c11cc22dc5b1b1ecfbd0f7714cca007721e8f63df1c7"
)
LEDGER_ENTRY_ID = "phase7-cme-equity-index-calendar-v1"
LEDGER_RELATIVE_PATH = (
    "mnq_lab/ledger/calendar_entries/"
    "2026-08-01-phase7-cme-equity-index-calendar-v1.json"
)

KNOWN_DATA_DISCREPANCIES = {
    20200228: "10:00",
    20200630: "09:15",
}

FIELDS = (
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


class CandidateError(RuntimeError):
    """Fail-closed candidate or acceptance error."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    ).encode("utf-8")


def weekdays(start: date, end: date) -> list[date]:
    result: list[date] = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            result.append(cursor)
        cursor += timedelta(days=1)
    return result


def hhmm(value: pd.Timestamp) -> str:
    local = value.tz_convert(TZ_NAME)
    return f"{local.hour:02d}:{local.minute:02d}"


def local_date(value: pd.Timestamp) -> date:
    return value.tz_convert(TZ_NAME).date()


def map_rth(session_class: str, raw_close: str | None) -> tuple[str, str, str]:
    if session_class == "full_exchange_holiday":
        if raw_close is not None:
            raise CandidateError("full holiday cannot carry a raw close")
        return "full_exchange_holiday", "", ""
    if session_class == "unscheduled_closure":
        if raw_close is not None:
            raise CandidateError("unscheduled closure cannot carry a raw close")
        return "unscheduled_closure", "", ""
    if session_class not in {"regular", "scheduled_early_close"}:
        raise CandidateError(f"unmapped session class {session_class!r}")
    if raw_close is None:
        raise CandidateError(f"{session_class} requires a raw close")

    close = datetime.strptime(raw_close, "%H:%M").time()
    if session_class == "regular":
        if close != time(16, 0):
            raise CandidateError(
                f"regular raw exchange close must be 16:00, got {raw_close}"
            )
        return "full_rth", "08:30", "15:00"

    if close <= time(8, 30):
        return "no_scheduled_rth", "", ""
    if close < time(15, 0):
        return "shortened_rth", "08:30", raw_close
    if close < time(16, 0):
        return "full_rth", "08:30", "15:00"
    raise CandidateError(
        "scheduled early close at or after regular 16:00 close is inconsistent"
    )


def validate_source_mechanics(
    *,
    calendar_name: str,
    timezone: str,
    market: str,
    raw_open: str,
    raw_close: str,
    open_on_prior_calendar_day: bool,
    session_class: str,
) -> None:
    if calendar_name != "CME Globex Equities":
        raise CandidateError("A7: source is not the CME Globex Equities calendar")
    if timezone != TZ_NAME:
        raise CandidateError("A7: source timezone is not America/Chicago")
    if market != MARKET:
        raise CandidateError("A7: source product group is not CME equity index futures")
    if raw_open != "17:00":
        raise CandidateError("A7: raw exchange open is not 17:00 CT")
    if not open_on_prior_calendar_day:
        raise CandidateError("A7: raw exchange open is not on the prior calendar day")
    map_rth(session_class, raw_close)


def source_event_id(trade_date: date, session_class: str, raw_close: str) -> str:
    suffix = raw_close.replace(":", "") if raw_close else "closed"
    return (
        f"pmc-{SOURCE_VERSION}:cme-globex-equities:"
        f"{trade_date.isoformat()}:{session_class}:{suffix}"
    )


def extract_rows() -> list[dict[str, Any]]:
    import pandas_market_calendars as mcal

    if mcal.__version__ != SOURCE_VERSION:
        raise CandidateError(
            f"pandas-market-calendars version {mcal.__version__!r} != {SOURCE_VERSION!r}"
        )
    calendar = mcal.get_calendar("CME Globex Equity")
    if calendar.name != "CME Globex Equities" or str(calendar.tz) != TZ_NAME:
        raise CandidateError("wrong calendar identity or timezone")
    schedule = calendar.schedule(START.isoformat(), END.isoformat())
    by_date = {stamp.date(): row for stamp, row in schedule.iterrows()}

    rows: list[dict[str, Any]] = []
    for trade_date in weekdays(START, END):
        source_row = by_date.get(trade_date)
        if source_row is None:
            session_class = "full_exchange_holiday"
            raw_open = ""
            raw_close = ""
        else:
            raw_open = hhmm(source_row["market_open"])
            raw_close = hhmm(source_row["market_close"])
            if raw_open != "17:00":
                raise CandidateError(
                    f"{trade_date}: raw exchange open must be 17:00, got {raw_open}"
                )
            if local_date(source_row["market_open"]) != trade_date - timedelta(days=1):
                raise CandidateError(f"{trade_date}: raw open is not on prior calendar day")
            if local_date(source_row["market_close"]) != trade_date:
                raise CandidateError(f"{trade_date}: raw close is not on trade date")
            session_class = (
                "regular" if raw_close == "16:00" else "scheduled_early_close"
            )
            validate_source_mechanics(
                calendar_name=calendar.name,
                timezone=str(calendar.tz),
                market=MARKET,
                raw_open=raw_open,
                raw_close=raw_close,
                open_on_prior_calendar_day=True,
                session_class=session_class,
            )

        rth_status, rth_open, rth_close = map_rth(
            session_class, raw_close or None
        )
        rows.append(
            {
                "trade_date": int(trade_date.strftime("%Y%m%d")),
                "market": MARKET,
                "session_class": session_class,
                "scheduled_rth_status": rth_status,
                "scheduled_rth_open_ct": rth_open,
                "scheduled_rth_close_ct": rth_close,
                "raw_exchange_open_ct": raw_open,
                "raw_exchange_close_ct": raw_close,
                "holiday_adjacent": False,
                "source_event_id": source_event_id(
                    trade_date, session_class, raw_close
                ),
                "source_label": SOURCE_LABEL,
                "source_as_of": SOURCE_AS_OF,
                "calendar_version": CALENDAR_VERSION,
                "schema_version": SCHEMA_VERSION,
            }
        )

    active_indices = [
        index
        for index, row in enumerate(rows)
        if row["session_class"] != "full_exchange_holiday"
    ]
    active_position = {row_index: position for position, row_index in enumerate(active_indices)}
    special_indices = [
        index
        for index, row in enumerate(rows)
        if row["session_class"] in {"full_exchange_holiday", "scheduled_early_close"}
    ]
    for index in special_indices:
        before = [candidate for candidate in active_indices if candidate < index]
        after = [candidate for candidate in active_indices if candidate > index]
        if before:
            rows[before[-1]]["holiday_adjacent"] = True
        if after:
            rows[after[0]]["holiday_adjacent"] = True
    del active_position
    return rows


def validate_table(rows: list[dict[str, Any]]) -> None:
    expected_dates = [int(value.strftime("%Y%m%d")) for value in weekdays(START, END)]
    actual_dates = [int(row["trade_date"]) for row in rows]
    if actual_dates != expected_dates:
        raise CandidateError("A2: candidate dates are not the exact ordered weekday grid")
    if len(actual_dates) != len(set(actual_dates)):
        raise CandidateError("A2: duplicate trade date")
    for row in rows:
        if tuple(row) != FIELDS:
            raise CandidateError("candidate row schema/order differs from frozen schema")
        if row["market"] != MARKET:
            raise CandidateError("A7: wrong product group")
        if row["source_as_of"] != SOURCE_AS_OF:
            raise CandidateError("source pin differs")
        expected = map_rth(
            str(row["session_class"]),
            str(row["raw_exchange_close_ct"]) or None,
        )
        actual = (
            row["scheduled_rth_status"],
            row["scheduled_rth_open_ct"],
            row["scheduled_rth_close_ct"],
        )
        if actual != expected:
            raise CandidateError(f"A7: non-total RTH mapping for {row['trade_date']}")
        if row["session_class"] in {"regular", "scheduled_early_close"}:
            if row["raw_exchange_open_ct"] != "17:00":
                raise CandidateError("A7: wrong raw exchange open")
        elif row["raw_exchange_open_ct"] or row["raw_exchange_close_ct"]:
            raise CandidateError("closure unexpectedly carries exchange times")


@dataclass(frozen=True)
class ObservedSession:
    trade_date: int
    final_end_ct: str
    final_rth_end_ct: str | None


def load_observed_sessions() -> dict[int, ObservedSession]:
    manifest_path = STORE / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["corpus"] != "exploration" or manifest["frequency"] != "5m":
        raise CandidateError("exploration store identity mismatch")
    if manifest["bar_seconds"] != 300 or manifest["row_count"] != 274847:
        raise CandidateError("exploration store shape mismatch")
    for name in ("ts_event_ns", "session_id"):
        record = manifest["columns"][name]
        path = STORE / record["file"]
        if sha256(path) != record["sha256"]:
            raise CandidateError(f"store hash mismatch for {name}")

    timestamps = np.load(STORE / "ts_event_ns.npy", mmap_mode="r")
    session_ids = np.load(STORE / "session_id.npy", mmap_mode="r")
    if timestamps.dtype != np.dtype("int64") or session_ids.dtype != np.dtype("int32"):
        raise CandidateError("store dtype mismatch")
    if timestamps.ndim != 1 or session_ids.ndim != 1 or len(timestamps) != len(session_ids):
        raise CandidateError("store column shape mismatch")
    if not np.all(timestamps[1:] > timestamps[:-1]):
        raise CandidateError("store timestamps are not strictly increasing")

    in_scope = (session_ids >= 20190506) & (session_ids <= 20230329)
    scoped_ts = np.asarray(timestamps[in_scope], dtype=np.int64)
    scoped_sessions = np.asarray(session_ids[in_scope], dtype=np.int32)
    ends = pd.to_datetime(scoped_ts + 300_000_000_000, unit="ns", utc=True).tz_convert(TZ_NAME)
    result: dict[int, ObservedSession] = {}
    for session_id in np.unique(scoped_sessions):
        mask = scoped_sessions == session_id
        local_ends = ends[mask]
        final_end = local_ends[-1]
        if final_end.strftime("%Y%m%d") != str(int(session_id)):
            raise CandidateError(f"session {session_id} final bar ends on wrong CT date")
        rth = local_ends[
            (local_ends.time >= time(8, 30)) & (local_ends.time <= time(15, 0))
        ]
        result[int(session_id)] = ObservedSession(
            trade_date=int(session_id),
            final_end_ct=final_end.strftime("%H:%M"),
            final_rth_end_ct=None if len(rth) == 0 else rth[-1].strftime("%H:%M"),
        )
    return result


def validate_against_observations(
    rows: list[dict[str, Any]], observed: dict[int, ObservedSession]
) -> dict[str, Any]:
    regular_matches: list[int] = []
    regular_discrepancies: dict[int, dict[str, str]] = {}
    timed_early_matches: list[int] = []
    no_rth_matches: list[int] = []
    full_closure_matches: list[int] = []

    for row in rows:
        trade_date = int(row["trade_date"])
        candidate_class = row["session_class"]
        actual = observed.get(trade_date)
        if candidate_class == "regular":
            if actual is None:
                raise CandidateError(f"A3a-regular: regular date {trade_date} is absent")
            if actual.final_end_ct == "16:00":
                regular_matches.append(trade_date)
            elif KNOWN_DATA_DISCREPANCIES.get(trade_date) == actual.final_end_ct:
                regular_discrepancies[trade_date] = {
                    "calendar_class": "regular",
                    "observed_final_end_ct": actual.final_end_ct,
                    "data_quality_status": "unresolved_truncated_session",
                }
            else:
                raise CandidateError(
                    f"A3a-regular: unregistered discrepancy {trade_date} "
                    f"ended {actual.final_end_ct}"
                )
        elif candidate_class == "scheduled_early_close":
            if actual is None:
                raise CandidateError(f"A3a: early close {trade_date} is absent")
            raw_close = row["raw_exchange_close_ct"]
            if actual.final_end_ct != raw_close:
                raise CandidateError(
                    f"A3a-exchange-time: {trade_date} expected {raw_close}, "
                    f"observed {actual.final_end_ct}"
                )
            if row["scheduled_rth_status"] == "no_scheduled_rth":
                if actual.final_rth_end_ct is not None:
                    raise CandidateError(f"A3a-RTH: {trade_date} unexpectedly has RTH")
                no_rth_matches.append(trade_date)
            else:
                if actual.final_rth_end_ct != row["scheduled_rth_close_ct"]:
                    raise CandidateError(
                        f"A3a-RTH: {trade_date} projected "
                        f"{row['scheduled_rth_close_ct']}, observed {actual.final_rth_end_ct}"
                    )
                timed_early_matches.append(trade_date)
        elif candidate_class == "full_exchange_holiday":
            if actual is not None:
                raise CandidateError(
                    f"A6: full closure {trade_date} has an observed session"
                )
            full_closure_matches.append(trade_date)
        elif candidate_class == "unscheduled_closure":
            raise CandidateError(
                "unscheduled closure may appear only when explicitly identified by authority"
            )
        else:
            raise CandidateError(f"unmapped candidate class {candidate_class!r}")

    candidate_dates = {int(row["trade_date"]) for row in rows}
    if set(observed) - candidate_dates:
        raise CandidateError("A2: observed session exists outside candidate weekday support")
    if set(regular_discrepancies) != set(KNOWN_DATA_DISCREPANCIES):
        raise CandidateError("A3b: registered discrepancy set differs")
    if len(observed) != 1009:
        raise CandidateError(f"observed session count {len(observed)} != 1009")
    if (
        len(regular_matches),
        len(timed_early_matches),
        len(no_rth_matches),
        len(full_closure_matches),
        len(regular_discrepancies),
    ) != (974, 32, 1, 9, 2):
        raise CandidateError("U10 support accounting differs")

    return {
        "a3a_regular_matches": regular_matches,
        "a3a_timed_early_close_matches": timed_early_matches,
        "a3a_no_scheduled_rth_structural_matches": no_rth_matches,
        "a3b_registered_data_quality_discrepancies": {
            str(key): value for key, value in regular_discrepancies.items()
        },
        "a6_full_closure_absent_weekday_matches": full_closure_matches,
        "corroborating_cells": 1016,
        "explicit_discrepancies": 2,
        "weekday_cells": 1018,
        "observed_sessions": 1009,
    }


def expect_failure(name: str, callback, expected: str) -> dict[str, str]:
    try:
        callback()
    except CandidateError as exc:
        message = str(exc)
        if expected not in message:
            raise CandidateError(
                f"negative {name!r} failed for wrong reason: {message!r}"
            ) from exc
        return {"mutation": name, "status": "killed", "message": message}
    raise CandidateError(f"negative {name!r} survived")


def execute_negative_battery(
    rows: list[dict[str, Any]], observed: dict[int, ObservedSession]
) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []

    def missing_date() -> None:
        validate_table(rows[:-1])

    results.append(expect_failure("a2_missing_date", missing_date, "A2"))

    def regular_time_mutation() -> None:
        changed = dict(observed)
        target = next(
            int(row["trade_date"])
            for row in rows
            if row["session_class"] == "regular"
            and int(row["trade_date"]) not in KNOWN_DATA_DISCREPANCIES
        )
        changed[target] = ObservedSession(target, "15:55", "15:00")
        validate_against_observations(rows, changed)

    results.append(
        expect_failure(
            "a3a_regular_final_end_1555", regular_time_mutation, "A3a-regular"
        )
    )

    def early_time_mutation() -> None:
        changed = deepcopy(rows)
        target = next(
            row
            for row in changed
            if row["session_class"] == "scheduled_early_close"
            and row["raw_exchange_close_ct"] == "12:15"
        )
        target["raw_exchange_close_ct"] = "12:00"
        target["scheduled_rth_close_ct"] = "12:00"
        validate_against_observations(changed, observed)

    results.append(
        expect_failure(
            "a3a_early_close_1215_to_1200", early_time_mutation, "A3a-exchange-time"
        )
    )

    def missing_discrepancy_registration() -> None:
        saved = KNOWN_DATA_DISCREPANCIES.pop(20200228)
        try:
            validate_against_observations(rows, observed)
        finally:
            KNOWN_DATA_DISCREPANCIES[20200228] = saved

    results.append(
        expect_failure(
            "a3b_remove_registered_discrepancy",
            missing_discrepancy_registration,
            "A3a-regular",
        )
    )

    def false_full_closure() -> None:
        changed = deepcopy(rows)
        target = next(row for row in changed if row["session_class"] == "regular")
        target["session_class"] = "full_exchange_holiday"
        target["scheduled_rth_status"] = "full_exchange_holiday"
        target["scheduled_rth_open_ct"] = ""
        target["scheduled_rth_close_ct"] = ""
        target["raw_exchange_open_ct"] = ""
        target["raw_exchange_close_ct"] = ""
        validate_against_observations(changed, observed)

    results.append(expect_failure("a6_false_full_closure", false_full_closure, "A6"))

    for mutation, session_class, raw_close, expected in (
        ("a7_raw_regular_close_1500", "regular", "15:00", "regular raw exchange close"),
        ("a7_raw_regular_close_1700", "regular", "17:00", "regular raw exchange close"),
        ("a7_early_close_at_1600", "scheduled_early_close", "16:00", "inconsistent"),
        ("a7_unknown_class", "cash_equity", "16:00", "unmapped session class"),
    ):
        results.append(
            expect_failure(
                mutation,
                lambda sc=session_class, rc=raw_close: map_rth(sc, rc),
                expected,
            )
        )

    if map_rth("scheduled_early_close", "15:30") != (
        "full_rth",
        "08:30",
        "15:00",
    ):
        raise CandidateError("A7 15:30 total-mapping fixture failed")
    results.append(
        {
            "mutation": "a7_early_close_1530_total_mapping",
            "status": "classified",
            "message": "scheduled early close at 15:30 maps to full_rth",
        }
    )

    source_defaults = {
        "calendar_name": "CME Globex Equities",
        "timezone": TZ_NAME,
        "market": MARKET,
        "raw_open": "17:00",
        "raw_close": "16:00",
        "open_on_prior_calendar_day": True,
        "session_class": "regular",
    }
    for mutation, changed_key, changed_value, expected in (
        ("a7_wrong_timezone", "timezone", "America/New_York", "timezone"),
        ("a7_wrong_raw_open", "raw_open", "18:00", "raw exchange open"),
        (
            "a7_same_day_open",
            "open_on_prior_calendar_day",
            False,
            "prior calendar day",
        ),
        (
            "a7_non_equity_product",
            "market",
            "CME_GLOBEX_INTEREST_RATE_FUTURES",
            "product group",
        ),
        (
            "a7_generic_calendar",
            "calendar_name",
            "CME Globex",
            "CME Globex Equities",
        ),
    ):
        arguments = dict(source_defaults)
        arguments[changed_key] = changed_value
        results.append(
            expect_failure(
                mutation,
                lambda values=arguments: validate_source_mechanics(**values),
                expected,
            )
        )
    return results


def write_canonical_table(rows: list[dict[str, Any]], path: Path) -> None:
    document = {
        "calendar_version": CALENDAR_VERSION,
        "columns": list(FIELDS),
        "rows": [[row[field] for field in FIELDS] for row in rows],
        "schema_version": SCHEMA_VERSION,
    }
    path.write_bytes(canonical_json_bytes(document))


def source_tree_sha256(records: list[dict[str, Any]]) -> str:
    material = b"".join(
        (
            f"{record['original_path']}\0{record['bytes']}\0{record['sha256']}\n"
        ).encode("utf-8")
        for record in records
    )
    return hashlib.sha256(material).hexdigest()


def retain_raw_source() -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    package_root = PMC_ROOT / "pandas_market_calendars"
    source_files = sorted(package_root.rglob("*.py"))
    if len(source_files) != 47:
        raise CandidateError(
            f"complete package source must contain 47 .py files, got {len(source_files)}"
        )
    for source in source_files:
        relative = source.relative_to(PMC_ROOT).as_posix()
        stored_relative = f"{relative}.txt"
        target = RAW_OUT / stored_relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if source.read_bytes() != target.read_bytes():
            raise CandidateError(f"raw source copy differs for {relative}")
        records.append(
            {
                "original_path": relative,
                "stored_path": f"raw_source_provenance/{stored_relative}",
                "bytes": target.stat().st_size,
                "sha256": sha256(target),
                "retrieval_date": "2026-08-01",
                "retrieval_method": "pinned shallow Git tag checkout",
            }
        )

    evidence = (
        (PMC_ROOT / ".git" / "HEAD", "git_HEAD.txt", ".git/HEAD"),
        (
            PMC_ROOT / ".git" / "packed-refs",
            "git_packed_refs.txt",
            ".git/packed-refs",
        ),
        (PMC_ROOT / "LICENSE", "LICENSE.txt", "LICENSE"),
        (PMC_ROOT / "pyproject.toml", "pyproject.toml.txt", "pyproject.toml"),
    )
    evidence_records: list[dict[str, Any]] = []
    for source, stored_name, original_path in evidence:
        target = RAW_OUT / stored_name
        shutil.copyfile(source, target)
        if source.read_bytes() != target.read_bytes():
            raise CandidateError(f"provenance copy differs for {original_path}")
        evidence_records.append(
            {
                "original_path": original_path,
                "stored_path": f"raw_source_provenance/{stored_name}",
                "bytes": target.stat().st_size,
                "sha256": sha256(target),
                "retrieval_date": "2026-08-01",
                "retrieval_method": "pinned shallow Git tag checkout",
            }
        )

    tree_hash = source_tree_sha256(records)
    source_index = {
        "complete_package_python_file_count": len(records),
        "files": records,
        "hash_material": "UTF-8 original_path + NUL + decimal bytes + NUL + lowercase sha256 + LF, in original_path order",
        "package": "pandas_market_calendars",
        "release": SOURCE_VERSION,
        "source_commit": SOURCE_COMMIT,
        "stored_files_are_inert": True,
        "stored_suffix": ".py.txt",
        "tree_sha256": tree_hash,
    }
    index_path = RAW_OUT / SOURCE_INDEX_NAME
    index_path.write_bytes(canonical_json_bytes(source_index))

    distributions = sorted(
        (
            {
                "name": distribution.metadata["Name"],
                "version": distribution.version,
            }
            for distribution in importlib.metadata.distributions(
                path=[str(EXTRACTION_SITE_PACKAGES)]
            )
            if distribution.metadata["Name"]
        ),
        key=lambda item: (item["name"].lower(), item["version"]),
    )
    lock = {
        "dependencies": distributions,
        "environment_role": "external one-time extraction environment; not the MNQ Atlas runtime",
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "pandas_market_calendars": SOURCE_VERSION,
        "platform": platform.platform(),
        "python": platform.python_version(),
    }
    lock_path = RAW_OUT / DEPENDENCY_LOCK_NAME
    lock_path.write_bytes(canonical_json_bytes(lock))

    return {
        "evidence_files": evidence_records,
        "package_file_count": len(records),
        "source_index": {
            "path": f"raw_source_provenance/{SOURCE_INDEX_NAME}",
            "bytes": index_path.stat().st_size,
            "sha256": sha256(index_path),
        },
        "dependency_lock": {
            "path": f"raw_source_provenance/{DEPENDENCY_LOCK_NAME}",
            "bytes": lock_path.stat().st_size,
            "sha256": sha256(lock_path),
        },
        "tree_sha256": tree_hash,
    }


def validate_retained_raw_source(
    provenance: dict[str, Any], *, mutate_first: bool = False
) -> None:
    index_path = OUT / provenance["source_index"]["path"]
    index = json.loads(index_path.read_text(encoding="utf-8"))
    records = index["files"]
    for position, record in enumerate(records):
        path = OUT / record["stored_path"]
        payload = path.read_bytes()
        if mutate_first and position == 0:
            payload += b"mutation"
        if (
            len(payload) != record["bytes"]
            or hashlib.sha256(payload).hexdigest() != record["sha256"]
        ):
            raise CandidateError(
                f"A1: retained raw bytes differ for {record['stored_path']}"
            )
    if source_tree_sha256(records) != provenance["tree_sha256"]:
        raise CandidateError("A1: retained source tree hash differs")


def main() -> None:
    if OUT.exists():
        raise CandidateError(f"output directory already exists: {OUT}")
    OUT.mkdir(parents=True)
    RAW_OUT.mkdir()

    rows = extract_rows()
    validate_table(rows)
    observed = load_observed_sessions()
    support = validate_against_observations(rows, observed)
    negatives = execute_negative_battery(rows, observed)

    table_path = OUT / TABLE_NAME
    write_canonical_table(rows, table_path)
    source_provenance = retain_raw_source()
    validate_retained_raw_source(source_provenance)
    negatives.append(
        expect_failure(
            "a1_corrupt_retained_source_bytes",
            lambda: validate_retained_raw_source(
                source_provenance, mutate_first=True
            ),
            "A1",
        )
    )
    extractor_path = OUT / "build_phase7_calendar_v1.py"
    shutil.copyfile(Path(__file__), extractor_path)

    manifest = {
        "artifact": {
            "path": TABLE_NAME,
            "bytes": table_path.stat().st_size,
            "sha256": sha256(table_path),
            "rows": len(rows),
            "columns": list(FIELDS),
            "dtypes_and_encodings": {
                "trade_date": "int32 YYYYMMDD",
                "holiday_adjacent": "JSON boolean",
                "all_other_columns": "UTF-8 strings; missing time is an empty string",
            },
            "format": "canonical sorted-key UTF-8 JSON with LF and one terminal newline; rows are arrays interpreted by columns",
        },
        "calendar_version": CALENDAR_VERSION,
        "coverage": {
            "declared_start_inclusive": START.isoformat(),
            "first_weekday": "2019-05-06",
            "end_inclusive": END.isoformat(),
            "weekday_rows": len(rows),
        },
        "extraction": {
            "method": "one-time static extraction from pinned Python source",
            "machine_bound_store_path_in_extractor": True,
            "retrieval_date": "2026-08-01",
            "runtime_import_forbidden": True,
            "script": {
                "path": extractor_path.name,
                "bytes": extractor_path.stat().st_size,
                "sha256": sha256(extractor_path),
            },
        },
        "environment": {
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "pandas_market_calendars": SOURCE_VERSION,
            "platform": platform.platform(),
            "python": platform.python_version(),
            "semantic_determinism_required_across_environments": True,
            "raw_byte_identity_claimed_only_for_matching_environment": True,
            "lab_environment": {
                "numpy": "2.2.3",
                "pandas": "3.0.1",
                "pandas_market_calendars": "deliberately absent",
            },
            "extraction_environment_differs_from_lab": True,
        },
        "external_derived_csv_not_committed": {
            "bytes": 310911,
            "sha256": "e06247ed02688e9af71ef9d4e147331b491f7619ec16bc81c709624418b0cef5",
        },
        "field_semantics": {
            "holiday_adjacent": "true for the immediately preceding and immediately following scheduled trading session around each full holiday or scheduled early close",
            "source_as_of": "pinned release and upstream commit, not an event publication date",
            "source_event_id": "deterministic extracted-row identifier; pandas-market-calendars exposes no upstream notice identifier",
        },
        "licensing": {
            "license": "MIT",
            "storage": "local-only on a non-pushed branch",
            "user_asserted_cme_license_authorization": "recorded separately under U8; not needed for permissively licensed Route B source",
        },
        "market": MARKET,
        "governance": {
            "discrepancies_path": "docs/DISCREPANCIES.md",
            "discrepancies_sha256_after_d19": DISCREPANCIES_SHA256,
            "ledger_entry_id": LEDGER_ENTRY_ID,
            "ledger_relative_path": LEDGER_RELATIVE_PATH,
            "phase7_production_authorized": False,
        },
        "program_id": "mnq-atlas-001",
        "source_provenance": source_provenance,
        "source_retention_limit": "complete pinned pandas_market_calendars Python package source is retained as inert .py.txt provenance; external interpreter dependencies are version-locked but not vendored, so the bundle is not claimed to be hermetic",
        "schema_version": SCHEMA_VERSION,
        "source": {
            "calendar": "CME Globex Equity",
            "calendar_name": "CME Globex Equities",
            "commit": SOURCE_COMMIT,
            "name": "pandas-market-calendars",
            "release": SOURCE_VERSION,
            "upstream": "https://github.com/rsheftel/pandas_market_calendars",
        },
        "timezone": TZ_NAME,
    }
    manifest_path = OUT / MANIFEST_NAME
    manifest_path.write_bytes(canonical_json_bytes(manifest))

    report = {
        "a1_raw_source_hashes": {
            "status": "passed",
            "source_provenance": source_provenance,
        },
        "a2_coverage": {
            "status": "passed",
            "weekday_rows": len(rows),
            "unique_trade_dates": len({row["trade_date"] for row in rows}),
        },
        "a3_and_a6_observational_battery": {
            "status": "passed_with_two_registered_data_quality_discrepancies",
            **support,
        },
        "a4_preregistered_known_dates": {
            "status": "ordering_violated_not_claimed",
            "reason": "candidate extraction preceded hand-specified expectations",
            "substitute_evidence": "A3/A6 exhaustive observational corroboration; correlated within mechanics; corroboration not proof",
        },
        "a5_calendar_import_boundary": {
            "status": "deferred_pending_explicit_xfail_and_dependent_code_gate",
            "reason": "real EWMA and MAD modules do not yet exist; U11 requires an explicit pending xfail now and a non-vacuous conversion before dependent computation",
        },
        "a7_product_and_time_mapping": {
            "status": "passed",
            "market": MARKET,
            "timezone": TZ_NAME,
            "raw_regular_open_ct": "17:00 prior calendar day",
            "raw_regular_close_ct": "16:00 trade date",
            "study_rth": "[08:30, min(raw close, 15:00)) CT",
        },
        "artifact": {
            "table": {
                "path": TABLE_NAME,
                "bytes": table_path.stat().st_size,
                "sha256": sha256(table_path),
            },
            "manifest": {
                "path": MANIFEST_NAME,
                "bytes": manifest_path.stat().st_size,
                "sha256": sha256(manifest_path),
            },
            "extractor": {
                "path": extractor_path.name,
                "bytes": extractor_path.stat().st_size,
                "sha256": sha256(extractor_path),
            },
        },
        "calendar_acceptance": "pending_committed_artifact_audit",
        "evidence_limit": "1,016 corroborating cells across five observable mechanics, strongly correlated within mechanic; approximately eight to ten holiday-rule families; corroboration, not proof",
        "negative_controls": negatives,
        "single_source_residual": [
            "holiday-adjacent flags have no independent time signature",
            "a purported full closure can coincide with vendor absence",
        ],
        "known_limits": [
            "calendar acceptance is single-source corroboration, not proof of every exchange classification",
            "no seasonal profile or Phase 7 result has been computed",
            "the retained source tree is inert provenance and is not a runtime dependency",
        ],
        "u10": "ratified_as_amended_with_a5",
    }
    report_path = OUT / REPORT_NAME
    report_path.write_bytes(canonical_json_bytes(report))

    print(
        json.dumps(
            {
                "output": str(OUT),
                "table": report["artifact"]["table"],
                "manifest": report["artifact"]["manifest"],
                "acceptance_report": {
                    "path": REPORT_NAME,
                    "bytes": report_path.stat().st_size,
                    "sha256": sha256(report_path),
                },
                "support": support,
                "killed_negative_controls": sum(
                    item["status"] == "killed" for item in negatives
                ),
                "positive_total_mapping_fixtures": sum(
                    item["status"] == "classified" for item in negatives
                ),
                "calendar_acceptance": report["calendar_acceptance"],
            },
            sort_keys=True,
            indent=2,
        )
    )


def configure_paths(
    *,
    source_root: Path,
    site_packages: Path,
    repo_root: Path,
    output_root: Path,
) -> None:
    global PMC_ROOT, EXTRACTION_SITE_PACKAGES, REPO, STORE, OUT, RAW_OUT, np, pd
    PMC_ROOT = source_root.resolve(strict=True)
    EXTRACTION_SITE_PACKAGES = site_packages.resolve(strict=True)
    REPO = repo_root.resolve(strict=True)
    STORE = REPO / "data" / "exploration" / "bars_5m"
    if not STORE.is_dir():
        raise CandidateError(f"exploration store is absent: {STORE}")
    OUT = output_root.resolve(strict=False)
    RAW_OUT = OUT / "raw_source_provenance"
    sys.path.insert(0, str(EXTRACTION_SITE_PACKAGES))
    sys.path.insert(0, str(PMC_ROOT))
    np = importlib.import_module("numpy")
    pd = importlib.import_module("pandas")


def cli_main() -> None:
    parser = argparse.ArgumentParser(
        description="One-time build of the pinned MNQ Atlas calendar input"
    )
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--site-packages", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    arguments = parser.parse_args()
    configure_paths(
        source_root=arguments.source_root,
        site_packages=arguments.site_packages,
        repo_root=arguments.repo_root,
        output_root=arguments.output_root,
    )
    main()


if __name__ == "__main__":
    cli_main()
