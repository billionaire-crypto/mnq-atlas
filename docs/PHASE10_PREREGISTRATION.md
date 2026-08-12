# Phase 10 Preregistration - Null Engine and No-Evidence Scaling Benchmark

Date: 2026-08-11

Producer: Codex implementation session

This document records implementation decisions and operator rulings for Phase 10. It
is not an audit, acceptance record, ledger entry, or ratification.

## 1. Operator authorization and scope

On 2026-08-11, the Codex implementation session asked the operator the following
question verbatim:

> Do you authorize Phase 10 implementation plus the no-evidence scaling benchmark, under exactly the scope and prohibitions stated in your message dated 2026-08-11?

The operator answered verbatim:

> YES

This authorization covers Phase 10 implementation, Tests 9-12, development-scale
synthetic-fixture exercise at `B = 199`, and a cost-only scaling benchmark whose
temporary outputs are discarded. It does not authorize corpus Type-I or power
evidence, reporting any corpus-derived rejection count, rejection frequency, or
p-value, creating an acceptance record, or beginning a later phase.

Every Phase 10 artifact and document records:

```text
effective_null_strata = calendar_quarter_only
```

## 2. Formal boundary and population

Phase 10 implements exactly one formal test, `vol_given_phase`, using whole-session
trajectory reassignment. `phase_given_vol` and `interaction` remain descriptive-only
interfaces and emit no p-value. Circular within-session rotation is invalid, and a
trajectory is never segmented by phase.

The formal null is interpreted as follows in every report:

> Conditional on the observed state trajectories and the declared exchangeability strata, there is no special pairing between a session's volatility-state trajectory and another session's subsequent outcome path.

The formal population excludes early closes, exchange holidays, schedule-excluded
sessions, unresolved truncated sessions, and, by the operator ruling below,
holiday-adjacent sessions. Holiday-adjacent sessions remain in descriptive output.

### 2.1 Required population measurements

The accepted calendar reproduced the following fixed counts:

| Calendar classification | Sessions |
|---|---:|
| all rows | 1,018 |
| regular and `full_rth` | 976 |
| `scheduled_early_close` | 33 |
| `full_exchange_holiday` | 9 |
| `holiday_adjacent`, all classes | 82 |
| regular and `full_rth` and `holiday_adjacent` | 70 |
| scheduled early close and `holiday_adjacent` | 12 |
| regular and `full_rth` and not `holiday_adjacent` | 906 |

Quarter-only stratum counts were:

| Quarter | Include adjacent | Exclude adjacent |
|---|---:|---:|
| 2019Q2 | 39 | 37 |
| 2019Q3 | 63 | 59 |
| 2019Q4 | 62 | 57 |
| 2020Q1 | 62 | 57 |
| 2020Q2 | 63 | 59 |
| 2020Q3 | 64 | 60 |
| 2020Q4 | 62 | 57 |
| 2021Q1 | 61 | 56 |
| 2021Q2 | 63 | 59 |
| 2021Q3 | 64 | 60 |
| 2021Q4 | 63 | 59 |
| 2022Q1 | 62 | 58 |
| 2022Q2 | 62 | 56 |
| 2022Q3 | 64 | 60 |
| 2022Q4 | 62 | 57 |
| 2023Q1 | 60 | 55 |
| **Total** | **976** | **906** |

Both alternatives have 16 usable quarters and zero strata below the frozen floor of
20. **Measurement A is context only and cannot discriminate.** The larger population
is not support for inclusion.

The session-aware v2 corpus contains 1,005 sessions across active session classes.
The four schedule exclusions `20200309`, `20200312`, `20200316`, and `20200318`
reduce the regular full-RTH counts to 972 including adjacent sessions and 902
excluding them. The unresolved truncated sessions `20200228` and `20200630` are
then excluded because they are not observed ordinary full-length sessions. The two
candidate realized populations before the operator ruling were therefore 970 and
900. Including the truncated pair in a sensitivity calculation left the q90 unchanged
and changed assigned-state proportions only marginally, so no separate ruling was
needed.

