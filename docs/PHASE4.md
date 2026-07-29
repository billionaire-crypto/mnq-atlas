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
tolerance where non-dyadic inputs make bit equality false.

For `S` contributing groups and `n_s` rows carrying group label `s`,
session-equal weights are:

```text
w_i = 1 / (S * n_s)
```

Each contributing group therefore has mathematical mass `1/S`. Unequal group
sizes can produce binary64 totals differing at rounding scale; unbalanced tests
use relative tolerance no larger than `1e-12` and must still kill the
anchor-equal mutation. Anchor-equal weights assign every row mass `1/n`.

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

`kernel.py` and `result.py` are deliberately deferred. No Phase 4 consumer
justifies them, and the Phase 4 handoff explicitly permits the smaller unit.
When a result surface is introduced later, `n_anchors`, `n_sessions`, and
`weight_ess` must appear together.

## Measured

- The Phase 4 starting replay produced 332 passed and 5 expected failures.
- All four signed-off spine gates passed.
- Completion remained 1,009 sessions and 78,702 gridpoints.
- The S00 artifact remained 7,636 bytes with SHA-256
  `725df33a00e53c6c356c4348df2a02fe9ed309d9d4e4118216894a70ef8a479d`.
- The frozen YAML SHA-256 remained
  `1c95aa595c30c48b853303291a7dbaabceaf5b7331bca565a30863e8dcf138d4`.
- The independent quant audit measured arbitrary-factor boundary changes and
  canonical-order behavior recorded in D13 and the contract above.

## Inferred

- Using the final cumulative value as total mass makes `q=1` select an in-range
  maximum positive-mass support point by construction.
- Canonical tied-weight accumulation makes row-order invariance structural for
  a fixed multiset of binary64 pairs.

## Not verified

- Phase 4 has not computed any market result.
- Bootstrap and fractional resampling behavior remain Phase 5 work.
- No cross-environment byte-identity claim is made. Semantic determinism is the
  cross-environment contract; byte determinism requires an identical environment
  fingerprint.
