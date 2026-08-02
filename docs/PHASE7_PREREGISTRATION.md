# Phase 7 Preregistration — Causal Volatility Conditioners and State Validity

**Program:** `mnq-atlas-001`
**Specification:** `REV6_FROZEN_SPEC.md`, revision 6
**Contract date:** 2026-08-01
**Base:** `ded8ba0733f525b31b3cb948ece9a6ada493c9ec`
**Branch:** `phase-7-conditioners`
**Status:** frozen contract proposed for independent ratification; production code is not authorized before `RATIFIED`

## 1. Governance and phase boundary

This document is the executable contract required before Phase 7 production.
It transcribes user-ratified U13 and U14 and fixes the remaining design latitude
without changing `REV6_FROZEN_SPEC.md` or `analysis_constants_v1.yaml`.

Phase 7 owns:

- causal five-minute close-to-close return construction;
- bias-adjusted EWMA RMS scales at halflives 39, 78, and 156;
- the independent rolling-MAD scale;
- permissive and strict component-coverage definitions;
- the accepted-calendar-qualified seasonal profile;
- `vol_rel`;
- expanding, rolling-60, and shifted-percentile tercile thresholds;
- causal conditioner assignments;
- alternative-definition cell migration; and
- the descriptive state-validity panel.

Phase 8 owns named outcome contrasts, positivity/overlap gates, and the
interaction estimand. Phase 9 owns prevalence on its own support. Phase 10 owns
null engines, calibration, and surface inference. Phase 11 owns guards, the
result ledger, vintages, forward budgets, and the final environment fingerprint.
Phase 12 owns S01A rendering and the Field Guide. Phase 7 emits no contrast,
prevalence, p-value, null, confirmation, vintage, forward-budget, report, S01A,
profitability, or trading artifact. A module-boundary test rejects Phase 7
imports of `mnq_lab.studies`, `mnq_lab.nulls`, or `mnq_lab.report`, and a planted
Phase 8 artifact key in a Phase 7 manifest must fail.

The accepted calendar reference input and its closeout are inherited from the
audited base. Its acceptance authorizes the input only. No production code may
be written until this document is committed, byte-pinned, and independently
ratified. Audit cadence is exactly two checkpoints: this contract ratification
and final Phase 7 closeout, unless a protected artifact changes or a fail-closed
gate fires. Phase 8 remains unauthorized.

## 2. Immutable definitions and arm inventory

### 2.1 Fixed arm order

The following order is immutable and is used in every artifact and registry.
Only one factor differs from the frozen primary in each sensitivity arm.

| order | arm_id | scale | coverage | threshold history | quantiles |
|---:|---|---|---|---|---|
| 0 | `primary_ewma78_permissive_expanding` | EWMA h=78 | permissive | expanding | 1/3, 2/3 |
| 1 | `coverage_strict` | EWMA h=78 | strict | expanding | 1/3, 2/3 |
| 2 | `ewma39` | EWMA h=39 | permissive | expanding | 1/3, 2/3 |
| 3 | `ewma156` | EWMA h=156 | permissive | expanding | 1/3, 2/3 |
| 4 | `mad78` | MAD 78 | permissive | expanding | 1/3, 2/3 |
| 5 | `threshold_rolling60` | EWMA h=78 | permissive | latest 60 qualifying sessions | 1/3, 2/3 |
| 6 | `threshold_shift_m05` | EWMA h=78 | permissive | expanding | 1/3−0.05, 2/3−0.05 |
| 7 | `threshold_shift_m02` | EWMA h=78 | permissive | expanding | 1/3−0.02, 2/3−0.02 |
| 8 | `threshold_shift_p02` | EWMA h=78 | permissive | expanding | 1/3+0.02, 2/3+0.02 |
| 9 | `threshold_shift_p05` | EWMA h=78 | permissive | expanding | 1/3+0.05, 2/3+0.05 |

The strict/permissive pair is deliberately not selected after measuring
coverage. The permissive definition occupies the frozen-primary pipeline
position solely to make the OFAT construction and artifact order executable;
both definitions are always emitted, their undefined fractions are reported by
year and session phase, and their assignment migration cross-tab is mandatory.
No measured result may promote, suppress, rename, or substitute either arm.

The MAD arm is a full normalization-sensitivity pipeline: its own seasonal
profile, `vol_rel`, expanding thresholds, assignments, and migration table. It
is an explicit U13/U14 scope addition beyond the YAML
`alternative_definitions` block and remains identified as the independent MAD
normalization sensitivity, never as a fourth EWMA parameter. The other arms are
the frozen YAML sensitivities. There is no factorial combination of arms.

### 2.2 Category encoding

The immutable integer encoding is `undefined=-1`, `low=0`, `mid=1`, `high=2`.
Names and codes are never reordered by measured frequency. Low means
`x <= lower`; mid means `lower < x <= upper`; high means `x > upper`. When
`lower == upper`, `threshold_status=degenerate_boundaries`; the same mapping is
still applied, the middle category is emitted with count zero, and no row or
declared category is dropped.

