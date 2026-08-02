# Unit O Preregistration - Causal Excursion Outcome Layer

**Program:** `mnq-atlas-001`  
**Specification:** `REV6_FROZEN_SPEC.md`, revision 6  
**Contract date:** 2026-08-01  
**Base:** `289977aaaf836c76788035670d099740dfaa05f7`  
**Branch:** `phase-7b-outcome-layer`  
**Status:** proposed frozen contract; no Unit O production code or MNQ outcome value is authorized before this document and `docs/PHASE8_PREREGISTRATION.md` are both independently ratified

## 1. Governance and boundary

This document preregisters Unit O, the calendar-independent outcome layer that
turns the already-audited exploration spine into future-path excursion rows.
It transcribes the user-ratified U16 outcome construction and the sequencing in
U17. It does not change `REV6_FROZEN_SPEC.md`,
`analysis_constants_v1.yaml`, any Phase 7 artifact, or any accepted-calendar
artifact.

Unit O owns only:

- the exact future clock-window labels for horizons 15, 30, and 60 minutes;
- anchor-close and future-high/low excursion arithmetic in integer ticks;
- the two frozen path estimands `fully_labeled_1m_grid` and
  `observed_bar_path`;
- per-anchor outcome validity and missingness statuses;
- horizon-specific and per-estimand common-support flags;
- semantic dependency masks and locality witnesses for the outcome values; and
- deterministic outcome-table and manifest schemas.

Unit O does not read conditioner assignments, volatility scales, the accepted
calendar, studies, contrasts, positivity results, prevalence, nulls, vintages,
reports, S01A artifacts, or the locked confirmation tier. It computes no
weighted quantile, contrast, confidence interval, p-value, ranking, parameter
selection, profitability statistic, or trading recommendation. Existing
`mnq_lab.outcomes.completion` is an input-side support engine, not a license to
change its audited definitions.

No market store is opened and no outcome value is computed while drafting this
contract. U17 requires this document and the Phase 8 contract to be committed
and byte-pinned in two separate commits, followed by one combined independent
contract audit. Production for either unit remains prohibited until both
contracts return `RATIFIED`.

## 2. Frozen inputs and constants

The implementation consumes only the exploration five-minute spine fields
needed for the declared calculation:

```text
session_id, ts_event_ns, symbol_code,
open_ticks, high_ticks, low_ticks, close_ticks,
observed_1m_components, expected_1m_components
```

The store manifest and the existing spine gates remain authoritative for row
count, bar duration, sorted unique timestamps, active-contract decoding, OHLC
validity, and exploration-tier identity. Unit O must call the existing
exploration-safety and five-minute-duration guards at its public boundary; it
may not reproduce them with a weaker local check.

Frozen constants loaded fail-closed from `analysis_constants_v1.yaml` are:

```text
storage_tz             UTC
session_tz             America/Chicago
bar_label              open
rth_start_ct           08:30
rth_end_ct             15:00
tick_size              0.25
horizons_minutes       [15, 30, 60]
path estimand primary  fully_labeled_1m_grid
```

The second estimand is the frozen spec name `observed_bar_path`. The literal
five-minute duration and the required five one-minute components are inherited
from the audited spine/completion layer. Missing constants, extra horizon
values, reordered horizons, non-integer horizons, or a horizon not divisible by
five halt the build.

Prices are already integer ticks. Unit O never converts them through floating
index points and never divides by a conditioner scale.

## 3. Event-time outcome window

`ts_event_ns` labels the **open** of a five-minute bar. For an anchor observed
at `tau`, the anchor bar is the bar labelled `tau - 5 minutes`; its close is the
reference price. Its own high and low are already known at `tau` and are never
part of the future excursion.

For a horizon `delta`, the required future bar-open labels are exactly:

```python
future_labels(tau, delta) = [
    tau + j * five_minutes
    for j in range(delta // five_minutes)
]
```

