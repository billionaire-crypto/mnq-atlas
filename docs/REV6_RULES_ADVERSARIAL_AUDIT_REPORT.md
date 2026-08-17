# Adversarial Audit of the Frozen Rules

Date: 2026-08-16

Scope: rules, constants, definitions, and validation design only. This report proposes
no remedy and records no production-code audit conclusion.

## 1. Authorization and ordering

The question asked before audit work began was, verbatim:

> Do you authorize me to begin this read-only audit, including making the required first audit commit containing this exact question and your answer verbatim, before performing any other work?

The operator answered, verbatim:

> Yes

The authorization-only commit is `562edb88640fc30e3c11980b196a6a9f4233651c`.
Its parent is `09c28fcaafe70194fb2dbf47eaa39b0e28883ed5`; the authorization
record is the commit's only path. This commit came before document inspection, corpus
measurement, the baseline suite, and sealed-evidence reading. The repository HEAD
supplied in the task (`1b2188a`) did not match the measured pre-authorization HEAD
(`09c28fc`); history was not changed to force a match.

## 2. Coverage and method

All 1,692 physical lines of the four required inputs were read:

| Input | Physical lines | Objective rule inventory |
|---|---:|---:|
| `REV6_FROZEN_SPEC.md` | 702 | all 16 sections; 59 explicitly numbered list/table rules; all unnumbered definitions and obligations |
| `analysis_constants_v1.yaml` | 120 | all 89 leaf settings |
| `docs/PHASE10_PREREGISTRATION.md` | 391 | all 9 sections; all rules, including 4 numbered estimator alternatives |
| `docs/PHASE10_CALIBRATION_PREREGISTRATION.md` | 479 | all 14 sections; all rules, including 11 explicitly numbered items |

Thus 163 objectively enumerable numbered/leaf rule units were checked, plus every
unnumbered normative clause in the four files. `docs/DISCREPANCIES.md` was read only as
the binding history for already-disclosed ambiguities; it was not edited.

Real-data measurements used
`data/exploration/derived/phase7-unit-o-session-aware-v2` and the fixed 900-session
formal slice. No permutation ensemble, calibration replication, evidence runner,
bootstrap acceptance fixture, or replication at `B=4999` was run. One deterministic
surface evaluation and one deterministic +60-tick worked intervention were computed
without RNG. The sealed calibration store was read only at detached commit `21ec0ff`,
then the worktree was returned to `phase-7b-outcome-layer`, exactly as authorized.

## 3. Findings, ordered by severity

### F1 — Unmeasurable years are scored as contrary evidence

**Documents and lines.** `REV6_FROZEN_SPEC.md:346-350` and
`docs/PHASE10_PREREGISTRATION.md:314-321`.

**Rule, verbatim.**

> `stability(R)      fraction of yearly blocks in which R's mean contrast keeps its sign`

The Phase 10 preregistration makes the denominator explicit:

> A yearly block contributes no sign retention if any region cell is invalid in that
> block; the denominator remains all declared yearly blocks.

**Measurement.** The formal corpus has five declared calendar years. Validity is the
same in both weighting planes, so the unique-lattice count is shown first and the
30-plane-cell total second.

| Year | Formal sessions | Valid cells per 15-cell plane | Valid cells over both planes |
|---:|---:|---:|---:|
| 2019 | 153 | 0 | 0 |
| 2020 | 227 | 9 | 18 |
| 2021 | 234 | 11 | 22 |
| 2022 | 231 | 5 | 10 |
| 2023 | 55 | 0 | 0 |

The often-quoted `0/9/11/5/0 of 30` sequence is therefore a mixed denominator: those
counts are per 15-cell weighting plane. Counting the two declared planes gives
`0/18/22/10/0 of 30`. This does not change the stability arithmetic because a region
never crosses planes.

Therefore any region has an unconditional ceiling of `3/5 = 0.6`. The planted
morning/midday/afternoon-high chain is jointly valid only in 2021, so its actual
ceiling is `1/5 = 0.2`, independent of effect magnitude. Invalidity and a measured
sign reversal both add zero to the numerator and one to the denominator.

The sealed evidence contains 498 strong-effect full-high-column regions (230 in plane
0 and 268 in plane 1). All 498 have stability exactly 0.2. Across all 4,812 retained
regions from the null/weak/medium/strong members, no stability exceeds 0.4.

**Inference.** The statistic does not estimate sign stability over measurable years.
It multiplies sign evidence by data availability and treats no evidence as refutation.