## 3. Event time, anchors, and input support

`ts_event` is the bar-open UTC nanosecond label for `[t,t+5 minutes)`.
Observation time is `tau = ts_event + 5 minutes`. Every time-of-day bucket and
phase uses `tau` converted with `ZoneInfo("America/Chicago")`, never the bar
label and never a fixed UTC offset.

State-anchor eligibility is the full declared observation-time grid
`08:30 <= tau < 15:00` CT. A normal session has 78 rows: the 08:25-labelled bar
has `tau=08:30` and is the first anchor; the 14:50-labelled bar has `tau=14:55`
and is the last. The 14:55-labelled bar has `tau=15:00` and is not an anchor.
Missing anchor bars remain explicit status rows. `tau=14:50` and `tau=14:55`
remain state anchors even where no future outcome horizon is available.
Conditioner construction and assignment never depend on outcome completeness.

Return support is the full Globex session, not RTH-only. The canonical session
is 17:00 CT on the prior calendar date through 16:00 CT on the trade date, with
the 16:00–17:00 maintenance halt excluded. Full-Globex support is necessary
because one RTH session contains only 78 bars and therefore only 77 internal
close-to-close returns, fewer than the required 78.

The only Phase 7 bar adapter has no tier, corpus, path, or override argument. It
resolves only `Corpus.EXPLORATION`. It validates before computation:

- manifest corpus `exploration`, frequency `5m`, `bar_seconds=300`, expected
  program/pipeline identity, hashes, nonempty date range, and coverage within
  the exploration seal;
- required one-dimensional aligned columns `ts_event_ns`, `session_id`,
  `symbol_code`, `open_ticks`, `high_ticks`, `low_ticks`, `close_ticks`,
  `volume`, `expected_1m_components`, `observed_1m_components`,
  `component_coverage_rate`, and `rollover` with the manifest-declared exact
  integer, float, and boolean dtypes;
- strictly increasing and unique timestamps, valid session ownership,
  nonempty decoded symbols, positive tick prices, nonnegative volume,
  `high >= max(open,close,low)`, `low <= min(open,close,high)`, finite coverage,
  and `0 <= observed <= expected == 5`.

Any validation failure halts. Synthetic unit tests construct arrays directly
and require no store. The adapter lives in `mnq_lab/spine/` or
`mnq_lab/conditioners/`, never `core/`; `core/` remains market-free. The adapter
cannot name, accept, stat, enumerate, import, open, or mmap the locked tier. No
confirmation or forward data enters Phase 7.

## 4. Returns, continuity, and resets

For two adjacent valid bars of the same decoded symbol, the return ending at the
second bar's observation time is evaluated in this written binary64 order:

```text
ratio = float64(close_ticks_current) / float64(close_ticks_previous)
r_t   = log(ratio)
```

Prices must be strictly positive. No open-to-close, tick difference, overnight
bridge, or `log(C_t)-log(C_{t-1})` alternative is permitted. The current anchor
return is formed and updates the scale before the value returned at `tau`.

The permissive coverage arm accepts a present five-minute bar with one through
five observed components and carries `observed_1m_components` and
`component_coverage_rate`; zero observed components cannot form a present bar.
The strict arm accepts a bar only when all five expected components are present.
An insufficient strict bar breaks contiguity and cannot be either endpoint of a
return. The following complete bar starts a new segment rather than bridging
the invalid bar.

A contiguous run breaks at a contract roll or decoded-symbol change, any
non-five-minute UTC spacing, an absent bar, a strict-arm coverage failure, the
scheduled 16:00–17:00 CT maintenance halt, or the weekend closure. The
maintenance halt and weekend are gaps under frozen §4.3 and U3: EWMA and MAD
carry no cross-day memory. A roll sets `reset_reason=roll_reset`; every other
break sets `reset_reason=gap_reset`. `scheduled_break=true` only for the
maintenance halt or weekend, distinguishing scheduled gaps from anomalies
without changing the failure family. No return spans a reset.

The first bar of a new segment has no return. At a roll it has
`return_missing_reason=symbol_change`; after a time discontinuity it has
`spacing_break`; a strict coverage failure has `insufficient_components`; an
absent declared anchor has `bar_absent`. Roll identity takes precedence over
spacing when both occur at the same boundary. Coverage failure takes precedence
over spacing only when the bar is present at the expected timestamp. These
precedence rules make the status mapping total.

## 5. Bar-scale estimators

### 5.1 Bias-adjusted EWMA RMS

For halflife `h` in `{39,78,156}`:

```text
decay_h = exp(log(0.5) / float64(h))
alpha_h = -expm1(log(0.5) / float64(h)) = 1 - decay_h

at reset: num = 0.0; den = 0.0; contiguous_return_count = 0
for each valid return r_t ending at or before tau:
    num = decay_h * num + r_t * r_t
    den = decay_h * den + 1.0
    contiguous_return_count += 1
    rms = sqrt(num / den)
```

