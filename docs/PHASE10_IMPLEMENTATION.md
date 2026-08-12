# Phase 10 Implementation and Cost-Scaling Report

Date: 2026-08-11

Producer: Codex implementation session

This is an implementation and no-evidence cost report. It is not an audit,
acceptance record, ledger entry, checkpoint, receipt, protected-path snapshot, or
ratification.

```text
formal_test              = vol_given_phase
permutation_population   = ordinary_full_rth_nonadjacent_resolved
permutation_sessions     = 900
liquidity_era             = undifferentiated_no_versioned_boundaries
liquidity_era_status      = inactive_missing_versioned_input
effective_null_strata     = calendar_quarter_only
rng_seed                  = 20260728
rng_root_entropy          = [20260728]
```

## 1. Implemented boundary

`mnq_lab.phase10` composes the audited Phase 8 and Phase 9 adapters, weight and
quantile machinery, lattice declarations, estimand declarations, diagnostics, and
artifact conventions. The formal adapter fails closed on manifest/hash/key/grid or
population disagreement and realizes exactly 900 ordinary full-RTH, non-adjacent,
resolved sessions with 78 canonical observation anchors each. Bar-open timestamps
are converted by the existing `anchor_observation_keys` implementation; the stored
observation time is exactly the bar open plus five minutes.

Whole donor state and validity trajectories move without replacement inside calendar
quarter, with no self-assignment. Recipient outcome/completeness masks stay fixed.
One mapping is recorded for every output in a replication. Strata below 20 remain
explicitly unusable. The generator root is
`numpy.random.SeedSequence((20260728,))`; one child is spawned per replication and
wrapped by `numpy.random.Generator(numpy.random.PCG64(child))`.

The engine evaluates the two frozen contrast-weighting interpretations as separate
5 by 3 planes, computes a shared null-ensemble sample standard deviation per valid
cell, applies that same denominator to observed and null contrasts, and detects
separate signed rook-connected regions. A missing, thin, non-ok, or unusably scaled
cell has false validity and a non-finite standardized value, so it breaks adjacency.
Only the frozen B = 4,999 formal entry point can call the exact plus-one, upper-tail,
tie-counting p-value. The B = 19, 49, and 199 benchmark entry point cannot return or
print a p-value.

`phase_given_vol` and `interaction` are descriptive-only deferred interfaces. They
have no executable null and no p-value.

## 2. Production-code mutation checks

Each mutant below was planted in production code, rejected by the named positive
gate assertion, and immediately reverted. The restored Tests 10-12 then passed
together. No mutant was committed.

| Planted defect | Assertion that rejected it |
|---|---|
| donor draw with replacement | `donor trajectories are not assigned without replacement` |
| recipient allowed to receive itself | `a recipient received its own trajectory` |
| two calendar-quarter strata pooled | `a donor trajectory crosses its stratum` |
| donor completeness mask carried to recipient | `a donor completeness mask replaced a recipient mask` |
| independent mapping used for a second output | `an output used an independent session mapping` |
| omitted plus-one numerator and denominator | exact fixed-list equality, observed 0.5 instead of the required 0.6 |
| strict `>` tie rule | exact fixed-list equality, observed 0.4 instead of the required 0.6 |
| magnitude taken before region detection | signed-region assertion found one merged positive region and no negative region |
| diagonal/8-neighbor adjacency | rook assertion found one two-cell region instead of two singleton regions |
| missing standardized cell filled with zero | non-finite-invalid assertion observed zero instead of a non-finite sentinel |

## 3. Same-assertion negative-case answers

- **Test 9:** Yes. Both fixed-summary negative cases call the same `_assert_gate`
  used by the positive structural case; an out-of-band theoretical count and a flat
  power/localization sequence each fail `decision.accepted`. These hand-written
  values spend no one-shot entropy and create no calibration evidence.
- **Test 10:** Yes. Positive and negative cases call
  `assert_joint_reassignment`; mapping-specific invariants are also enforced by its
  nested `assert_mapping_contract` call. Production mutants for replacement, self,
  pooling, masks, and jointness all failed those same assertions.
- **Test 11:** Yes. Positive and negative cases call the same `_assert_exact` helper
  on one fixed list. Both production formula mutants failed the exact equality.
- **Test 12:** Yes. Positive and magnitude-mutant cases call the same
  `_assert_signed_regions` helper; rook and missing-value cases use their positive
  topology/non-finite assertions directly, and the corresponding production mutants
  failed those assertions.

The accelerated point/status path is additionally compared directly with the Phase 8
production composition for both weighting planes and for ok, missing, thin, and
incomplete support. The negative fixture changes a point and fails the same complete
equivalence assertion used by the positive fixture.

## 4. Explicit non-actions

No calibration or randomized-control run was performed. No corpus Type-I or power
evidence, corpus or randomized-control rejection count/frequency, corpus p-value,
acceptance decision, or smallest-across-surfaces value was produced. No synthetic
session generator or max-t band was implemented.

There was no selection, ranking, optimization, best-parameter search, expectancy,
Sharpe ratio, P&L, currency figure, alpha tooling, or live-strategy change. The locked
confirmation tier was not accessed. Phase 8, Phase 9, the frozen constants/spec,
`docs/DISCREPANCIES.md`, data, ledger files, receipt-pinned paths, and the protected
stash were not modified. Phase 9 production was not run; no canonical spine build,
dataset, generated array, pin, receipt, checkpoint identity, protected-path snapshot,
ledger entry, audit, self-ratification, Phase 11 work, or Phase 12 work was created.