For the fixed primary arm `primary_ewma78_permissive_expanding`, state measurement B
was:

| Population | Sessions | Anchors | Undefined | Assigned | Low | Mid | High |
|---|---:|---:|---:|---:|---:|---:|---:|
| holiday-adjacent | 70 | 5,460 | 468 (8.57%) | 4,992 | 2,004 (40.14%) | 1,522 (30.49%) | 1,466 (29.37%) |
| non-adjacent, resolved | 900 | 70,200 | 9,035 (12.87%) | 61,165 | 16,040 (26.22%) | 22,119 (36.16%) | 23,006 (37.61%) |

Outcome measurement C used `fully_labeled_1m_grid`, horizon-specific support,
downward excursion at 30 minutes, q90, and session-equal mass divided equally over
eligible anchors within each session:

| Population | Contributing sessions | Eligible anchors | `weight_ess` | q90 ticks |
|---|---:|---:|---:|---:|
| holiday-adjacent | 64 | 4,672 | 4,672.00 | 239 |
| non-adjacent, resolved | 785 | 57,240 | 57,143.14 | 273 |
| non-adjacent including the truncated pair | 787 | 57,255 | 55,298.08 | 273 |

Measurements B and C are the deciding evidence. They were not used to rank or search
populations, and no p-value or rejection outcome was computed.

### 2.2 Operator population ruling

On 2026-08-11, the operator supplied the following question and answer verbatim:

> Question: Given measurements B and C, do you rule that Phase 10's
> permutation population EXCLUDES holiday-adjacent regular full-RTH
> sessions (900 realized sessions after the stated trims), or INCLUDES
> them (970 realized sessions after the same trims)?
>
> Answer: EXCLUDE. Phase 10's permutation population is the 900
> realized ordinary full-RTH sessions, after schedule exclusions and
> the two unresolved truncated sessions.

The operator supplied the following basis and scope verbatim:

> Basis: measurements B and C confirm both legs of the confounding
> mechanism. Holiday-adjacent sessions carry 40.1% low-volatility
> assignments against 26.2% on ordinary sessions, and a q90 downward
> excursion of 239 ticks against 273. Day type moves both the
> condition and the outcome, and day type is not a permitted stratum
> under the frozen strata. Measurement A is recorded as context only
> and did not inform this ruling: both populations have 16 usable
> quarters and no stratum below the floor of 20, so stratum viability
> could not discriminate.
>
> These sessions remain in all descriptive output. Only the formal
> permutation test uses the trimmed population, and every reported
> result must state that population explicitly.
>
> Record separately in the Phase 10 document, as a finding rather than
> housekeeping: holiday-adjacent sessions are measurably quieter in
> both assigned state and realized excursion. Any future strategy
> should treat holiday weeks as out of scope by default, and bringing
> them in requires its own evidence rather than an assumption that the
> ordinary-session result carries over.
>
> The permutation population is frozen for this study version. It is
> not a configurable option and must not be re-run under the
> alternative population to compare results.

Finding: holiday-adjacent sessions are measurably quieter in both assigned state and
realized excursion. This is a scope finding, not a strategy change or trading action.
The formal population is frozen at 900 sessions and is not configurable.

## 3. Liquidity-era ruling

Phase 10 records:

```text
liquidity_era         = undifferentiated_no_versioned_boundaries
liquidity_era_status  = inactive_missing_versioned_input
effective_null_strata = calendar_quarter_only
```

The operator's ruling is: **Phase 10 stratifies on calendar quarter only. The gap is
declared, not filled.** Its reasoning is recorded verbatim:

> The spec never defines a liquidity era. §9.5 calls it "an
> ordered calendar" — that is, contiguous time blocks. Calendar
> quarter is a strictly finer calendar partition, so each
> quarter already falls inside exactly one era, and quarter-only
> strata lose nothing.
>
> The spec sets the precedent on the same line that defines the
> strata. §9.2 refuses event-day strata because "no verified
> event calendar exists locally, and inventing one is worse than
> declaring the gap." This is the same situation, so it gets the
> same answer: declare the gap, use calendar quarter.
>
> It does not affect the formal test. The primary surface is the
> 5x3 phase-by-volatility lattice, which never uses
> liquidity_era. Its absence limits only optional descriptive
> surfaces and a state-validity diagnostic that is already
> marked deferred.

