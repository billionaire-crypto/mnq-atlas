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
completion rates are over that population. `weight_ess` is NaN until Phase 4 and is
omitted from the tables below for width.

### Completion by phase × horizon

| phase | Δ | n_anchors | n_sessions | rate fully_labeled_1m_grid | rate observed_bar_path |
|---|---|---|---|---|---|
| open | 15 | 6,038 | 1,008 | 0.99868 | 0.99917 |
| open | 30 | 6,038 | 1,008 | 0.99801 | 0.99884 |
| open | 60 | 6,038 | 1,008 | 0.99669 | 0.99818 |
| morning | 15 | 18,125 | 1,008 | 0.99895 | 0.99967 |
| morning | 30 | 18,125 | 1,008 | 0.99834 | 0.99945 |
| morning | 60 | 18,125 | 1,008 | 0.99757 | 0.99912 |
| midday | 15 | 24,003 | 1,006 | 0.99429 | 0.99588 |
| midday | 30 | 24,003 | 1,006 | 0.99000 | 0.99175 |
| midday | 60 | 24,003 | 1,006 | 0.98188 | 0.98350 |
| afternoon | 15 | 17,532 | 974 | 0.99949 | 1.00000 |
| afternoon | 30 | 17,532 | 974 | 0.99926 | 1.00000 |
| afternoon | 60 | 17,532 | 974 | 0.99914 | 1.00000 |
| close | 15 | 9,740 | 974 | 1.00000 | 1.00000 |
| close | 30 | 6,818 | 974 | 1.00000 | 1.00000 |
| close | 60 | 974 | 974 | 1.00000 | 1.00000 |

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
  ≥0.99669 elsewhere) — quiet-regime minutes are the ones that go missing, so
  "quiet → less observable" is live in this data.
- The gap between the two estimands (bars present but partially labeled) is
  concentrated in 2019–2020; from 2021 on the two rates coincide to 5 decimals.

The magnitudes are small (worst cell ≈ 1.8% incomplete), but the *direction* is the
§6 confound made real, and any Phase 3+ result conditioned on year, phase, or
volatility must carry it. Phase 3 computes `s00_p05` and freezes
`min_completion_h15/h30/h60` with a ledger entry — deliberately **not done here**.

### Session flags (D11b)

35 sessions flagged `observed_rth_ended_early` (25 ending 12:00 CT, 7 at 12:15, 1 at
10:00, 1 at 09:15, 1 with zero RTH bars: 20210402, `last_rth_bar_end_ct_minute = -1`);
4 sessions flagged `observed_mid_rth_gap`; none flagged both. No calendar claim is
made or possible (D11b); `calendar_early_close` is `"unknown"` for every session.

## Reproducible commands

```powershell
# full suite (Phase 1 + Phase 2): expect 279 passed, 5 xfailed
python -m pytest tests -q

# Phase 2 gate tests only
python -m pytest tests/test_time_and_timezone.py tests/test_event_time_conditioner.py tests/test_window_boundaries.py tests/test_estimand_definition.py -q

# the four Phase 1 fail-closed gates, unchanged: expect 4/4 pass
python -m mnq_lab.spine.gates --store data

# completion accounting over the exploration store (JSON to stdout)
python -m mnq_lab.outcomes.completion --store data
```

## What was not verified

- Whether any of the 35 observed short sessions was a *scheduled* early close —
  impossible without a versioned CME calendar table, and not claimed (D11b).
- `BAR_MINUTES = 5` is asserted structural to the bars_5m store (all 274,847
  exploration labels sit on the 300 s grid — measured) but is not a YAML constant; a
  future store at another frequency must not reuse this module unchanged.
- Completion-vs-**volatility-state** (the full §16.5-item-6 program) cannot be
  measured until conditioners exist (Phase 7); completion-vs-year and vs-phase are the
  Phase 2 slice of it.
