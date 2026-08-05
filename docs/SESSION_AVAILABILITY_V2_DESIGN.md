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
Precisely: the column exists on all 1,018 rows and is *populated* on 1,008. The
ten blanks are the 9 `full_exchange_holiday` rows plus the single
`no_scheduled_rth` session (20210402) — rows the calendar validator requires to
be empty, not missing data.

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
| B1 | Registered temporary interruption, boundaries known | registered interruption input | supported, none registered |
| B2 | Official interruption, boundaries unresolved | **session-exclusion registry (D33)** | **yes** |
| C | Genuine data absence | bars absent while structurally available | yes |
| D | Present but not fully labeled | existing estimand split | yes (unchanged) |
| E | No scheduled RTH | calendar v1 `scheduled_rth_status = no_scheduled_rth` | **yes** |

D33 split the original case B. B1 remains the model for interruptions whose exact
start and end are authoritative; no such record exists yet, and the machinery is
retained for future ones. B2 is the treatment ruled for the four March 2020
sessions whose CME boundaries are not established: the whole session is excluded
rather than classified intraday.

Never infer A, B1, B2 or E from absent bars. C is the *residual* case: it is what
remains after the others are excluded, never a positive inference.

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

**The exclusion registry (D33).** A separate byte-pinned input, never a calendar
mutation:

```
SessionExclusion           (frozen)
    session_id: int                        # references a calendar v1 identity
    reason: str                            # closed vocabulary
    source_id: str
    recorded_by_ruling: str                # "D33"
```

It is loaded once into an immutable frozenset held on the schedule table, is
pinned by sha256 in the manifest, and fails closed on an unknown reason, a
duplicate session, or a session absent from calendar v1. The registry adds no
per-row filesystem access: exclusion is a set membership test on an in-memory
structure. The only registered reason today is
`excluded_unresolved_official_interruption`, carrying the four March 2020
sessions. Calendar v1 is not edited, reissued or superseded.

---

## 7. The decision function

```
outcome_window_structurally_available(
    session_id, tau_ct_minute, horizon_minutes, schedule_table
) -> (available: bool, reason: str)
```

**Exclusion is checked first (D33).** Before any schedule arithmetic, the function
tests session exclusion. An excluded session never reaches the scheduled-close or
interruption tests. Excluded sessions fail closed: no anchor from one may enter
Phase 7 eligibility or the Unit O v2 population, so such rows are not emitted at
all rather than emitted with a status.

Order of evaluation:

1. session excluded            -> not in population (fail closed)
2. no scheduled RTH            -> unavailable, `no_scheduled_rth`
3. window exceeds the close    -> unavailable, `scheduled_close`
4. window meets an interruption -> unavailable, `registered_interruption`
5. otherwise                   -> available, `not_applicable`

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

A commissioned primary-source sweep across CME rulebook, Special Executive
Reports, advisories and rule filings, and across SEC, CFTC, Federal Register,
NYSE, Nasdaq and Cboe CFE material, returned no document fixing exact CME or MNQ
transition timestamps. It terminated on resource limits rather than exhausting
the source space, so the result is "not established", not "proven absent".

**Ruling (D33).** The user chose conservative whole-session exclusion of
2020-03-09, 03-12, 03-16 and 03-18 in preference to uncertain intraday
classification. Pre-halt and post-resumption anchors from these four sessions are
not retained. This supersedes the preserve-post-resumption requirement for these
four sessions only; it stands everywhere else, and the B1 machinery is retained
for any interruption whose boundaries are later established authoritatively.

**Measured impact of the exclusion** (structural counts, no magnitudes read):

| | v1 | after exclusion | delta |
|---|---:|---:|---:|
| Unit O rows | 472,212 | 470,340 | −1,872 |
| Phase 7 assignment rows | 787,020 | 783,900 | −3,120 |
| distinct sessions | 1,009 | 1,005 | −4 |

Each excluded session contributes exactly 468 Unit O rows (78 anchors × 2
estimands × 3 horizons) and 780 assignment rows, uniformly across all four — so
the exclusion is even and no session is partially represented.

---

## 11. Consequence for sequencing

The 39-session census is 33 scheduled early closes plus 6 regular sessions, and
the coverage witnesses (`5006/5006`, `5456/5456`) are driven by *scheduled
closes*. The S00 h60 movement is therefore driven by case A, which is fully
decidable from ratified calendar v1 today.

The four March sessions are settled by D33: excluded whole, via the registry in
§12. The rebuild therefore proceeds on cases A, B2, C, D and E, with B1 retained
but unpopulated.

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
| **exclusion registry dir** | `mnq_lab/spine/calendar_inputs/session_exclusions_v1/` |
| **exclusion registry file** | `session_exclusions_v1.json` + `.manifest.json` |
| **exclusion schema** | `mnq-session-exclusion-registry-v1` |
| **exclusion reason code** | `excluded_unresolved_official_interruption` |
| **exclusion ledger entry** | `mnq_lab/ledger/calendar_entries/<date>-session-exclusions-v1.json` |
| Phase 7 artifacts schema | `phase7-conditioner-artifacts-v2` |
| Unit O schema | `unit-o-outcome-table-v2` |
| Phase 7 + Unit O tree | `data/exploration/derived/phase7-unit-o-session-aware-v2/` |
| Unit O v2 certificate | `unit_o_ratification_certificate_v2` |
| S00 v2 record | `data/exploration/s00/s00_threshold_input_v2.json` |
| constants v2 | `analysis_constants_v2.yaml` |
| Phase 8 v2 tree | `data/exploration/derived/phase8-session-aware-v2/` |
| Phase 8 v2 checkpoint | `data/exploration/derived/phase8-session-aware-v2.checkpoint/` |

**No calendar v2 — user ruled.** Calendar v1 already contains every field the
repair needs, and its 32 timed early closes are already validated against observed
bar ends. The user ruled that calendar v1 stays unchanged and ratified, and that
corrections arrive as separate versioned inputs: the exclusion registry now, and
an interruption input if authoritative boundaries are later established. Minting a
v2 with identical scheduled-session content would create a second calendar
identity for no scientific gain.

---

## 13. Not decided here

The common-support threshold-horizon question raised by the uncommitted
`diagnostics.py` comment (D32 forward reference); the CRLF normalisation of the
two uncommitted Phase 8 source files; the Stage 4 quality vocabulary itself; any
threshold value. Tests are Stage 2 and are deliberately absent from this commit.
