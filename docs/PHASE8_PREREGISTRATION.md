# Phase 8 Preregistration - Named Contrasts, Positivity, and Interaction

**Program:** `mnq-atlas-001`  
**Specification:** `REV6_FROZEN_SPEC.md`, revision 6  
**Contract date:** 2026-08-01  
**Base:** `289977aaaf836c76788035670d099740dfaa05f7`  
**Branch:** `phase-7b-outcome-layer`  
**Status:** proposed frozen contract; Phase 8 production is not authorized before this document and `docs/OUTCOME_LAYER_PREREGISTRATION.md` are both independently ratified

## 1. Governance and phase boundary

This document preregisters frozen-spec Phase 8, the named-contrast,
positivity/overlap, uncertainty, and descriptive-interaction layer. It
transcribes the user-ratified joint P1-P4 resolution and U17 choices P8-8
through P8-14. It is written before Unit O computes the first MNQ excursion
value, so no outcome result can influence the contract.

Phase 8 owns:

- weighted absolute outcome distributions and the five frozen section 8 named
  contrast families;
- the three frozen population estimands and their support diagnostics;
- exact positivity and completion gates with total status precedence;
- whole-session joint-bootstrap confidence intervals and block sensitivity;
- the one-surface alternative-arm survival check;
- the descriptive four-cell quantile interaction; and
- deterministic tidy schemas and manifests for those results.

Phase 8 does **not** own prevalence (Phase 9), formal null reassignment,
permutation p-values, surface-coherence calibration (Phase 10), guards,
vintages, forward budgets (Phase 11), or S01A rendering (Phase 12). It emits no
p-value, prevalence, null, vintage, report, S01A, confirmation, profitability,
ranking, selection, optimization, or trading artifact. Frozen section 8's
`four_cell_standardized_population`, section 9.1's two descriptive-only null
tests, and section 9.6's synthetic generators and max-t bands remain deferred
and are not reopened.

No production code for Unit O or Phase 8 is authorized until both contracts
are committed, byte-pinned, and return `RATIFIED` in one combined independent
audit. Unit O must then close before any Phase 8 computation consumes a real
outcome value. The accepted calendar and Phase 7 conditioner artifacts are
inputs, not mutable Phase 8 outputs.

## 2. Frozen inputs and no-selection boundary

Phase 8 consumes only:

- a ratified Unit O outcome table and manifest;
- the closed Phase 7 assignment, arm, migration and calendar fields;
- existing Phase 4 inverse-CDF weighted-quantile and weight-concentration
  functions;
- existing Phase 5 whole-session stationary resampling and percentile-interval
  functions; and
- fail-closed constants from `analysis_constants_v1.yaml`.

It may not read raw prices to redefine an outcome, recompute conditioner labels,
change a calendar classification, infer a holiday from observed truncation, or
access the locked confirmation tier. Joins are exact on declared immutable keys
and must be one-to-one or many-to-one as declared; a duplicate, missing required
key, mismatched fingerprint, or mismatched exploration seal halts.

Canonical row and arm order is structural. No table is sorted by outcome,
contrast, confidence bound, support, completion, migration, or any other
measured quantity. No smallest, largest, best, most stable, most significant or
surviving result is selected for emphasis. Every declared row is emitted with a
status.

## 3. Fixed axes and statistics (P8-8)

The primary Phase 8 outcome directions are exactly:

```text
downward_excursion_ticks
upward_excursion_ticks
```

The statistics for each direction are exactly the inverse-CDF weighted
quantiles:

```text
q50 = 0.50
q75 = 0.75
q90 = 0.90
```

This set is fixed before outcomes exist and may never be extended after results.
`q95` and `q99` are excluded. Under session-equal weighting, tail support is a
function of contributing sessions rather than the raw anchor count, so adding
more extreme quantiles after seeing results would create an unregistered thin-
support selection surface.

The frozen primary surface is exactly:

```text
outcome     downward_excursion_ticks
horizon     30 minutes
statistic   q90
contrast    vol_effect_given_phase
estimand    prospective_cell
```

