# Phase 2 — time model, clock-window engine, completion accounting

Branch `phase-2-time-model` off `phase-1-spine`. Spec §15 row 2; gate = §13 tests 1–2
(`test_time_and_timezone`, `test_event_time_conditioner`) plus `test_window_boundaries`
and `test_estimand_definition`. Phase 3 (S00 atlas, threshold freezing) is **not**
started here.

## What was built

| File | Contents |
|---|---|
| `mnq_lab/core/causality.py` | The §4.1 event-time rule, market-free: conditioner mask (interval end ≤ τ, inclusive), outcome mask (start ≥ τ, < τ+Δ), required-label grids, presence accounting. int64 UTC ns only; bar length and horizon are parameters; no RTH/session/phase concept (§16.3). |
| `mnq_lab/spine/timemodel.py` | `TimeModel`: RTH bounds, session phases, and horizons **consumed from `analysis_constants_v1.yaml`** with fail-closed validation (phases must tile RTH; `session_tz` must match the vendored runtime — audit-M2 pattern). τ derivation (label + 5 min), CT bucketing by tz-convert (never a fixed UTC offset), anchor eligibility per ruling D11a, the declared per-session τ-grid with `anchor_bar_missing` statuses, per-session proof that no UTC-offset change falls inside RTH, and the D11b data-derived session flags. |
| `mnq_lab/outcomes/completion.py` | Per anchor × horizon window completion under both §6 estimands (`fully_labeled_1m_grid`, `observed_bar_path`); `state_anchor` vs `outcome_eligible_*_h{Δ}` kept structural (§10.2); by-cell and by-year summaries emitting every declared cell with a `status`; `weight_ess` reserved as a NaN column until Phase 4 (§16.4.6). CLI: `python -m mnq_lab.outcomes.completion --store data`. |
| `tests/test_time_and_timezone.py` | §13 test 1: worked example exact; bar-end interpretation fails; RTH from YAML with the divergent-YAML negative; both US DST transitions; US/EU divergence week; early closes (synthetic + one real session selected by data); D11a's two discriminating edges. |
| `tests/test_event_time_conditioner.py` | §13 test 2: hand-built timestamps; anchor return in, anchor path out; gapped-series proof that the rule is event-time, not positional; three detectably-wrong implementations (strict `<`, label-keyed, off-by-one window). |
| `tests/test_window_boundaries.py` | Half-open windows and required grids; the §4.2 registered close-phase counts (1/7/10) computed on a synthetic AND a real full session; proof those counts cannot discriminate the D11a ruling; declared-grid emission with statuses. |
| `tests/test_estimand_definition.py` | Estimand names tied to the YAML; struck rev-1–5 names absent from the package; the test-5 discriminating case at window level; §10.2 horizon-invariance; cell summaries on synthetic and real stores with negative cases. |

Definitional choice, documented rather than silent: under `observed_bar_path` a window
is complete when **all required 5-min bars are present in the source** (1-minute
coverage not required); a window missing an entire 5-min bar is incomplete under
*both* estimands, because an excursion across an absent interval would invent prices.
The estimands differ exactly on 1-minute coverage — §13 test 5's discriminating case.

`fully_labeled_1m_grid` requires `observed_1m_components == expected_1m_components == 5`
per required bar. Measured: every bar in both built stores has
`expected_1m_components == 5`, so the `== 5` conjunct is currently redundant; it is kept
so a future store expecting fewer labels at a boundary cannot qualify as "fully
labeled" with fewer than five.

## Binding obligations discharged

- **The re-audit's consumption gap is closed.** `rth_start_ct`, `rth_end_ct`,
  `session_phases`, and `horizons_minutes` are read from the YAML by `TimeModel`.
  `test_negative_a_divergent_yaml_changes_anchor_output` replays the re-audit's exact
  scenario (`rth_start_ct: "09:00"`) and proves the anchor grid now changes (72 vs 78
  gridpoints); `test_negative_an_inconsistent_yaml_refuses_to_construct` proves a bound
  moved without its phases fails closed before any grid is built.