Thus the window is half-open `[tau, tau + delta)`. The first included bar is
labelled exactly `tau`; the bar labelled `tau + delta` is excluded. The anchor
bar labelled `tau - 5 minutes` supplies only `anchor_close_ticks`.

Every expected future label must resolve to exactly one row with the same
`session_id` and decoded `symbol_code` as the anchor. A positional slice,
`shift`, row adjacency, or tolerance match may implement no part of this rule.
The implementation constructs the expected UTC labels and checks equality.
The RTH structural check is the existing observation-time rule
`tau + delta <= 15:00 CT`; a window outside it is not an outcome path. Scheduled
short sessions remain visible through absent-path statuses and are not silently
dropped or extended.

Required discriminating examples include:

- the 08:30-labelled bar closes at `tau=08:35`; its 15-minute path is the
  08:35, 08:40, and 08:45 labelled bars;
- the `tau=08:30` anchor uses the 08:25-labelled bar's close and begins its path
  at the 08:30-labelled bar;
- `tau=14:00` has a structurally valid 60-minute window ending at 15:00; and
- `tau=14:05` does not have a structurally valid 60-minute window.

## 4. Excursion outcomes

For a valid future path, let `C_tau` be the anchor close in ticks, `L_min` the
minimum future low over the required bars, and `H_max` the maximum future high.
Unit O emits four int32 outcomes:

```text
downward_excursion_ticks          = max(0, C_tau - L_min)
upward_excursion_ticks            = max(0, H_max - C_tau)
signed_downward_extreme_ticks     = C_tau - L_min
signed_upward_extreme_ticks       = H_max - C_tau
```

The nonnegative pair is the named primary outcome pair. It has coherent
distance semantics: if the future path never crosses the anchor, the excursion
in that direction is zero. The signed companions preserve whether the entire
future path stayed on the opposite side of the anchor. They are descriptive
companions, not substitutes for the named nonnegative outcomes and not an
additional Phase 8 surface family.

All int32 prices are cast to int64 **before** subtraction, extrema and flooring.
Each final value is checked against the int32 range before conversion. Overflow,
an invalid OHLC row, a non-integer price, an empty path presented as valid, or a
negative value in either floored outcome is corruption and halts the build; it
does not receive a missingness status.

The arithmetic is deliberately independent of the tick size in points. The
output unit is raw MNQ ticks. No price normalization, volatility division,
currency conversion, rounding, or clipping other than the two explicit zero
floors is allowed.

## 5. Path estimands and completion

Both estimands require the complete expected five-minute timestamp grid:

```text
observed_bar_path:
    every required five-minute label exists exactly once in the same session
    and decoded symbol; one-minute component completeness is not required.

fully_labeled_1m_grid:
    every observed_bar_path requirement, and every required future bar has
    observed_1m_components == expected_1m_components == 5.
```

A wholly missing five-minute bar invalidates **both** estimands. This is binding
D12: an excursion over an absent interval would invent a path. A present bar
built from fewer than five one-minute rows invalidates only
`fully_labeled_1m_grid`. The anchor bar and its close must exist, but the anchor
bar's component completeness is irrelevant because it is not part of the
future outcome path.

For each estimand, `common_support` is computed independently as validity at the
maximum declared horizon, 60 minutes. A 15- or 30-minute result on common
support uses that estimand's own 60-minute-valid anchors. It is not the
intersection of the two estimands, and one estimand's component rule may not
remove rows from the other.

The layer emits every declared anchor x horizon x estimand row. It never filters
the table down to valid paths. Completion, year, phase, calendar flags and the
two known truncated regular sessions are downstream diagnostics only; none may
alter an outcome value or relabel a calendar class.

## 6. Closed status taxonomy and precedence

Missingness gets a status; corruption halts. The first matching outcome status
is emitted, and all mechanically true diagnostic flags are retained in separate
boolean fields:

```text
1 anchor_bar_missing
2 window_outside_rth
3 path_timestamp_missing
4 path_session_mismatch
5 path_symbol_mismatch
6 insufficient_components       (fully_labeled_1m_grid only)
7 ok
```