All other Phase 8 rows are descriptive. Unit O's signed extreme companions
remain available as diagnostics but are not part of the Phase 8 contrast or
surface inventory and may not replace either named excursion direction.

All weighted quantiles use the frozen step function
`inf{x: cumulative_weight(x) / total_weight >= q}` and the existing Phase 4
implementation. Default linear interpolation is forbidden. Every statistic is
reported with `n_anchors`, `n_sessions`, and `weight_ess`; that name is never
expanded to "effective sample size."

## 4. Named contrast supports and arithmetic (P8-9)

For a target phase-volatility cell `C=(p,v)`, the five frozen names and baseline
supports are:

```text
absolute_distribution:
    target C; no baseline; emitted as the weighted quantile level.

phase_effect_given_vol:
    target (p,v); baseline {(p',v): p' != p}.

vol_effect_given_phase:
    target (p,v); baseline {(p,v'): v' != v}.

cell_vs_complement:
    target (p,v); baseline every phase-vol cell except (p,v).

cell_vs_population:
    target (p,v); baseline the whole declared population INCLUDING (p,v).
```

For every comparative family the statistic is:

```text
contrast_ticks = weighted_quantile(target_ticks, q)
               - weighted_quantile(baseline_ticks, q)
```

It is a difference in raw ticks. Ratios, percentages, normalized outcomes and
division by a conditioner scale are forbidden. Positive means the target
quantile is larger. Target and baseline weighted quantiles are themselves
retained beside the difference so the result is auditable.

Every multi-cell baseline emits both frozen weightings, labelled without a
post-result choice:

- `equal_phase_contrast`: equal mass to each declared comparison phase for
  `phase_effect_given_vol`, and analogously equal mass to each comparison
  volatility state for `vol_effect_given_phase`; for complement/population,
  equal mass to each constituent phase-vol cell. Within a constituent cell,
  the named estimand's session-equal construction applies.
- `natural_prevalence_contrast`: pool the declared baseline anchors at their
  natural observed frequency under the named estimand.

`absolute_distribution` carries `contrast_weighting=not_applicable`.
`cell_vs_population` explicitly includes the target in its baseline and is
labelled as diluted. No baseline is relabelled degenerate merely because its
support overlaps the target.

`degenerate_baseline` fires **only** when the exact target and baseline support
keys and normalized weights are mathematically identical. It is independent of
sample size and outcome values. A test with overlapping but nonidentical support
must remain nondegenerate, while a byte-identical support/weight pair must fire.

Quantile supports and differences are integer ticks. Inputs widen to int64
before subtraction. A valid point or interval endpoint must be an exact integer
within int64 range; invalid numeric output halts rather than rounding.

## 5. Population estimands and weights

### 5.1 `prospective_cell` - primary

The target uses every exploration session in which the target cell has at least
one eligible outcome anchor. The baseline uses the sessions in which its
declared comparison support occurs. No later state in the same session is
required, so the population is prospectively recognizable. Within each
constituent condition, select sessions with equal total mass and then split a
session's mass equally over its eligible anchors.

### 5.2 `common_session_paired` - diagnostic

The support is the exact session intersection needed by both target and
baseline. A retained session must contain at least one eligible target anchor
and at least one eligible anchor in the declared baseline support. For a
multi-cell baseline it need not contain every baseline cell unless the named
contrast explicitly requires them. The same retained session set is used on
both sides. This is a post-session mechanism diagnostic and is never described
as prospectively selectable.

### 5.3 `standardized_shared_population` - formal comparison

The target population is all ordinary full-length RTH exploration sessions
eligible for the named Unit O outcome, horizon and path estimand. Scheduled
early closes, full holidays, and the two regular-but-truncated data-quality
sessions are not ordinary full-length target sessions; their calendar classes
are not changed.

Standardization cells are **calendar year-quarter only**. For each quarter `q`:

```text
T_q = eligible target sessions in q / all eligible target sessions

condition_session_weight(c, q)
    = T_q / n_contributing_sessions(c, q)

anchor_weight(session, c, q)
    = condition_session_weight(c, q)
      / n_eligible_condition_anchors(session, c)
```