- **Ruling D11a/D11b implemented and logged** in `docs/DISCREPANCIES.md` D11.
- pandas-3.0 `datetime64[us]` never enters: every ingress validates int64 ns and the
  grid emits int64 ns (`test_grid_timestamps_are_int64_ns`,
  `test_negative_non_ns_instants_are_rejected`).

## Measured on the real exploration store (1009 sessions × 78 = 78,702 gridpoints)

Reproduce with `python -m mnq_lab.outcomes.completion --store data`. `n_anchors` is the
structurally eligible population per cell (state anchor AND window inside RTH);
completion rates are over that population. `weight_ess` is rendered beside every
`n_anchors` as §16.4.6 requires; it is `NaN` because the weighting layer arrives in
Phase 4 — that is "not computed yet", not a computed value of zero.

### Completion by phase × horizon

| phase | Δ | n_anchors | n_sessions | weight_ess | rate fully_labeled_1m_grid | rate observed_bar_path |
|---|---|---|---|---|---|---|
| open | 15 | 6,038 | 1,008 | NaN (Phase 4) | 0.99868 | 0.99917 |
| open | 30 | 6,038 | 1,008 | NaN (Phase 4) | 0.99801 | 0.99884 |
| open | 60 | 6,038 | 1,008 | NaN (Phase 4) | 0.99669 | 0.99818 |
| morning | 15 | 18,125 | 1,008 | NaN (Phase 4) | 0.99895 | 0.99967 |
| morning | 30 | 18,125 | 1,008 | NaN (Phase 4) | 0.99834 | 0.99945 |
| morning | 60 | 18,125 | 1,008 | NaN (Phase 4) | 0.99757 | 0.99912 |
| midday | 15 | 24,003 | 1,006 | NaN (Phase 4) | 0.99429 | 0.99588 |
| midday | 30 | 24,003 | 1,006 | NaN (Phase 4) | 0.99000 | 0.99175 |
| midday | 60 | 24,003 | 1,006 | NaN (Phase 4) | 0.98188 | 0.98350 |
| afternoon | 15 | 17,532 | 974 | NaN (Phase 4) | 0.99949 | 1.00000 |
| afternoon | 30 | 17,532 | 974 | NaN (Phase 4) | 0.99926 | 1.00000 |
| afternoon | 60 | 17,532 | 974 | NaN (Phase 4) | 0.99914 | 1.00000 |
| close | 15 | 9,740 | 974 | NaN (Phase 4) | 1.00000 | 1.00000 |
| close | 30 | 6,818 | 974 | NaN (Phase 4) | 1.00000 | 1.00000 |
| close | 60 | 974 | 974 | NaN (Phase 4) | 1.00000 | 1.00000 |

The close-phase structural counts are exactly 10, 7, and 1 anchors per contributing
session (9,740 / 6,818 / 974 over 974 sessions) — the §4.2 registered prediction
reproduced in aggregate on real data.

### Completion by year × horizon (`fully_labeled_1m_grid` / `observed_bar_path`)

| year | Δ15 | Δ30 | Δ60 |
|---|---|---|---|
| 2019 | 0.99366 / 0.99836 | 0.99031 / 0.99658 | 0.98469 / 0.99257 |
| 2020 | 0.99787 / 0.99803 | 0.99601 / 0.99617 | 0.99196 / 0.99208 |
| 2021 | 0.99892 / 0.99892 | 0.99775 / 0.99775 | 0.99509 / 0.99509 |
| 2022 | 0.99876 / 0.99876 | 0.99742 / 0.99742 | 0.99438 / 0.99438 |
| 2023 | 0.99871 / 0.99871 | 0.99731 / 0.99731 | 0.99415 / 0.99415 |

### The §6 selection confound, measured first and stated loudly (§16.5 item 6)

Completion is **not** uniform across the conditioning dimensions the atlas will use:

- **By year:** 2019 is the worst year at every horizon under `fully_labeled_1m_grid`
  (0.98469 at Δ60 vs ≥0.99196 for every later year) — exactly §6's predicted
  direction: rejecting incomplete windows preferentially removes early, thinner data.
- **By phase:** midday is the least complete phase at every horizon (0.98188 at Δ60 vs
  ≥0.99669 elsewhere). That is the entire measured claim. This document previously
  added that "quiet-regime minutes are the ones that go missing", making
  `quiet → less observable` sound established; it is not. Completion versus
  volatility state cannot be measured until conditioners exist (Phase 7), and no
  volatility variable was involved in producing this table. The phase-level result is
  *consistent with* the §6 mechanism and is not evidence for it (audit finding M-8).
- The gap between the two estimands (bars present but partially labeled) is
  concentrated in 2019–2020; from 2021 on the two rates coincide to 5 decimals.

The magnitudes are small (worst cell ≈ 1.8% incomplete), but the *direction* is the
§6 confound made real, and any Phase 3+ result conditioned on year, phase, or
volatility must carry it. Phase 3 computes `s00_p05` and freezes
`min_completion_h15/h30/h60` with a ledger entry — deliberately **not done here**.

### Session flags (D11b)

Re-measured after the audit split the zero-RTH case out of "ended early":

| flag | sessions | detail |
|---|---|---|
| `observed_rth_ended_early` | 34 | last RTH bar ends 12:00 CT ×25, 12:15 ×7, 10:00 ×1, 09:15 ×1 |
| `observed_no_rth_bars` | 1 | 20210402 — no RTH bar at all; `last_rth_bar_end_ct_minute = -1` |
| `observed_mid_rth_gap` | 4 | interior RTH labels missing, trading to 15:00 |
| both early and gap | 0 | |

The zero-RTH session was previously counted among 35 "ended early" sessions. It is now
its own state: a session that never started did not end early, and the `-1` sentinel is
excluded from any earliest-ending selection. No calendar claim is made or possible
(D11b); `calendar_early_close` is `"unknown"` for all 1,009 sessions.

## Reproducible commands

```powershell
# full suite (Phase 1 + Phase 2): expect 294 passed, 5 xfailed
python -m pytest tests -q

# Phase 2 gate tests only
python -m pytest tests/test_time_and_timezone.py tests/test_event_time_conditioner.py tests/test_window_boundaries.py tests/test_estimand_definition.py -q

# the four Phase 1 fail-closed gates, unchanged: expect 4/4 pass
python -m mnq_lab.spine.gates --store data

# completion accounting over the exploration store (JSON to stdout)
python -m mnq_lab.outcomes.completion --store data
```

## External audit round 1 (2026-07-28) — verdict FAIL, and what changed

An external adversarial audit replayed the baseline, mutation-tested the suite, and
diffed these claims against their mechanisms. All 30 published completion figures
reproduced exactly and Phase 1 did not regress, but **two required mutations survived
the whole suite** and nine claims exceeded their mechanisms. Every finding is closed
below; the completion tables above are unchanged by the fixes (re-measured, not
transcribed), and the session-flag census changed as noted.

