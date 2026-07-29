# Phase 4 — market-free weighted-statistics kernel

Phase 4 is limited to the market-free weighted inverse CDF, generic
session-equal and anchor-equal weight construction, weight-concentration
diagnostics, and `weight_ess`. It does not implement bootstrap, conditioners,
excursions, contrasts, nulls, reports, S01A, or market-data access.

## Ratified executable contract

Opus 5 returned `RATIFIED WITH BINDING AMENDMENTS` on 2026-07-29. No frozen-text
discrepancy remained.

### Weighted inverse CDF

- Values and weights are aligned, non-empty, one-dimensional arrays.
- Accepted inputs are real integer or floating NumPy dtypes, or array-likes that
  convert to those dtypes. Bool, complex, object, string, datetime, and timedelta
  inputs fail closed.
- Integer inputs with absolute value greater than `2**53` fail closed because the
  binary64 computation could not return the exact observed input support.
- Every value and weight must be finite, including a value paired with zero
  weight. Invalid rows are never masked or dropped.
- Weights are nonnegative and their accumulated total must be strictly positive.
- Quantile probabilities are finite, real, non-bool scalars in `0 < q <= 1`.
  In particular, `q=0` is rejected: the literal infimum in frozen spec §7.2 is
  negative infinity there, not an observed support value.
- Zero weights contribute no CDF mass. Returned values are observed support
  points carrying positive aggregated mass.
- Tied values form one support point carrying their combined mass.
- The result is the smallest support value whose cumulative mass is at least the
  requested fraction of total mass. It never interpolates.

The binary64 accumulation path is frozen:

1. Convert accepted values and weights to binary64 without pre-normalization,
   rescaling, or rounding beyond that declared conversion.
2. Stably order rows by value using mergesort.
3. Within each tied-value group, order weights ascending and accumulate them in
   that canonical order. This makes the result a function of the multiset of
   `(value, weight)` pairs rather than input row order.
4. Accumulate tied-group masses in ascending support order with
   `np.cumsum(..., dtype=np.float64)`.
5. Define total mass as the final cumulative value `C[-1]`, never as an
   independently computed sum.
6. Evaluate the threshold once as `q * C[-1]`.
7. Select with `C_j >= q * C[-1]`, equivalently
   `np.searchsorted(C, q * C[-1], side="left")`.
8. Equality returns the current support point.
9. No division-form comparison, epsilon, tolerance, interpolation, rounding, or
   nearest-boundary rule is allowed in selection.

Single-q output is a Python `float`. Multi-q output is a float64 NumPy array in
the caller's quantile order; duplicate probabilities are allowed. Calls never
mutate input arrays.

Row-order invariance is exact under canonical tie aggregation. Positive-scale
invariance is exact for power-of-two factors. Arbitrary positive rescaling can
move an exact boundary by binary64 rounding; D13 records the limitation.

### Weight concentration and construction

`weight_ess` is exactly:

```text
(sum(w) ** 2) / sum(w ** 2)
```

It is always named `weight_ess`, never “effective sample size.” It measures
weight concentration only and does not correct overlapping outcomes, serial
dependence, or regime dependence. Floating identities use declared relative
tolerance `1e-12` where non-dyadic inputs make bit equality false.

For `S` contributing groups and `n_s` rows carrying group label `s`,
session-equal weights are:

```text
w_i = 1 / (S * n_s)
```

Each contributing group therefore has mathematical mass `1/S`. Unequal group
sizes can produce binary64 totals differing at rounding scale; unbalanced tests
use relative tolerance no larger than `1e-12` and must still kill the
anchor-equal mutation. Anchor-equal weights assign every row mass `1/n`.
Session-equal group masses sum to `1.0` only within binary64 rounding, so the
maximum group-mass fraction divides by the observed total group mass rather than
assuming that total is exactly one.

Group identifiers are opaque labels. They carry no calendar, exchange, market,
or trading meaning.

## API boundary

The ratified Phase 4 API is centered on `mnq_lab/core/weights.py`:

```text
weighted_quantile(values, weights, q)          -> float
weighted_quantiles(values, weights, quantiles) -> np.ndarray[float64]
weight_ess(weights)                            -> float
session_equal_weights(group_ids)               -> weights plus diagnostics
anchor_equal_weights(n)                        -> weights plus diagnostics
```