Definitions are exact:

- `anchor_bar_missing`: no unique row exists at `tau-5m`, so no reference close
  exists;
- `window_outside_rth`: the half-open clock window fails the frozen RTH bound;
- `path_timestamp_missing`: at least one expected future label is absent;
- `path_session_mismatch`: a resolved future label is not in the anchor session;
- `path_symbol_mismatch`: a resolved future label changes decoded symbol;
- `insufficient_components`: the exact path exists but at least one required
  future bar is not a full five-component label grid; and
- `ok`: every requirement of the named estimand holds.

Duplicate timestamps, impossible status combinations, an unknown vocabulary
value, `ok` with an invalid numeric outcome, or a non-`ok` row carrying a valid
numeric outcome halt. The observed-path row can be `ok` when the corresponding
fully-labelled row is `insufficient_components`; the reverse combination is
impossible and halts.

## 7. Semantic dependencies and isolation

For a row `(session, tau, delta, estimand)`, the exact bar dependency is the
anchor bar at `tau-5m` plus every expected future bar label in
`[tau, tau+delta)`. No earlier bar, no bar at or after `tau+delta`, and no row in
another session is admitted. Component-count fields are dependencies only for
`fully_labeled_1m_grid`; changing them must leave `observed_bar_path` outcome
values and validity unchanged when all five-minute bars remain present.

Admission compares a production-declared mask with an independent semantic
mask using `numpy.array_equal`, never containment. Expected masks and witnesses
are constructed from this contract in tests and import no production outcome
module.

The outcome layer has no conditioner argument, assignment argument, scale
argument, category argument, threshold argument, or calendar path argument. A
sentinel test monkeypatches the real conditioner and accepted-calendar loaders
to raise, executes every public Unit O entry point on synthetic bars, and proves
neither sentinel is reached. An in-memory mutant of a real outcome module adds
conditioner access and must reach the sentinel. This guard is non-vacuous: it
asserts discovery of the real excursion module and execution of valid and
invalid paths.

The existing completion layer may be called or its exact boolean fields may be
consumed because it is itself outcome-side and conditioner-free. Unit O must
still compute extrema only from the exact resolved future labels; a completion
boolean is authorization to compute, not a substitute for the bars.

## 8. Output schema

The canonical tidy outcome table has one row per fixed estimand order
`(fully_labeled_1m_grid, observed_bar_path)`, session, `tau`, and horizon order
`(15, 30, 60)`:

```text
estimand, session_id, ts_event_ns, tau_ns, observation_time_ct,
session_phase, horizon_minutes, anchor_symbol_code,
anchor_close_ticks, anchor_close_valid,
n_required_bars, n_present_bars, n_fully_labeled_bars,
window_fits_rth, common_support,
outcome_status, path_timestamp_missing, path_session_mismatch,
path_symbol_mismatch, insufficient_components,
downward_excursion_ticks, upward_excursion_ticks,
signed_downward_extreme_ticks, signed_upward_extreme_ticks,
outcome_valid
```

Integer missing values use separate validity booleans, never a magic tick
sentinel. Timestamps are int64 UTC nanoseconds; session IDs are int32 YYYYMMDD;
horizons and counts are integers; flags are boolean; statuses and estimands use
closed ASCII vocabularies. Valid tick outcomes are int32. Column order and row
order are immutable and never determined by a measured value.

The artifact is an immutable `.npy` column store with a canonical sorted-key,
indent-2, ASCII-safe UTF-8 JSON manifest and one terminal newline. The manifest
records hashes of the frozen spec, YAML, both preregistrations, input store
manifest and code; base and build commits; dirty flag; environment fingerprint;
schema version; row counts; status counts; per-column dtype, byte count and
SHA-256; exact horizons and estimands; and the semantic comparison policy.

No market-derived Unit O artifact may be committed while the contracts are
being ratified. Later production artifacts remain exploration-only and may not
contain a confirmation-tier path or fingerprint.

## 9. Prefix invariance and determinism

