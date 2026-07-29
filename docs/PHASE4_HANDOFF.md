# Phase 4 handoff — kernel core, weighted inverse CDF, and `weight_ess`

This is the continuity document for the implementation session after Phase 3.
Phases 1–3 are complete and independently signed off. Phase 4 builds only the
market-free statistical kernel needed by later atlas phases:

```text
inverse-CDF weighted statistics
session-equal and anchor-weight primitives
weight_ess and weight-concentration diagnostics
the smallest generic kernel/result interfaces justified by the frozen spec
```

Phase 4 is not a study run. It must not compute MNQ conditional excursions,
conditioners, contrasts, bootstrap intervals, null results, or S01A output.

## 1. Roles and working agreement

- **Codex:** developer. Implements code, tests, documentation, and fixes.
- **Opus 5:** quant and routine independent auditor. It must ratify unresolved
  mathematical boundary conventions before implementation and audit each
  completed coding unit.
- **Fable 5:** escalation auditor only for the hardest unresolved defect or a
  high-risk final dispute.
- After each completed coding unit, Codex supplies a compact ready-to-paste
  Opus audit prompt.

Developer-authored code, tests, fixtures, and prose are claims, not independent
audit evidence. Mutations for audits run only in external disposable clones.

## 2. Immutable starting state

Repository:

```text
repo                    C:\mnq-atlas
current branch          phase-3-s00
Phase 3 signed off      65e9901a47902a67469dffdf99624e88623a833d
next branch             phase-4-kernel
```

The Phase 4 branch must be created from the commit containing this handoff,
whose parent is the signed-off Phase 3 commit above. Do not branch from a remote
tracking branch.

Starting replay:

```powershell
git status --short --branch
git log -8 --oneline
python -m pytest tests -q
python -m mnq_lab.spine.gates --store data
python -m mnq_lab.outcomes.completion --store data
python -m mnq_lab.outcomes.s00 --store data
```

Expected:

```text
tests                   332 passed, 5 xfailed
Phase 1 gates           4/4 pass
exploration sessions    1,009
completion gridpoints   78,702
S00 artifact bytes      7,636
S00 artifact sha256     725df33a00e53c6c356c4348df2a02fe9ed309d9d4e4118216894a70ef8a479d
```

Frozen and ledgered hashes:

```text
REV6_FROZEN_SPEC.md
70dae16c8b12fe26d38a7bfdabf0202066fe7149f790d0d2942279d9c3b8ff50

analysis_constants_v1.yaml — current Phase 3 freeze
1c95aa595c30c48b853303291a7dbaabceaf5b7331bca565a30863e8dcf138d4

analysis_constants_v1.yaml — store build-time input / ledger old hash
3f5c4bd5258eeb306d76d45aa4ad568a2483f007415e7d11df89ebbc8c4b182a
```

The two YAML hashes are intentionally different. The exploration manifest
preserves the old hash used to build the store. The current YAML contains the
audited Phase 3 thresholds. `tests/test_manifest_hashes.py` and
`tests/test_threshold_ledger.py` verify the provenance chain. Do not rewrite
the store manifest to the current hash.

Current thresholds:

```yaml
min_completion_h15: 0.99
min_completion_h30: 0.99
min_completion_h60: 0.98
```

They are immutable for all affected later results. Do not edit them.

Exploration provenance:

```text
path              data/exploration/bars_5m
pipeline_version  spine-1.0.0
build_id          0ad7843647f17258
manifest_sha256   1cf6ec5ce7822ce1333984909b52d5c937e4ccc06e280030bcacda22620ffd73
bar_seconds       300
rows              274,847
sessions          1,009
first session     20190506
last session      20230329
```

Phase 4 core code has no reason to open any market-data store. Never inspect,
import, or mmap `data/locked_confirmation/`. Existing signed-off spine gates
and legacy test fixtures retain their already-audited access boundary; do not
broaden it.

## 3. Read in this order