**Consequence already produced.** Rejections were null `10/300`, weak `13/300`,
medium `0/300`, and strong `0/300`. All 900 power members had zero nonzero localization.
The strong p-values were bounded below by 0.1368. The power gate failed after the full
run.

**Grade: DEFINITELY WRONG.**

### F2 — The “at least one observation per year” invariant cannot protect stability

**Document and lines.** `docs/PHASE10_CALIBRATION_PREREGISTRATION.md:215-226`.

**Rule, verbatim.**

> every one of the three target cells has at least one eligible selected observation
> in every represented calendar year. Failure of the last condition halts rather
> than silently changing the stability multiplier for reasons unrelated to effect
> magnitude.

**Measurement.** The rule's `>=1` check passes in the two boundary years, and the
30-anchor gate also passes, but the same rule set requires 20 contributing sessions:

| Year | Target cell | Eligible anchors | Contributing sessions | `>=1` | `>=30 anchors` | `>=20 sessions` |
|---:|---|---:|---:|---:|---:|---:|
| 2019 | morning/high | 121 | 7 | yes | yes | no |
| 2019 | midday/high | 92 | 5 | yes | yes | no |
| 2019 | afternoon/high | 56 | 4 | yes | yes | no |
| 2023 | morning/high | 158 | 13 | yes | yes | no |
| 2023 | midday/high | 223 | 12 | yes | yes | no |
| 2023 | afternoon/high | 176 | 12 | yes | yes | no |

**Inference.** The stated justification does not follow. Passing the invariant says
nothing about whether a yearly contrast can be evaluated under the simultaneously
frozen positivity rules.

**Consequence already produced.** The invariant passed while both boundary years
contributed zero valid cells and the 498 strong planted regions remained fixed at 0.2.

**Grade: DEFINITELY WRONG.**

### F3 — Planting the high cells also creates large non-target low/mid effects

**Document and lines.** `docs/PHASE10_CALIBRATION_PREREGISTRATION.md:162-188` and
`:197-209`.

**Rules, verbatim.**

> The planted cells are: `(morning, high)`, `(midday, high)`,
> `(afternoon, high)`.

> The expected planted region sign is positive.

> control-assigned volatility state equals canonical `high`;
> phase is `morning`, `midday`, or `afternoon`;

**Measurement.** On the real 900-session corpus, a deterministic +60-tick
intervention changed 17,700 eligible high-cell outcomes. Re-evaluating the raw q90
surface produced:

| Surface cells | Intended? | Count over two planes | Contrast change |
|---|---|---:|---:|
| morning/midday/afternoon high | yes | 6 | exactly +60 ticks each |
| morning/midday/afternoon low | no | 6 | −40 through −44 ticks |
| morning/midday/afternoon mid | no | 6 | −46 through −55 ticks |

The arithmetic follows from the rule defining each state's baseline as the other two
states in the same phase. Moving `high` therefore moves the baseline used by `low` and
`mid`; changing only selected outcome rows does not mean changing only selected
contrasts.

**Inference.** The intervention is not a three-cell positive-region intervention in
the statistic it calibrates. It creates six intended positive plane-cells and twelve
unintended negative plane-cells. The localization target nevertheless contains only
the three high cells and the formal statistic scans both signs.

**Consequence already produced.** The sealed strong arm contains large connected
negative low/mid regions as well as the 498 positive full-high-column regions. No
medium or strong member rejected, and no power member had nonzero localization.
Stability is the demonstrated primary limiter, so these facts do not isolate how much
of the failure was caused by baseline contamination.

**Grade: DEFINITELY WRONG.**

### F4 — The validation fixtures could not expose annual missingness

**Document and line.** `REV6_FROZEN_SPEC.md:554`.

**Rule, verbatim.**

> `test_null_calibration` — Type-I ≈ α within Monte Carlo binomial bounds. Power:
> positive overall trend, intervals consistent with increasing power, strong effects
> clearly beating weak, localization overlap improving

**Measurement.** The end-to-end synthetic calibration fixture has 120 of 120 sessions
in calendar year 2020. Its stability denominator is one and all 30 plane-cells are
required to be `ok`. The signed-surface fixture creates four yearly copies of the same
surface and marks every yearly cell valid. No ordinary test changes a yearly-valid
entry to false. Thus the validation inputs contain zero partial years and zero
unmeasurable annual cells.

