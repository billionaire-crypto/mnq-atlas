# Phase 3 S00 preregistration

This document freezes the S00 artifact schema and threshold mathematics before
the S00 implementation is written. It does not contain measured S00 values and
does not authorize an edit to `analysis_constants_v1.yaml`.

## Quant preflight

Opus 5 returned `VERDICT: RATIFIED` on 2026-07-28 for the following reading of
the frozen specification:

```text
c(p,h) = N_complete(p,h) / N_eligible(p,h)

s00_p05(h)
    = inf{x : (1/5) sum_p 1[c(p,h) <= x] >= 0.05}
    = min_p c(p,h)

raw_threshold(h)  = floor(100 * s00_p05(h)) / 100
min_completion(h) = max(0.90, raw_threshold(h))
```

The five declared phase cells receive equal weight. Ties at the minimum do not
change the result. Default linear interpolation is inadmissible. Candidate
arithmetic uses the exact integer count fraction; the floored percentage is
computed as `(100 * N_complete) // N_eligible`, never from a rounded display
value.

The ratification is about the mathematical convention only. Opus did not
inspect an S00 value.

## Undefined-cell ruling

The handoff requires missing, duplicate, extra, non-finite, and wrong-estimand
cells to fail closed. It also requires a mutation that silently skips an empty
or NaN cell to be killed. Therefore:

- every one of the 15 declared phase-by-horizon cells is emitted;
- an empty cell retains its honest status in completion accounting;
- an empty cell makes `c(p,h)` undefined and blocks S00 candidate derivation;
- no empty or non-finite cell is excluded from `C_h`;
- no threshold freeze may proceed while any declared cell is undefined.

This resolves the zero-denominator boundary raised in the Opus ratification
without adding an analyst-selected population rule.

## Canonical artifact

The generated artifact is strict UTF-8 JSON with:

- keys sorted lexicographically;
- compact separators;
- one trailing line feed;
- no non-standard `NaN` or infinity tokens;
- rows in YAML phase order, then YAML horizon order;
- candidates in YAML horizon order.

`weight_ess` is encoded as JSON `null`, accompanied by
`weight_ess_status: "not_computed_until_phase_4"`. It is not zero and is not a
Phase 4 calculation.

The artifact contains:

1. schema, program, spec, and study identifiers;
2. declared and observed source-population bounds;
3. exploration-store build ID, pipeline version, bar duration, row count, and
   manifest SHA-256;
4. the frozen path estimand, equal-phase inverse-CDF convention, and threshold
   rule;
5. the observed session-flag census, with calendar status remaining unknown;
6. the complete 15-row threshold-input table, including observed-path
   diagnostic counts and rates;
7. horizon-specific p05 fractions and proposed thresholds.

The artifact deliberately excludes:

- the full YAML file hash, because adding the artifact's own derived thresholds
  later must not alter S00;
- a deriving Git commit, because that provenance belongs in the ledger and
  documentation rather than in replay-dependent bytes;
- Phase 4 weights, bootstrap output, conditioners, excursion estimates, P&L, or
  rankings.

The default replay path is:

```text
data/exploration/s00/s00_threshold_input_v1.json
```

Generated data remain uncommitted. The SHA-256 covers the exact artifact bytes.