1. This handoff.
2. `REV6_FROZEN_SPEC.md` §14 (STRUCK).
3. Frozen spec §7.1, then §7.2.
4. Frozen spec §12 fields `estimands` and `reporting`.
5. Frozen spec §13 test 7.
6. Frozen spec §15 row 4.
7. Frozen spec §16.3 through §16.7.
8. `analysis_constants_v1.yaml`.
9. `docs/PHASE3.md` and `docs/PHASE3_PREREGISTRATION.md`.
10. `docs/DISCREPANCIES.md`, especially D8, D11, and D12.
11. `mnq_lab/constants.py`.
12. `mnq_lab/core/causality.py`, `mnq_lab/core/units.py`, and
    `mnq_lab/core/__init__.py`.
13. `mnq_lab/outcomes/s00.py` only to understand the frozen artifact boundary;
    do not move S00 threshold mathematics into the Phase 4 kernel.
14. `mnq_lab/ledger/freeze.py`, `tests/test_s00.py`,
    `tests/test_threshold_ledger.py`, `tests/test_no_selection.py`, and
    `tests/test_spec_consistency.py`.
15. `CLAUDE.md`.

Older revision notes and chat summaries are not authoritative over the frozen
spec, binding rulings, ledger, and recorded audit closures.

## 4. What is signed off

### Phase 1

- Deterministic `.npy` `BarStore`.
- Causal active-contract chain.
- Exploration/locked sealing.
- One-minute component coverage.
- Four fail-closed gates.

### Phase 2

- Observation time `tau = bar-open label + 5 minutes`.
- RTH anchor eligibility and phase assignment from observation time.
- Full 78-point session grid.
- Conservative D12 path completeness.
- Completion accounting and honest observed session flags.

### Phase 3

- Canonical 15-cell S00 completion artifact.
- Equal-phase inverse-CDF p05 convention.
- Independently reproduced candidates:
  - h15 `0.99`
  - h30 `0.99`
  - h60 `0.98`
- Ledger-before-YAML freeze.
- No-default threshold loader.
- S00 artifact unchanged by its derived YAML values.
- Final Opus verdict `CLOSED`.

One non-blocking Phase 3 audit note remains: the name
`test_ledger_artifact_provenance_matches_generated_bytes` overstates the direct
mechanism because the test hashes the existing generated artifact rather than
regenerating it. The protection works after regeneration. Do not silently
represent that test as stronger than it is.

## 5. Exact Phase 4 scope

Frozen spec §15 row 4:

```text
Kernel core, inverse-CDF weighted statistics, weight_ess
Gate: §13 test 7
```

The minimum Phase 4 deliverables are:

1. A market-free weighted inverse-CDF primitive implementing §7.2.
2. A market-free `weight_ess` primitive implementing the exact frozen formula.
3. Generic weight construction sufficient to distinguish:
   - `session_equal_weighted` primary; and
   - `anchor_weighted` companion.
4. Diagnostics needed to prove the session-equal mechanism:
   - contributing-session count;
   - per-session total mass equality;
   - maximum mass fraction from one session; and
   - `weight_ess`.
5. The smallest generic kernel/result interface required to carry values,
   weights, quantiles, counts, and statuses without market/study concepts.
6. Tests and adversarial mutations proving every claim.
7. `docs/PHASE4.md` with measured, inferred, and not-verified sections.

Do not implement standardized-shared-population or positivity weighting; those
depend on later condition/contrast support and belong to Phase 8. Do not
implement bootstrap; that is Phase 5. Do not create actual market cells merely
to exercise the kernel; use deterministic synthetic fixtures.

The package boundary is binding:

```text
mnq_lab/core/weights.py     market-free weights, quantiles, weight diagnostics
mnq_lab/core/kernel.py      only the smallest ratified generic orchestration
mnq_lab/core/result.py      only generic result/status structures if justified
```

`core/` may know arrays, identifiers, weights, values, and statuses. It may not
know MNQ, RTH, phases, horizons, volatility states, sessions as exchange
calendars, holidays, excursions, studies, or profit.

## 6. Frozen mathematics

