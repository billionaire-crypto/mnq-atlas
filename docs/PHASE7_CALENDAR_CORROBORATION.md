# Phase 7 Calendar Corroboration v1

## Scope and boundary

This report independently compares observed MNQ OHLCV activity with the accepted CME equity-index calendar. Observed shortening is not used as a calendar oracle: this study generates no classification, changes no accepted date, does not close D19, and is not an audit or operator acceptance decision.

The source contains OHLCV-1m bars only. It has no session-calendar or market-status stream. Observed activity is therefore weaker evidence than a status stream, especially for a full closure: an absent bar sequence cannot distinguish an exchange closure from vendor absence.

## Inputs and identity

- Accepted calendar: `mnq_lab/spine/calendar_inputs/cme_equity_index_v1/cme_equity_index_sessions_20190506_20230329_v1.json`
- Accepted calendar SHA-256, re-read before derivation: `b86e112c16112bf11a6a548ca8b3f21d28a08f90442b4dde84098f9d3f6eb069`
- Accepted range: 2019-05-06 through 2023-03-29
- Databento source (not copied): `C:\Users\kyawz\Downloads\GLBX-20260331-885WT5W7KA\glbx-mdp3-20100606-20260329.ohlcv-1m.csv`
- Source bytes: 421,879,836
- Source SHA-256: `7af016ba7a2fda53d6663b22991ed628386f011eecff6c4e8ba1e9f5ccbab834`

The structured result is stored beside this report as `docs/corroboration_v1.json`. The originally requested `data/exploration/derived/...` target is excluded by the repository-wide `data/` ignore rule, so the task's documented fallback was used.

The calendar companion manifest, acceptance record, and immutable calendar ledger entry were also re-read without modification. Their SHA-256 values are recorded in the structured result.

## Method

1. The CSV was streamed through `mnq_lab.spine.source.scan_source`, which validates the required schema, nulls, finite OHLC values, nonnegative volume, OHLC invariants, timestamp parsing, and global timestamp order while aggregating per-session outright volume.
2. `mnq_lab.spine.rolls.build_causal_active_contract_map` was called on that aggregate. This is the exact spine definition: a trade date's contract is fixed before that date's volume is consulted, with any observed crossover taking effect on the next available session.
3. A second streaming pass reused `mnq_lab.spine.source.read_source_chunks`, `mnq_lab.spine.symbols.OUTRIGHT_PATTERN`, `mnq_lab.spine.vendored.cme_session_mask(..., 'open')`, and `mnq_lab.spine.calendar.trade_date_strings`. Only the mapped active contract was retained. Active timestamps were required to be strictly increasing and each trade date to have one active contract.
4. The source-only observation table was completed before the accepted calendar was loaded. `ts_event` was treated as the bar open, so the observed session end is the last bar-open timestamp plus 60 seconds. UTC nanoseconds are retained and Chicago-time strings are reported.
5. Calendar regular and scheduled-early-close dates agree only when the observed end exactly matches the declared raw close. A different observed end is a directional disagreement. A full-holiday date with observed trading is a disagreement. A full-holiday date without OHLCV is `UNDETERMINED`, not `AGREE_HOLIDAY`, because this source has no status stream and cannot distinguish closure from vendor absence.

## Validation summary

- Source rows validated: 3,665,228
- Source-only weekday grid derived before calendar comparison: 1,018
- In-range active-chain rows: 1,369,566
- In-range observed sessions: 1,009
- Active-chain timestamps: strictly increasing
- Active contract per observed trade date: exactly one

## Bucket counts

- AGREE_REGULAR: 974
- AGREE_EARLY_CLOSE: 33
- AGREE_HOLIDAY: 0
- DISAGREE_REGULAR_OBSERVED_SHORT: 2
- DISAGREE_EARLY_CLOSE_END: 0
- DISAGREE_HOLIDAY_TRADING_OBSERVED: 0
- DISAGREE_UNMAPPED_CALENDAR_CLASS: 0
- UNDETERMINED: 9

## Disagreements and undetermined dates