Each multiplication, addition, division, and square root is binary64 in the
written order, with no fused or algebraically rearranged implementation claimed
byte-equivalent. The bias adjustment removes a separate seed term; the first
squared return has its normalized geometric weight rather than being installed
as `v_1`. Output is `warmup` until exactly 78 contiguous returns have updated
the recursion, for every halflife. The first defined result is returned after
the 78th current return is included. A finite zero RMS is valid and canonicalized
to `+0.0`; a negative or non-finite intermediate or output is corruption and
halts.

R3 and R4 are coupled: fixed 78-return warmup is authorized only with this
bias-adjusted numerator/denominator recurrence. Changing initialization reopens
the warmup ruling.

The following arithmetic disclosure accompanies every halflife-sensitivity
panel; it is a limitation, not a measured MNQ result:

| h | den at 78 | den near RTH open (186 returns) | den at 275 | steady-state den | fraction of steady state at 275 |
|---:|---:|---:|---:|---:|---:|
| 39 | 42.57 | 54.68 | 56.34 | 56.77 | 99.2% |
| 78 | 56.52 | 91.39 | 103.22 | 113.03 | 91.3% |
| 156 | 66.07 | 126.85 | 159.09 | 225.56 | 70.5% |

Daily reset caps all arms at one Globex session. The realized effective-history
contrast is narrower than the nominal 39:78:156 halflife ratio, and the h=156
arm never reaches its steady-state window.

### 5.2 Independent rolling MAD

At `tau`, MAD uses exactly the 78 most recent valid contiguous returns ending at
or before `tau`, within one segment and decoded symbol:

```text
center = Q_return(0.5, method="inverted_cdf")
mad    = Q_abs(r_i-center)(0.5, method="inverted_cdf")
scale  = float64(1.4826) * mad
```

`inverted_cdf` means the lower order statistic at even `n`; it is used for both
centering and absolute-deviation medians. The constant 1.4826 is not adjusted
for the small downward effect of the lower-median convention, and that fact is
disclosed. With fewer than 78 contiguous returns, status is `warmup`. If the
MAD is exactly zero, status is `zero_scale` and no numeric scale is emitted.
Negative or non-finite output is corruption and halts.

## 6. Accepted calendar and completed-session qualification

The only calendar input is the accepted immutable JSON:

`mnq_lab/spine/calendar_inputs/cme_equity_index_v1/cme_equity_index_sessions_20190506_20230329_v1.json`

Its required SHA-256 is
`b86e112c16112bf11a6a548ca8b3f21d28a08f90442b4dde84098f9d3f6eb069`,
schema version `cme-equity-index-session-calendar-v1`, calendar version
`mnq-cme-equity-index-calendar-v1`, timezone `America/Chicago`, and coverage
2019-05-06 through 2023-03-29. Its manifest, acceptance record, provenance,
ledger, and closeout remain protected by the audited base.

Seasonal-reference eligibility comes only from this calendar. A qualifying
completed session for an arm and phase must:

1. precede the current session strictly by trade date;
2. have its scheduled Globex interval end at or before the exploration
   truncation boundary (`seal_boundary - max_horizon_bars` at the corpus edge);
3. be calendar class `regular`, not `full_exchange_holiday` or
   `scheduled_early_close`;
4. have at least one defined scale observation for that arm in the phase.

Full holidays and scheduled early closes are excluded from the reference and do
not count toward 60-session warmup or rolling-60 history. Holiday-adjacent rows
and externally identified unscheduled closures are flagged but not excluded.
Observed shortening, `observed_rth_ended_early`, `observed_no_rth_bars`, and
`observed_mid_rth_gap` never create or change a calendar class. A calendar-
regular truncated or gapped session remains eligible if it otherwise meets the
rule, with its reduced observations and data-quality flag disclosed. Future
outcome completeness never qualifies a session.

A missing calendar row inside accepted coverage is corruption and halts. A
synthetic or explicitly out-of-coverage requested session emits
`calendar_classification_missing`; it may not be silently treated as regular.
`unscheduled_closure` may be populated only by an authoritative input, never
inferred from bars.

Holiday-adjacent means the immediately preceding and immediately following
scheduled trading session around each full holiday or scheduled early close,
using the accepted table's active-session order. No 2026 trade-date rule is
applied to this historical artifact.

## 7. Seasonal profiles

Profiles are materialized for each `(arm_id, current_session_id,
observation_bucket)` in the 78-bucket RTH observation grid. The bucket key is
the CT wall-clock `HH:MM` of `tau`; the phase is the exact half-open mapping in
the frozen YAML. Each qualifying strictly prior session contributes at most one
defined scale value to a bucket.

For a current session and phase, let each qualifying prior session's phase value
be the `inverted_cdf` median of that session's defined arm-scale values in the
phase. The phase fallback is the `inverted_cdf` median of those per-session
phase medians. This gives each qualifying session one unit of mass regardless
of its anchor count.