For real-valued nonnegative weights:

```text
Q(q) = inf{x : (sum_{x_i <= x} w_i) / (sum_i w_i) >= q}
```

This is a step function. It returns an observed support value and never
interpolates. It must be replication-invariant and match:

```python
np.quantile(repeated_values, q, method="inverted_cdf")
```

for rational weights represented by integer replication counts.

The default NumPy `linear` convention is forbidden.

Weight concentration:

```text
weight_ess = (sum_i w_i)^2 / sum_i(w_i^2)
```

It is named exactly `weight_ess`, never “effective sample size.” It does not
correct for overlapping outcomes, serial dependence, or regime dependence.

For a filtered cell with `S` contributing sessions and `n_s` eligible anchors
in session `s`, the natural executable reading of session-equal weighting is:

```text
w_i = 1 / (S * n_s)
```

for each eligible anchor `i` in session `s`. Each contributing session then has
total mass `1/S`. Anchor weighting assigns equal mass to each eligible anchor.
Opus must ratify this executable normalization before implementation.

## 7. Quant preflight required before coding

The formula is frozen, but several boundary conventions are not explicit enough
to guess. Before production code, give Opus this exact question:

```text
Does §7.2 authorize the following executable Phase 4 contract?

1. Inputs are one-dimensional, aligned value and weight arrays.
2. Values and weights must be finite real numbers; bools, NaN, and infinity fail.
3. Weights must be nonnegative and total weight must be strictly positive.
4. Zero-weight observations contribute no CDF mass and cannot change Q(q).
5. The inverse CDF returns the smallest observed value whose cumulative
   normalized weight is at least q; it never interpolates.
6. Tied values are one support point carrying their combined weight.
7. Input row order and positive rescaling of all weights cannot change Q(q).
8. Inputs are never mutated in place.
9. weight_ess uses all nonnegative weights, is scale-invariant, equals 1 for one
   positive-weight observation, and ignores zero weights algebraically.
10. session_equal_weighted gives every contributing session total mass 1/S and
    every eligible anchor within session s mass 1/(S*n_s).
11. anchor_weighted gives every eligible anchor equal mass.

The unresolved q=0 boundary must be adjudicated explicitly:

A. Restrict the public contract to 0 < q <= 1, matching the literal infimum
   formula over the real line; or
B. Admit 0 <= q <= 1 and define Q(0) as the minimum positive-weight support
   value, matching practical NumPy inverted-CDF behavior.

Also adjudicate whether a non-finite value paired with zero weight still fails
closed (recommended: yes, because validation should not depend on weight-based
data hiding), and what numerical accumulation rule is required at an exact CDF
boundary for real-valued fractional weights.

Return RATIFIED with the exact contract, or DISCREPANCY with the frozen text
that requires a user ruling. Do not implement until resolved.
```

If Opus judges the q boundary or real-weight accumulation materially
underdetermined, add a new discrepancy and obtain a user ruling. Do not choose
whichever convention makes a test easiest.

## 8. Weighting semantics to prove

Spec §7.1 makes session-equal weighting primary:

```text
select uniformly among sessions containing at least one eligible cell anchor,
then uniformly among that session's eligible anchors
```

Use an unbalanced synthetic fixture where one session has one anchor and another
has many. It must prove:

- session-equal and anchor-weighted quantiles can differ;
- each contributing session has equal total session-equal mass;
- within a session, eligible anchors have equal mass;
- empty sessions do not enter `S`;
- duplicating every anchor within one session does not increase that session's
  total session-equal mass;
- anchor weighting does respond to duplicated anchors;
- canonical input ordering is not required for semantic correctness;
- session identifiers are labels only, not CME-specific concepts.

Do not implement the non-overlapping-anchor sensitivity. It depends on clock
grids and later outcome-cell construction, not the Phase 4 market-free kernel.

## 9. Kernel/result boundary

The frozen spec names a “kernel core” but does not fully prescribe an API.
Before creating a large abstraction, preregister the smallest interface with
Opus.

