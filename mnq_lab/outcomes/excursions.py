"""Calendar-independent causal excursion outcomes (Unit O).

The anchor is observed at ``tau`` and is labelled ``tau - 5 minutes``.  Its
close is the reference price.  Future extrema use only exact bar-open labels in
the half-open interval ``[tau, tau + horizon)``.  This module consumes neither
conditioner assignments nor an exchange-reference calendar.
"""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral, Real
from types import MappingProxyType
from typing import Mapping

import numpy as np

from mnq_lab import SpineError
from mnq_lab.constants import Constants, load_constants
from mnq_lab.core.causality import required_interval_starts
from mnq_lab.spine.availability import (
    REASON_NOT_APPLICABLE,
    UNAVAILABILITY_REASONS,
    SessionScheduleTable,
    outcome_window_structurally_available,
)
from mnq_lab.spine.exploration import validate_exploration_store
from mnq_lab.spine.seal import assert_exploration_safe
from mnq_lab.spine.store import BarStore
from mnq_lab.spine.timemodel import (
    BAR_MINUTES,
    BAR_NS,
    TimeModel,
    assert_store_bar_seconds,
)

ESTIMAND_FULLY_LABELED = "fully_labeled_1m_grid"
ESTIMAND_OBSERVED = "observed_bar_path"
ESTIMAND_ORDER = (ESTIMAND_FULLY_LABELED, ESTIMAND_OBSERVED)

STATUS_ANCHOR_BAR_MISSING = "anchor_bar_missing"
# D32: renamed from window_outside_rth. That name asserted the window left RTH,
# which is false for a scheduled early close (RTH ended earlier than 15:00) and
# actively false for an intraday interruption (RTH did not end at all). The
# reason lives in its own closed column, so the status axis stays stable while
# reasons can be added under version control. 24 chars: fits the <U25 dtype.
STATUS_STRUCTURALLY_UNAVAILABLE = "structurally_unavailable"
STATUS_PATH_TIMESTAMP_MISSING = "path_timestamp_missing"
STATUS_PATH_SESSION_MISMATCH = "path_session_mismatch"
STATUS_PATH_SYMBOL_MISMATCH = "path_symbol_mismatch"
STATUS_INSUFFICIENT_COMPONENTS = "insufficient_components"
STATUS_OK = "ok"
OUTCOME_STATUSES = (
    STATUS_ANCHOR_BAR_MISSING,
    STATUS_STRUCTURALLY_UNAVAILABLE,
    STATUS_PATH_TIMESTAMP_MISSING,
    STATUS_PATH_SESSION_MISMATCH,
    STATUS_PATH_SYMBOL_MISMATCH,
    STATUS_INSUFFICIENT_COMPONENTS,
    STATUS_OK,
)

OUTCOME_SCHEMA = (
    "estimand",
    "session_id",
    "ts_event_ns",
    "tau_ns",
    "observation_time_ct",
    "session_phase",
    "horizon_minutes",
    "anchor_symbol_code",
    "anchor_close_ticks",
    "anchor_close_valid",
    "n_required_bars",
    "n_present_bars",
    "n_fully_labeled_bars",
    "window_fits_rth",
    "common_support",
    "outcome_status",
    "structural_unavailability_reason",
    "path_timestamp_missing",
    "path_session_mismatch",
    "path_symbol_mismatch",
    "insufficient_components",
    "downward_excursion_ticks",
    "upward_excursion_ticks",
    "signed_downward_extreme_ticks",
    "signed_upward_extreme_ticks",
    "outcome_valid",
)