For bucket `b`, `n` is the number of qualifying strictly prior sessions having
a defined arm-scale value at `b`. Each contributes exactly one observation, so
the bucket median needs no additional equal-mass weighting. After at least 60
qualifying prior sessions exist for the arm and phase:

```text
bucket_median = inverted_cdf median of the n bucket values
phase_median  = inverted_cdf median of per-session phase medians

if n >= 30: profile = bucket_median
if 0 < n < 30:
    w = float64(n) / float64(n + 30)
    profile = w * bucket_median + (1.0 - w) * phase_median
if n == 0: profile = phase_median
```

Operations occur in the written binary64 order. Sessions 1 through 60 on the
qualifying arm/phase clock are `warmup`; the first profile and assignment are
on the 61st qualifying session. Warmup is evaluated separately by arm and
phase. If the phase fallback has no defined member, status is
`seasonal_fallback_unavailable`. Negative or non-finite profile values halt;
zero is finite and retained so downstream `vol_rel` can report `zero_scale`.

DST keys remain CT wall-clock. Contiguity is evaluated in exact UTC nanoseconds.
CME equity-index DST changes occur inside the weekend closure, so no real corpus
session contains an intra-session repeated or skipped wall time. A synthetic
fixture plants an intra-session UTC-offset change and must break recursion; a
real-data test only verifies identical RTH wall-clock bucket keys across both
transition weeks and must not claim to exercise an intra-session transition.

## 8. Relative volatility

For a defined current scale and seasonal profile:

```text
vol_rel = float64(scale) / float64(seasonal_profile)
```

It is one binary64 division with no intermediate rounding. A non-finite or
negative operand is corruption. A zero denominator emits `zero_scale` and no
numeric value. A zero numerator over a positive denominator yields canonical
`+0.0`. Any non-ok operand status emits `upstream_undefined` with the exact
`upstream_stage`; no `inf`, `nan`, or signed negative zero is emitted.

## 9. Tercile thresholds and assignments

Thresholds are computed separately for each arm, current session, and session
phase over eligible `vol_rel` rows from qualifying strictly prior sessions.
Current-session and future-session rows are forbidden. Each prior session with
at least one eligible value in the phase receives total mass 1, distributed
uniformly across its eligible anchors. A session with zero eligible anchors
contributes no mass and does not count toward warmup or the rolling window.

The expanding primary and all non-rolling arms use all qualifying prior
sessions. `threshold_rolling60` uses the latest 60 sessions satisfying the same
qualification rule. The first threshold and assignment occur on the 61st
qualifying session; earlier rows have
`threshold_status=insufficient_threshold_history` and
`assignment_status=warmup`.

Boundaries use the frozen weighted inverse CDF:

```text
Q(q) = inf{x : sum(w_i for x_i <= x) / sum(w_i) >= q}
```

The unshifted probabilities are exactly `1/3` and `2/3`. A signed shift `d` in
`{-0.05,-0.02,+0.02,+0.05}` is added to both probabilities. The implementation
must use the Phase 4 weighted-quantile kernel and the `inverted_cdf` convention,
never default linear interpolation. Threshold output is deterministic even
under heavy ties. `lower > upper`, non-finite values, negative weights, or zero
total mass are corruption; `lower == upper` is the explicit
`degenerate_boundaries` status described in §2.2.

Thresholds are materialized once per `(arm_id, session_id, phase)` before
anchor assignment. Assignment combines the current `vol_rel` with those
strictly prior thresholds. The anchor's return may enter current `vol_rel`; the
anchor and current session may not enter its thresholds.

## 10. Exact semantic dependency windows

Dependency masks are boolean over BAR indices on the event-time coordinate axis.
A window whose first return is `r_i` includes bar `i-1`; 78 returns span 79
bars. Expected masks are constructed in tests from the pseudocode in this
section and never by calling an estimator, its window accessor, or its metadata.
Admission requires `numpy.array_equal(declared_mask, semantic_mask)`. Equality,
not containment, closes D17 #8.

Define:

```text
segment_start(tau):
    first valid bar of the contiguous run containing anchor_bar(tau)
    where a run breaks at roll/symbol change, non-5-minute spacing,
    maintenance halt, weekend closure, absent bar, and, for strict coverage,
    any bar with fewer than five components
```

The exact masks are:

- EWMA h=39/78/156: bars `[segment_start(tau), anchor_bar]`, inclusive. All
  three halflives have bit-identical masks. Undefined warmup outputs still
  expose the structural declared segment mask but are not admitted as defined
  witness cases.
- MAD: exactly bars `[anchor_bar-78, anchor_bar]`, 79 bars inclusive, all in
  one contiguous same-symbol run. If unavailable, MAD is undefined and no
  defined-output admission case exists for that anchor.
- Seasonal profile `(s,b,a)`: the scale-series row at bucket `b` from each
  qualifying strictly prior session for arm `a`, plus every scale-series member
  used to construct the per-session phase medians and phase fallback. No row
  from session `s` and no row after a prior session's end.