| trade date | bucket | calendar | observed evidence | direction |
|---|---|---|---|---|
| 2019-12-25 | UNDETERMINED | full_exchange_holiday | no active-chain OHLCV; no in-session outright OHLCV | calendar says closed; no OHLCV trading observed |
| 2020-01-01 | UNDETERMINED | full_exchange_holiday | no active-chain OHLCV; no in-session outright OHLCV | calendar says closed; no OHLCV trading observed |
| 2020-02-28 | DISAGREE_REGULAR_OBSERVED_SHORT | regular | first 2020-02-27T17:00:00-06:00; last open 2020-02-28T09:58:00-06:00; end 2020-02-28T09:59:00-06:00; contract MNQH0 | calendar close 16:00 CT; observed OHLCV ends 09:59 CT |
| 2020-04-10 | UNDETERMINED | full_exchange_holiday | no active-chain OHLCV; no in-session outright OHLCV | calendar says closed; no OHLCV trading observed |
| 2020-06-30 | DISAGREE_REGULAR_OBSERVED_SHORT | regular | first 2020-06-29T17:00:00-05:00; last open 2020-06-30T09:10:00-05:00; end 2020-06-30T09:11:00-05:00; contract MNQU0 | calendar close 16:00 CT; observed OHLCV ends 09:11 CT |
| 2020-12-25 | UNDETERMINED | full_exchange_holiday | no active-chain OHLCV; no in-session outright OHLCV | calendar says closed; no OHLCV trading observed |
| 2021-01-01 | UNDETERMINED | full_exchange_holiday | no active-chain OHLCV; no in-session outright OHLCV | calendar says closed; no OHLCV trading observed |
| 2021-12-24 | UNDETERMINED | full_exchange_holiday | no active-chain OHLCV; no in-session outright OHLCV | calendar says closed; no OHLCV trading observed |
| 2022-04-15 | UNDETERMINED | full_exchange_holiday | no active-chain OHLCV; no in-session outright OHLCV | calendar says closed; no OHLCV trading observed |
| 2022-12-26 | UNDETERMINED | full_exchange_holiday | no active-chain OHLCV; no in-session outright OHLCV | calendar says closed; no OHLCV trading observed |
| 2023-01-02 | UNDETERMINED | full_exchange_holiday | no active-chain OHLCV; no in-session outright OHLCV | calendar says closed; no OHLCV trading observed |

## Nine preserved vendor contradictions

| trade date | pandas-market-calendars | exchange-calendars | observed evidence | comparison bucket |
|---|---|---|---|---|
| 2019-07-03 | 12:15 CT | regular | first 2019-07-02T17:00:00-05:00; last open 2019-07-03T12:14:00-05:00; end 2019-07-03T12:15:00-05:00; contract MNQU9 | AGREE_EARLY_CLOSE |
| 2019-11-29 | 12:15 CT | 12:00 CT | first 2019-11-28T17:00:00-06:00; last open 2019-11-29T12:14:00-06:00; end 2019-11-29T12:15:00-06:00; contract MNQZ9 | AGREE_EARLY_CLOSE |
| 2019-12-24 | 12:15 CT | 12:00 CT | first 2019-12-23T17:00:00-06:00; last open 2019-12-24T12:14:00-06:00; end 2019-12-24T12:15:00-06:00; contract MNQH0 | AGREE_EARLY_CLOSE |
| 2020-11-27 | 12:15 CT | 12:00 CT | first 2020-11-26T17:00:00-06:00; last open 2020-11-27T12:14:00-06:00; end 2020-11-27T12:15:00-06:00; contract MNQZ0 | AGREE_EARLY_CLOSE |
| 2020-12-24 | 12:15 CT | 12:00 CT | first 2020-12-23T17:00:00-06:00; last open 2020-12-24T12:14:00-06:00; end 2020-12-24T12:15:00-06:00; contract MNQH1 | AGREE_EARLY_CLOSE |
| 2021-04-02 | 08:15 CT | full holiday | first 2021-04-01T17:00:00-05:00; last open 2021-04-02T08:14:00-05:00; end 2021-04-02T08:15:00-05:00; contract MNQM1 | AGREE_EARLY_CLOSE |
| 2021-11-26 | 12:15 CT | 12:00 CT | first 2021-11-25T17:00:00-06:00; last open 2021-11-26T12:14:00-06:00; end 2021-11-26T12:15:00-06:00; contract MNQZ1 | AGREE_EARLY_CLOSE |
| 2022-06-20 | 12:00 CT | regular | first 2022-06-19T17:00:00-05:00; last open 2022-06-20T11:59:00-05:00; end 2022-06-20T12:00:00-05:00; contract MNQU2 | AGREE_EARLY_CLOSE |
| 2022-11-25 | 12:15 CT | 12:00 CT | first 2022-11-24T17:00:00-06:00; last open 2022-11-25T12:14:00-06:00; end 2022-11-25T12:15:00-06:00; contract MNQZ2 | AGREE_EARLY_CLOSE |

The observations above are reported as evidence only. This study does not decide which of the two vendors was right on any preserved contradiction.

## What was not checked

- No CME calendar or status extract was available or retrieved, and nothing was retrieved from cmegroup.com.
- No full closure was proven. The nine calendar holidays remain undetermined under OHLCV-only evidence.
- The two short regular sessions are reported from the raw one-minute source as 09:59 and 09:11 CT. D19's earlier 10:00 and 09:15 figures came from five-minute resampled bars; this study does not substitute those rounded endpoints for the source-defined last bar plus 60 seconds.
- No holiday classification, holiday-adjacent flag, unscheduled closure, or accepted calendar byte was generated or amended.
- No outcome, conditioner, seasonal profile, Phase 8 result, Phase 9 result, signal, selection, ranking, optimization, or trading decision was inspected or produced.
- No claim is made that the accepted calendar is proven correct. This is corroboration evidence only, and D19 remains `OPEN; COMMITTED ARTIFACT AUDIT PENDING`.