_DTYPES = MappingProxyType(
    {
        "estimand": np.dtype("<U22"),
        "session_id": np.dtype("int32"),
        "ts_event_ns": np.dtype("int64"),
        "tau_ns": np.dtype("int64"),
        "observation_time_ct": np.dtype("<U5"),
        "session_phase": np.dtype("<U9"),
        "horizon_minutes": np.dtype("int16"),
        "anchor_symbol_code": np.dtype("int16"),
        "anchor_close_ticks": np.dtype("int32"),
        "anchor_close_valid": np.dtype("bool"),
        "n_required_bars": np.dtype("int8"),
        "n_present_bars": np.dtype("int8"),
        "n_fully_labeled_bars": np.dtype("int8"),
        "window_fits_rth": np.dtype("bool"),
        "common_support": np.dtype("bool"),
        "outcome_status": np.dtype("<U25"),
        "structural_unavailability_reason": np.dtype("<U24"),
        "path_timestamp_missing": np.dtype("bool"),
        "path_session_mismatch": np.dtype("bool"),
        "path_symbol_mismatch": np.dtype("bool"),
        "insufficient_components": np.dtype("bool"),
        "downward_excursion_ticks": np.dtype("int32"),
        "upward_excursion_ticks": np.dtype("int32"),
        "signed_downward_extreme_ticks": np.dtype("int32"),
        "signed_upward_extreme_ticks": np.dtype("int32"),
        "outcome_valid": np.dtype("bool"),
    }
)

_PRICE_COLUMNS = ("open_ticks", "high_ticks", "low_ticks", "close_ticks")
_RESOLVER_COLUMNS = (
    "ts_event_ns",
    "session_id",
    "symbol_code",
    *_PRICE_COLUMNS,
    "observed_1m_components",
    "expected_1m_components",
)
_INT32 = np.iinfo(np.int32)


@dataclass(frozen=True)
class OutcomeDependencyMasks:
    bar_rows: np.ndarray
    component_rows: np.ndarray


@dataclass(frozen=True)
class OutcomeTable:
    columns: MappingProxyType

    @property
    def row_count(self) -> int:
        return int(self.columns[OUTCOME_SCHEMA[0]].size)

    def column(self, name: str) -> np.ndarray:
        try:
            return self.columns[name]
        except KeyError as exc:
            raise SpineError(f"unknown Unit O outcome column {name!r}") from exc

    def mutable_copy(self) -> dict[str, np.ndarray]:
        return {name: np.array(values, copy=True) for name, values in self.columns.items()}

    @classmethod
    def from_columns(cls, columns: Mapping[str, np.ndarray]) -> "OutcomeTable":
        if tuple(columns) != OUTCOME_SCHEMA:
            raise SpineError(
                f"Unit O column order must be {list(OUTCOME_SCHEMA)}, got {list(columns)}"
            )
        immutable: dict[str, np.ndarray] = {}
        lengths = set()
        for name in OUTCOME_SCHEMA:
            array = np.asarray(columns[name], dtype=_DTYPES[name])
            if array.ndim != 1:
                raise SpineError(f"Unit O column {name!r} must be one-dimensional")
            copy = np.array(array, copy=True)
            copy.setflags(write=False)
            immutable[name] = copy
            lengths.add(copy.size)
        if len(lengths) != 1:
            raise SpineError("Unit O columns must have one aligned row count")
        return cls(MappingProxyType(immutable))


@dataclass(frozen=True)
class _OutcomeContract:
    time_model: TimeModel
    horizons: tuple[int, ...]
    # D32: supplied once per build and passed explicitly. Never loaded inside a
    # per-row function, never a mutable global.
    schedule_table: SessionScheduleTable | None = None

    def with_schedule(self, schedule_table: SessionScheduleTable) -> "_OutcomeContract":
        if not isinstance(schedule_table, SessionScheduleTable):
            raise SpineError("Unit O requires a canonical SessionScheduleTable")
        return _OutcomeContract(self.time_model, self.horizons, schedule_table)

    @classmethod
    def from_constants(cls, constants: Constants | None = None) -> "_OutcomeContract":
        constants = constants if constants is not None else load_constants()
        required_literals = (
            (("time", "storage_tz"), "UTC"),
            (("time", "session_tz"), "America/Chicago"),
            (("time", "bar_label"), "open"),
            (("time", "rth_start_ct"), "08:30"),
            (("time", "rth_end_ct"), "15:00"),
            (("estimands", "path"), ESTIMAND_FULLY_LABELED),
        )
        for path, expected in required_literals:
            actual = constants.get(*path)
            if actual != expected:
                raise SpineError(
                    f"required Unit O constant {'.'.join(path)} must be "
                    f"{expected!r}, got {actual!r}"
                )
        tick_size = constants.get("time", "tick_size")
        if isinstance(tick_size, bool) or not isinstance(tick_size, Real):
            raise SpineError("time.tick_size must be numeric")
        if float(tick_size) != 0.25:
            raise SpineError(f"time.tick_size must be 0.25, got {tick_size!r}")
        raw_horizons = constants.get("horizons_minutes")
        if not isinstance(raw_horizons, list) or raw_horizons != [15, 30, 60]:
            raise SpineError(
                "Unit O requires exact ordered horizons_minutes [15, 30, 60]"
            )
        if any(
            isinstance(value, bool)
            or not isinstance(value, Integral)
            or int(value) % BAR_MINUTES
            for value in raw_horizons
        ):
            raise SpineError("every Unit O horizon must be an integer divisible by five")
        return cls(TimeModel.from_constants(constants), tuple(int(v) for v in raw_horizons))