**Inference.** A test population with one year, or repeated identical fully valid
years, cannot distinguish “divide by measurable years” from “divide by all declared
years.”

**Consequence already produced.** The 1,772-test permitted suite passed before the
calibration, yet the first real five-year run exposed the 0.2 stability collapse.

**Grade: DEFINITELY WRONG.**

### F5 — The formal population differs between the frozen spec and preregistration

**Documents and lines.** `REV6_FROZEN_SPEC.md:116-119`, `:286-297`; and
`docs/PHASE10_PREREGISTRATION.md:44-46`, `:122-162`.

**Rules, verbatim.** The spec says:

> Holiday-adjacent and unscheduled closures are flagged, not excluded.

Its exact null algorithm excludes:

> Early closes and holidays

The preregistration instead says:

> The formal population excludes ... holiday-adjacent sessions.

**Measurement.** Under the same schedule/truncation trims, including regular
holiday-adjacent sessions gives 970 sessions; excluding 70 gives 900, a reduction of
`70/970 = 7.216%`. The exclusion ruling was made after observing 40.14% low-state mass
versus 26.22% (a 13.92-point difference) and q90 downward excursion 239 versus 273
ticks (34 ticks lower) in the adjacent group.

**Inference.** The documents do not define the same formal population. Separately,
choosing the formal population after measuring both its conditioner distribution and
formal outcome makes the population decision outcome-informed; the effect on the
eventual p-value was not measured because the alternative population was forbidden
from being run.

**Consequence already produced.** Every one of the 300 calibration quartets and all
their internal ensembles used 900 sessions, not the 970-session population implied by
a literal reading of the spec's exclusion list.

**Grade: DEFINITELY WRONG** for the incompatible definitions. The inferential effect
of the outcome-informed choice is **NOT VERIFIED**.

### F6 — “Formal population estimand” names two different estimands

**Documents and lines.** `analysis_constants_v1.yaml:39-44`, `:97-104`;
`REV6_FROZEN_SPEC.md:201-203`, `:325-333`; and
`docs/PHASE10_PREREGISTRATION.md:298-303`.

**Rules, verbatim.** The YAML declares:

> `population_formal: standardized_shared_population`

but its formal primary surface declares:

> `estimand: prospective_cell`

and the Phase 10 preregistration repeats `prospective_cell` for the formal surface.

**Measurement.** The project has exactly one formal test. Its primary contract uses
`prospective_cell`; the `population_formal` YAML leaf has no Phase 10 role. The sealed
run contains 1,200 member evaluations under that primary contract.

**Inference.** “Formal” can mean either a general preferred comparison or the actual
formal test, and the documents do not state a precedence rule. The field name implies
the latter while execution documents specify the former.

**Consequence already produced.** The formal calibration evaluated prospective-cell
contrasts, not standardized-shared-population contrasts.

**Grade: UNCLEAR.**

### F7 — The localization number conflates no detection with wrong localization

**Document and lines.** `docs/PHASE10_CALIBRATION_PREREGISTRATION.md:246-260`.

**Rule, verbatim.**

> A non-rejection scores zero. A rejection with no regions scores zero. Mean
> localization for each effect level is calculated over all 300 replications,
> including every zero.

**Worked example.** Thirty of 300 perfect localizations and 270 non-rejections yield
mean `30 × 1 / 300 = 0.10`. Three hundred detections each with Jaccard 0.20 yield mean
0.20. The rule reports the second as twice as localized although its conditional
localization is five times worse.

**Measurement.** The weak arm rejected 13 times, but all 13 had localization zero;
medium and strong rejected zero times. All three reported mean localization zero.

**Inference.** The quantity is joint detection-and-localization performance, not
localization conditional on detection. Its label and gate language do not preserve
that distinction.

**Consequence already produced.** The evidence cannot use the reported localization
means alone to distinguish never detecting from detecting only wrong regions.

**Grade: PROBABLY WRONG.**

### F8 — The effect ladder has no derivation and was empirically uninformative

**Document and lines.** `docs/PHASE10_CALIBRATION_PREREGISTRATION.md:177-195` and
`:344-363`.

**Rules, verbatim.**

> weak 10; medium 30; strong 60

> Whether 10, 30, and 60 ticks span a useful detectable range is itself a
> preregistered finding and an accepted design risk.