Recommended minimum:

```text
weighted_quantile(values, weights, q) -> scalar
weighted_quantiles(values, weights, quantiles) -> aligned array
weight_ess(weights) -> float
session_equal_weights(group_ids) -> aligned weights + diagnostics
anchor_equal_weights(n) -> aligned weights + diagnostics
```

A generic result object, if introduced, should carry only:

```text
status
n_anchors
n_sessions
weight_ess
quantile probabilities
quantile values
weighting name
```

Do not invent a market cell schema, interval fields, contrast fields, or report
format in Phase 4. If no consumer yet justifies `kernel.py` or `result.py`,
Opus may approve a smaller unit centered on `core/weights.py`; document that
scope honestly rather than creating unused architecture to satisfy filenames.

## 10. Required implementation order

### Stage A — branch and baseline

1. Verify the handoff commit and clean tree.
2. Create `phase-4-kernel`.
3. Replay 332/5, gates 4/4, completion, S00, hashes, ledger/YAML agreement.
4. Confirm all three threshold keys exist exactly and load as
   `{15: 0.99, 30: 0.99, 60: 0.98}`.
5. Confirm no Phase 4 modules already exist.

### Stage B — mathematical preregistration

1. Have Opus ratify §7.2’s executable contract and the §7.1 session-equal
   normalization.
2. Resolve q=0, zero-weight/non-finite handling, and exact-boundary accumulation.
3. Preregister the public API, accepted dtypes, error behavior, return types,
   and semantic-versus-byte determinism claims.
4. Add a discrepancy instead of guessing if needed.

### Stage C — inverse-CDF primitive

1. Implement the smallest market-free primitive.
2. Match the repeated-value inverted-CDF oracle for rational weights.
3. Prove ties, zero weights, n=1, input order, scaling, and no input mutation.
4. Prove default linear interpolation cannot replace it.
5. Commit and have Opus mutation-audit the unit.

### Stage D — weights and `weight_ess`

1. Implement `weight_ess`.
2. Implement session-equal and anchor-equal weight construction.
3. Emit generic diagnostics including max session mass fraction.
4. Use a discriminating unbalanced-session fixture.
5. Commit and have Opus mutation-audit the unit.

### Stage E — minimal kernel/result integration

1. Add only the interface ratified in Stage B.
2. Require `n_anchors`, `n_sessions`, and `weight_ess` together.
3. Emit statuses for empty/invalid result requests rather than dropping them,
   where a result-table interface exists.
4. Do not connect it to S00 or compute real MNQ results.
5. Commit and audit.

### Stage F — closeout

1. Run full suite, four gates, completion CLI, S00 CLI twice, and hash checks.
2. Prove the S00 artifact and YAML are unchanged.
3. Run required adversarial mutations in a disposable clone.
4. Write `docs/PHASE4.md`.
5. Obtain final Opus verdict `CLOSED`.
6. Stop before Phase 5.

## 11. Required tests and mutations

At minimum:

### Weighted inverse CDF

- Rational weights match repeated-sample
  `np.quantile(..., method="inverted_cdf")`.
- Heavy ties return an observed tied value without interpolation.
- Zero-weight values cannot change a result.
- A zero-weight extreme cannot enter the support returned by the quantile.
- `n=1` returns the sole positive-weight value at every admitted q.
- Input order invariance.
- Positive weight-scale invariance.
- Values and weights remain byte-identical after calls.
- Multi-q output follows input q order, never measured-value order.
- Default linear interpolation gives a detectably different answer on a fixture.
- Missing, empty, mismatched, multidimensional, negative-weight, all-zero,
  bool, non-finite, and invalid-q inputs fail closed.
- Exact CDF-boundary behavior matches the ratified convention.

### `weight_ess`

- Exact formula on hand-computed weights.
- Equal positive weights give the count of positive-weight observations.
- One positive weight gives 1.
- Zero weights do not change it.
- Positive rescaling does not change it.
- Concentrated weights lower it.
- It is always named `weight_ess`.
- No claim calls it “effective sample size.”