`unsupported_target_mass(c)` is the sum of `T_q` over target quarters where
condition `c` has no contributing support. A quarter with support is never
dropped, merged, borrowed, or pooled into another quarter. A missing target
quarter is never silently removed from the denominator. Every report labels
this estimand **"calendar-quarter standardized"** and never "controlled for
market regimes."

This adjustment does not control for news, trend, volatility persistence,
unknown liquidity regimes, or any unmeasured factor. Day type does not enter the
primary formal standardization. A future day-type-expanded sensitivity requires
a new preregistered structural-support analysis before outcomes are compared
and may not be chosen after results.

The `anchor_weighted` companion and deterministic non-overlapping-clock-grid
sensitivity from frozen section 7.1 are reported separately from the three
population estimands. A non-overlap grid uses the exact fixed timestamp or
drops the anchor; it never uses a tolerance and is never selected by movement,
volatility, volume, completion, or result size.

## 6. Calendar-derived day type and inactive liquidity era

`day_type` is an external-calendar descriptive family with total precedence:

```text
scheduled_early_close > holiday_adjacent > regular
```

An accepted-calendar `scheduled_early_close` row receives that type even when
`holiday_adjacent=true`. Otherwise an active holiday-adjacent session receives
`holiday_adjacent`; otherwise an accepted regular active session receives
`regular`. A full exchange holiday has no eligible RTH outcome row. An unknown
active combination halts; there is no default.

The accepted calendar's already-audited partition under this precedence is
pinned as a structural test oracle:

```text
regular 906 | holiday_adjacent 70 | scheduled_early_close 33 |
full_exchange_holiday 9 = 1018 calendar weekdays
```

The two unresolved truncated sessions, 2020-02-28 and 2020-06-30, remain
`day_type=regular` with `data_quality_status=unresolved_truncated_session`.
Observed shortening never relabels them. Thin day types produce explicit
support or overlap statuses. They are not replaced with day-of-week, and day
type does not automatically become a formal stratum.

For the primary arm, Phase 8 emits descriptive absolute distributions by day
type for the fixed outcomes, horizons, quantiles and path estimands, with the
same completion and support companions. It emits no day-type p-value, connected
region, formal standardization, or alternative-arm cross-product.

`liquidity_era` is retained visibly but inactive:

```text
liquidity_era         = undifferentiated_no_versioned_boundaries
liquidity_era_status  = inactive_missing_versioned_input
effective_null_strata = calendar_quarter_only
```

It contributes one structural level and no partition. Its correlation is
**undefined**, not zero. No report may claim that quarter-only exchangeability
is conservative, and no artifact may describe the inactive field as adjustment
for a liquidity regime. The formal null assumes exchangeability within calendar
quarter without longer-term liquidity-regime adjustment. The YAML remains
unchanged so provenance is preserved; every consuming artifact records that the
declared YAML era dimension was inactive for lack of versioned boundaries.

## 7. Positivity and overlap (P8-11)

For a contrast's declared comparison set, a positivity stratum is exactly:

```text
(session_phase, vol_rel_tercile)
```

No year-quarter, day type, liquidity era, outcome value, arm migration, or
completion result is added to this stratum. For each target stratum, baseline
support is evaluated under the named estimand and contrast weighting.

Frozen thresholds are loaded from the YAML with no fallback:

```text
minimum baseline anchors per stratum       30
minimum contributing sessions              20
maximum single-anchor weight share          0.02
maximum weight coefficient of variation     2.0
maximum unsupported target mass             0.05
```

Unsupported target mass is the share of **target weight** in strata where the
baseline has fewer than 30 anchors or fewer than 20 contributing sessions. The
single-anchor weight share and weight CV are computed from session-equal anchor
weights **within each stratum**, even when the displayed contrast baseline is
`natural_prevalence_contrast`. CV is population standard deviation divided by
mean over strictly positive weights; an empty set or nonpositive mean is
invalid support, not zero CV.

Any one of the five frozen thresholds breaching sets the
`insufficient_overlap` flag. Equality passes the inclusive min/max threshold;
strictly worse fails. There is no clipping, trimming, cap, redistribution,
quarter pooling, fallback weighting, or repaired estimate. Every diagnostic
value and breach identity is emitted.