No era boundaries are invented and the era field remains one structural level. The
formal null assumes exchangeability within calendar quarter without longer-term
liquidity-regime adjustment. Quarter-only exchangeability is not described as
conservative.

The "each quarter falls inside exactly one era" equivalence is exact when era
boundaries coincide with quarter boundaries. Any era calendar adopted later that
splits a quarter would break it and would require re-preregistration.

## 4. Cell standardization decision

### 4.1 Chosen estimator

Let `d[b,c]` be the raw signed tick contrast for replication `b` and cell `c`,
with `b = 1..B` denoting the null replications. For each cell, let `V[c]` be the
valid null contrasts whose complete Phase 8 status is `ok`. The shared scale is the
sample standard deviation

```text
mean[c]  = sum(V[c]) / n[c]
scale[c] = sqrt(sum((V[c] - mean[c])^2) / (n[c] - 1))
```

with `n[c] >= 2`. The signed cell value is

```text
z[b,c]   = d[b,c] / scale[c]
z[obs,c] = d[obs,c] / scale[c]
```

The null mean is used only to estimate dispersion; it is not subtracted from the raw
contrast because zero remains the scientific no-contrast reference and the region
sign must remain the raw contrast sign.

The scale is computed once from the complete fixed null ensemble, not from the
observed surface. Exactly the same cell denominator is applied to the observed and
every permuted contrast. Thus this is a shared null-ensemble standardization, not a
mapping-specific studentized statistic and not an observed-data scale reused under
permutation. The scale is recomputed when the authorized dev `B = 199` is replaced by
the frozen final `B = 4999`; final and dev runs are different declared run scales.

If a cell is missing, thin, or has any non-`ok` status in a particular mapping, its
`z` value is represented by a non-finite storage sentinel with `z_valid = false` and
the explicit upstream status. It does not become zero. If `n[c] < 2`, or the shared
scale is non-finite or zero, the cell has `scale_status = unusable_null_scale` for the
observed surface and every replication. Every invalid cell breaks adjacency.

### 4.2 Alternatives considered and cost

1. **Session-block bootstrap inside every mapping.** This is the honest bootstrap
   studentization: the scale would be recomputed for the observed mapping and each of
   4,999 null mappings. At the existing minimum 999 draws this requires
   `5,000 x 999 = 4,995,000` bootstrap surface evaluations, or 74,925,000 cell
   contrast evaluations for the 15-cell surface. Phase 8 v2 measured 29,086.906
   seconds for 574,805,016 request-draw evaluations on a 32-worker, 252-GiB host.
   A simple throughput ratio projects about 3,791 seconds (63 minutes) on that much
   larger host before nested-plan and local-machine overhead. It would be the dominant
   Phase 10 cost and is rejected on cost grounds; it is not rejected because of any
   observed surface value.

2. **One observed-data bootstrap scale reused everywhere.** This needs only 999
   bootstrap surfaces, or 14,985 cell contrast evaluations. It is much cheaper, but
   the observed pairing would determine the scale used to judge all null pairings.
   That asymmetry can make the observed association influence its own normalization,
   so this alternative is rejected on statistical grounds.

3. **Analytic quantile standard error.** This would require an unregistered density
   estimator or smoothing/bandwidth rule for a discrete, weighted q90, and would have
   to be applied again under every mapping. No such rule is frozen. It is rejected on
   statistical-specification grounds.

4. **Shared null-ensemble dispersion (chosen).** The 4,999 by 15 raw-contrast matrix
   is already required by the formal null. Its signed-int64 storage is 599,880 bytes;
   a 74,985-byte validity matrix accompanies it. Computing 15 sample dispersions is
   linear in those 74,985 values and adds no resampling pass. It standardizes cells by
   the variability induced by the retained null, avoids observed-surface normalization,
   and is the only considered alternative that adds neither an unfrozen estimator nor
   a nested bootstrap.