**Measurement.** The sealed rejection counts were 13, 0, and 0 in weak-to-strong
order. Median observed statistics increased `2.4086 → 2.7755 → 3.4879`, but median
p-values were `0.4492 → 0.2454 → 0.1716` and no medium/strong p-value crossed 0.05.
The 60-tick level is 24 index points because one tick is 0.25.

**Inference.** The document openly records that the numbers have no reproducible
scientific basis. The completed run confirms that they did not span the intended
power curve. The magnitude-independent annual-validity cap means this result cannot
be interpreted as evidence that 60 ticks is intrinsically weak.

**Consequence already produced.** All 900 power replications were spent without a
nonzero localization result, and the calibration gate failed.

**Grade: PROBABLY WRONG.**

### F9 — Numerous YAML thresholds are frozen without a recorded derivation

**Document and lines.** `analysis_constants_v1.yaml:13-37`, `:46-75`, `:80-90`, and
`:97-106`.

**Rules.** No derivation was found in the four audited documents for the internal
phase cut points; horizons 15/30/60; seasonal 60-session warmup, 30-observation cutoff,
or shrink `k=30`; MAD factor 1.4826; ±2/±5 tercile shifts; rolling 60-session
sensitivity; 0.90 completion floor; 0.05 completion imbalance; the five positivity
limits (30, 20, 0.02, 2.0, 0.05); bootstrap block 5 and sensitivity 1/5/10/20;
midday/mid references; 20-session null floor; development minimum 199; or signed
z-thresholds ±1.0.

By contrast, the audited documents do state reproducible bases for tick size 0.25,
EWMA 78 (one RTH session), completion values 0.99/0.99/0.98 (the frozen S00 rule),
final `B=4999` (p-value resolution), the primary 30-minute q90 surface (stop-tail
objective and close support), and `0.01 × 5 ≈ 0.05` for forward testing.

**Measurement.** One ungrounded value is already load-bearing: the 20-session rule
rejects the six boundary-year target cells in F2 despite 56–223 eligible anchors.
Aggregate formal evaluation passes all 30 plane-cells, while annual reapplication
leaves only 0/18/22/10/0 valid plane-cells by year.

**Inference.** Absence of a derivation does not prove each value numerically wrong, but
it prevents reproducing why that value, rather than a nearby value, defines evidence.

**Consequence already produced.** The annual positivity thresholds are part of the
stability collapse. Consequences of the other ungrounded values were not isolated;
doing so would require counterfactual analyses outside this audit.

**Grade: PROBABLY WRONG** as a provenance/justification defect. Numerical optimality
of the individual constants is **NOT VERIFIED**.

### F10 — Seasonal shrinkage and fallback never operate on the real corpus

**Documents and lines.** `REV6_FROZEN_SPEC.md:111-114` and
`analysis_constants_v1.yaml:24-26`.

**Rule, verbatim.**

> When a bucket has n < 30 prior observations, shrink toward the session-phase median
> with weight n/(n+30). Absent bucket -> session-phase median.

**Measurement.** The real Phase 7 artifact has 391,950 seasonal rows: 25,920 warmup
and 366,030 `ok`. Among `ok` rows, the minimum bucket count is 47, zero rows have
`n<30`, every shrink weight is exactly 1.0, zero buckets are absent, and zero phase
fallbacks are unavailable.

**Inference.** The stated smoothing mechanism contributes nothing to this study and
has no real-corpus validation. This does not establish that its hypothetical behavior
would be wrong on a different corpus.

**Consequence already produced.** Zero observed seasonal profiles were blended or
filled; `seasonal_min_bucket_obs` and `seasonal_shrink_k` did not affect any result.

**Grade: PROBABLY WRONG** as a dormant-rule/design-justification defect.

### F11 — “Concentrate in one year” has no executable threshold

**Document and line.** `REV6_FROZEN_SPEC.md:189`.

**Rule, verbatim.**

> `status = insufficient_completion` also fires ... when accepted sessions
> concentrate in one year or era.

**Measurement.** No numeric concentration threshold exists in the YAML. In the formal
corpus, five low-state cells have a majority of contributing sessions in 2021:
open 52.63%, morning 55.02%, midday 54.59%, afternoon 54.63%, and close 57.75%.
Nevertheless all 30 aggregate plane-cells have status `ok`; the operative check only
rejects complete confinement to one year.

**Inference.** “Concentrate” can mean a majority, a preregistered fraction, or total
confinement. Those readings produce different statuses on the measured corpus.