For `standardized_shared_population`, the quarter-level unsupported target mass
from section 5.3 is also checked against the same 0.05 ceiling and carried
separately from the phase-vol stratum mass so the two mechanisms cannot mask
one another.

## 8. Completion and support gates

Completion is evaluated separately for each path estimand and horizon on the
structurally eligible anchor population. Frozen minimums are:

```text
h15 0.99 | h30 0.99 | h60 0.98
maximum absolute target-baseline completion imbalance 0.05
```

Both target and baseline must meet the applicable horizon minimum, and their
absolute completion-rate difference must not exceed 0.05. The table also emits
completion by calendar year before any contrast interpretation. With no frozen
numeric concentration threshold, the only threshold-free concentration failure
is support confined entirely to one calendar year while the declared source
population spans more than one; broader year concentration remains a disclosed
diagnostic rather than an invented tuned cutoff. Liquidity-era concentration is
not evaluated because the era field is explicitly inactive.

The close-phase long-horizon thinness is structural and must surface as support
status, not a lowered threshold. Completion diagnostics are right-hand-side
only: they never change Phase 7 assignments, Unit O values, calendar types, or
the state-anchor prevalence population.

## 9. Total result status precedence (P8-12)

Every declared result cell is emitted. All true failures are recorded in a
closed, canonically ordered `status_flags` field, while `status` reports the
first match in exactly this order:

```text
1 degenerate_baseline
2 insufficient_anchors
3 insufficient_completion
4 insufficient_overlap
5 ok
```

Rules:

- `degenerate_baseline`: target and baseline support keys plus normalized
  weights are mathematically identical; counts do not affect this test.
- `insufficient_anchors`: a required target or baseline top-level support has
  fewer than 30 eligible anchors, or no contributing session. Stratum-specific
  baseline shortages continue into unsupported target mass for overlap.
- `insufficient_completion`: any section 8 completion rule fails.
- `insufficient_overlap`: any section 7 positivity rule fails.
- `ok`: none of the four flags is true.

For `absolute_distribution`, baseline-only flags are not applicable;
`insufficient_anchors` and `insufficient_completion` still apply to its target.
An invalid-status row has null point and interval validity booleans but retains
all counts and diagnostics. Unknown flags, reordered precedence, a valid number
on a non-`ok` row, a missing declared cell, or a failure hidden because a
higher-priority failure also fired halts.

## 10. Arm scope and survival check (P8-10)

The primary Phase 7 arm
`primary_ewma78_permissive_expanding` receives the full Phase 8 inventory:

- both named outcome directions;
- horizons 15, 30 and 60;
- q50, q75 and q90;
- all five section 4 contrast names;
- all three population estimands;
- both frozen contrast weightings where applicable;
- horizon-specific and per-estimand common support;
- the day-type descriptive family; and
- the section 12 interaction rows.

The other nine Phase 7 arms, in their frozen order, recompute only the single
declared surface:

```text
coverage_strict, ewma39, ewma156, mad78, threshold_rolling60,
threshold_shift_m05, threshold_shift_m02,
threshold_shift_p02, threshold_shift_p05
```

For each, the surface is exactly one outcome x one horizon x one statistic x one
contrast x one estimand over the 5x3 phase-volatility lattice:

```text
downward_excursion_ticks x 30 x q90 x
vol_effect_given_phase x prospective_cell
```

Both `equal_phase_contrast` and `natural_prevalence_contrast` rows are emitted
inside that one named contrast; they are labelled interpretations, not separate
surfaces chosen after results. Alternative arms receive no q50/q75 expansion,
other horizon, upward direction, other contrast, other estimand, day-type panel
or interaction cross-product. They are a one-factor-at-a-time survival check,
not candidates for ranking. Phase 7 cell-migration diagnostics are displayed
beside survival results; conditioner-estimation uncertainty is not folded into
the confidence intervals.

## 11. Joint whole-session uncertainty (P8-13)

Every valid absolute level, contrast difference and interaction carries a 95%
closed percentile interval. Phase 8 uses the existing Phase 5 implementation:

```text
scheme                    whole_session_stationary
draws per block length    4999
confidence_level          0.95
mean block lengths        [1, 5, 10, 20] sessions
primary block length      5 sessions
interval endpoints        equal-replicate inverse-CDF q=(0.025, 0.975)
truncate partial session  false
early stopping            false
```

The draw count is fixed now, before outcome values, above Phase 5's generic
minimum of 999. The Phase 8-only root entropy is the integer tuple
`(20260801, 8, 13, 1)`. `SeedSequence` receives that tuple and spawns four child
sequences in the fixed block-length order 1, 5, 10, 20; each child instantiates
`Generator(PCG64(child))`. No Phase 5 registered entropy is reused. The manifest
records the root tuple, spawn order, child spawn keys, bit generator, draw count
and environment fingerprint before the first draw.

For each block length and replicate, **one** whole-session resample plan applies
jointly to the complete aligned Phase 8 frame. It is shared across arms,
outcomes, horizons, statistics, contrasts, estimands, weightings, day types and
interaction terms. Eligibility masks apply after the global plan. No cell,
condition, outcome or interaction redraws; no prefilter to sessions containing a
requested cell; no retry of an undefined replicate; and no individual session
is truncated by rows.

Within a replicate, target and baseline quantiles are recomputed under the same
session multiplicities, and the replicate contrast is their difference.
Interaction is recomputed as the four-term difference-in-differences inside the
same replicate. A contrast CI is never constructed by subtracting marginal CI
endpoints. Original baseline weights, target masses and eligibility definitions
remain frozen; the session multiplicities compose with those weights through
the audited Phase 5 path.

The L=5 interval is primary; L=1, 10 and 20 are mandatory labelled sensitivity
rows. A conclusion reversing between block lengths 5 and 10 is reported as
unstable, never repaired or used to choose a block length.

Every interval carries both frozen disclosures:

> This interval measures uncertainty within the historical mixture, not
> uncertainty about future regime change.

> Conditioner-estimation uncertainty is excluded by construction; alternative
> definitions and cell migration make that sensitivity visible instead.

Intervals also state that `weight_ess` corrects no serial dependence,
overlapping outcome windows or regime dependence.

## 12. Descriptive interaction (P8-14)

The reference phase is `midday` and the reference volatility state is `mid`.
For q in exactly `{q50, q90}`:

```text
I(p,v,q) = [Q_q(Y|p,v) - Q_q(Y|p,mid)]
           - [Q_q(Y|midday,v) - Q_q(Y|midday,mid)]
```

Interaction support is `four_cell_common_sessions`: the exact same retained
session set must contain eligible anchors in all four terms. Within a retained
session, each cell receives equal session mass split over its eligible anchors.
Pairwise common sessions, four different session sets, union support and the
deferred `four_cell_standardized_population` are forbidden.

For non-reference `(p,v)` cells, support is adequate only if the common set has
at least 20 sessions and every one of the four cells has at least 30 eligible
anchors and passes the named outcome/horizon/estimand completion gate. Otherwise
the row is `insufficient_interaction_support`. The full 5x3 lattice is emitted:
rows where `p=midday` or `v=mid` are `degenerate_baseline` because the algebraic
supports collapse by construction; the eight non-reference cells carry either
`ok` or `insufficient_interaction_support`.

Both q50 and q90 receive 95% CIs from the same joint whole-session resample used
by every section 11 output. The interaction panel states **DESCRIPTIVE ONLY - NO
P-VALUE**. It makes no additive decomposition, causal or natural-law claim.

## 13. Dependency and prefix invariance

A Phase 8 result depends exactly on:

- the Unit O rows in its declared target and baseline support;
- the Phase 7 assignment rows needed to name those supports;
- the accepted-calendar fields needed for quarter, full-length eligibility and
  day type;
- the fixed weight construction and status diagnostics; and
- for an interval, the one recorded joint resample plan per replication.

