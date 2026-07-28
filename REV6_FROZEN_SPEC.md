# MNQ Empirical Market Atlas — Rev 6 (FROZEN SPECIFICATION)

> **Status: FROZEN.** This document supersedes revs 1–5 entirely. Where earlier revisions differ, they are wrong — do not consult them. Every component has exactly one executable rule here.
>
> **Struck rules from earlier revs are listed in §14 so they cannot be reintroduced.**
>
> Changes to anything in §4 or `analysis_constants_v1.yaml` require a ledger entry **before** the affected result is computed, never after.

---

## 1. Context

The pre-registered LoRA experiment returned `reject_price_only_program`: median AUC 0.5002640, CI [0.4950300, 0.5055930], p = 0.4787504, accuracy 0.51404 *below* the 0.51680 positive rate. Price-history-only direction prediction on MNQ at 10 minutes is dead, and it was killed properly.

The gap is not modeling capacity. We have **no measured facts about MNQ** — only public ones, whose prior odds are low precisely because they are public.

This builds:

> **A versioned empirical map of when market states occur, whether those states are stable enough to mean anything, what path distributions follow them, and how often equally convincing structure appears after the proposed relationship is deliberately destroyed.**

Three layers in order: **state validity → state prevalence → conditional path.** Without the first, one can find a stable path difference for a category whose meaning drifted underneath it.

**This is a measurement instrument, not a strategy search.** It produces facts hypotheses are later built *from*, in a separate lab.

---

## 2. How this document was produced (read before trusting it)

Six adversarial review rounds. Every load-bearing defect was caught by **querying the data**, never by re-reading prose:

| Defect | How it was caught |
|---|---|
| `np.quantile` default is not replication-invariant | Ran it: q=0.25 gives 0.25 at K=1, 0.0 at K≥2 |
| Bar timestamps are open, not close | Maintenance-halt labels: `15:59` last, none in `[16:00,17:00)`, `17:00` first |
| RTH boundary ambiguity would have cost an hour | Volume profile: 5× jump at 08:30 CT, the day's highest minute |
| "Vendor omits no-trade bars" was inferred, not computed | Only *observed* fact: 0 explicit zero-volume rows |

Recurring failure mode across all six rounds: **a fluent claim stronger than its mechanism** — "structural" guards that were friction, a conditioner that "cannot be constructed," a test oracle that was invalid, a worked example with no timezone.

**Instruction to the implementing session: when this spec asserts something you could check against the data, check it.** Report contradictions rather than coding around them.

---

## 3. Verified findings

| # | Finding | Status |
|---|---|---|
| A | `np.quantile` default `linear` is **not** replication-invariant; `inverted_cdf` is | Computed |
| B | **0 explicit zero-volume rows** in 3,665,228. *Therefore* absent intervals cannot be classified no-trade vs missing-data. The vendor's generation rule is **not** established | Computed / inference marked |
| C | Roll fixture valid: 28 rolls, 2019-06-18 → 2026-03-18 (~6.75y × 4 quarterly) despite the `3y` filename. `trigger_trade_date` = `effective_trade_date − 1` | Computed |
| D | Source 2019-05-05 → 2026-03-29; 87 symbols; MNQ outrights **98.4%**, remainder calendar spreads. The `20100606` in the filename is the request start | Computed |
| E | `ts_event` is the bar **OPEN**; interval `[t, t+60s)` | Computed |
| F | RTH `[08:30, 15:00)` CT = **71.2%** of volume. 08:29 → 08:30 volume jumps 0.146% → 0.724% | Computed |

---

## 4. Frozen constants

```
Storage timestamps      UTC nanoseconds
Session calendar        America/Chicago
Bar label semantics     ts_event = bar OPEN; interval [t, t + bar_seconds)
RTH                     [08:30, 15:00) CT  =  [09:30, 16:00) ET
Maintenance break       [16:00, 17:00) CT
Globex session          17:00 CT -> 16:00 CT next day
Tick size               0.25 index points  (prices stored int32 ticks)
Study configs           exchange-local CT unless explicitly overridden
Reports                 label both CT and ET
```

### 4.1 The time model

```
anchor bar label        08:30 CT  /  09:30 ET
covers                  [08:30, 08:35) CT
close observed at       08:35 CT              <- anchor_observation_time
time-of-day bucket      keyed on 08:35, NEVER on the 08:30 label
outcome window          [08:35, 08:50) CT     (delta = 15 clock minutes)
required bars           08:35, 08:40, 08:45   all present, all 1-min complete
```

**The general rule, in event time — not as an implementation:**

> At observation time τ, a **conditioner** may use every return whose ending timestamp ≤ τ and none ending after τ. An **outcome** may use only the path strictly after τ.

Consequences, which are *different rules and must not be conflated*:
- The anchor bar's own return **enters** the volatility state — it ends exactly at τ and is the freshest information available
- The anchor bar's own high/low is **excluded** from the excursion — realized by τ, so including it measures known movement as if it were future

`shift()` is one possible implementation of the above. **It is never the specification.**

### 4.2 Session phases (observation-time CT)

```
open       [08:30, 09:00)     30 min
morning    [09:00, 10:30)     90 min
midday     [10:30, 12:30)    120 min
afternoon  [12:30, 14:00)     90 min
close      [14:00, 15:00)     60 min
```

**Registered prediction, so it cannot later be reported as a discovery:** RTH-bounded windows make `close` structurally thin at long horizons. Δ=60 requires τ ≤ 14:00 → **1 eligible anchor/session**; Δ=30 → 7; Δ=15 → 10. Expect `close × Δ60` to return `insufficient_anchors`. This is a consequence of the RTH-only decision, not a market fact.