| # | Finding | Resolution |
|---|---|---|
| M-1 | Scalar `tau_ns`/`horizon_ns` were converted with a bare `np.int64(...)`, so a `datetime64[us]` scalar silently became a value 1000× too small | `_as_scalar_int64` rejects unit-bearing and float scalars outright. `test_negative_scalar_unit_bearing_inputs_fail_closed` pins the exact leak. |
| M-2 | The phase-tiling validator accepted a *backwards* phase (`morning = [10:30, 09:00]`), which chains end-to-start while overlapping its neighbours | Every phase must have positive duration and the boundary sequence must be strictly increasing. `test_negative_a_backwards_phase_is_refused`. |
| M-3 | **Mutation survived:** dropping `expected == 5` from the fully-labeled criterion | Every fixture set `expected = 5`, so the conjunct was untestable. `synthetic_session_bars` gained `expected_components`; `test_a_bar_expecting_fewer_than_five_labels_is_not_fully_labeled` fails on the mutation. |
| M-4 | **Mutation survived:** deleting the intra-RTH offset guard | Worse than reported — the guard was also *unreachable*: τ-grid localization raised an anonymous pandas `ValueError` first. The guard now runs before grid localization and is exercised by `test_the_intra_rth_offset_guard_actually_fires` (Africa/Khartoum, 2000-01-15, a real +02→+03 jump at 12:00 local). |
| M-5 | `BAR_MINUTES = 5` claimed "structural to the store" but nothing consumed the store's declaration; a 10-minute store passed the divisibility check | `assert_store_bar_seconds` consumes the manifest's `bar_seconds` (300), and `_assert_bar_grid` checks the observed label stride. Two negative tests. |
| M-6 | Presence matched by exact UTC instant across the whole input, without pairing on `session_id` | `_assert_sessions_own_their_bars` enforces `session_id == CME trade date` per bar via the spine's own rule. `test_negative_a_bar_labelled_with_the_wrong_session_is_refused`. |
| M-7 | This document rendered `n_anchors` without `weight_ess` "for width" — a direct §16.4.6 violation | Column restored to the table above. |
| M-8 | Prose claimed `quiet → less observable` is "live", which no measurement here supports | Rewritten to the measured claim only; see the confound section above. |
| L-1 | `completion_by_year` iterated only the years present, dropping absent intervening years | Declared year axis is now the contiguous span, absent years emitted as empty cells with a status. `test_an_absent_intervening_year_is_emitted_as_an_empty_cell`. |
| adj. | Session 20210402 (zero RTH bars) was flagged `observed_rth_ended_early` | Split into its own `observed_no_rth_bars` state; the `-1` sentinel is excluded from earliest-ending selection. |

Both previously-surviving mutations were re-applied after the fix and now fail the
suite; the mutation was reverted from a scratch backup, not from git, so no fix was
lost in the process.

## Open question the user must rule on before Phase 3

**`observed_bar_path` window completeness is an implementer interpretation, not a
ruled one.** This build treats a window as complete when all required 5-min bars are
present, so a window missing an entire bar fails *both* estimands. §6's phrase
"excursions across the bars present in the source" does not uniquely compel that
reading — it can also be read as "measure across whatever bars exist, however sparse".
The audit flagged this as unruled, and it is load-bearing: Phase 3 freezes completion
thresholds computed under whichever reading is chosen. Logged as **D12 (OPEN)**. Under
the current reading the two estimands differ only on 1-minute coverage, and the
measured gap between them is small (worst cell **0.175 pp, midday Δ30** — round 2
corrected the original "0.16 pp at Δ60" claim, which had compared only within one
horizon; see D12).

## External audit round 2 (2026-07-28) — verdict FAIL, and what changed

Round 2 confirmed every round-1 repair present and effective (all 18 round-1
mutations plus 9 new ones discriminated by named tests, all 30 published figures
reproduced, D12 not silently adjudicated) — but found one surviving required
mutation and three fresh claim/mechanism defects. All four are closed:

| # | Finding | Resolution |
|---|---|---|
| M-1 | **Mutation survived:** deleting the `assert_store_bar_seconds` call from the completion CLI — the helper was tested standalone, the *wiring* was not | `test_the_cli_entry_point_refuses_a_wrong_duration_store` drives `completion._run` end to end against a real on-disk store declaring 600-second bars (no mocks), with a 300-second positive control through the same path. Mutation re-applied and verified caught. |
| M-2 | D12's measured-impact claim was numerically false: "at most 0.16 pp, worst at midday Δ60". The real worst is **0.174978 pp at midday Δ30** — the gap is not monotone in horizon, and only Δ60 cells had been compared | Corrected in D12 and above, with the faulty reasoning named. |
| M-3 | `_as_scalar_int64` accepted `np.uint64(2**63)`, which `np.int64(...)` silently WRAPS to the negative extreme — nonsensical comparisons instead of an error | Scalars now convert through exact Python int and are range-checked against int64 bounds. `test_negative_unsigned_overflow_scalars_fail_closed` pins every entry point; representable unsigned scalars still pass. |
| M-4 | `assert_store_bar_seconds` compared `int(declared)`, truncating `300.9` and coercing `"300"` into passing an exactness check | The declaration must be a plain (or numpy) integer equal to 300; bool, float, string, and list forms are refused. `test_negative_a_malformed_bar_seconds_declaration_is_refused`. |
| adj. | `_assert_bar_grid`'s docstring claimed the smallest label gap "IS the bar duration", stronger than the mechanism on a pathologically sparse store | Docstring weakened to what it is: a fail-closed frequency check that errs toward refusal; the manifest's `bar_seconds` is the authoritative declaration. |