def _require_int32_scalar(value, name: str) -> np.int32:
    array = np.asarray(value)
    if array.ndim != 0 or array.dtype != np.dtype("int32"):
        raise SpineError(f"{name} must be an int32 tick scalar, got {array.dtype}")
    return np.int32(array.item())


def _require_int32_vector(values, name: str) -> np.ndarray:
    array = np.asarray(values)
    if array.ndim != 1 or array.dtype != np.dtype("int32"):
        raise SpineError(f"{name} must be a one-dimensional int32 tick array")
    return array


def _checked_int32(value: int, name: str) -> int:
    if not (_INT32.min <= value <= _INT32.max):
        raise SpineError(f"{name}={value} does not fit in int32 tick storage")
    return value


def compute_excursion_ticks(
    anchor_close_ticks,
    future_low_ticks: np.ndarray,
    future_high_ticks: np.ndarray,
) -> tuple[int, int, int, int]:
    """Return the floored pair and signed companions using int64 arithmetic."""
    anchor = _require_int32_scalar(anchor_close_ticks, "anchor_close_ticks")
    lows = _require_int32_vector(future_low_ticks, "future_low_ticks")
    highs = _require_int32_vector(future_high_ticks, "future_high_ticks")
    if lows.size == 0 or highs.size == 0 or lows.shape != highs.shape:
        raise SpineError("a valid excursion path cannot be empty or misaligned")

    anchor64 = np.int64(anchor)
    lows64 = lows.astype(np.int64, copy=False)
    highs64 = highs.astype(np.int64, copy=False)
    signed_down = int(anchor64 - np.min(lows64))
    signed_up = int(np.max(highs64) - anchor64)
    down = max(0, signed_down)
    up = max(0, signed_up)
    if down < 0 or up < 0:
        raise SpineError("negative floored excursion is corrupt")
    checked = (
        _checked_int32(down, "downward_excursion_ticks"),
        _checked_int32(up, "upward_excursion_ticks"),
        _checked_int32(signed_down, "signed_downward_extreme_ticks"),
        _checked_int32(signed_up, "signed_upward_extreme_ticks"),
    )
    return checked


def outcome_dependency_masks(
    ts_event_ns: np.ndarray,
    tau_ns: int,
    horizon_minutes: int,
    estimand: str,
) -> OutcomeDependencyMasks:
    labels = np.asarray(ts_event_ns)
    if labels.ndim != 1 or labels.dtype != np.dtype("int64"):
        raise SpineError("ts_event_ns must be a one-dimensional int64 array")
    if estimand not in ESTIMAND_ORDER:
        raise SpineError(f"unknown Unit O estimand {estimand!r}")
    if horizon_minutes not in (15, 30, 60):
        raise SpineError(f"unknown Unit O horizon {horizon_minutes!r}")
    future = required_interval_starts(
        tau_ns, horizon_minutes * 60 * 1_000_000_000, BAR_NS
    )
    coordinates = np.concatenate(
        [np.asarray([int(tau_ns) - BAR_NS], dtype=np.int64), future]
    )
    bar_rows = np.isin(labels, coordinates)
    component_rows = (
        np.isin(labels, future)
        if estimand == ESTIMAND_FULLY_LABELED
        else np.zeros(labels.size, dtype=bool)
    )
    bar_rows.setflags(write=False)
    component_rows.setflags(write=False)
    return OutcomeDependencyMasks(bar_rows, component_rows)