**Consequence already produced.** A majority reading would affect ten plane-cells;
the total-confinement reading affected zero aggregate plane-cells.

**Grade: UNCLEAR.**

### F12 — The liquidity-era justification assumes the boundary fact it lacks

**Documents and lines.** `REV6_FROZEN_SPEC.md:284-297` and
`docs/PHASE10_PREREGISTRATION.md:164-202`.

**Rules, verbatim.** The spec freezes:

> Strata: calendar-quarter × liquidity-era.

The preregistration changes this to quarter only and reasons:

> Calendar quarter is a strictly finer calendar partition, so each quarter already
> falls inside exactly one era.

It later concedes:

> The "each quarter falls inside exactly one era" equivalence is exact when era
> boundaries coincide with quarter boundaries. Any era calendar adopted later that
> splits a quarter would break it.

**Worked example.** An era boundary on 2021-02-15 splits 2021Q1. Quarter-only has one
stratum; quarter×era has two. “Ordered calendar” does not imply quarter-aligned
boundaries.

**Measurement.** No versioned era boundaries exist. The formal run therefore used 16
quarter-only strata over 900 sessions; the smallest had 37 sessions and none triggered
the 20-session floor.

**Inference.** Quarter-only is exactly equivalent only to the implemented single
structural era level, not to the meaningful but undefined liquidity-era rule stated in
the spec. The formal assumption is consequently quarter exchangeability without
liquidity-regime adjustment, as the preregistration itself discloses.

**Consequence already produced.** All calibration mappings used quarter only.

**Grade: UNCLEAR.**

### F13 — The YAML's `null` key is not a string under normal YAML loading

**Document and line.** `analysis_constants_v1.yaml:80`.

**Rule, verbatim.**

> `null:`

**Worked example.** `yaml.safe_load` yields `None in parsed["inference"] == True` and
`"null" in parsed["inference"] == False`; direct string lookup fails. One custom
normalization is required before the file has the key it visibly claims.

**Inference.** The frozen constants file is not a portable, literal source of the
declared null-engine mapping under the parser used by the project.

**Consequence already produced.** Current production is protected by the disclosed
normalization and test, so no formal result used an empty null config. An independent
reproducer using ordinary safe loading receives a different mapping.

**Grade: DEFINITELY WRONG.**

### F14 — The frozen environment rule says a live Git repository is not Git

**Document and lines.** `REV6_FROZEN_SPEC.md:625-632`.

**Rule, verbatim.**

> The workspace is NOT a git repo (git log is empty). Record `"vcs": "none"` in
> fingerprints.

**Measurement.** `C:\mnq-atlas\.git` exists; `git rev-parse` succeeded; the measured
pre-audit branch was `phase-7b-outcome-layer` at `09c28fc`. The sealed calibration
identity records code commit `21ec0ff` and `vcs=git`-style commit identity.

**Inference.** An empty history was conflated with absence of version control.

**Consequence already produced.** Following the frozen sentence literally would make
the reproducibility fingerprint false. Existing artifacts use the disclosed accepted
deviation and record Git identity instead.

**Grade: DEFINITELY WRONG.**

### F15 — Finding F's stated percentages do not reproduce

**Document and lines.** `REV6_FROZEN_SPEC.md:53` and `:191`.

**Rule/finding, verbatim.**

> RTH `[08:30, 15:00)` CT = 71.2% of volume. 08:29 → 08:30 volume jumps
> 0.146% → 0.724%.

**Measurement.** The recorded full-source checks give:

| Population | RTH share | 08:29 | 08:30 |
|---|---:|---:|---:|
| active chain, full 6.9 years | 72.8511% | 0.1134% | 0.6572% |
| active exploration tier | 71.6971% | 0.0980% | 0.6614% |
| active locked tier | 73.7909% | 0.1260% | 0.6538% |
| raw source, all 87 symbols | 72.7950% | 0.1136% | 0.6587% |

The closest RTH value is 0.4971 percentage points away. No recorded population
reproduces any of the three stated percentages. Every population does reproduce the
08:30 boundary and a large volume jump.

**Inference.** The numerical claim has no reproducible denominator/population, while
the boundary conclusion remains supported.

**Consequence already produced.** The RTH boundary is unaffected; reports repeating
71.2% state an unsupported number. No YAML constant encodes the percentage.

**Grade: DEFINITELY WRONG.**

### F16 — Four standalone spec phrases require external rulings to be executable