## 5. Surface and p-value contract

The primary surface is exactly downward excursion, 30 minutes, q90,
`vol_effect_given_phase`, `prospective_cell`, over the imported 5 by 3 ordered
phase-volatility lattice. No connected region spans another outcome, horizon,
quantile, contrast, or estimand.

Positive regions are maximal rook-connected valid cells with `z > 1.0`. Negative
regions are maximal rook-connected valid cells with `z < -1.0`. Opposite signs are
never merged. Missing or invalid cells break adjacency. For a region, yearly stability
is the fraction of yearly blocks whose mean raw signed contrast retains the region's
sign. The statistic is the larger of the declared positive- and negative-region
scores. If no region exists, that side contributes zero.

The final run uses exactly 4,999 replications and no early stopping. Its p-value is
exactly `(1 + count(T_null >= T_observed)) / (B + 1)`; ties count. No smallest value
across surfaces is computed or reported. Descriptive-only interfaces expose no
p-value method.

## 6. RNG contract

The only root entropy is the frozen `inference.rng_seed = 20260728`. Phase 10 records
both `rng_seed = 20260728` and `rng_root_entropy = [20260728]`. It constructs
`numpy.random.SeedSequence((20260728,))`, spawns one child per replication in
replication order, and constructs each generator as
`numpy.random.Generator(numpy.random.PCG64(child))`. One child's joint stratum mapping
is shared across every outcome, horizon, statistic, and surface output in that
replication. `default_rng` and bare integer generator construction are forbidden.

## 7. Calibration gate preregistration

The later one-shot calibration evidence is not authorized here. Phase 10 implements
only an acceptance-plan interface and exercises it with fixed synthetic summaries.
No session generator is implemented.

The null-control plan fixes 300 replications at nominal alpha 0.05. Before any run,
the exact central 95% binomial acceptance band is **8 through 23 rejections,
inclusive** for `Binomial(300, 0.05)`. A result outside that band is a finding and the
band is never widened.

Power summaries are supplied in fixed weak, medium, strong order. The gate requires:

- a positive least-squares slope across the three rejection fractions;
- adjacent 95% Wilson intervals to be consistent with increasing power, meaning a
  later interval must not lie wholly below the preceding interval;
- the strong-effect Wilson lower bound to exceed the weak-effect Wilson upper bound;
- a positive least-squares slope across the three mean localization overlaps; and
- strong-effect mean localization overlap greater than weak-effect overlap.

Strict adjacent monotonicity of point rejection fractions or overlap values is not
required. The one-shot runner must require a separately authorized evidence boundary
and is not collected by the ordinary suite. Fixed deterministic summaries used to
exercise validation logic do not spend one-shot entropy; generating randomized
control replications, counting their rejections, or evaluating corpus permutations
does spend it and remains forbidden under this authorization.

## 8. Artifact and benchmark boundary

Every Phase 10 artifact and document records all of:

```text
formal_test              = vol_given_phase
permutation_population   = ordinary_full_rth_nonadjacent_resolved
permutation_sessions     = 900
liquidity_era             = undifferentiated_no_versioned_boundaries
liquidity_era_status      = inactive_missing_versioned_input
effective_null_strata     = calendar_quarter_only
rng_seed                  = 20260728
```

The cost-only benchmark may use real corpus inputs at `B = 19`, `49`, and `199`, then
project to 4,999. It reports only seconds, memory bytes, row/array sizes, input wiring,
scale, and deletion of temporary output. A newly created directory outside the
repository is removed in a `finally` block. The benchmark does not serialize or report
raw contrasts, standardized cells, regions, statistics, p-values, rejection outcomes,
or acceptance decisions.

## 9. Negative-case contract

For Tests 9-12, each negative case must fail the same assertion used by its positive
case. Tests 10-12 additionally require planted production-code mutants covering the
declared mapping, p-value, and signed-rook-region failure modes. Every mutant is
reverted immediately after the test rejects it; no mutant may enter a commit.