## 5. Cost-only scaling benchmark

The hidden benchmark read the 900-session, 70,200-row formal corpus and exercised
both 15-cell weighting planes. It emitted no surface values, statistics, p-values,
rejection outcomes, or acceptance decisions. The external temporary directory was
deleted in a `finally` block; the final cleanup record was
`temporary_directory_deleted = true`.

| B | Wall seconds | Peak RSS bytes | Peak traced bytes | Result-array bytes | Temporary bytes |
|---:|---:|---:|---:|---:|---:|
| 19 | 387.989900 | 816,873,472 | 220,742,717 | 30,932 | 85 |
| 49 | 970.471907 | 817,598,464 | 221,629,970 | 79,772 | 170 |
| 199 | 3,891.369812 | 826,560,512 | 227,593,082 | 323,972 | 256 |

Ordinary least squares on wall seconds against B gives
`seconds = 17.446379 + 19.466264 * B`. At B = 4,999 this projects
97,329 seconds, or 27.04 hours. As an empirical uncertainty range, extrapolating
each of the three pairwise measured slopes gives 97,080 to 97,360 seconds
(26.97 to 27.04 hours). This narrow range describes scaling fit only; it does not
cover future machine contention.

The corresponding linear RSS projection is 1,093,977,583 bytes. Pairwise-slope
projections range from 937,222,144 to 1,113,346,048 bytes. Traced-memory projection
is 412,871,689 bytes, with a pairwise range of 368,026,715 to 418,412,666 bytes.
Result arrays grow exactly 1,628 bytes per replication and project to 8,138,372
bytes. Initial free physical memory was 2,422,513,664 bytes. The projected peak fits
this machine at the measured state and remains far below the 4,000,000,000-byte stop
boundary, but the projected 27-hour wall time makes shared-runner contention an
important operational constraint.

## 6. Authorized suite

The exact authorized command was run after all implementation and test changes:

```text
python -m pytest tests --ignore=tests/test_bootstrap_acceptance.py -q
```

Its terminal summary was:

```text
1536 passed, 2 skipped, 1 xfailed in 384.31s (0:06:24)
```

Relative to the verified baseline, passes increased by 30. Both Windows-gated skips
remain, and `consumed_vintage_artifacts` remains the sole Phase 11 xfail. The
one-shot bootstrap-acceptance file was never collected or run.

## 7. Cost correction dated 2026-08-12

This is an append-only correction. The original §5 timing table and projection are
retained as historical measurements but are superseded as estimates of normal engine
runtime. The original benchmark started `tracemalloc` before its wall clock and stopped
it only after wall capture. The reported 97,329 seconds / 27.04 hours at B = 4,999
therefore measured the engine together with allocation tracing, not production wall
time. The producer independently isolated a 6.821x inflation at B = 19; the auditor
independently isolated 6.616x at B = 3.

Before the type-guard optimization, the corrected untraced basis was
`wall(B) = 3.4362593 + 2.868437975 * B` seconds. It projected B = 4,999 at
14,342.76 seconds, or 3.98 hours. This pre-optimization basis is itself superseded by
the post-fast-path measurement below.

The benchmark now executes two explicit passes. The first measures wall time and RSS
with `tracemalloc` disabled. The second measures traced allocations separately. Only
the first pass enters runtime fitting. Both passes exercise identical surface wiring,
discard their surface outputs, emit cost fields only, and remain subject to the 4 GB
RSS stop. The external temporary directory was deleted in the benchmark's `finally`
block, and the cleanup record was `temporary_directory_deleted = true`.

Post-fast-path measurements on the 900-session, 70,200-row corpus were:

| B | Untraced wall seconds | Timed-pass peak RSS bytes | Allocation-pass seconds | Allocation-pass peak RSS bytes | Peak traced bytes | Result-array bytes | Temporary bytes |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 3 | 8.094956 | 205,377,536 | 58.827710 | 211,173,376 | 124,365,341 | 4,884 | 84 |
| 19 | 40.763704 | 209,125,376 | 294.017601 | 215,769,088 | 124,941,614 | 30,932 | 169 |
| 49 | 101.903838 | 212,774,912 | 735.956578 | 218,394,624 | 126,135,378 | 79,772 | 254 |

Ordinary least squares on the three untraced wall measurements gives
`wall(B) = 1.9941832 + 2.0391542 * B` seconds. At B = 4,999 this projects
10,195.73 seconds, or 2.832 hours, for one full run. The 1,200-run calibration design
therefore projects 3,398.58 core-hours. Pairwise fits project one B = 4,999 run from
2.831 to 2.836 hours and the complete design from 3,396.68 to 3,402.97 core-hours.
This range measures small-B scaling-fit variation only; it does not include machine
contention, parallel-efficiency loss, interruption, or rental-host differences.

The post-fast-path slope is 28.91% below the corrected pre-optimization slope. No
surface value, statistic, p-value, rejection outcome, Type-I or power result, or
acceptance decision was printed or retained by this benchmark.