**Document and lines.** `REV6_FROZEN_SPEC.md:50`, `:74-84`, `:156-159`, `:173-176`,
and `:597-600`.

**Rules, verbatim.**

> `trigger_trade_date` = `effective_trade_date − 1`

> Rebuilt 5-min bars 2023-03-29 → 2026-03-29 row-for-row identical

> `observed_bar_path` — excursions across the bars present in the source

> Bootstrap: whole-session, block sensitivity, dual estimand

**Measurement/worked examples.** Four different ambiguities have nonzero arithmetic:

- A roll triggered Friday 2019-09-13 became effective Monday 2019-09-16: three
  calendar days but one adjacent trading session.
- The Gate 2 file spans UTC labels 2023-03-29 through 2026-03-29 but CME trade dates
  2023-03-30 through 2026-03-30; both descriptions cover the same 211,968 rows.
- Observation-time anchor eligibility admits the 08:25-labeled bar at tau 08:30;
  label-time eligibility does not. The choice moves one anchor per session, about 20%
  of open-phase anchor mass, even though both readings reproduce the registered close
  counts.
- For `observed_bar_path`, allowing a wholly absent 5-minute bar versus requiring every
  5-minute bar changes real cell completion by as much as 0.175 percentage points.
  “Dual estimand” separately admits three plausible pairs elsewhere in the spec.

**Inference.** The frozen phrases alone do not select a unit, date coordinate,
eligibility edge, missing-bar rule, or estimand pair.

**Consequence already produced.** Binding governance rulings selected adjacent
sessions, all Gate 2 rows without a date filter, observation-time eligibility, the
conservative missing-5-minute-bar reading, and the two path estimands. Current results
therefore have defined rules, but those rules cannot be reproduced from the standalone
frozen spec alone.

**Grade: UNCLEAR.**

## 4. Rules checked and found sound

| Rule family | Grade | What was checked |
|---|---|---|
| Time/event model | SOUND | Formal corpus has 900×78 = 70,200 canonical anchors; tau is keyed to observation time. The close-phase structural counts 10/7/1 for 15/30/60 minutes are consistent with the half-open RTH window. |
| Completion | SOUND | At the formal 30-minute surface, minimum target and baseline completion are both 1.0, maximum imbalance is 0, and all 30 plane-cells pass the 0.99/0.05 completion gates. Missing cells remain invalid rather than becoming zero. |
| Weighted q90 contrast | SOUND | The inverse-CDF weighted-quantile contract, session-equal primary weights, and target-minus-baseline sign are internally consistent. The deterministic +60 check moved every intended high contrast by exactly +60. |
| P-value | SOUND | At `B=4999`, `p=(1+k)/5000 <= 0.05` iff `k<=249`; ties are included. No early stopping occurred in sealed evidence. |
| Binomial null gate | SOUND | `P(8<=X<=23)` for `X~Binomial(300,0.05)` is 0.967187924786, with false-failure probability 0.032812075214. The calibration preregistration accurately labels this a chosen discrete band, not exact size. The observed null count 10 passed it. |
| Shared standardization amendment | SOUND | Observed and null values enter one pooled per-cell dispersion and the same denominator is applied to each. Invalid cells remain non-finite. This removes the disclosed observed/null denominator asymmetry. |
| Signed surface topology | SOUND | Positive and negative regions are separate, rook-connected, and missing cells break adjacency. The sealed null regions were nearly sign-balanced (603 positive, 600 negative). |
| RNG/evidence identity | SOUND | The sealed run has 300 unique replication indices, 4 members each, `B=4999`, the declared calibration digest, and code commit `21ec0ff`. No evidence was regenerated. |
| Null strata floor | SOUND | All 16 effective quarter strata have at least 37 sessions, so none is silently pooled or marked unusable. The non-closure of derangements is explicitly disclosed; the real null count, rather than an exactness claim, governs the gate. |
| Calibration gate behavior | SOUND | The conjunctive gate did not allow the passing 10-event null count to rescue the failed power/localization criteria. No acceptance claim was found. |
| Forward error budget | SOUND | `5 × 0.01 = 0.05`; the permanent cap and no-reset rule follow the stated Bonferroni bound without an independence assumption. No forward test was evaluated. |
| Struck-rule audit | SOUND | All 17 §14 entries were checked. Old path-estimand names occur only in rejection tests/docs; there is one formal test; no circular phase rotation, within-phase interaction null, event-day strata, max-t bands, synthetic session generator, production default-quantile oracle, tolerance-window anchor selection, or positive-only/absolute-z region rule was found. The roll-causality fixture begins at 17:00 CT and the classifier uses symbol membership rather than a spread percentage. |