No future session may alter a pre-`T` point estimate whose definition is
strictly prefix-bounded. Full-corpus descriptive results and their bootstrap
intervals are deterministic functions of the explicit corpus seal and are not
mislabelled prefix-invariant. Semantic dependency tests therefore distinguish
prefix-defined inputs from corpus-defined summaries rather than asserting an
impossible invariance for a full-corpus contrast.

Out-of-support outcome mutation must leave a cell bit-identical. Mutating an
eligible target or baseline value in a deterministic quantile witness must move
the intended result. A widened support mask, current/future assignment leak,
wrong estimand support, separate bootstrap plan, or day-type/calendar mutation
outside the declared family must fail equality against an independent
contract-derived mask.

## 14. Deterministic output schemas

### 14.1 Contrast table

One row per fixed arm, outcome, support kind, horizon, quantile, contrast,
estimand, contrast weighting, target phase and target state:

```text
arm_id, outcome_name, support_kind, horizon_minutes, statistic,
contrast_name, population_estimand, contrast_weighting,
target_phase, target_vol_tercile,
target_quantile_ticks, target_quantile_valid,
baseline_quantile_ticks, baseline_quantile_valid,
contrast_ticks, contrast_valid,
n_anchors, n_sessions, weight_ess,
baseline_n_anchors, baseline_n_sessions, baseline_weight_ess,
completion_target, completion_baseline, completion_imbalance,
unsupported_target_mass, quarter_unsupported_target_mass,
max_single_anchor_weight_share, weight_cv,
status, status_flags
```

### 14.2 Interval table

One row per valid point-row key and block length:

```text
point_row_id, mean_block_sessions, draws, confidence_level,
ci_lower_ticks, ci_upper_ticks, interval_valid,
rng_root_entropy, rng_child_spawn_key,
historical_mixture_disclosure, conditioner_uncertainty_disclosure
```

### 14.3 Day-type descriptive table

One row per primary-arm day type, outcome, support kind, horizon, quantile and
path estimand, carrying weighted level, counts, completion, status and all
required companions. There is no contrast ranking or p-value field.

### 14.4 Interaction table

One row per primary-arm outcome, support kind, horizon, path/population
estimand, q50/q90, phase and volatility state:

```text
arm_id, outcome_name, support_kind, horizon_minutes, population_estimand,
statistic, phase, vol_rel_tercile, reference_phase, reference_vol_tercile,
interaction_ticks, interaction_valid, common_n_sessions,
cell_anchor_counts, cell_weight_ess, completion_diagnostics,
status, status_flags
```

Every table uses immutable literal column order and structural row order.
Integer outcomes and contrasts use integer storage plus validity booleans, never
NaN or magic sentinels. Structured count vectors and flag tuples have canonical
key/order vocabularies.

Artifacts use immutable `.npy` column stores and canonical sorted-key indent-2
ASCII-safe UTF-8 JSON manifests with one terminal newline. Each manifest records
the frozen spec, YAML, both preregistration hashes, Unit O and Phase 7 input
manifests, accepted-calendar version/hash, corpus seal, code commit/dirty flag,
environment fingerprint, schema and arm versions, complete declared cell
counts, status counts, per-column byte counts and SHA-256, bootstrap contract,
and all known limitations. Same-fingerprint reruns are byte-identical;
cross-environment reproduction is semantic within declared policies.

## 15. Required tests and mutation floor

Every assertion has a named failing input or mutation, and every fixture proves
nonempty target, baseline and, where relevant, four-cell support. At minimum:

1. use default linear rather than inverse-CDF quantiles;
2. add q95 or q99 after the fixed set;
3. compute a ratio instead of a tick difference;
4. omit either frozen contrast weighting;
5. exclude the target from `cell_vs_population`;
6. flag an overlapping but nonidentical baseline as degenerate;
7. fail to flag an exactly identical support/weight pair as degenerate;
8. pool anchors across sessions instead of session-equal mass;
9. use anchor-equal mass for `equal_phase_contrast`;
10. require a future second state for `prospective_cell`;
11. use different session sets on the two sides of `common_session_paired`;
12. standardize on quarter x day type or liquidity era;
13. drop or pool an unsupported quarter;
14. omit within-session anchor division in standardized weights;
15. calculate unsupported mass from baseline rather than target weight;
16. compute positivity on outcome-selected or natural-prevalence weights instead
    of session-equal within-stratum weights;