### 4.3 Volatility estimator

```
Bar-level scale     causal EWMA RMS of 5-min log returns, halflife 78 bars (one RTH session),
                    using all returns ending <= tau; reset at contract roll with 78-bar warmup;
                    gaps break the recursion rather than bridging it.

Seasonal profile    per 5-min bucket keyed on OBSERVATION time; MEDIAN scale over all strictly
                    prior completed sessions, after 60-session warmup. When a bucket has n < 30
                    prior observations, shrink toward the session-phase median with weight
                    n/(n+30). Absent bucket -> session-phase median.

Holiday handling    from a VERSIONED CME calendar table. Full exchange holidays AND early closes
                    are excluded from the seasonal reference profile but RETAINED in outcome
                    studies with a flag. Holiday-adjacent and unscheduled closures are flagged,
                    not excluded. No informal labels.

vol_rel             bar scale / seasonal profile

Terciles            warmup-then-expanding: no assignment before session 60; thereafter boundaries
                    are empirical quantiles over ALL strictly prior completed sessions. One
                    distribution per session phase, each prior session contributing equal total
                    mass across its eligible anchors. Realized frequencies reported -- expanding
                    bins will NOT yield exact thirds forward.
```

**Independent scale estimator** (for the normalization sensitivity only — deliberately non-exponential so it is not a re-parameterization of the same estimator):

```
MAD_scale(tau) = 1.4826 * median( |r_i - median(r)| )
                 over the 78 most recent completed, CONTIGUOUS returns ending <= tau
Centering        the median of those same 78 returns
Undefined when   fewer than 78 valid returns, OR MAD == 0
Reset at         contract roll and at any gap breaking contiguity
```

**Raw ticks are the primary outcome.** Conditioning on `vol_rel_tercile` while dividing outcomes by the same scale mechanically flattens the relationship being measured. Normalized forms are secondary, with the shared estimator disclosed on every affected panel.

---

## 5. Data spine

Rebuild 1-min and 5-min continuous active-contract bars, 2019-05-05 → 2026-03-29. Reuse `scan_daily_outright_volume`, `build_causal_active_contract_map`, `collect_active_rows`, `resample_active_chain_to_five_minutes`, `_trade_date_strings` from `prepare_databento_mnq.py`.

**Store format: `.npy` column store.** `pyarrow` and `fastparquet` are both absent; `to_parquet()` raises `ImportError`. One `.npy` per column plus `manifest.json` with per-file sha256, reusing `_sha256_file` (`data_pipeline.py:113`). Loads via `mmap_mode="r"`.

**Component coverage is written during resample** (so no 1-min spine is needed at study time): `expected_1m_components`, `observed_1m_components`, `component_coverage_rate`, `first_component_time`, `last_component_time`.

**Session index computed once in the spine.** Never call `lora_statistics.cme_session_ids` at study time — it is a Python loop with per-row tz conversion. It survives only as a DST test oracle.

### 5.1 Four fail-closed gates

1. Rebuilt roll list == the verified 28-roll fixture (finding C)
2. Rebuilt 5-min bars 2023-03-29 → 2026-03-29 **row-for-row identical** to `data/mnq_active_5m_3y.csv`
3. **Symbol classification, not a percentage.** Every retained symbol matches the outright MNQ pattern; every rejected symbol matches an explicit spread pattern; exact counts recorded in the manifest and re-versioned on a new source. The classifier is authoritative
4. **Roll causality, directly.** Rule: session *d*'s contract is fixed **entirely from volumes through completed session *d−1***. Prefix invariance is *not sufficient* — a map using a full day's volume to pick that same day's contract stays prefix-invariant once the day completes. **The fixture must diverge from 17:00 CT at the start of session *d*** (an RTH-open divergence would miss a procedure using session *d*'s own overnight volume from 17:00–08:29). Two versions identical through the end of session *d−1*, then wholly different volume throughout session *d*; assignment must be identical **and frozen for the entire Globex session**, never recalculated at RTH

**On any gate failure: STOP.** Locate the first mismatching session, classify the cause (roll mapping / missing bars / timestamps / aggregation / duplicates / source revision), then either reproduce the original pipeline exactly or rebuild *both* corpus tiers under a new pipeline version. **Never bridge two data definitions** — a difference would be unattributable between market and pipeline.

**Roll resets:** trailing trend, EWMA scale, and range state reset at contract boundaries. A basis change at roll mimics momentum and volatility.

---

## 6. Missingness and the complete-window estimand

Finding B means a missing minute is unclassifiable. Rejecting incomplete windows avoids inventing prices but **creates a selection effect aligned with the conditioning dimensions** — preferentially removing 2019, overnight, quiet regimes, and holidays while retaining liquid, active, possibly more volatile conditions. So *"high volatility → larger excursions"* could partly mean *"high volatility → more likely observable."*

**5-min bar existence is not sufficient.** A 5-min bar may aggregate fewer than five 1-min rows, and the missing minutes hide exactly the extremes excursion quantiles are made of.

Two estimands, named to claim only what the data support (all five 1-min labels present proves every expected interval has an OHLCV row — not that the feed captured every trade; and the source is bars, not trades):

- **`fully_labeled_1m_grid`** — S01A primary; every 5-min bar in the path contains all five expected 1-min labels
- **`observed_bar_path`** — excursions across the bars present in the source

**Fail closed**, not merely report:

```python
raw_threshold  = math.floor(s00_p05 * 100) / 100
min_completion = max(0.90, raw_threshold)
```

where `s00_p05` is the 5th percentile of S00 cell completion rates over a frozen population: **RTH only · the exact five phases of §4.2 · 2019-05-05 through 2023-03-29 · `fully_labeled_1m_grid` criterion · thin cells included · holidays and early closes included and flagged.**