Suite after round 2: **291 passed, 5 xfailed**; gates 4/4; all 30 completion figures
and the flag census unchanged (doc-number corrections only — M-2 changed a *claim
about* the numbers, not the numbers).

## Initial developer response submitted for external audit round 3 (2026-07-28)

The round-3 audit confirmed the four round-2 repairs, then found one fresh medium
defect and one low mutation-coverage gap. These changes are implementation claims,
not an audit closure:

| # | Finding | Developer implementation |
|---|---|---|
| M-1 | `_as_scalar_int64` validated each operand, but valid operands could still overflow when `interval_end_ns` formed `start + interval` or an outcome function formed `tau + horizon` | Result bounds are now checked in exact Python integers before NumPy arithmetic. `test_negative_int64_result_arithmetic_overflow_fails_closed` covers all three public result-producing paths and exact-boundary positive controls. |
| L-1 | Changing the inclusive scalar range check to strict inequalities rejected valid `INT64_MIN`/`INT64_MAX` values but survived the suite | `test_exact_int64_boundaries_are_accepted_when_arithmetic_is_safe` pins both scalar endpoints through public entry points, including a representable `np.uint64(INT64_MAX)`. |

Developer replay after these changes: **293 passed, 5 xfailed**; gates 4/4; completion
figures and session flags unchanged. D12 remains **OPEN** and still blocks Phase 3.

### Developer response to the round-3 audit finding — pending Opus 5 verification

The round-3 audit verified both fixes above, but correctly returned **FAIL** because
the original fixed-offset mutation had not been applied independently to both
timezone-conversion sites. Replacing `TimeModel.ct_minute_of_day`'s conversion with
fixed UTC−5 survived all 293 tests: every direct caller fixture was in CDT, where
UTC−5 is accidentally correct.

`test_ct_minute_of_day_tracks_cst_and_cdt_not_a_fixed_offset` now drives that public
method with the same 08:30 CT wall minute in both summer and winter. The instants
are 13:30 and 14:30 UTC respectively, while both must map to CT minute 510 and the
open phase. In an external scratch clone the named test fails under both mutations:
fixed UTC−5 maps winter to minute 570; fixed UTC−6 maps summer to minute 450.

Developer replay after this change: **294 passed, 5 xfailed**; gates 4/4; completion
figures and session flags unchanged. This is an implementation claim pending Opus
5's independent audit. D12 remains **OPEN** and continues to block Phase 3.

## What was not verified

- Whether any of the 34 observed short sessions was a *scheduled* early close —
  impossible without a versioned CME calendar table, and not claimed (D11b).
- Completion-vs-**volatility-state** (the full §16.5-item-6 program) cannot be
  measured until conditioners exist (Phase 7); completion-vs-year and vs-phase are the
  Phase 2 slice of it, and neither is evidence about volatility.
- The engine is proven correct for 5-minute bars only. It now *refuses* other
  frequencies (M-5) rather than assuming them, but no other frequency was tested for
  correctness — refusal is the claim, not support.
- `_assert_sessions_own_their_bars` enforces the CME trade-date rule specifically, so
  it is meaningful only for a CME session calendar; the Khartoum guard fixture
  deliberately runs before it.