### Weight construction

- Session-equal total mass is identical across contributing sessions.
- Anchor-equal mass is identical across anchors.
- Session-equal and anchor-equal differ on an unbalanced corpus.
- Duplicating anchors in one session preserves that session's total
  session-equal mass.
- Empty input and malformed group identifiers fail closed.
- Output weights align with original row order.
- Input group identifiers are not mutated.
- Max session mass fraction is computed from session totals, not anchor maxima.

### Regression/scope

- `tests/test_no_selection.py` still passes.
- No core module imports `spine`, `outcomes`, `conditioners`, studies, report,
  or ledger.
- No core module names the locked tier.
- S00 artifact SHA-256 stays
  `725df33a00e53c6c356c4348df2a02fe9ed309d9d4e4118216894a70ef8a479d`.
- YAML SHA-256 stays
  `1c95aa595c30c48b853303291a7dbaabceaf5b7331bca565a30863e8dcf138d4`.
- Ledger/YAML agreement remains valid.

Required adversarial mutations:

- use NumPy default linear quantile;
- interpolate between bracketing observations;
- treat zero-weight values as positive support;
- allow negative weights;
- accept an all-zero vector;
- normalize by row count rather than total weight;
- compute `weight_ess` as `sum(w)` or `1/sum(w^2)` without normalization;
- label `weight_ess` as effective sample size;
- use anchor-equal weights for the session-equal primary;
- let a many-anchor session dominate session-equal mass;
- reorder output quantiles by value;
- mutate inputs while sorting;
- silently drop invalid rows;
- bridge into S00 and change its artifact;
- read the locked tier.

Each must be killed by a named test or a fail-closed guard.

## 12. Prohibitions and stop conditions

- No access to locked-confirmation data from Phase 4 code.
- No Phase 5 bootstrap.
- No conditioner or volatility-state implementation.
- No path-excursion calculation.
- No contrast, positivity, or null engine.
- No S01A output.
- No change to the three completion thresholds.
- No rewrite of the S00 artifact or its ledger entry.
- No YAML edit unless a genuinely new frozen constant is first justified,
  audited, ledgered, and explicitly authorized by the user.
- No ranking cells, profitability language, P&L, Sharpe, expectancy, or
  trading recommendation.
- No market/session concept in `core/`.
- No tolerance/nearest matching.
- No silent dropping of invalid values or weights.
- No claim that `weight_ess` corrects dependence.

Stop immediately if:

- a Phase 1 gate fails;
- the 332/5 baseline regresses without an explained Phase 4 test addition;
- S00 or YAML hash changes;
- ledger/YAML validation fails;
- the quantile boundary convention remains unresolved;
- the repeated-sample oracle disagrees;
- any required mutation survives;
- a proposed kernel API requires Phase 5+ concepts;
- any new code path touches the locked tier.

## 13. Definition of done

Phase 4 is complete only when:

- Opus ratifies all executable math and boundary conventions.
- Weighted inverse CDF passes §13 test 7 and adversarial variants.
- `weight_ess` implements exactly the frozen formula and is described honestly.
- Session-equal and anchor-equal weights are discriminated by synthetic tests.
- The core remains market-free.
- Any kernel/result interface is minimal and justified.
- Full suite and all four Phase 1 gates pass.
- Phase 3 artifact, YAML, and ledger remain unchanged.
- `docs/PHASE4.md` separates measured, inferred, and not verified.
- Final Opus verdict is `CLOSED`.
- No Phase 5 or S01A result has been computed.

## 14. First new-session behavior

The first Phase 4 turn should:

1. verify the exact starting commit and clean tree;
2. create `phase-4-kernel`;
3. replay the entire signed-off baseline;
4. read the required sources above;
5. inspect—not implement—the proposed Phase 4 API;
6. prepare the exact §7.2/§7.1 preflight question for Opus;
7. stop before production code until Opus ratifies the boundary contract or
   identifies a discrepancy requiring a user ruling.

