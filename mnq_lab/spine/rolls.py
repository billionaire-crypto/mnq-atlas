"""Causal active-contract selection.

Spec §5.1 gate 4: "session *d*'s contract is fixed **entirely from volumes through
completed session *d-1***." The map below satisfies this by construction: `active[d]` is
assigned from `current` *before* session `d`'s own volume is consulted, and any crossover
detected on `d` takes effect on `d+1`.

Ported from `prepare_databento_mnq.py` (`_contract_expiry_from_first_year` :64,
`build_causal_active_contract_map` :218). The algorithm is preserved exactly — Gate 1
checks the result against the verified 28-roll fixture, which is the real oracle.

Spec §14 struck the earlier fixture that diverged at the RTH open. The causality fixture
must diverge at 17:00 CT, the start of session `d`, because an RTH-open divergence would
not catch a procedure using session `d`'s own 17:00-08:29 overnight volume.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from mnq_lab import SpineError
from mnq_lab.spine.symbols import OUTRIGHT_PATTERN

__all__ = [
    "MONTH_BY_CODE",
    "contract_expiry_from_first_year",
    "build_causal_active_contract_map",
    "RollMap",
]

# prepare_databento_mnq.py:32
MONTH_BY_CODE = {"H": 3, "M": 6, "U": 9, "Z": 12}


def contract_expiry_from_first_year(symbol: str, first_year: int) -> date:
    """Third Friday of the contract month. Verbatim from prepare_databento_mnq.py:64.

    A one-digit year code is resolved forward from the year the symbol was first
    observed, which is why `first_year` is required rather than inferred.
    """
    match = OUTRIGHT_PATTERN.fullmatch(symbol)
    if not match:
        raise SpineError(f"not an outright MNQ quarterly symbol: {symbol}")
    month_code, year_code = match.groups()
    if len(year_code) == 1:
        digit = int(year_code)
        year = first_year + ((digit - first_year % 10) % 10)
    else:
        value = int(year_code)
        year = 2000 + value if value < 70 else 1900 + value

    month = MONTH_BY_CODE[month_code]
    fifteenth = date(year, month, 15)
    third_friday = fifteenth + timedelta(days=(4 - fifteenth.weekday()) % 7)
    return third_friday


@dataclass(frozen=True)
class RollMap:
    active: dict[str, str]
    rolls: list[dict[str, Any]]
    expiries: dict[str, date]

    @property
    def roll_count(self) -> int:
        return len(self.rolls)


def build_causal_active_contract_map(
    daily_volume: dict[tuple[str, str], int],
    first_year_by_symbol: dict[str, int],
) -> RollMap:
    """Choose each session's contract from information known before it opens.

    Verbatim port of prepare_databento_mnq.py:218.

    The causality argument, stated so it can be checked against the code below:

      * `active[trade_date] = current` is executed before this session's volumes are
        read. `current` was last modified during a *previous* loop iteration.
      * The crossover test reads `volume_by_day[trade_date]`, i.e. session `d`'s own
        aggregate — but its only effect is to reassign `current`, which is consumed on
        iteration `d+1`. The recorded `effective_trade_date` is `sessions[i+1]`.
      * The expiry guard uses only the contract calendar, which is public well before
        the session opens.

    Therefore session `d`'s assignment is a function of volumes through `d-1` only, and
    it is a single value for the whole Globex session — there is no intraday
    recalculation anywhere in this function. `tests/test_roll_causality.py` proves this
    empirically rather than relying on the argument.
    """
    if not daily_volume:
        raise SpineError("no outright daily volume was found")

    expiries = {
        symbol: contract_expiry_from_first_year(symbol, first_year_by_symbol[symbol])
        for symbol in first_year_by_symbol
    }
    contracts = sorted(expiries, key=lambda symbol: expiries[symbol])
    sessions = sorted({trade_date for trade_date, _ in daily_volume})
    volume_by_day: dict[str, dict[str, int]] = defaultdict(dict)
    for (trade_date, symbol), volume in daily_volume.items():
        volume_by_day[trade_date][symbol] = volume

    first_day = sessions[0]
    current = max(
        volume_by_day[first_day],
        key=lambda symbol: volume_by_day[first_day][symbol],
    )
    active: dict[str, str] = {}
    rolls: list[dict[str, Any]] = []

    for session_index, trade_date in enumerate(sessions):
        session_date = date.fromisoformat(trade_date)
        current_index = contracts.index(current)

        # Contract expiry is public before the session. If a crossover somehow
        # did not occur, force the chain forward after the expiry date.
        while current_index + 1 < len(contracts) and session_date > expiries[current]:
            previous = current
            current_index += 1
            current = contracts[current_index]
            rolls.append(
                {
                    "effective_trade_date": trade_date,
                    "from": previous,
                    "to": current,
                    "reason": "post_expiry_guard",
                }
            )

        active[trade_date] = current
        if current_index + 1 >= len(contracts):
            continue
        next_contract = contracts[current_index + 1]
        current_volume = volume_by_day[trade_date].get(current, 0)
        next_volume = volume_by_day[trade_date].get(next_contract, 0)

        # The day's aggregate is only known after this session. The resulting
        # switch therefore becomes effective on the next available session.
        if next_volume > current_volume and next_volume > 0:
            next_session = (
                sessions[session_index + 1]
                if session_index + 1 < len(sessions)
                else None
            )
            rolls.append(
                {
                    "trigger_trade_date": trade_date,
                    "effective_trade_date": next_session,
                    "from": current,
                    "to": next_contract,
                    "reason": "prior_session_volume_crossover",
                    "current_volume": current_volume,
                    "next_volume": next_volume,
                }
            )
            current = next_contract

    return RollMap(active=active, rolls=rolls, expiries=expiries)
