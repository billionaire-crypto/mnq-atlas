# Session availability v2 — canonical design

Stage 1 deliverable for the D32 repair sequence. **Design only.** No production
behaviour is implemented here and no artifact is produced by this document.

Governing ruling: `docs/DISCREPANCIES.md` D32. Predecessor finding: D31.

---

## 1. Scope

In scope: the canonical per-session availability model, its placement in the
dependency graph, its typed records, its decision function, the Unit O v2 status
schema, and the versioned identifiers for every corrected product.

Out of scope, and explicitly not decided here: any change to Phases 1–6; any
bootstrap parameter; any threshold value; any outcome magnitude.

---

## 2. Root defect (verified, not quoted)

`TimeModel.outcome_window_fits_rth` (`mnq_lab/spine/timemodel.py:279-293`):

```python
return minutes + horizon_minutes <= self.rth_end_minute
```

`rth_end_minute` is parsed once from the single global constant
`time.rth_end_ct: "15:00"` (`analysis_constants_v1.yaml:9`) at
`timemodel.py:158`. The function takes **no session argument**. Five distinct
market conditions therefore collapse onto one fixed boundary.

The precedence order is *already correct*: `window_outside_rth` is rank 2, ahead
of `path_timestamp_missing` at rank 3 (`excursions.py:618-632`). Only the
predicate feeding it is wrong. This is why the repair is narrow.

---

## 3. Measured current state

All figures below were measured in this repository, not assumed.

**Accepted calendar v1 already carries per-session scheduled close.** Columns
include `scheduled_rth_open_ct`, `scheduled_rth_close_ct`, `scheduled_rth_status`
(`mnq_lab/conditioners/calendar.py:46,79`). 1,018 sessions:

| `session_class` | n | | `scheduled_rth_status` | n |
|---|---:|---|---|---:|
| `regular` | 976 | | `full_rth` | 976 |
| `scheduled_early_close` | 33 | | `shortened_rth` | 32 |
| `full_exchange_holiday` | 9 | | `no_scheduled_rth` | 1 |
| | | | `full_exchange_holiday` | 9 |

`scheduled_rth_close_ct` is loaded and validated but **never consumed for a
decision**. The data required to fix scheduled closes has been present all along.

**Phase 7 v1 labels six sessions `unresolved_truncated_session`** — measured from
`phase7-unit-o-first-run-v1/phase7/assignments`: 1,003 `ok`, 6 truncated, being
`20200228, 20200309, 20200312, 20200316, 20200318, 20200630`. This confirms the
brief's witness exactly.

**A latent contradiction, previously unrecorded.**
`mnq_lab/phase8/day_types.py:30` freezes
`TRUNCATED_REGULAR_SESSIONS = (20200228, 20200630)` and lines 76–79 raise
`SpineError` for any other session carrying that status. That premise is **false**
against Phase 7 v1, which produces six. It never fired because
`classify_calendar_day_type` is **never called from production code** — its only
call sites are `tests/test_phase8_day_types.py`. Production derives day types
inline at `production.py:994-996`. Recorded here; to be resolved in Stage 4.

**A live consumer of the label.** `production.py:527`:
`ordinary = (session_class == "regular") & (data_quality == "ok")`. All six
sessions are currently excluded from `ordinary`. Any Stage 4 change to the
quality vocabulary therefore has a real downstream dependency that must be
enumerated, not assumed inert.

---

## 4. The five distinctions and how each is decided

| | Case | Decided by | Available now? |
|---|---|---|---|
| A | Scheduled closure | calendar v1 `scheduled_rth_close_ct` | **yes** |
| B | Registered temporary interruption | new registered interruption input | **no — gated, see §10** |
| C | Genuine data absence | bars absent while structurally available | yes |
| D | Present but not fully labeled | existing estimand split | yes (unchanged) |
| E | No scheduled RTH | calendar v1 `scheduled_rth_status = no_scheduled_rth` | **yes** |

A, C, D and E are decidable today from ratified inputs. Only B is blocked.

Never infer A, B or E from absent bars. C is the *residual* case: it is what
remains after A, B and E are excluded, never a positive inference.

---

## 5. Placement and layering

New module: **`mnq_lab/spine/availability.py`**.

`mnq_lab/outcomes` already imports `spine.timemodel`, `spine.store`,
`spine.seal`, `spine.exploration` and `core.causality`, and imports **nothing**
from `conditioners`. Placing the model in `spine/` preserves that.

The canonical loader currently lives in the wrong layer:
`load_accepted_calendar()` is at `mnq_lab/conditioners/calendar.py:210-242`.
Outcomes must not import conditioners. Therefore the canonical loader moves to
`spine/`, and `conditioners/calendar.py` **delegates** to it. One implementation,
two callers — never two implementations.