- `vol_rel`: the current anchor scale row plus exactly its seasonal-profile
  dependency rows.
- Expanding, rolling-60, and shifted thresholds: exactly the eligible
  same-phase `vol_rel` rows from the qualifying strictly prior sessions used by
  that arm; only the latest 60 for rolling.
- Assignment: the current `vol_rel` row plus exactly its threshold dependency
  rows.

Required semantic-mask failures are: EWMA widened one bar before
`segment_start`; any mask widened one bar after the anchor; any mask narrowed
one required bar; MAD narrowed to 78 bars; and MAD widened back to
`segment_start` on a run longer than 79 bars. On that long-run fixture, mutating
bar `anchor-79` must change EWMA while MAD remains bit-identical. The same
mutation proves both meanings without consulting either implementation.

Composite-stage fixtures additionally widen a seasonal mask with a different
bucket, add the current session to a profile, add the current session to a
threshold, and add the 61st-oldest qualifying session to rolling-60; each must
fail exact mask equality even if the value happens not to change.

## 11. Closed status taxonomy

Missingness receives a status; corruption halts. Every declared anchor row is
emitted. Every vocabulary is closed, every required companion field is checked,
and an unmatched combination raises with no default branch.

| field | allowed values and rules |
|---|---|
| `anchor_status` | `ok`, `anchor_bar_missing` |
| `return_status` | `ok`, `missing_return` |
| `return_missing_reason` | empty iff return is ok; otherwise exactly `bar_absent`, `insufficient_components` (strict only), `spacing_break`, or `symbol_change` |
| `reset_reason` | `none`, `roll_reset`, `gap_reset` |
| `scheduled_break` | boolean; true only for maintenance/weekend gap reset |
| `ewma_status` | `ok`, `warmup` |
| `mad_status` | `ok`, `warmup`, `zero_scale` |
| `seasonal_status` | `ok`, `warmup`, `seasonal_fallback_unavailable`, `calendar_classification_missing` |
| `vol_rel_status` | `ok`, `zero_scale`, `upstream_undefined` |
| `upstream_stage` | required iff `vol_rel_status=upstream_undefined`; one of `ewma`, `mad`, `seasonal` |
| `threshold_status` | `ok`, `insufficient_threshold_history`, `degenerate_boundaries` |
| `assignment_status` | `ok`, `warmup`, `upstream_undefined` |

At a reset boundary the first post-reset row carries the reset reason; later
warmup rows use `reset_reason=none`. `anchor_bar_missing` implies
`return_status=missing_return` and `bar_absent`. `roll_reset` implies
`symbol_change`; `gap_reset` cannot. A permissive partial bar cannot use
`insufficient_components`. `scheduled_break=true` requires `gap_reset` and
`spacing_break`. A numeric field is present only when its stage status permits
it. Negative or non-finite scale, invalid calendar class/status combinations,
unmatched statuses, impossible timestamp ordering, and mask violations halt.

Each identity has a planted fixture: missing anchor, missing prior bar, strict
partial bar, spacing gap, symbol change, 77-return warmup, constant 78-return
MAD, 59 prior sessions, absent bucket with and without phase fallback, zero
seasonal scale, missing synthetic calendar classification, degenerate tied
thresholds, and every upstream propagation. One unmatched combination must halt
rather than emit.

## 12. Registry admission

Every real anchor-level causal callable enters only through the Phase 6
`register_causal_conditioner` in-call path. The identifier formula is:

```text
mnq.phase7.<stage>.<arm_id>.v1
```

where `stage` is one of `scale`, `seasonal_profile`, `vol_rel`, `thresholds`, or
`assignment`, and only applicable arm/stage pairs are instantiated. Shared
primary-scale/profile objects used by rolling and shifted threshold arms retain
their primary identifier rather than being re-registered aliases. Duplicate
identifiers or callable identities fail.

Immutable registration metadata includes stage, arm id/order, estimator kind,
halflife or MAD window, coverage rule, warmup, bucket timezone, calendar version
and hash where applicable, threshold history, quantile probabilities, exact
semantic-mask version, output kind, and comparison policy. Sensitivity metadata
names the one varied factor and value and is descriptive only; no selection,
ranking, or substitution code may read it.

Admission executes nonempty locality cases, deterministic witnesses, and both
Phase 6 negative-control failure identities atomically, then additionally
asserts exact independent semantic-mask equality for every real case. Caller-
created evidence is never accepted; a Phase 7 negative test attempts to reuse a
different callable's evidence and must be rejected. Alternative arms are causal
because they obey event time and produce causal assignments. State-validity
calculations are descriptive analyses, not conditioners, and never enter the
causal registry. A deliberately leaky or bridging callable is test-only and
never registered.

Exact outputs—timestamps, ticks, masks, counts, integer categories, booleans,
status enums, and identifiers—use exact comparison. Float64 estimators use
`OutputKind.FLOAT`, `atol=0.0`, `rtol=1e-12` in immutable metadata and the Phase
6 disjoint two-band witness rule. Tolerance may not hide timestamp, mask,
category, or status disagreement.