**Thresholds are horizon-specific** — `min_completion_h15`, `min_completion_h30`, `min_completion_h60` — because a pooled threshold would conceal that long-horizon close-period support is structurally worse (§4.2's registered prediction).

`status = insufficient_completion` also fires when completion imbalance between compared cells exceeds `0.05` absolute, or when accepted sessions concentrate in one year or era.

Every section states: *these estimates apply to anchors with fully observed clock-time paths, not to all MNQ market time.* **S01A is RTH-only** — 71.2% of volume (finding F).

---

## 7. Estimands, weights, bootstrap

### 7.1 Three labelled estimands — none universally primary

Session composition is a real confound: morning high-vol may occur chiefly on news days while afternoon high-vol occurs on trend days. But requiring both states to occur selects sessions that **switched state**, and at the first state's observation time one cannot know whether the second will occur later. That is not lookahead in computing the historical outcome, but it is **post-session selection** and cannot define a prospectively recognizable population.

1. **Prospective cell** — all sessions where the target cell occurs. **Primary for anything that will become a trading hypothesis**, because it is the only one recognizable live
2. **Common-session paired** — only sessions containing both conditions. A mechanism/robustness diagnostic, not prospectively selectable
3. **Standardized shared population** — both conditions reweighted to a preregistered common session population; the best formal comparison when overlap passes the positivity gate

**Within an estimand, `session_equal_weighted` is primary:** select uniformly among sessions containing ≥1 eligible cell anchor, then uniformly among that session's eligible anchors. Always reported with eligible sessions, sessions containing the cell, presence rate, median anchors per contributing session, and **max mass fraction from one session**.

**Companion:** `anchor_weighted`. **Sensitivity:** non-overlapping anchors on a deterministic clock grid using the **exact fixed timestamp or dropping the anchor** — never a tolerance window (which gives different sessions different clock exposure), never selected on volatility, movement, or volume.

### 7.2 Weighted statistics

```
Q(q) = inf{ x : (sum_{x_i <= x} w_i) / (sum w_i) >= q }
```

Step-function, replication-invariant, validated against `np.quantile(repeated, q, method="inverted_cdf")` — **never the default `linear`** (finding A). Real-valued nonnegative weights subsume bootstrap integer counts and fractional baseline mass on one code path, so point estimate and CI cannot diverge.

`weight_ess = (Σw)² / Σw²` — **named `weight_ess`, never "effective sample size."** It measures weight concentration only and corrects for none of overlapping outcomes, serial dependence, or regime dependence. Always displayed beside anchor count, session count, and interval.

### 7.3 Bootstrap

Whole-session stationary block resample. Sample whole session IDs until the original session **count** is reached; the final *block* may be truncated by session count, **never an individual session by rows** — that is the defect in `lora_statistics.stationary_session_resample` (negligible pooled, systematically under-weighting late-session buckets). The original stays untouched for LoRA reproducibility.

**One resample serves the entire tidy frame** — jointly coherent CIs, naturally varying per-cell n, paired contrasts free. Resampling inside a pre-filtered cell would treat "sessions containing this condition" as the population and pin n artificially.

**Block-length sensitivity at 1, 5, 10, 20 sessions.** A conclusion reversing between 5 and 10 is not a conclusion.

Every interval carries: *this measures uncertainty within the historical mixture, not uncertainty about future regime change.*

**Conditioner-estimation uncertainty is excluded by construction** and made visible instead: intervals condition on realized labels; alternative definitions are run (**tercile thresholds shifted ±2 and ±5 percentile points; rolling-60-session vs expanding; EWMA halflife 39 and 156 vs 78**); **cell migration rates** reported; conclusions checked for survival.

**Horizon support:** emit both horizon-specific (max data) and common support (only anchors valid at max horizon).

---

## 8. Contrasts

`degenerate_baseline` fires **only when target and baseline supports are mathematically identical** — comparing morning-high-vol against high-vol in other phases is the *useful* contrast, not a degenerate one.

| Name | Question |
|---|---|
| `absolute_distribution` | Outcome distribution in (*p*, *v*) |
| `phase_effect_given_vol` | Does phase *p* differ from other phases, holding *v* fixed? |
| `vol_effect_given_phase` | Does state *v* differ from other states, within phase *p*? |
| `cell_vs_complement` | Does this combination differ from everything outside it? |
| `cell_vs_population` | Versus the whole population **including itself** — dilutes; valid, read as such |

**"Other phases" weighting — emit both, interpretations labelled, choice never made after seeing results:**
- `equal_phase_contrast` — each comparison phase session-equal weighted internally, then phases equal-weighted against each other, so midday's longer duration cannot dominate. Answers: *how does the target phase compare with an artificial average giving every phase equal importance?*
- `natural_prevalence_contrast` — pooled at natural anchor frequency. Answers: *how does it compare with the other market time actually encountered?*

Same rule for `vol_effect_given_phase` across states.

**Positivity gate:** ≥ 30 baseline anchors per stratum, ≥ 20 contributing sessions, max single-anchor weight share ≤ 0.02 of stratum mass, weight CV ≤ 2.0, ≤ 5% of target mass in unsupported strata. Breach ⇒ `insufficient_overlap`. **No clipping.**

**Interaction estimand.** Quantiles are not additive (`Q₀.₉(X+Y) ≠ Q₀.₉(X) + Q₀.₉(Y)`), so "open effect + high-vol effect" is not a decomposition law. Frozen as an explicit quantile difference-in-differences against `p₀ = midday`, `v₀ = mid`:

```
I(p,v,q) = [ Q_q(Y | p, v) - Q_q(Y | p, v0) ] - [ Q_q(Y | p0, v) - Q_q(Y | p0, v0) ]
```

A chosen contrast, explicitly — not a natural law, not a causal claim. **Requires one common population across all four cells**; pairwise common-session does not fix a four-term contrast, or the number mixes phase effect, volatility effect, population composition, and the intended interaction.

```
MVP:      interaction_support = four_cell_common_sessions
          -> report when support is adequate, else `insufficient_interaction_support`
DEFERRED: four_cell_standardized_population, until its target population, covariates,
          weighting model, strata, and positivity thresholds are separately specified
```

---

## 9. Inference

### 9.1 Exactly one formal test in the MVP

| Test | Status |
|---|---|
| `vol_given_phase` | **Formal.** Whole-session trajectory reassignment (§9.2) |
| `phase_given_vol` | **Descriptive only, no p-value.** Circular within-session rotation is *invalid*: it makes 14:55 CT adjacent to 08:30 CT (not a possible market path); it destroys the volatility–outcome association as well as the phase one when the vol trajectory stays fixed; and it relocates a 60-min outcome from 09:00 to 14:30 where that support cannot exist |
| `interaction` | **Descriptive only, no p-value.** "Trajectory reassignment within phase" is not executable: a trajectory spans phases, so segmenting it breaks transitions, alters run lengths, splits episodes, and can pair segments with mismatched completion support |

Both deferred tests await null generators that pass Type-I calibration, marginal preservation, state-transition preservation, completion-support, and localization-power tests. **The atlas does not need a p-value for every descriptive relationship**, and the weakest inferential mechanism must not delay or contaminate the strongest measurement system.

### 9.2 The retained null — exact mapping algorithm

Strata: **calendar-quarter × liquidity-era.** Event-day strata (FOMC/CPI/NFP/opex) are **not** used — no verified event calendar exists locally, and inventing one is worse than declaring the gap. Event-day stratification is a declared future variant contingent on a versioned calendar.

```
1. Restrict formal inference to ordinary full-length RTH sessions.
   Early closes and holidays are excluded from the permutation population.
2. Build each session's state vector on the exact canonical observation-time grid.
3. Keep the RECIPIENT session's outcomes and completeness mask fixed.
4. Reassign only the DONOR's state vector.
5. Preserve undefined/warmup entries from the donor vector.
6. Permute WITHOUT replacement within each stratum.
7. Disallow self-assignment where the stratum permits.
8. Strata with fewer than 20 sessions are marked unusable, not silently pooled.
9. Use ONE joint permutation across all outcomes, horizons and statistics within a
   replication, to preserve joint dependence.
```

**Null interpretation, stated in every report:**

> Conditional on the observed state trajectories and the declared exchangeability strata, there is no special pairing between a session's volatility-state trajectory and another session's subsequent outcome path.

This is **not** a test of the online volatility-estimation procedure. It treats realized labels as fixed objects.

### 9.3 The p-value

```
B          4999 permutations for final analysis (fewer permitted in unit/dev tests only)
p          ( 1 + sum_b [ T_b >= T_observed ] ) / ( B + 1 )
Sided      one-sided upper (T is a max statistic)
Ties       counted in the numerator via >=
RNG        numpy PCG64, seed recorded in the artifact
Stopping   none; early stopping forbidden
```

999 permutations is barely sufficient for a minimum p near 0.01; 4999 is the frozen value.

### 9.4 The surface family

**One surface = one outcome × one horizon × one statistic × one contrast × one estimand, over the 5 × 3 phase-volatility lattice.** A connected region may never span different horizons, outcomes, or quantiles as though they were adjacent geometric cells.

**Primary S01A surface, chosen from the economic objective (stop placement) before execution:**

```
outcome    downward excursion
horizon    30 minutes            (delta=60 leaves the close phase with 1 anchor)
statistic  90th percentile       (stop distance is a tail question)
contrast   vol_effect_given_phase
estimand   prospective cell      (a stop must be set from what is recognizable at entry)
```

All other surfaces are **descriptive**. **The smallest p-value across surfaces is never reported.**

### 9.5 Surface-coherence statistic (frozen before seeing MNQ results)

Detects coherent **negative** structure as well as positive — a state consistently producing *smaller* excursions is equally important.

```
z_c        standardized contrast per cell
positive region   maximal set of 4-adjacent cells (NOT diagonal) with z_c > +1.0
negative region   maximal set of 4-adjacent cells (NOT diagonal) with z_c < -1.0
                  on ORDERED families only; missing/insufficient cells break adjacency
stability(R)      fraction of yearly blocks in which R's mean contrast keeps its sign

T_plus  = sqrt(|R|) * mean_{c in R}( z_c)  * stability(R)     over positive regions
T_minus = sqrt(|R|) * mean_{c in R}(-z_c)  * stability(R)     over negative regions
T       = max( max T_plus, max T_minus )
```

**`abs(z)` is never used inside a region** — it would merge adjacent opposite-sign cells into a falsely "coherent" region.

`SurfaceTopology` per family: `session_phase` and `vol tercile` are **ordered chains**; `liquidity_era` is an **ordered calendar**; `day_type` is **unordered**, so connected regions are undefined there.

### 9.6 Calibration, honestly scoped

The lab **demonstrates acceptable calibration under preregistered null processes that preserve the most important observed dependencies.** It cannot prove false-positive behaviour under every plausible market process: a permutation may preserve session structure and marginal volatility while destroying regime persistence, long-range dependence, or the missingness–volatility relationship.

**Synthetic session generators are deferred** — a simulator that "preserves volatility clustering" is itself a model with many design choices and can supply false reassurance.

**Negative controls:** *synthetic* controls have nulls known by construction and test calibration and code; *real-market* controls have merely plausible nulls and are diagnostics — regime persistence and seasonality can make one reject legitimately. Use **repeated randomized controls judged by rejection frequency**, never a single pass. Rejection halts interpretation pending diagnosis; it may indicate a bad control rather than a bad lab.

**Max-t simultaneous bands are deferred** until the bootstrap is independently calibrated: SEs are unstable for extreme quantiles in thin cells, cells are highly dependent, and a centered confidence band is not automatically a valid null distribution.

---

## 10. State validity and prevalence

### 10.1 State validity — descriptive only in S01A

Per conditioner level: category frequency, average run length, transition entropy, cell migration under alternative definitions, threshold drift through time, correlation with raw volatility, **correlation with missingness/completion**, correlation with liquidity era, fraction undefined/warmup.

**No state is automatically passed or failed in S01A, and no composite "state quality score" is invented.** Thresholds set before their distributions are known would be the same tuning this lab exists to avoid. Later hypotheses preregister validity requirements against the now-known diagnostic ranges.

### 10.2 Prevalence, on its own support

Prevalence must not depend on whether a future window is complete — otherwise a 14:30 CT state counts at Δ=15 but vanishes at Δ=60 for lack of remaining session, making prevalence horizon-dependent though the condition never changed.

```
state_anchors                  condition assigned causally at tau, regardless of outcome availability
outcome_eligible_anchors_h15   condition AND complete 15-min window
outcome_eligible_anchors_h30
outcome_eligible_anchors_h60
```

Occurrence decomposed explicitly: **bar occupancy**, **episode** (one continuous run), **session presence**, **entry** and **exit transitions**. Transitions reset at session boundaries, missing intervals, contract rolls, and warmup — so a state ending Friday and one beginning Sunday is never one episode.

---

## 11. Corpus tiers, guardrails, provenance

| Tier | Span | Status |
|---|---|---|
| Exploration | 2019-05-05 → 2023-03-29 (~985 sessions) | Free use |
| Locked confirmation | 2023-03-30 → 2026-03-29 | Post-preregistration only. **Explicitly contaminated** by prior Kronos/LoRA train+validation work |
| Forward vintages | Sessions accruing after freeze | The only untouched evidence |

Physically separate `data/exploration/` and `data/locked_confirmation/`; the exploration runtime does not import or mmap the locked store. `Corpus.EXPLORATION` is truncated at `seal_boundary − max_horizon_bars` so rows are absent from the object, not merely flagged. **Friction plus procedure — no encrypted-service theater around already-contaminated data.**

**Forward testing schedule (frozen):** one primary confirmatory hypothesis per vintage at **α = 0.01**, hard program cap of **5 confirmatory tests** before full re-preregistration. Familywise bound ≈ 0.05 by Bonferroni without requiring independence.

After five tests the counter **does not reset**. A new program requires a new declared research family, justification, and preregistration under a new permanent `program_id` with recorded lineage. **Previously consumed vintages remain consumed. A failed family may not be cosmetically renamed and restarted.** A failed forward result may not be revised and re-run on the same vintage.

**Guardrails are friction, not structure.** A regex banning `pnl|profit|expectancy|sharpe` stops nothing — write `score`. `up_first` at a fixed ladder **is** a stop-versus-target race regardless of name. Retained as *accidental-selection friction*: forbidden names, `SelectionAttemptError` on `sort_values`/`nlargest`/`idxmax`/`argmax`/`rank`, full cross-product asserted so thin cells surface with `status`, canonical row order never sorted by a measured value, grids frozen per `study_version`.

The **actual** protections: preregistration, immutable study definitions, complete output, the ledger, access control, forward vintages, human discipline. Stated inside the Field Guide, because a reader who believes the code prevents selection will select more freely.

**Two registries:** `register_causal_conditioner` (must pass the declared adversarial suite) and `register_descriptive_conditioner` (exempt, permanently marked `NONCAUSAL — NOT ELIGIBLE FOR CONFIRMATION`). Only causal conditioners serve confirmation or forward studies. A conditioner cannot enter the *causal* registry unless it passes the suite — that is an empirical test, not a proof.

**Hypothesis provenance logged:** source atlas run IDs, sections viewed, motivating cells, date written, exploration-only status, exact confirmation test. The exploration interval can never be cited as independent confirmation — it generated the hypothesis. Chain: *exploration observation → frozen hypothesis → contaminated historical confirmation → untouched forward vintage.*

**Reporting discipline:** pointwise intervals across many cells are descriptive. **No stars, no red/green highlighting, no "significant cell" language** unless the preregistered family procedure supports it.

---

## 12. `analysis_constants_v1.yaml`

**S01A refuses to run if any constant is absent.** No defaults, no inline literals. Report specification tables are **generated from this file** so prose cannot drift from code.

```yaml
spec_version: 6
program_id: mnq-atlas-001

time:
  storage_tz: UTC
  session_tz: America/Chicago
  bar_label: open                 # ts_event = interval start
  rth_start_ct: "08:30"
  rth_end_ct:   "15:00"
  maintenance_break_ct: ["16:00", "17:00"]
  tick_size: 0.25

session_phases:                   # observation-time CT
  open:      ["08:30", "09:00"]
  morning:   ["09:00", "10:30"]
  midday:    ["10:30", "12:30"]
  afternoon: ["12:30", "14:00"]
  close:     ["14:00", "15:00"]

horizons_minutes: [15, 30, 60]

volatility:
  ewma_halflife_bars: 78
  seasonal_warmup_sessions: 60
  seasonal_min_bucket_obs: 30
  seasonal_shrink_k: 30           # weight = n / (n + k)
  tercile_scheme: warmup_then_expanding
  independent_estimator:
    kind: rolling_mad
    window_bars: 78
    scale_factor: 1.4826
    require_contiguous: true

alternative_definitions:
  tercile_shift_pctpoints: [-5, -2, 2, 5]
  rolling_window_sessions: [60]
  ewma_halflife_bars: [39, 156]

estimands:
  path: fully_labeled_1m_grid     # alt: observed_bar_path
  weighting_primary: session_equal_weighted
  population_primary: prospective_cell
  population_diagnostic: common_session_paired
  population_formal: standardized_shared_population

completion:
  source_population:
    rth_only: true
    years: ["2019-05-05", "2023-03-29"]
    include_holidays_flagged: true
    include_thin_cells: true
  rule: "min_completion = max(0.90, floor(s00_p05 * 100) / 100)"
  horizon_specific: true          # min_completion_h15 / h30 / h60
  max_imbalance_absolute: 0.05

positivity:
  min_baseline_anchors_per_stratum: 30
  min_contributing_sessions: 20
  max_single_anchor_weight_share: 0.02
  max_weight_cv: 2.0
  max_unsupported_target_mass: 0.05

bootstrap:
  scheme: whole_session_stationary
  mean_block_sessions_primary: 5
  block_sensitivity: [1, 5, 10, 20]
  truncate_partial_session: false

interaction:
  reference_phase: midday
  reference_vol: mid
  support: four_cell_common_sessions

inference:
  formal_tests: [vol_given_phase]
  descriptive_only: [phase_given_vol, interaction]
  null:
    kind: whole_session_trajectory_reassignment
    strata: [calendar_quarter, liquidity_era]
    min_sessions_per_stratum: 20
    exclude_early_close: true
    exclude_holidays: true
    without_replacement: true
    disallow_self_assignment: true
    joint_across_outputs: true
  permutations_final: 4999
  permutations_dev_min: 199
  p_value: "(1 + #{T_b >= T_obs}) / (B + 1)"
  sided: one_sided_upper
  rng: PCG64
  rng_seed: 20260728
  early_stopping: false

surface:
  definition: "one outcome x one horizon x one statistic x one contrast x one estimand over 5x3"
  primary:
    outcome: downward_excursion
    horizon_minutes: 30
    statistic: q90
    contrast: vol_effect_given_phase
    estimand: prospective_cell
  z_threshold_positive:  1.0
  z_threshold_negative: -1.0
  adjacency: rook            # 4-adjacent, NOT diagonal
  use_abs_z: false
  ordered_families: [session_phase, vol_rel_tercile, liquidity_era]
  unordered_families: [day_type]

forward:
  alpha_per_vintage: 0.01
  max_confirmatory_tests: 5
  reset_allowed: false

reporting:
  significance_markers: false
  require_n_sessions_beside_n_anchors: true
  require_weight_ess: true
```

---

## 13. Verification suite

1. `test_time_and_timezone` — the §4.1 worked example asserted exactly; **a bar-end interpretation must fail**; RTH asserts 08:30/15:00 CT (finding F); coverage across both US DST transitions, early closes, and US/EU DST divergence weeks
2. `test_event_time_conditioner` — hand-built timestamps proving exactly which returns enter the state at τ; the anchor bar's own return **is** included, its path **is not**
3. `test_roll_causality` — **hard gate.** Two session versions identical through the end of session *d−1*, diverging from **17:00 CT**; assignment identical and frozen for the whole Globex session
4. `test_prefix_invariance` — build through T, rebuild through T+k; assert unchanged before T: contract assignments, roll boundaries, 5-min bars, session IDs, **seasonal profiles, tercile thresholds, conditioner assignments, prevalence results**, consumed-vintage artifacts
5. `test_component_coverage` — a 5-min bar from fewer than five 1-min rows is rejected under `fully_labeled_1m_grid`, retained-with-flag under `observed_bar_path`
6. `test_dependency_locality` — random **out-of-window** mutation leaves output bit-identical; sensitivity proven by a **deterministic witness fixture** per function, *not* random in-window mutation (a median is insensitive to changing a non-central value; a thresholded category may not flip). Bit-identity for ticks, integer categories, boolean masks; declared tolerance for floating estimators
7. `test_weighted_quantile` — inverse-CDF matches `np.quantile(repeated, q, method="inverted_cdf")` for rational weights, heavy ties, zero weights, n=1; asserts `linear` is not used
8. `test_bootstrap_properties` — all-ones weights reproduce the point estimate exactly; 95% CI covers a known synthetic median within a **preregistered binomial interval** over 300 replications; AR(1)-within-session data gives materially wider session-block CIs than an i.i.d. row bootstrap
9. `test_null_calibration` — Type-I ≈ α **within Monte Carlo binomial bounds** (6.3% vs 5.0% at 300 reps is not a failure). Power: positive overall trend, intervals consistent with increasing power, strong effects clearly beating weak, localization overlap improving — **not** strict adjacent monotonicity
10. `test_permutation_mapping` — reassigns whole vectors only; preserves run lengths and transitions; recipient completeness masks unchanged; never crosses strata; exact multiset of trajectories preserved; one joint permutation across all outputs
11. `test_permutation_pvalue` — on a fixed list of observed and null statistics, assert the exact plus-one value
12. `test_surface_sign` — plant one positive and one negative region; both detectable; **opposite signs never merged into one region**
13. `test_spec_consistency` — load `analysis_constants_v1.yaml` and assert prose-derived critical values match: path estimand name, formal tests enabled, session phases, roll fixture start time, number of null engines, reference levels, completion rule
14. `test_prevalence_support` — prevalence invariant to Δ; `outcome_eligible_anchors_h*` shrink with Δ; episodes reset at session, gap, and roll boundaries
15. `test_completion_gate` — a low-completion cell returns `insufficient_completion` rather than a confident estimate
16. `test_baseline_contrasts` — `phase_effect_given_vol` and `vol_effect_given_phase` are **not** flagged degenerate; `degenerate_baseline` fires only on identical supports. `test_baseline_positivity` — a thin stratum triggers `insufficient_overlap`
17. `test_determinism` — **semantic determinism** (values within declared tolerance) always; **artifact determinism** (identical bytes) required only when the environment fingerprint matches exactly
18. `test_spine_fails_closed`, `test_roll_reset`, `test_estimand_definition`, `test_window_boundaries`, `test_1m_5m_consistency`, `test_session_id_equivalence`, `test_seal_guard`, `test_vintage_consumption`, `test_no_selection`

---

## 14. STRUCK — rules from revs 1–5 that must not be reintroduced

| Struck rule | Replacement |
|---|---|
| ~~`complete_1m_path` / `observed_trade_path`~~ | `fully_labeled_1m_grid` / `observed_bar_path` (§6) |
| ~~Common-session comparison is primary~~ | Three labelled estimands; **prospective cell** primary for trading hypotheses (§7.1) |
| ~~Three residual tests each with its own null~~ | **One** formal test: `vol_given_phase` (§9.1) |
| ~~`phase_given_vol` via circular within-session rotation~~ | Descriptive only, no p-value — the rotation is invalid (§9.1) |
| ~~`interaction` via within-phase trajectory reassignment~~ | Descriptive only, no p-value — not executable as written (§9.1) |
| ~~Roll fixture diverging at the RTH open~~ | Diverges at **17:00 CT**, start of session *d* (§5.1 gate 4) |
| ~~Region detection via `z_c > 1.0` only~~ | Positive **and** negative regions; `T = max(T₊, T₋)`; `abs(z)` never used (§9.5) |
| ~~"assert ≈1.6% spread rows"~~ | Symbol classifier authoritative with exact recorded counts (§5.1 gate 3) |
| ~~Anti-selection guards are "structural"~~ | Accidental-selection friction (§11) |
| ~~A leaky conditioner "cannot be constructed"~~ | Cannot enter the *causal registry* without passing the suite (§11) |
| ~~The lab "proves" its false-positive rate~~ | Demonstrates calibration under chosen nulls (§9.6) |
| ~~`np.repeat` + default `np.quantile` as test oracle~~ | `method="inverted_cdf"` (§7.2, finding A) |
| ~~`shift(1)` as the volatility specification~~ | Event-time rule; `shift` is an implementation (§4.1) |
| ~~Non-overlap sensitivity with ±5-min tolerance~~ | Exact timestamp or drop (§7.1) |
| ~~Synthetic session generators in the MVP~~ | Deferred (§9.6) |
| ~~Max-t simultaneous bands in the MVP~~ | Deferred (§9.6) |
| ~~Event-day permutation strata~~ | Deferred — no verified calendar exists locally (§9.2) |

---

## 15. Build order

| # | Phase | Days | Gate to pass before proceeding |
|---|---|---|---|
| 1 | Spine, `BarStore`, four fail-closed gates, component coverage | 4 | Tests 3, 4, 5, 18 |
| 2 | Time model + clock-window engine + completion accounting | 3 | Tests 1, 2 |
| 3 | S00 atlas; **freeze completion thresholds into the YAML** | 2 | Thresholds written and ledgered before S01A |
| 4 | Kernel core, inverse-CDF weighted statistics, `weight_ess` | 3 | Test 7 |
| 5 | Bootstrap: whole-session, block sensitivity, dual estimand | 3 | Test 8 |
| 6 | Dependency-window harness + witness fixtures + registries | 3 | Test 6 |
| 7 | Conditioners, frozen seasonal estimator, state-validity panel | 5 | Tests 6, 13 |
| 8 | Named contrasts + positivity gate + interaction estimand | 3 | Tests 15, 16 |
| 9 | Prevalence layer on its own support | 2 | Test 14 |
| 10 | Null engine: one retained null, software controls, surface calibration, deferred-null interfaces | 5 | Tests 9, 10, 11, 12 |
| 11 | Guards, ledger, vintages, forward budget, fingerprint | 3 | Test 17 |
| 12 | S01A-Descriptive + S01A-Calibration + Field Guide | 3 | End-to-end acceptance |
| | **Total** | **~39 focused engineering days after this spec is frozen** | |

**S01A splits in two:**
- **S01A-Descriptive** — state validity, prevalence, absolute path distributions, named contrasts, session-block uncertainty, yearly stability, completion diagnostics, alternative-definition migration. **No local significance declarations.**
- **S01A-Calibration** — synthetic software controls, the single retained null, Type-I and power testing, null-surface diagnostics.

**End-to-end acceptance:** spine → S00 → S01A → read `section.md`. Success is a page carrying **state validity, condition prevalence, and** conditional excursion quantiles in raw ticks — with session-count-honest intervals, completion rates, a per-year stability strip, null comparison, and block-length sensitivity; no ranking, no "best" parameter, no currency figure — **whose repeated negative controls rejected at approximately the nominal rate and whose planted-effect calibration showed power.**

---

# 16. HANDOFF — instructions for the implementing session

## 16.1 Read this first

You are implementing a **measurement instrument, not a trading strategy**. Nothing you build may rank cells by profitability, select a "best" parameter, or emit a currency figure. If a task seems to require that, you have misread the task.

**Read §14 (STRUCK) before writing any code.** Earlier revisions of this plan contained rules that are now wrong. If you find them quoted anywhere — in old notes, in a chat summary, in your own reasoning — §14 is authoritative.

## 16.2 Environment facts (verified; do not re-derive)

```
Platform            Windows 10, PowerShell primary (Bash also available)
Python              3.13.2 | pandas 3.0.1 | numpy 2.2.3
pyarrow/fastparquet ABSENT -- df.to_parquet() raises ImportError. Use .npy column stores.
Git                 The workspace is NOT a git repo (git log is empty).
                    Record "vcs": "none" in fingerprints; hash source files directly.
Source data         C:\Users\kyawz\Downloads\GLBX-20260331-885WT5W7KA\
                      glbx-mdp3-20100606-20260329.ohlcv-1m.csv   (402 MB, 3,665,228 rows)
                    Full streaming pass measured at 5.3 s -- this is NOT a scale problem.
                    The memory constraint is collect_active_rows' frame concat (1-2 GB peak
                    over 7 years). Fix with per-year shards, not clever chunking of the read.
```

**Reuse, do not reimplement** (all under `C:\Users\kyawz\Documents\Codex\2026-07-27\role-context-you-are-an-elite\`):

| File | What to reuse |
|---|---|
| `prepare_databento_mnq.py` | `scan_daily_outright_volume`, `build_causal_active_contract_map`, `collect_active_rows`, `resample_active_chain_to_five_minutes`, `_trade_date_strings` |
| `lora_statistics.py` | `session_row_groups`; `stationary_session_resample` as the **reference to generalize** (do not call it — it truncates the final session); `cme_session_ids` as a **DST test oracle only** |
| `data_pipeline.py` | `_sha256_file` (:113), `_cme_session_mask`, CME timezone constants |
| `scale_only_targets.py` | `lagged_ewma_rms` |
| `data/mnq_active_5m_3y.csv.manifest.json` | The verified 28-roll regression fixture |

## 16.3 Package layout

```
mnq_lab/
  spine/      build.py store.py calendar.py seal.py
  core/       barframe.py protocols.py causality.py units.py weights.py
              bootstrap.py contrasts.py kernel.py result.py
  conditioners/  outcomes/  nulls/  studies/  report/  ledger/
tests/
field_guide/
analysis_constants_v1.yaml
```

**Responsibility rule — this is what makes the guardrails enforceable:** `core/` knows nothing about markets. `conditioners/` and `outcomes/` know markets but nothing about studies. `studies/` is pure config. `report/` reads only tidy frames. The profit concept then has no place to live.

## 16.4 Non-negotiables

1. **Never touch `data/locked_confirmation/`.** The exploration runtime must not import or mmap it.
2. **Never change a value in `analysis_constants_v1.yaml` after the affected result is computed.** Changing one before is fine *with a ledger entry*.
3. **Fail closed.** Every gate in §5.1 halts the build. Do not add a fallback path, do not "handle" the discrepancy, do not proceed with a warning.
4. **No selection verbs** anywhere in `core/`: no `sort_values`, `nlargest`, `idxmax`, `argmax`, `rank`, `best`, `top` on measurement output.
5. **Emit every declared cell**, including empty ones, with a `status`. Never drop a thin cell.
6. `n_anchors` never rendered without `n_sessions` and `weight_ess` beside it.

## 16.5 Build in this order, and try to break each before moving on

The seven adversarial targets, in the order they will bite:

1. **Timestamp alignment** — the highest-risk item. `ts_event` is bar *open* (finding E); the anchor observation time is `t + bar_seconds`; time-of-day buckets key on observation time, never the label. An off-by-one here shifts every result by five minutes and **no statistical test will catch it**.
2. **Contract selection** — write `test_roll_causality` (fixture diverging at 17:00 CT) *before* trusting the roll map. The manifest's `trigger = effective − 1` is supporting evidence, not proof.
3. **One-minute component coverage** — verify a 5-min bar built from 3 one-minute rows is actually rejected under `fully_labeled_1m_grid`.
4. **Session weighting** — construct an unbalanced synthetic corpus where session-equal and anchor-weighted must diverge, and check they do.
5. **Volatility-state assignment** — hand-build timestamps and assert exactly which returns enter at τ. The anchor bar's own return is *in*.
6. **Completion selection** — measure completion rate by condition and by year *first*. If it varies strongly with volatility state, say so loudly; that is the §6 confound made real.
7. **Whole-session trajectory permutation** — verify it preserves run lengths, transitions and the exact trajectory multiset, and that recipient completeness masks stay fixed.

## 16.6 When something disagrees with this spec

Report it. Do not code around it.

Specifically: if a fail-closed gate fires, **stop and diagnose** — locate the first mismatching session, classify the cause, and report. Do not pin one era to an old file, do not relax a threshold, do not add a tolerance. Two data definitions in one atlas make every difference unattributable between the market and the pipeline.

If S00 shows completion rates so low that `min_completion` would exclude most cells, that is a **finding to report**, not a threshold to lower.

## 16.7 The failure mode to guard against

Across six review rounds, every defect in this plan took the same form: **a fluent claim stronger than its mechanism.** Guards described as "structural" that were friction. A test oracle that was invalid. A worked example missing a timezone. Each survived because it read well.

Each was caught by running a query — not by re-reading.

So: when this spec asserts something checkable, check it. When you write a test, ask whether it *can* fail — the LoRA experiment that preceded this project shipped with a canary whose pass threshold was negative, so a fully collapsed representation satisfied it. A check that cannot fail is worse than no check, because it produces confidence.

Report what you measured, label what you inferred, and state plainly what you did not verify.