17. clip a heavy weight or repair an overlap breach;
18. treat equality at a frozen positivity boundary as failure;
19. report only the first failure and discard the remaining flags;
20. reorder status precedence;
21. permit a non-`ok` row to carry a valid point or interval;
22. make day-type categories overlap or let observed shortening relabel them;
23. call inactive liquidity-era correlation zero;
24. claim quarter-only null exchangeability is conservative;
25. expand an alternative arm beyond the one declared surface;
26. select a preferred arm from outcome values;
27. resample separately by cell, output, arm, statistic or interaction term;
28. truncate the final session by rows;
29. retry or redraw an undefined bootstrap replicate;
30. construct a contrast CI from marginal interval endpoints;
31. omit any block length or choose one after seeing interval width;
32. use pairwise rather than four-cell-common interaction support;
33. emit an interaction p-value;
34. reopen four-cell standardization, synthetic generators or max-t bands;
35. sort/rank cells by measured output or report a smallest p-value;
36. omit `n_sessions` or `weight_ess` beside `n_anchors`;
37. mutate an out-of-support row and move the result;
38. admit a widened/narrowed semantic support mask; and
39. access, name, accept or mmap the locked confirmation tier.

Discriminating fixtures include: unequal anchors per session; identical versus
overlapping supports; a quarter absent for one condition; exactly-on-threshold
positivity cases; multiple simultaneous status failures; all three day-type
precedence cases including the twelve overlap dates; a four-cell dataset where
pairwise intersections exist but the four-way intersection does not; and a
joint-bootstrap fixture whose paired contrast differs under separate resamples.

## 16. Phase 8 gate and implementation order

After both contracts are ratified and Unit O closes, Phase 8 proceeds tests
first:

1. literal axes, named supports, tick differences and independent support-mask
   oracles;
2. three estimand weight constructors and quarter-only standardization;
3. completion, positivity and total status precedence;
4. full primary-arm rows and the nine one-surface survival arms;
5. one joint whole-session bootstrap across all outputs and block lengths;
6. four-cell descriptive interaction;
7. deterministic artifacts, protected hashes, a Phase 8 closeout document and
   the authorized safe suite.

No real contrast is computed until all Unit O gates and synthetic Phase 8
mutations pass. If a fail-closed gate fires, stop at the first mismatch and
classify it under frozen section 16.6. Do not lower support thresholds, pool a
quarter, clip weights, change the quantile set, expand an arm, alter a calendar
class, or code around missingness.

The only authorized repository test command is:

```text
python -m pytest tests --ignore=tests/test_bootstrap_acceptance.py -q
```

The acceptance module must never be imported, collected or executed, and the
bare full suite is forbidden. Phase 8 closeout requires one focused independent
audit before Phase 9 or any market-result interpretation is authorized.

## 17. Known limits and mandatory language

Phase 8 is descriptive measurement. A weighted quantile difference is not a
causal effect. Common-session pairing is post-session selection.
Calendar-quarter standardization controls only the declared quarter mixture and
must never be labelled market-regime control. Inactive liquidity era leaves the
formal null without longer-term regime adjustment; no direction of
conservativeness is known.

Day type has thin special classes and is descriptive only. The two truncated
regular sessions remain unresolved data-quality discrepancies. The accepted
calendar is a single-source input whose close-time evidence is corroborating,
not proof of every classification.

Confidence intervals describe resampling uncertainty within the historical
mixture. They do not include future regime change, conditioner-estimation
uncertainty, price-feed completeness, calendar-classification uncertainty or
model-selection uncertainty. Overlapping horizons and serial dependence are
not repaired by `weight_ess`; the whole-session block sensitivity makes some,
not all, dependence visible.

No Phase 8 output establishes profitability, a stop recommendation, a trade
entry, a preferred conditioner arm, statistical significance, confirmation, or
future performance. No p-value is emitted. Phase 9, Phase 10, Phase 11, Phase
12, S01A and locked-confirmation work remain unauthorized after this contract
is ratified.