class _ExactResolver:
    def __init__(
        self,
        columns: Mapping[str, np.ndarray],
        contract: _OutcomeContract,
        symbols: tuple[str, ...] | None = None,
    ):
        missing = set(_RESOLVER_COLUMNS) - set(columns)
        if missing:
            raise SpineError(f"Unit O input is missing columns {sorted(missing)}")
        self.columns = {name: np.asarray(columns[name]) for name in _RESOLVER_COLUMNS}
        lengths = {value.size for value in self.columns.values()}
        if len(lengths) != 1 or any(value.ndim != 1 for value in self.columns.values()):
            raise SpineError("Unit O input columns must be aligned one-dimensional arrays")
        expected_dtypes = {
            "ts_event_ns": np.dtype("int64"),
            "session_id": np.dtype("int32"),
            "symbol_code": np.dtype("int16"),
            "open_ticks": np.dtype("int32"),
            "high_ticks": np.dtype("int32"),
            "low_ticks": np.dtype("int32"),
            "close_ticks": np.dtype("int32"),
            "observed_1m_components": np.dtype("int8"),
            "expected_1m_components": np.dtype("int8"),
        }
        for name, dtype in expected_dtypes.items():
            if self.columns[name].dtype != dtype:
                raise SpineError(
                    f"Unit O input {name!r} must have dtype {dtype}, "
                    f"got {self.columns[name].dtype}"
                )
        self.labels = self.columns["ts_event_ns"]
        if self.labels.size > 1 and not bool(np.all(self.labels[1:] > self.labels[:-1])):
            raise SpineError("Unit O timestamps must be strictly increasing and duplicate-free")
        self.contract = contract
        self.symbols = symbols
        if symbols is not None:
            if not symbols or not all(isinstance(symbol, str) and symbol for symbol in symbols):
                raise SpineError("Unit O decoded symbol table must contain nonempty strings")
            codes = self.columns["symbol_code"]
            if bool(np.any(codes < 0)) or bool(np.any(codes >= len(symbols))):
                raise SpineError("Unit O symbol_code is outside its decoded symbol table")

    def _indices(self, required: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        indices = np.searchsorted(self.labels, required)
        present = indices < self.labels.size
        clipped = np.minimum(indices, max(self.labels.size - 1, 0))
        if self.labels.size:
            present &= self.labels[clipped] == required
        else:
            present[:] = False
        return clipped.astype(np.int64), present

    def _validate_ohlc(self, indices: np.ndarray) -> None:
        if indices.size == 0:
            return
        open_ticks = self.columns["open_ticks"][indices]
        high_ticks = self.columns["high_ticks"][indices]
        low_ticks = self.columns["low_ticks"][indices]
        close_ticks = self.columns["close_ticks"][indices]
        valid = (
            (open_ticks > 0)
            & (high_ticks > 0)
            & (low_ticks > 0)
            & (close_ticks > 0)
            & (high_ticks >= open_ticks)
            & (high_ticks >= close_ticks)
            & (high_ticks >= low_ticks)
            & (low_ticks <= open_ticks)
            & (low_ticks <= close_ticks)
        )
        if not bool(np.all(valid)):
            raise SpineError("Unit O dependency contains an invalid OHLC row")

    def resolve(
        self,
        *,
        session_id: int,
        tau_ns: int,
        tau_ct_minute: int,
        session_phase: str,
        horizon_minutes: int,
        estimand: str,
    ) -> dict[str, object]:
        if estimand not in ESTIMAND_ORDER:
            raise SpineError(f"unknown Unit O estimand {estimand!r}")
        if horizon_minutes not in self.contract.horizons:
            raise SpineError(f"unknown Unit O horizon {horizon_minutes!r}")
        future = required_interval_starts(
            tau_ns, horizon_minutes * 60 * 1_000_000_000, BAR_NS
        )
        future_indices, present = self._indices(future)
        anchor_label = np.asarray([int(tau_ns) - BAR_NS], dtype=np.int64)
        anchor_indices, anchor_present = self._indices(anchor_label)
        anchor_exists = bool(anchor_present[0])
        anchor_index = int(anchor_indices[0]) if anchor_exists else 0

        dependency_indices = future_indices[present]
        if anchor_exists:
            dependency_indices = np.concatenate(
                [np.asarray([anchor_index], dtype=np.int64), dependency_indices]
            )
        self._validate_ohlc(dependency_indices)

        anchor_symbol = int(self.columns["symbol_code"][anchor_index]) if anchor_exists else 0
        anchor_close = int(self.columns["close_ticks"][anchor_index]) if anchor_exists else 0
        if anchor_exists and int(self.columns["session_id"][anchor_index]) != int(session_id):
            raise SpineError("anchor bar session differs from its declared anchor session")

        present_indices = future_indices[present]
        n_required = int(future.size)
        n_present = int(present.sum())
        full_flags = np.zeros(n_required, dtype=bool)
        if n_present:
            observed = self.columns["observed_1m_components"][present_indices]
            expected = self.columns["expected_1m_components"][present_indices]
            full_flags[present] = (observed == expected) & (expected == 5)
        n_fully = int(full_flags.sum())
        path_timestamp_missing = n_present != n_required
        path_session_mismatch = bool(
            n_present
            and np.any(self.columns["session_id"][present_indices] != int(session_id))
        )
        if self.symbols is None:
            path_symbol_mismatch = bool(
                anchor_exists
                and n_present
                and np.any(self.columns["symbol_code"][present_indices] != anchor_symbol)
            )
        else:
            anchor_decoded = self.symbols[anchor_symbol] if anchor_exists else ""
            future_decoded = np.asarray(
                [self.symbols[int(code)] for code in self.columns["symbol_code"][present_indices]],
                dtype=object,
            )
            path_symbol_mismatch = bool(
                anchor_exists and n_present and np.any(future_decoded != anchor_decoded)
            )
        insufficient_components = bool(
            estimand == ESTIMAND_FULLY_LABELED
            and n_present
            and np.any(~full_flags[present])
        )
        # D32: session-aware structural availability replaces the fixed 15:00
        # close. The schedule table is on the contract, supplied once per build.
        # Nothing here reads a bar to decide availability, and no fallback close
        # exists: an absent schedule raises rather than assuming 15:00.
        if self.contract.schedule_table is None:
            raise SpineError(
                "Unit O resolution requires a session schedule; there is no "
                "fallback close"
            )
        decision = outcome_window_structurally_available(
            session_id=int(session_id),
            tau_ct_minute=int(tau_ct_minute),
            horizon_minutes=int(horizon_minutes),
            schedule_table=self.contract.schedule_table,
        )
        fits = bool(decision.available)
        unavailability_reason = str(decision.reason)

        predicates = (
            (not anchor_exists, STATUS_ANCHOR_BAR_MISSING),
            (not fits, STATUS_STRUCTURALLY_UNAVAILABLE),
            (path_timestamp_missing, STATUS_PATH_TIMESTAMP_MISSING),
            (path_session_mismatch, STATUS_PATH_SESSION_MISMATCH),
            (path_symbol_mismatch, STATUS_PATH_SYMBOL_MISMATCH),
            (insufficient_components, STATUS_INSUFFICIENT_COMPONENTS),
        )
        status = next((name for failed, name in predicates if failed), STATUS_OK)
        outcome_valid = status == STATUS_OK
        outcomes = (0, 0, 0, 0)
        if outcome_valid:
            outcomes = compute_excursion_ticks(
                np.int32(anchor_close),
                self.columns["low_ticks"][future_indices],
                self.columns["high_ticks"][future_indices],
            )
        hour, minute = divmod(int(tau_ct_minute), 60)
        return {
            "estimand": estimand,
            "session_id": int(session_id),
            "ts_event_ns": int(tau_ns) - BAR_NS,
            "tau_ns": int(tau_ns),
            "observation_time_ct": f"{hour:02d}:{minute:02d}",
            "session_phase": session_phase,
            "horizon_minutes": int(horizon_minutes),
            "anchor_symbol_code": anchor_symbol,
            "anchor_close_ticks": anchor_close,
            "anchor_close_valid": anchor_exists,
            "n_required_bars": n_required,
            "n_present_bars": n_present,
            "n_fully_labeled_bars": n_fully,
            "window_fits_rth": fits,
            "common_support": False,
            "outcome_status": status,
            # The reason is carried only when the status is the structural one.
            # Anchor-bar-missing outranks it, so a row that is both keeps
            # anchor_bar_missing and reports not_applicable; window_fits_rth is
            # the column that records the structural fact for such rows.
            "structural_unavailability_reason": (
                unavailability_reason
                if status == STATUS_STRUCTURALLY_UNAVAILABLE
                else REASON_NOT_APPLICABLE
            ),
            "path_timestamp_missing": path_timestamp_missing,
            "path_session_mismatch": path_session_mismatch,
            "path_symbol_mismatch": path_symbol_mismatch,
            "insufficient_components": insufficient_components,
            "downward_excursion_ticks": outcomes[0],
            "upward_excursion_ticks": outcomes[1],
            "signed_downward_extreme_ticks": outcomes[2],
            "signed_upward_extreme_ticks": outcomes[3],
            "outcome_valid": outcome_valid,
        }


def resolve_outcome_row(
    columns: Mapping[str, np.ndarray],
    *,
    session_id: int,
    tau_ns: int,
    tau_ct_minute: int,
    session_phase: str,
    horizon_minutes: int,
    estimand: str,
    schedule_table: SessionScheduleTable | None = None,
) -> dict[str, object]:
    """Resolve one synthetic/audit row through the production exact resolver.

    ``schedule_table`` defaults to the canonical byte-pinned one. This is an
    audit/test entry point, not the production builder, which requires the table
    explicitly; the default here is the ratified table, never a fabricated close.
    """
    if schedule_table is None:
        from mnq_lab.spine.availability import load_session_schedule_table

        schedule_table = load_session_schedule_table()
    contract = _OutcomeContract.from_constants().with_schedule(schedule_table)
    return _ExactResolver(columns, contract).resolve(
        session_id=session_id,
        tau_ns=tau_ns,
        tau_ct_minute=tau_ct_minute,
        session_phase=session_phase,
        horizon_minutes=horizon_minutes,
        estimand=estimand,
    )


def _records_to_table(records: list[dict[str, object]]) -> OutcomeTable:
    columns = {
        name: np.asarray([record[name] for record in records], dtype=_DTYPES[name])
        for name in OUTCOME_SCHEMA
    }
    return OutcomeTable.from_columns(columns)


def build_outcome_table(
    store: BarStore, *, schedule_table: SessionScheduleTable
) -> OutcomeTable:
    """Build every estimand x session x tau x horizon row from an exploration store.

    ``schedule_table`` is required and explicit. Unit O does not load a calendar,
    does not hold one in a module global, and has no fallback close: availability
    is decided from the schedule handed in, once, before any row is resolved.
    """
    if not isinstance(store, BarStore):
        raise SpineError("build_outcome_table requires a BarStore")
    if not isinstance(schedule_table, SessionScheduleTable):
        raise SpineError("build_outcome_table requires a canonical SessionScheduleTable")
    assert_exploration_safe(store.root)
    assert_store_bar_seconds(store.manifest)
    bars = validate_exploration_store(store)
    contract = _OutcomeContract.from_constants().with_schedule(schedule_table)
    resolver = _ExactResolver(bars.columns, contract, bars.symbols)
    grid = contract.time_model.anchor_grid(
        bars.column("session_id"), bars.column("ts_event_ns")
    )

    records: list[dict[str, object]] = []
    max_horizon = contract.horizons[-1]
    for estimand in ESTIMAND_ORDER:
        for anchor in grid.itertuples(index=False):
            # D33: an excluded session contributes no anchor at all. It is
            # dropped here rather than resolved and marked, so no row from it can
            # enter the population by any later path.
            if schedule_table.is_excluded(int(anchor.session_id)):
                continue
            anchor_rows = [
                resolver.resolve(
                    session_id=int(anchor.session_id),
                    tau_ns=int(anchor.tau_ns),
                    tau_ct_minute=int(anchor.tau_ct_minute),
                    session_phase=str(anchor.phase),
                    horizon_minutes=horizon,
                    estimand=estimand,
                )
                for horizon in contract.horizons
            ]
            common = next(
                bool(row["outcome_valid"])
                for row in anchor_rows
                if row["horizon_minutes"] == max_horizon
            )
            for row in anchor_rows:
                row["common_support"] = common
            records.extend(anchor_rows)
    table = _records_to_table(records)
    validate_outcome_table(table)
    return table


def validate_outcome_table(table: OutcomeTable) -> None:
    if not isinstance(table, OutcomeTable):
        raise SpineError("Unit O output must be an OutcomeTable")
    if tuple(table.columns) != OUTCOME_SCHEMA:
        raise SpineError("Unit O output schema or column order differs from the contract")
    if table.row_count <= 0:
        raise SpineError("Unit O output table must be nonempty")
    for name, expected_dtype in _DTYPES.items():
        values = table.column(name)
        if values.ndim != 1 or values.size != table.row_count:
            raise SpineError(f"Unit O column {name!r} is not aligned")
        if values.dtype != expected_dtype:
            raise SpineError(
                f"Unit O column {name!r} dtype must be {expected_dtype}, got {values.dtype}"
            )

    estimands = table.column("estimand")
    statuses = table.column("outcome_status")
    if not bool(np.all(np.isin(estimands, ESTIMAND_ORDER))):
        raise SpineError("Unit O table contains an unknown estimand")
    if not bool(np.all(np.isin(statuses, OUTCOME_STATUSES))):
        raise SpineError("Unit O table contains an unknown outcome status")
    if table.row_count % (len(ESTIMAND_ORDER) * 3) != 0:
        raise SpineError("Unit O table omits a declared estimand or horizon row")

    n_per_estimand = table.row_count // len(ESTIMAND_ORDER)
    if not np.array_equal(
        estimands,
        np.concatenate(
            [np.full(n_per_estimand, value, dtype=_DTYPES["estimand"]) for value in ESTIMAND_ORDER]
        ),
    ):
        raise SpineError("Unit O estimand row order is not canonical")
    horizons = table.column("horizon_minutes")
    if not np.array_equal(
        horizons,
        np.tile(np.asarray([15, 30, 60], dtype=np.int16), table.row_count // 3),
    ):
        raise SpineError("Unit O horizon row order is not canonical or a row is missing")
    if not np.array_equal(table.column("ts_event_ns"), table.column("tau_ns") - BAR_NS):
        raise SpineError("Unit O anchor label must equal tau minus five minutes")

    n_required = table.column("n_required_bars")
    if not np.array_equal(n_required, horizons // BAR_MINUTES):
        raise SpineError("Unit O required-bar count differs from horizon/5")
    n_present = table.column("n_present_bars")
    n_fully = table.column("n_fully_labeled_bars")
    if bool(np.any(n_present < 0)) or bool(np.any(n_present > n_required)):
        raise SpineError("Unit O present-bar count is outside its required range")
    if bool(np.any(n_fully < 0)) or bool(np.any(n_fully > n_present)):
        raise SpineError("Unit O fully-labelled count is outside its present range")
    if not np.array_equal(
        table.column("path_timestamp_missing"), n_present != n_required
    ):
        raise SpineError("Unit O timestamp-missing flag differs from exact label counts")
    observed = estimands == ESTIMAND_OBSERVED
    if bool(np.any(table.column("insufficient_components")[observed])) or bool(
        np.any(statuses[observed] == STATUS_INSUFFICIENT_COMPONENTS)
    ):
        raise SpineError("observed_bar_path cannot require one-minute components")

    expected_status = np.full(table.row_count, STATUS_OK, dtype=_DTYPES["outcome_status"])
    precedence = (
        (~table.column("anchor_close_valid"), STATUS_ANCHOR_BAR_MISSING),
        (~table.column("window_fits_rth"), STATUS_STRUCTURALLY_UNAVAILABLE),
        (table.column("path_timestamp_missing"), STATUS_PATH_TIMESTAMP_MISSING),
        (table.column("path_session_mismatch"), STATUS_PATH_SESSION_MISMATCH),
        (table.column("path_symbol_mismatch"), STATUS_PATH_SYMBOL_MISMATCH),
        (table.column("insufficient_components"), STATUS_INSUFFICIENT_COMPONENTS),
    )
    unresolved = np.ones(table.row_count, dtype=bool)
    for failure, name in precedence:
        selected = unresolved & failure
        expected_status[selected] = name
        unresolved[selected] = False
    if not np.array_equal(statuses, expected_status):
        raise SpineError("Unit O outcome status violates the closed precedence")

    valid = table.column("outcome_valid")
    if not np.array_equal(valid, statuses == STATUS_OK):
        raise SpineError("Unit O outcome validity differs from status")
    # D32: the reason axis is closed, and carries a reason exactly when the
    # status is the structural one. Tested both ways so neither can drift.
    reasons = table.column("structural_unavailability_reason")
    if not np.all(np.isin(reasons, np.asarray(UNAVAILABILITY_REASONS))):
        raise SpineError("Unit O carries an undeclared structural-unavailability reason")
    structural = statuses == STATUS_STRUCTURALLY_UNAVAILABLE
    if not np.array_equal(structural, reasons != REASON_NOT_APPLICABLE):
        raise SpineError(
            "structural_unavailability_reason must be set exactly when the "
            "status is structurally_unavailable"
        )
    if bool(np.any(structural & table.column("window_fits_rth"))):
        raise SpineError("a structurally unavailable row reports a fitting window")
    outcome_names = (
        "downward_excursion_ticks",
        "upward_excursion_ticks",
        "signed_downward_extreme_ticks",
        "signed_upward_extreme_ticks",
    )
    for name in outcome_names:
        if bool(np.any(table.column(name)[~valid] != 0)):
            raise SpineError("a non-ok Unit O row carries a numeric outcome")
    down = table.column("downward_excursion_ticks")
    up = table.column("upward_excursion_ticks")
    signed_down = table.column("signed_downward_extreme_ticks")
    signed_up = table.column("signed_upward_extreme_ticks")
    if bool(np.any(down[valid] < 0)) or bool(np.any(up[valid] < 0)):
        raise SpineError("negative floored Unit O excursion is corruption")
    if not np.array_equal(down[valid], np.maximum(0, signed_down[valid])) or not np.array_equal(
        up[valid], np.maximum(0, signed_up[valid])
    ):
        raise SpineError("Unit O floored outcomes differ from their signed companions")

    common = table.column("common_support")
    for start in range(0, table.row_count, 3):
        expected_common = bool(valid[start + 2])
        if not np.array_equal(common[start : start + 3], [expected_common] * 3):
            raise SpineError("Unit O common support is not per-estimand h60 validity")
    for offset in range(n_per_estimand):
        full_index = offset
        observed_index = n_per_estimand + offset
        if valid[full_index] and not valid[observed_index]:
            raise SpineError("impossible cross-estimand validity: full path without observed path")


__all__ = [
    "ESTIMAND_FULLY_LABELED",
    "ESTIMAND_OBSERVED",
    "ESTIMAND_ORDER",
    "OUTCOME_SCHEMA",
    "OUTCOME_STATUSES",
    "STATUS_ANCHOR_BAR_MISSING",
    "STATUS_STRUCTURALLY_UNAVAILABLE",
    "STATUS_PATH_TIMESTAMP_MISSING",
    "STATUS_PATH_SESSION_MISMATCH",
    "STATUS_PATH_SYMBOL_MISMATCH",
    "STATUS_INSUFFICIENT_COMPONENTS",
    "STATUS_OK",
    "OutcomeDependencyMasks",
    "OutcomeTable",
    "build_outcome_table",
    "compute_excursion_ticks",
    "outcome_dependency_masks",
    "resolve_outcome_row",
    "validate_outcome_table",
]