```
spine/availability.py   <- canonical schedule + interruptions + decision function
        ^                        ^
        |                        |
conditioners/calendar.py    outcomes/excursions.py
   (delegates)                 (consumes)
```

---

## 6. Typed records

Frozen dataclasses, matching house style (`spine/rolls.py:61`, `spine/symbols.py:46`).

```
SessionSchedule            (frozen)
    session_id: int
    scheduled_rth_open_ct: int | None      # CT minutes from midnight
    scheduled_rth_close_ct: int | None
    scheduled_rth_status: str              # closed vocabulary
    structural_interruptions: tuple[StructuralInterruption, ...]
    calendar_version: str
    calendar_sha256: str
    interruption_source_id: str | None

StructuralInterruption     (frozen)
    start_ct_minute: int
    end_ct_minute: int
    reason: str                            # closed vocabulary
    source_id: str
```

`None` open/close is legal **only** when `scheduled_rth_status` is
`no_scheduled_rth` or `full_exchange_holiday`. Any other combination fails closed.

`SessionScheduleTable` holds a `MappingProxyType` keyed by `session_id` — immutable,
loaded once, passed explicitly. No module-level mutable calendar, no per-row I/O.

---

## 7. The decision function

```
outcome_window_structurally_available(
    session_id, tau_ct_minute, horizon_minutes, schedule_table
) -> (available: bool, reason: str)
```

Boundary convention, declared and separately tested:

- The outcome window is the half-open interval `[τ, τ + Δ)`, consistent with
  `ts_event` being the bar OPEN and the interval `[t, t + bar_seconds)`.
- Available requires `τ + Δ <= scheduled_rth_close_ct`. Equality is **available**
  — this reproduces the v1 rule exactly on full sessions, where
  `scheduled_rth_close_ct == 15:00`.
- An interruption `[s, e)` blocks the window iff the half-open intervals
  intersect: `τ < e AND s < τ + Δ`. A window ending exactly at `s` is
  **available**. A window beginning exactly at `e` is **available**.
- Wall-clock semantics are preserved. Trading time is never compressed across an
  interruption and no later bar is ever substituted for a missing scheduled
  timestamp.

Fails closed, with no fallback: unknown session; reversed or empty interruption;
overlapping interruptions (no canonical merge is defined, so they are rejected);
interruption outside the scheduled session; undeclared reason; missing schedule.
There is **no fallback to 15:00**.

---

## 8. Schema decision — **Option A selected**

Unit O v2 uses one general structural-unavailability status plus a separate,
closed, typed reason field.

**Why A over B.** The decisive argument is byte-comparability, which Stage 8
depends on. `outcome_status` is `numpy` dtype `<U25` (`excursions.py`), i.e. a
fixed 100-byte element. Option B needs strings such as
`window_after_scheduled_close` (28 chars), forcing the dtype wider; a width change
rewrites **every** element in the column, so the Stage 8 v1↔v2 comparison would
show all 472,212 rows differing and could no longer isolate the intended change.
Option A keeps the column at `<U25` and confines the diff to genuinely changed
rows. Secondary: the reason axis can be extended later under version control
without disturbing the status axis that Phase 8 switches on.

**Status vocabulary v2** — precedence order preserved, rank 2 renamed:

| rank | status | change |
|---:|---|---|
| 1 | `anchor_bar_missing` | unchanged |
| 2 | `structurally_unavailable` (24 ch) | **renames** `window_outside_rth` |
| 3 | `path_timestamp_missing` | unchanged |
| 4 | `path_session_mismatch` | unchanged |
| 5 | `path_symbol_mismatch` | unchanged |
| 6 | `insufficient_components` | unchanged |
| 7 | `ok` | unchanged |

Rank 2 is renamed rather than reused because labelling an 11:56 intraday halt
`window_outside_rth` would be actively false — RTH did not end. D32 and the brief
both forbid it.

**New column** `structural_unavailability_reason`, closed vocabulary:
`not_applicable` | `scheduled_close` | `no_scheduled_rth` | `registered_interruption`.
Invariant, tested both ways: reason is `not_applicable` **iff** status is not
`structurally_unavailable`.

---

## 9. An open tension in the precedence, flagged for audit

The brief's expected blast radius is 7,218 fit changes = 5,874 rows currently
`anchor_bar_missing` + 1,344 currently `path_timestamp_missing`, but only **1,344
status changes**. That arithmetic only holds if `anchor_bar_missing` keeps rank 1,
above structural unavailability — i.e. an anchor whose bar is absent *because the
session was already closed* keeps the status `anchor_bar_missing`.