### All 89 YAML leaves

This grouping is exhaustive; the leaf counts sum to 89.

| YAML group | Leaves | Audit disposition |
|---|---:|---|
| `spec_version`, `program_id` | 2 | SOUND identity declarations. |
| `time.*` | 7 | SOUND timezone, bar-label, RTH, maintenance, and tick definitions. The unsupported 71.2% prose claim is not a YAML value and is F15. |
| `session_phases.*` | 5 | Interval partition is internally complete; numerical basis gap is F9. |
| `horizons_minutes` | 1 | Correctly propagated; numerical basis gap is F9. |
| `volatility.*` | 9 | EWMA/MAD/tercile mechanisms execute; seasonal cutoff/shrink provenance and dormancy are F9/F10. |
| `alternative_definitions.*` | 3 | All declared arms exist; ±2/±5 and rolling-60 bases are F9, while 39/156 are reproducible half/double sensitivities around 78. |
| `estimands.*` | 5 | Path, primary weighting, primary population, and diagnostic population are consistent; `population_formal` conflict is F6. |
| `completion.*` | 10 | Source population and S00-derived 0.99/0.99/0.98 values reproduce; 0.90/0.05 bases are F9. |
| `positivity.*` | 5 | All five load and pass aggregate formal cells; annual interaction and basis defects are F1/F2/F9. |
| `bootstrap.*` | 4 | Whole-session/truncation semantics are SOUND; block-number basis is F9. |
| `interaction.*` | 3 | Four-cell common support is explicitly descriptive; reference-level basis is F9. |
| `inference.*` | 17 | One formal test, p-value, RNG, joint mapping, and no-stopping rules are SOUND; `null` parsing is F13, era strata are F12, and threshold basis gaps are F9. |
| `surface.*` | 12 | Primary outcome/horizon/statistic/contrast and signed rook topology are consistent; primary-estimand conflict is F6 and z-threshold basis is F9. |
| `forward.*` | 3 | SOUND arithmetic and no-reset contract; empirical use not evaluated. |
| `reporting.*` | 3 | SOUND no-markers and companion-count requirements. |

Existing binding rulings also make the Gate 2 comparison unambiguous (all 211,968
reference rows, no date filter), define `trigger = effective − 1` as adjacent sessions
rather than calendar-day subtraction, define anchor eligibility at tau, choose the
conservative `observed_bar_path`, and define Phase 5 “dual estimand” as the two path
estimands. Those rulings are sound as current governance, although the frozen spec's
standalone phrases remain insufficient without them.

## 5. Rules not evaluated

- No counterfactual threshold sensitivity was run. The individual numerical
  optimality of the ungrounded constants in F9 is not verified.
- No 970-session alternative formal test was run, so the p-value consequence of the
  holiday-adjacent population change is not verified.
- No locked-confirmation or forward-vintage outcome was read. The empirical behavior
  of the forward alpha/test budget is not verified.
- No alternative liquidity-era calendar exists, so liquidity-era adjustment cannot be
  evaluated.
- The bootstrap's coverage under future regime change is not evaluable from this one
  history; the spec correctly limits that claim.
- The raw-source volume pass behind D10 was not repeated in this session; its recorded
  population measurements and hashes were checked. The 08:30 boundary itself was not
  in dispute.
- Rules for future event-day strata, max-t bands, synthetic session generators,
  standardized interaction populations, and future registries have no current
  executable estimand and were checked only for non-reintroduction.

## 6. Integrity and test record

Pre-audit frozen/protected SHA-256 values:

| Path | Before SHA-256 |
|---|---|
| `REV6_FROZEN_SPEC.md` | `70dae16c8b12fe26d38a7bfdabf0202066fe7149f790d0d2942279d9c3b8ff50` |
| `analysis_constants_v1.yaml` | `1c95aa595c30c48b853303291a7dbaabceaf5b7331bca565a30863e8dcf138d4` |
| `docs/PHASE10_PREREGISTRATION.md` | `aa10cae1b4cc8025e4af33fdecbf42827fd70ef3a8d8e06f28dc03bafc3aaef4` |
| `docs/PHASE10_CALIBRATION_PREREGISTRATION.md` | `6c47d60d14443b4fc2995eb66b39fc82f5716ea552e3bf7a50f59c26d18cc795` |
| `docs/DISCREPANCIES.md` | `61ed0aacc30e714c294c8211ce5f44d31ca6d55d5039fa3e9eba9b212df08767` |