Both constructors return `(weights, diagnostics)`. Anchor-equal construction
uses `WeightDiagnostics(row_count, weight_ess)`. Session-equal construction uses
`GroupWeightDiagnostics`, which adds `contributing_group_count`,
`group_total_mass`, and `max_group_mass_fraction`. Group-mass records retain
first-occurrence label order while the row-aligned weights retain original input
order. Accepted group labels are finite real scalars, strings, or bytes; bool,
missing, non-finite, complex, multidimensional, and container-valued labels fail
closed.

`kernel.py` and `result.py` are deliberately deferred. No Phase 4 consumer
justifies them, and the Phase 4 handoff explicitly permits the smaller unit.
When a result surface is introduced later, `n_anchors`, `n_sessions`, and
`weight_ess` must appear together.

## Measured

- The Phase 4 starting replay produced 332 passed and 5 expected failures.
- The Stage F replay produced 443 passed and the same 5 expected failures.
- The market-free focused suite produced 122 passed.
- All four signed-off spine gates passed at closeout.
- The completion CLI remained 1,009 sessions and 78,702 gridpoints.
- The S00 artifact remained 7,636 bytes with SHA-256
  `725df33a00e53c6c356c4348df2a02fe9ed309d9d4e4118216894a70ef8a479d`.
  Two consecutive Stage F CLI generations, and the bytes present before them,
  all had that exact size and hash.
- The frozen-spec SHA-256 remained
  `70dae16c8b12fe26d38a7bfdabf0202066fe7149f790d0d2942279d9c3b8ff50`.
- The frozen YAML SHA-256 remained
  `1c95aa595c30c48b853303291a7dbaabceaf5b7331bca565a30863e8dcf138d4`.
- Ledger/YAML validation passed, and the no-default threshold loader returned
  `{15: 0.99, 30: 0.99, 60: 0.98}`.
- The independent quant audit measured arbitrary-factor boundary changes and
  canonical-order behavior recorded in D13 and the contract above.
- Independent mutation audits ran in disposable clones. Stage C and Stage D
  closed all five reported enforcement defects; the required inverse-CDF,
  validation, scope, `weight_ess`, construction, and diagnostic mutations were
  killed by named tests or fail-closed guards.
- Stage D's synthetic one-versus-seven fixture gives each group mass `0.5`;
  anchor-equal weighting instead gives those groups mass `0.125` and `0.875`.
  At `q=0.25`, the two weightings return different observed support values.
- A separate 2/3/5-row grouped fixture returns a maximum group-mass fraction of
  approximately `1/3`, distinct from its maximum individual row weight `1/6`.
- The final 27/19/28/13-row diagnostic fixture measured raw maximum group mass
  `0.24999999999999997`, observed total mass `0.9999999999999998`, and normalized
  maximum mass fraction `0.25000000000000006`.
- The final core package contains only `__init__.py`, `causality.py`, `units.py`,
  and `weights.py`. Scope tests found no market-aware or ledger import and no
  name or access path for the locked tier.

## Inferred

- Using the final cumulative value as total mass makes `q=1` select an in-range
  maximum positive-mass support point by construction.
- Canonical tied-weight accumulation makes row-order invariance structural for
  a fixed multiset of binary64 pairs.
- Creating unused `kernel.py` or `result.py` abstractions would add no verified
  Phase 4 consumer contract, so their deferral is the smaller ratified boundary.

## Not verified

- No Phase 4 primitive has been applied to market observations; no market
  `weight_ess` or conditional result has been computed.
- Bootstrap and fractional resampling behavior remain Phase 5 work. In
  particular, the current grouped-label factorization and per-group boolean
  scans have not been performance-benchmarked across bootstrap replicates.
- No cross-environment byte-identity claim is made. Semantic determinism is the
  cross-environment contract; byte determinism requires an identical environment
  fingerprint.

## Audit status

The mathematical preflight, both implementation units, and final Phase 4
closeout independently returned `CLOSED`. A subsequent Phases 1–4 red-team audit
also returned `CLOSED` with one operational finding: a direct build with the
post-freeze YAML changes sealed provenance while preserving scientific content.
`docs/SEALED_STORE_REBUILD.md` records the remediation, preservation requirement,
scientific-reconstruction procedure, and the dirty-fingerprint limit on exact
artifact regeneration. Phase 5 is not authorized by this document.