## 13. Output schemas and deterministic artifacts

All tables use immutable column order and ascending event/session order. No row
is sorted by a measured value. Strings use closed ASCII vocabularies;
timestamps are int64 UTC nanoseconds; session IDs are int32 `YYYYMMDD`; category
codes are int8; counts are int64; flags are boolean; numeric scales, profiles,
thresholds, correlations, entropy, and fractions are float64.

### 13.1 Anchor-scale table

One row per `(coverage_arm, scale_estimator, session_id, tau)` ordered by fixed
coverage/estimator order, session, then tau:

```text
arm_id, session_id, ts_event_ns, tau_ns, observation_bucket_ct, session_phase,
symbol_code, observed_1m_components, component_coverage_rate,
anchor_status, return_status, return_missing_reason,
reset_reason, scheduled_break, contiguous_return_count,
scale_value, ewma_status, mad_status
```

Only the status applicable to the estimator is nonempty. Missing numeric values
use a separate validity boolean in `.npy` storage, never NaN as a status.

### 13.2 Seasonal-profile table

One row per `(scale arm, current session, bucket)` ordered by scale-arm order,
session, bucket:

```text
arm_id, session_id, observation_bucket_ct, session_phase,
qualifying_prior_sessions, bucket_n, bucket_median,
phase_session_median, shrink_weight, seasonal_profile,
seasonal_status, calendar_version, calendar_sha256
```

### 13.3 Threshold table

One row per `(assignment arm, session, phase)` ordered by arm, session, frozen
phase order:

```text
arm_id, session_id, session_phase, history_kind,
qualifying_prior_sessions, lower_probability, upper_probability,
lower_threshold, upper_threshold, threshold_status
```

### 13.4 Assignment table

Every declared anchor appears for every arm, ordered by arm, session, tau:

```text
arm_id, session_id, ts_event_ns, tau_ns, observation_bucket_ct, session_phase,
scale_value, scale_valid, seasonal_profile, seasonal_valid,
vol_rel, vol_rel_valid, vol_rel_status, upstream_stage,
lower_threshold, upper_threshold, threshold_status,
category_code, category_name, assignment_status,
calendar_session_class, holiday_adjacent, data_quality_status
```

### 13.5 Artifact manifest

Phase 7 arrays use the existing immutable `.npy` column-store pattern with a
canonical sorted-key UTF-8 JSON manifest. The manifest records source build ID;
hashes of the frozen spec, YAML, this preregistration, and accepted calendar;
calendar and schema versions; code commit and dirty flag; environment
fingerprint; arm and schema versions; row counts; per-column dtype, byte count,
and SHA-256; and every registry comparison policy. Seasonal, `vol_rel`,
threshold, assignment, or validity artifacts require non-null calendar version
and hash. A null calendar hash in any such artifact halts.

Semantic determinism is always required: exact for discrete fields and within
the registered float tolerance for float64 fields. Byte identity is required
only when the complete environment fingerprint matches. Same-fingerprint
reruns must be byte-identical. No unconditional cross-environment floating-byte
claim is made. Negative zero is canonicalized before storage.

## 14. Prefix invariance

A build through session `T` and a build through `T+k` must agree for every
pre-`T` Phase 7 key and status exactly and for floats under the artifact policy.
Under a matching fingerprint their pre-`T` bytes must be identical.

The existing xfails `seasonal_profiles`, `tercile_thresholds`, and
`conditioner_assignments` become real passing tests and are removed only by that
conversion. `prevalence_results` remains deferred to Phase 9 and
`consumed_vintage_artifacts` to Phase 11. The calendar A5 xfail becomes a real
passing test before the first Phase 7 implementation commit.

Each positive prefix check has a nonempty-prefix and nonempty-extension vacuity
guard. Required negative controls independently demonstrate failure for:

- corpus-wide normalization;
- seasonal inclusion of the current or any future session;
- thresholds including the current session;
- carrying an extended-corpus assignment backward into the prefix; and
- same-session threshold construction.

The bar-scale EWMA and MAD series also receive prefix-invariance tests even
though they were not among the original five xfails.

## 15. `test_roll_reset` and reset equivalence

The frozen §13 item-18 name is a file-level convention. Phase 7 creates
`tests/test_roll_reset.py`, and an append-only discrepancy entry records the
convention and closes F-0. No standalone pre-implementation documentation
commit is made; the discrepancy update accompanies the authorized Phase 7 test
unit.

The synthetic fixture contains a mid-corpus contract roll and asserts:

1. no return spans the roll; the boundary row is `missing_return` with
   `symbol_change`;
2. every post-roll EWMA and MAD value is bit-identical to a from-scratch run on
   the post-roll segment alone—not merely different from the pre-roll value;
3. no scale is emitted before 78 contiguous post-roll returns; the boundary is
   `roll_reset`, followed by `warmup` rows;