The sealed checkpoint store contained 3,303 files and 36,589,608 bytes. Its
path/content manifest hash before reading was
`8934d19c29315312384571fedcce8d4769fb76a1cffcc3998650d7e07a9886b7`.

Tracked-tree Git object identities before this audit's report work were:

| Scope | Before object |
|---|---|
| `mnq_lab/` | `6ac553e811a1d0fcdbf072401807d41d57e7c0d7` |
| `tests/` | `334f12adef98f8a325915423a7d72fb4b325b211` |
| effect ladder file `mnq_lab/phase10/calibration_controls.py` | `033bce2000979922ad453f6a7ca2315b6724c3af` |

After-audit comparison (before committing this report):

| Protected scope | Before | After | Equal |
|---|---|---|---:|
| `REV6_FROZEN_SPEC.md` SHA-256 | `70dae16c8b12fe26d38a7bfdabf0202066fe7149f790d0d2942279d9c3b8ff50` | `70dae16c8b12fe26d38a7bfdabf0202066fe7149f790d0d2942279d9c3b8ff50` | yes |
| `analysis_constants_v1.yaml` SHA-256 | `1c95aa595c30c48b853303291a7dbaabceaf5b7331bca565a30863e8dcf138d4` | `1c95aa595c30c48b853303291a7dbaabceaf5b7331bca565a30863e8dcf138d4` | yes |
| Phase 10 preregistration SHA-256 | `aa10cae1b4cc8025e4af33fdecbf42827fd70ef3a8d8e06f28dc03bafc3aaef4` | `aa10cae1b4cc8025e4af33fdecbf42827fd70ef3a8d8e06f28dc03bafc3aaef4` | yes |
| Calibration preregistration SHA-256 | `6c47d60d14443b4fc2995eb66b39fc82f5716ea552e3bf7a50f59c26d18cc795` | `6c47d60d14443b4fc2995eb66b39fc82f5716ea552e3bf7a50f59c26d18cc795` | yes |
| `docs/DISCREPANCIES.md` SHA-256 | `61ed0aacc30e714c294c8211ce5f44d31ca6d55d5039fa3e9eba9b212df08767` | `61ed0aacc30e714c294c8211ce5f44d31ca6d55d5039fa3e9eba9b212df08767` | yes |
| production tree `mnq_lab/` Git object | `6ac553e811a1d0fcdbf072401807d41d57e7c0d7` | `6ac553e811a1d0fcdbf072401807d41d57e7c0d7` | yes |
| test tree `tests/` Git object | `334f12adef98f8a325915423a7d72fb4b325b211` | `334f12adef98f8a325915423a7d72fb4b325b211` | yes |
| ladder file Git object | `033bce2000979922ad453f6a7ca2315b6724c3af` | `033bce2000979922ad453f6a7ca2315b6724c3af` | yes |

No frozen file, production file, test, effect-ladder value, corpus artifact, or sealed
evidence artifact was edited. The only repository additions are the authorization
record and this audit report.

Baseline suite command:

```text
python -m pytest tests --ignore=tests/test_bootstrap_acceptance.py -q
1772 passed, 2 skipped, 1 xfailed in 425.66s (0:07:05)
```

After-audit suite command:

```text
python -m pytest tests --ignore=tests/test_bootstrap_acceptance.py -q
1772 passed, 2 skipped, 1 xfailed in 423.38s (0:07:03)
```

The bootstrap acceptance file was neither collected nor run in either suite. Final
sealed-store comparison follows after the mandated detached-checkout verification.

## 7. Residual classification

**MEASUREMENT**

- File/line coverage, hashes, repository identity, corpus/session counts, per-year
  validity, intervention contrast changes, seasonal trigger counts, sealed rejection,
  region/stability/localization counts, and test outcomes are direct measurements.

**INFERENCE**

- Statistical meaning assigned to outcome-informed population selection, unconditional
  localization, missing threshold bases, and the scientific interpretation of the
  effect ladder is inference from the measured mechanisms.

**NOT VERIFIED**

- Counterfactual p-values, alternative thresholds, future-market calibration,
  liquidity-era adjustment, locked/forward results, and causal attribution among the
  several power-failure mechanisms were not verified.