Building through session `T` and rebuilding through `T+k` must leave every
pre-`T` Unit O value, status, support flag and dependency mask unchanged. Exact
integer, boolean and status fields are bit-identical. Artifact bytes must be
identical when the complete environment fingerprint matches; cross-environment
reproduction requires semantic identity, not an unsupported floating-byte
claim.

Although Unit O arithmetic is integer-only, the same deterministic artifact
rules apply. Same-fingerprint reruns receive no timestamp, random identifier or
unordered mapping. A prefix test has nonempty-prefix and nonempty-extension
guards, and a test-only backward-carry mutant must fail.

## 10. Required tests and mutation floor

Implementation is not complete until each assertion has a named failing input
or mutation and each fixture proves the asserted region is nonempty. At minimum:

1. include the anchor bar's high/low in the future extrema;
2. exclude the future bar labelled exactly `tau`;
3. include the bar labelled exactly `tau+delta`;
4. use the anchor open instead of its close;
5. use positional adjacency instead of exact UTC labels;
6. accept a wholly missing five-minute bar under `observed_bar_path`;
7. reject a partial-component path under both estimands;
8. require component completeness on the anchor bar;
9. allow a path to cross a session or decoded-symbol boundary;
10. subtract int32 values before widening to int64;
11. omit either zero floor or apply it to a signed companion;
12. intersect common support across the two estimands;
13. omit an invalid anchor row instead of emitting its status;
14. read conditioner assignments or the accepted calendar;
15. widen the semantic mask by one bar before the anchor;
16. widen it to the bar at `tau+delta`;
17. narrow it by removing the anchor close or any required future bar;
18. carry an outcome backward under corpus extension; and
19. access, name, accept or mmap the locked confirmation tier.

The load-bearing test files claim the existing frozen names
`tests/test_window_boundaries.py` and `tests/test_estimand_definition.py` and add
focused excursion arithmetic, locality, isolation, prefix-invariance,
integer-overflow and artifact tests. The 08:35 worked example is asserted
exactly. Hand-computed tick fixtures distinguish floored and signed outcomes,
including paths wholly above and wholly below the anchor.

## 11. Implementation gate and order

After **both** preregistrations are independently ratified, Unit O implementation
may proceed in this order:

1. closed statuses, exact timestamp resolver and independent semantic-mask
   fixtures;
2. int64-safe excursion arithmetic and both estimands;
3. conditioner/calendar isolation and prefix invariance;
4. deterministic table and manifest writers; and
5. a closeout document, protected hashes and the authorized safe suite.

No real MNQ outcome computation occurs until synthetic tests, all mutations,
dependency equality, isolation and exploration-tier guards pass. If a gate
fires, stop at the first mismatch and classify it under frozen section 16.6; do
not relax support, infer a missing bar, interpolate a price, or code around it.
Unit O closeout must precede any Phase 8 computation that consumes outcome
values.

The only authorized repository test command is:

```text
python -m pytest tests --ignore=tests/test_bootstrap_acceptance.py -q
```

The acceptance module must never be imported, collected or executed, and the
bare full suite is forbidden.

## 12. Known limits and required claims

These outcomes describe extrema among recorded OHLC bars on complete expected
clock-time paths. Five one-minute labels do not prove every trade was captured,
and a five-minute OHLC bar does not reveal intrabar ordering. The floored
excursions are distances, not executable stops or fills. The signed companions
are extrema relative to the anchor, not returns.

Rejecting incomplete paths creates the frozen section 6 selection surface. Both
estimands, completion rates by year and phase, and common support remain visible;
none repairs missingness. Results apply to eligible recorded paths, not all MNQ
market time. The two unresolved truncated regular sessions remain data-quality
discrepancies and are never relabelled by Unit O.

Passing Unit O proves conformance to finite fixtures and declared dependency
masks, not market-data completeness, causality, profitability, future regime
stability, or an execution rule. Unit O creates a measurement input only. Phase
8 production remains unauthorized until the combined contract audit ratifies
both byte-pinned documents.