4. the same from-scratch equivalence holds for an anomalous gap and the
   maintenance halt, with `scheduled_break=true` only for the halt; and
5. a test-only implementation carrying numerator/denominator across the roll
   fails the from-scratch equality assertion.

The fixture contains enough post-reset returns for defined EWMA and MAD output;
otherwise the proof would be vacuous.

## 16. Calendar isolation gate A5

Before any EWMA, MAD, seasonal, `vol_rel`, threshold, or assignment computation
is committed, `a5_calendar_import_isolation` must convert from strict xfail to a
passing test. EWMA, MAD, return, and median scale modules may neither import the
calendar module nor accept a calendar/path argument. The positive test executes
real scale modules while a monkeypatched calendar loader raises a sentinel and
proves it is never reached. A test-only mutant that adds the calendar access
must reach the sentinel and fail. Seasonal-reference qualification is the first
and only layer allowed to read the accepted calendar. Deleting the xfail without
this conversion is forbidden.

## 17. Descriptive state-validity panel

State validity is computed only after causal assignments exist. It is
descriptive, emits no composite score or pass/fail decision, and never ranks an
arm, state, or parameter. Its support is `state_anchors`, independent of future
outcome availability.

Rows are ordered by fixed arm order, frozen phase order, metric order, category
code, comparison-arm order, year, and horizon—never by value. The fixed metric
order and definitions are:

1. `category_frequency`: counts and fractions for undefined, low, mid, and high
   on all declared state anchors, plus assignment-status counts. Denominators
   are explicit.
2. `average_run_length`: arithmetic mean of maximal consecutive equal defined
   category runs within an arm and phase. Runs reset at session/phase boundary,
   gap, roll, warmup, missing, or undefined assignment. Emit episode count and
   total anchors with the mean.
3. `transition_entropy`: within each arm and phase, pool only adjacent defined
   five-minute transitions not spanning any reset. Let `N_ij` be transition
   counts, `P_ij=N_ij/sum_j N_ij`, and
   `pi_i=sum_j N_ij/sum_ij N_ij`. Emit the complete 3×3 count and probability
   matrix and `H=sum_i pi_i*(-sum_j P_ij*log2(P_ij))`, with
   `0*log2(0)=0`. If no eligible transition exists, emit undefined status rather
   than zero entropy.
4. `cell_migration`: primary-by-alternative 4×4 cross-tabs including undefined
   for every alternative arm, on identical declared anchor keys; emit counts,
   row fractions, common-defined changed fraction, and directional undefined
   counts. Comparisons are always primary versus one OFAT arm, never variants
   against each other for selection.
5. `threshold_drift`: emit the complete lower and upper threshold series by arm
   and phase, followed by the preregistered summary
   `median_absolute_consecutive_change` separately for each boundary over
   adjacent qualifying sessions. No fitted trend, post-hoc interval, or
   alternative summary is selected.
6. `raw_volatility_correlation`: Spearman correlation, using average ranks for
   ties, between ordered defined category code and that arm's unseasonalized
   raw scale on common defined anchors, by arm and phase. For rolling/shifted
   threshold arms the raw scale is the shared primary EWMA; for MAD it is MAD.
   Emit pair count and undefined status when variance is zero or support is
   insufficient. Strong positive association is expected by construction and
   is not a finding or validation.
7. `missingness_completion_correlation`: completion and missingness appear only
   as right-hand-side diagnostic variables. Emit Spearman correlation with
   average tie ranks between defined category code and (a) anchor
   `observed_1m_components/5`, and (b) each binary
   `outcome_complete_h15`, `outcome_complete_h30`, and
   `outcome_complete_h60`, separately by arm and phase. Also emit the association
   between assignment-definedness and each RHS over all declared anchors. These
   RHS values may not enter returns, dependency masks, profiles, thresholds, or
   assignments. Horizon diagnostics are separate and never change state support.
8. `liquidity_era_correlation`: emit one explicit row per arm and phase with
   `liquidity_era_status=deferred_missing_versioned_input`, null value, and zero
   consumed era rows. No era boundaries exist and none may be invented. This is
   the user-ratified R11 deferral and remains visible for later amendment.
9. `undefined_warmup_fraction`: counts and fractions for every non-ok stage
   status by arm, phase, and year, including strict/permissive undefined
   fractions. Denominators include all declared state anchors.

No state-validity metric may depend on whether an anchor has a usable future
outcome except the explicitly named RHS completion correlations. The panel may
not become Phase 9 prevalence: it does not emit bar occupancy, episode
prevalence, session presence, or entry/exit prevalence estimands. It may not
auto-pass or auto-fail a state, invent a quality score, choose a preferred arm,
or sort by a measured result.

## 18. Test and mutation floor

Every assertion has a matched negative input or named mutation, and every
fixture has a vacuity guard proving it exercises the asserted region. A mutant
counts as killed only when the intended assertion fails for the intended
identity. Witness expectations are hand-computed from this contract or an
independent reference construction, never obtained from the implementation.