This is in tension with Stage 5's stated precedence, which puts anchor structural
eligibility first. Scientifically, such an anchor is structurally undefined rather
than missing data, so ranking it `anchor_bar_missing` arguably repeats the D32
defect one level up.

Design position: **preserve rank 1** for this rebuild. Reasons: it reproduces the
pinned witness; the Phase 8 denominator is driven by the fit predicate, not the
status string, so completion arithmetic is identical either way; and it keeps the
v1↔v2 diff narrow and explainable. The residual is recorded honestly rather than
resolved silently, and it is the single most important question for the design
audit. If reproduction at Stage 5 yields a different split, work stops and reports
rather than coding around it.

---

## 10. Feasibility gate on registered interruptions (case B)

**Established** from the NYSE MWCB Working Group report and CME's price-limit
FAQ: CME halts US equity index futures — the Nasdaq-100 family, which covers MNQ
— when the cash market declares a Level 1 MWCB. Four Level 1 halts occurred on
2020-03-09, 03-12, 03-16 and 03-18.

**Not established, and therefore blocking:**

1. The NYSE report states CME halted affected symbols *"approximately one minute
   after each breach was triggered."* The futures halt start is thus **not** the
   cash trigger instant, and "approximately" is not a boundary.
2. Sources conflict on resumption: the cash-market Level 1 halt is 15 minutes,
   while CME material states US-hours equity index products reopen **10 minutes**
   after the halt is instituted. These cannot both define the futures window.

Per D32 and the brief, exact futures boundaries must come from authoritative CME
records, must not be guessed, and must not be derived from MNQ bar gaps.
**Therefore the interruption input cannot be built yet, and case B remains
unregistered.** The design fails closed on its absence: with no registered
interruption, the four March sessions retain genuine-data-absence treatment. They
are never silently marked available.

This gate does **not** block cases A, C, D and E, which is the material point —
see §11.

---

## 11. Consequence for sequencing

The 39-session census is 33 scheduled early closes plus 6 regular sessions, and
the coverage witnesses (`5006/5006`, `5456/5456`) are driven by *scheduled
closes*. The S00 h60 movement is therefore driven by case A, which is fully
decidable from ratified calendar v1 today.

The four March interruption sessions are a separable, smaller matter. Whether to
block the whole rebuild on them or to proceed with calendar-driven availability
and register interruptions as a later versioned input is a **user ruling**, not an
implementer's choice. It is put to the user with the Stage 1 report.

---

## 12. Versioned identifiers, recorded before production

Proposed, pending design audit and user ruling. Nothing below exists yet.

| product | identifier |
|---|---|
| availability module | `mnq_lab/spine/availability.py` |
| availability contract | `session-availability-v1` |
| interruption input dir | `mnq_lab/spine/calendar_inputs/structural_interruptions_v1/` |
| interruption schema | `cme-equity-index-structural-interruptions-v1` |
| interruption ledger entry | `mnq_lab/ledger/calendar_entries/<date>-structural-interruptions-v1.json` |
| Phase 7 artifacts schema | `phase7-conditioner-artifacts-v2` |
| Unit O schema | `unit-o-outcome-table-v2` |
| Phase 7 + Unit O tree | `data/exploration/derived/phase7-unit-o-session-aware-v2/` |
| Unit O v2 certificate | `unit_o_ratification_certificate_v2` |
| S00 v2 record | `data/exploration/s00/s00_threshold_input_v2.json` |
| constants v2 | `analysis_constants_v2.yaml` |
| Phase 8 v2 tree | `data/exploration/derived/phase8-session-aware-v2/` |
| Phase 8 v2 checkpoint | `data/exploration/derived/phase8-session-aware-v2.checkpoint/` |

**Recommendation against a calendar v2.** The brief lists an "accepted session
schedule/calendar v2". Measurement shows calendar v1 already contains every field
the repair needs, and its 32 timed early closes are already validated against
observed bar ends. Minting a v2 whose content would be identical adds a second
calendar identity and provenance churn for no scientific gain, against the
standing warning that two data definitions make differences unattributable.
Recommendation: **keep calendar v1 unchanged and ratified**, and add the
interruption input as a separate versioned artifact. This is a deviation from the
brief's wording and is therefore put to the user rather than taken silently.

---

## 13. Not decided here

The common-support threshold-horizon question raised by the uncommitted
`diagnostics.py` comment (D32 forward reference); the CRLF normalisation of the
two uncommitted Phase 8 source files; the Stage 4 quality vocabulary itself; any
threshold value. Tests are Stage 2 and are deliberately absent from this commit.