The mandatory floor is:

1. bucket seasonal values by bar-open label instead of observation time;
2. omit the anchor return;
3. read one return ending after `tau`;
4. bridge an absent or non-five-minute interval;
5. fail to reset at a contract roll;
6. bridge the maintenance halt or weekend;
7. emit EWMA or MAD before 78 contiguous returns;
8. replace bias-adjusted EWMA with `v_1=r_1^2` seeding;
9. use a non-lower median for either MAD median;
10. include the current or a future session in a seasonal profile;
11. use fewer than 60 qualifying strictly prior sessions;
12. count calendar-excluded sessions toward warmup;
13. include a scheduled holiday or early close in the seasonal reference;
14. infer a calendar class solely from observed shortening;
15. use bar-label time for seasonal buckets;
16. permit an absent bucket without the phase fallback or omit the unavailable
    fallback status;
17. pool anchors for the phase fallback instead of taking per-session medians;
18. use anchor-equal rather than session-equal threshold mass;
19. calculate thresholds from the current session;
20. use default linear quantiles;
21. reverse or blur the pinned tie boundaries;
22. silently omit the middle category under degenerate thresholds;
23. assign on the 60th rather than 61st qualifying session;
24. carry an assignment backward when the corpus is extended;
25. widen or narrow each real semantic dependency mask as specified in §10;
26. derive a semantic mask or witness expectation from implementation metadata;
27. bypass or borrow causal-registration evidence;
28. make assignment depend on future outcome completion;
29. rank alternatives, measured states, or parameters;
30. access, name, or accept the locked tier;
31. allow a calendar import from scale code;
32. emit a seasonal-dependent artifact with a null or wrong calendar hash;
33. accept an unknown status or impossible status combination;
34. place market-aware code in `core/`; and
35. add a contrast, prevalence, null, vintage, or report artifact to Phase 7.

The accepted calendar's own A1–A7 gate remains passing and protected; Phase 7
does not re-author or relabel it.

## 19. Phase 7 gates and implementation order

Frozen §15 row 7 requires tests 6 and 13:

- Test 6 passes only when every real callable completes Phase 6 locality,
  deterministic witness, negative-control admission, and U14 exact semantic-
  mask equality, including the EWMA/MAD long-run discriminating cross-check.
- Test 13 passes only when `test_spec_consistency` asserts the frozen YAML and
  this preregistration agree on event-time buckets, phases, warmups, halflives,
  MAD window/factor, seasonal shrinkage, threshold definitions, arm inventory,
  calendar identity, statuses, category encoding, deferred liquidity era, and
  Phase 7/8/9 boundaries. A changed critical value must fail.

Implementation proceeds tests first in this fixed order, without intermediate
audit checkpoints:

1. real A5 isolation conversion, exploration adapter, return construction,
   closed statuses, and independent semantic-mask fixtures;
2. bias-adjusted EWMA and rolling MAD, including prefix invariance and
   `test_roll_reset`;
3. accepted-calendar loader and seasonal profiles, including DST, exclusion,
   shrinkage, and prefix invariance;
4. `vol_rel`, threshold families, assignments, and their prefix-invariance and
   migration tests;
5. integrated real-conditioner adversarial registry gate;
6. descriptive state-validity panel and deterministic artifacts; and
7. `docs/PHASE7.md`, protected hashes, and the authorized safe suite.

If any fail-closed gate fires, implementation stops at the first mismatch and
classifies the cause under frozen §16.6. It may not relax a threshold, widen a
mask, infer a holiday, change a constant, or code around the discrepancy. A
protected-artifact change also forces a new independent review. Otherwise the
only next independent audit is final Phase 7 closeout.

## 20. Known limits and required claims

Passing Phase 7 establishes an event-time-causal implementation against a
finite declared adversarial suite. It does not prove causality, universal
purity, or absence of every hidden trigger. Exact semantic masks and registry
admission are empirical evidence, not mathematical proof.

The accepted calendar's presence does not prove every exchange classification
is correct. It is single-source corroboration; holiday-adjacent flags lack an
independent time signature, vendor absence can coincide with a full closure,
and the two documented regular-session truncations remain data-quality
discrepancies.

Daily maintenance and weekend resets mean volatility state has no cross-day
memory. The h=156 sensitivity reaches at most 70.5% of its steady-state
effective history within a session, so the realized halflife contrast is
compressed. Lower-median MAD with factor 1.4826 has a small finite-window
downward convention effect that is disclosed and not retuned.

State-validity diagnostics are descriptive. Alternative arms measure migration
and sensitivity and validate no preferred model. Liquidity-era correlation is
explicitly deferred for lack of a versioned input. Completion associations may
diagnose selection but never repair it or feed backward into assignments.

Phase 7 establishes no conditional market effect, contrast, prevalence,
statistical significance, confirmation, profitability, execution rule, or
trading strategy. No parameter may be optimized or selected after measured
results. Phase 8 remains unauthorized after Phase 7 closes.
