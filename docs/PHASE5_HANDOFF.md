# Phase 5 handoff — whole-session stationary bootstrap

This is the continuity document for the implementation session after Phase 4.
Phases 1–4 are complete and independently closed. A subsequent red-team audit
found no Phase 1–4 scientific-correctness or leakage defect. Its one operational
finding—the sealed store cannot be reproduced under the current YAML with the
same provenance identity—was corrected through explicit preservation and
scientific-reconstruction guidance in `docs/SEALED_STORE_REBUILD.md`.

Phase 5 builds only the market-free bootstrap machinery required by frozen spec
§7.3 and §15 row 5:

```text
whole-session stationary block resampling
one coherent resample for an entire row-aligned frame
block-length sensitivity at 1, 5, 10, and 20 sessions
bootstrap multiplicities composed with the Phase 4 weighted-statistics path
the frozen §13 test 8 calibration and dependence discriminators
```

Phase 5 is not a study run. It must not implement conditioners, volatility
states, path excursions, contrasts, positivity, prevalence, nulls, surfaces,
reports, S01A, confirmation, or forward-vintage consumption.

## 1. Roles and working agreement

- **Codex:** developer. Implements code, tests, documentation, and fixes.
- **Opus 5:** quant and routine independent auditor. It must ratify the complete
  executable bootstrap contract before production code and mutation-audit each
  completed unit.
- **Fable 5:** escalation auditor only for the hardest unresolved discrepancy or
  high-risk final dispute.
- After each completed coding unit, Codex supplies a compact ready-to-paste Opus
  audit prompt.

Developer-authored code, tests, simulation fixtures, coverage counts, and prose
are claims, not independent audit evidence. Auditor mutations run only in
disposable clones. Do not mutate the user’s working repository to demonstrate a
test kill.

## 2. Immutable starting state

Repository continuity:

```text
repo                              C:\mnq-atlas
current branch                    phase-4-kernel
Phase 4 implementation closeout   edf0a0129d43c03cc94e77ba64abc9ef2c639667
sealed-store guidance correction  2e0cf57
next branch                       phase-5-bootstrap
```

The Phase 5 branch must be created from the exact handoff tip reported in the
new-session prompt. Do not branch from a remote tracking branch and do not omit
the post-closeout sealed-store correction.

Starting replay:

```powershell
git status --short --branch
git log -10 --oneline
python -m pytest tests -q
python -m mnq_lab.spine.gates --store data
python -m mnq_lab.outcomes.completion --store data
python -m mnq_lab.outcomes.s00 --store data
```

Expected:

```text
tests                   443 passed, 5 xfailed
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

analysis_constants_v1.yaml — sealed-store build input / ledger old hash
3f5c4bd5258eeb306d76d45aa4ad568a2483f007415e7d11df89ebbc8c4b182a
```

The two YAML hashes are intentionally different. The store manifests retain the
historical build-input hash; the current YAML contains the audited completion
thresholds. Never rewrite a manifest to the current hash.

Current thresholds are binding and immutable:

```yaml
min_completion_h15: 0.99
min_completion_h30: 0.99
min_completion_h60: 0.98
```

The threshold loader must return exactly:

```python
{15: 0.99, 30: 0.99, 60: 0.98}
```

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

Do not rebuild canonical `data/`. Its exact artifact identity must be preserved;
a current-YAML rebuild has new provenance and is expected to fail pinned tests.
If the store is absent, stop and follow `docs/SEALED_STORE_REBUILD.md`; do not
overwrite or fabricate sealed manifests.

Do not manually inspect, import, or mmap `data/locked_confirmation/`. Existing
signed-off spine gates and legacy fixtures retain their audited access boundary.
Do not broaden it.

## 3. Read in this order

Read each selected document completely before implementation:

1. This handoff.
2. `REV6_FROZEN_SPEC.md` §14 (STRUCK).
3. Frozen spec §7.1, §7.2, and §7.3.
4. Frozen spec §12 fields `estimands`, `bootstrap`, and `reporting`.
5. Frozen spec §13 tests 7 and 8.
6. Frozen spec §15 rows 4–6.
7. Frozen spec §16.3 through §16.7.
8. `analysis_constants_v1.yaml`.
9. `docs/PHASE4.md`.
10. `docs/PHASE4_HANDOFF.md`, especially its package boundary and mutation
    discipline.
11. `docs/DISCREPANCIES.md`, especially D8, D11, D12, and D13.
12. `docs/SEALED_STORE_REBUILD.md`.
13. `mnq_lab/core/weights.py` and its complete tests:
    `tests/test_weighted_quantile.py` and `tests/test_weights.py`.
14. `tests/test_no_selection.py`, `tests/test_spec_consistency.py`,
    `tests/test_s00.py`, and `tests/test_threshold_ledger.py`.
15. `CLAUDE.md`.
16. The external `lora_statistics.py` reference named in `CLAUDE.md`, limited to
    `session_row_groups` and `stationary_session_resample`.

The external resampler is a defect reference, not callable production code. It
stops after a row target and slices the concatenated row array, which can cut
the final session. Generalize the intended session-block process without
copying that defect. Do not import the external module into `mnq_lab`.

Older revisions and chat summaries are not authoritative over the frozen spec,
binding rulings, ledger, Phase 4 contract, and recorded audit closures.

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
- Completion accounting and honest data-derived session flags.

### Phase 3

- Canonical 15-cell S00 completion artifact.
- Equal-phase discrete inverse-CDF p05 convention.
- Thresholds h15 `0.99`, h30 `0.99`, h60 `0.98`.
- Ledger-before-YAML freeze and no-default loader.
- S00 byte stability under the frozen threshold values.

### Phase 4

- Market-free discrete weighted inverse CDF.
- Exact `0 < q <= 1` public probability domain; `q=0` fails closed.
- Canonical binary64 tie aggregation and multiplication-form boundary selection.
- Zero-weight observations carry no support, while all values—including
  zero-weight values—must still be finite.
- Exact observed-support return values with no interpolation or tolerance.
- `weight_ess = (sum(w) ** 2) / sum(w ** 2)`, named only `weight_ess`.
- Session-equal weights `1 / (S * n_s)` and anchor-equal weights `1/n`.
- Group-mass and concentration diagnostics.
- Market-free scope and locked-tier/import guards.
- Phase 4 final audit `CLOSED`; all 30 closeout mutations killed.
- Phases 1–4 red-team audit `CLOSED` with zero required mutation survivors.

The Phase 4 accumulation path is binding for Phase 5. Do not fork a second
weighted-quantile implementation for bootstrap.

## 5. Carried-forward findings and caveats

### D13 — arbitrary binary64 scaling

Phase 4 guarantees exact weighted-quantile scale invariance for power-of-two
factors. Arbitrary positive scaling can move an exact CDF boundary because the
scaled binary64 inputs differ after rounding. Phase 5 fractional bootstrap
weights must use the existing canonical Phase 4 path and must not add:

- pre-normalization;
- division-form boundary comparison;
- epsilon or tolerance around a CDF boundary;
- a claim of arbitrary-factor exact invariance.

An all-ones bootstrap multiplicity vector must reproduce the point estimate
using byte-identical baseline weights, not a mathematically equivalent
renormalization that changes binary64 inputs.

### Performance caveat

Phase 4’s opaque-label validation uses a Python hash loop and
`session_equal_weights` currently computes a boolean mask per group. At the
real exploration scale this is roughly 79 million mask operations for one
construction. Correctness is closed, but repeatedly reconstructing those
weights inside every bootstrap draw is a known Phase 5 throughput risk.

Construct baseline weights once. Prefer applying integer group multiplicities
to those row-aligned baseline weights. Benchmark before refactoring the signed
Phase 4 implementation; any behavior-changing optimization requires the Phase
4 mutation suite to be replayed.

### Sealed-store reproducibility

The scientific arrays can be reconstructed, but certified byte recreation of
the sealed artifact is not claimed because its manifest records a dirty build
state whose uncommitted contents were not preserved. This is operational
provenance, not permission to change any statistical input.

## 6. Exact Phase 5 scope

Frozen spec §15 row 5:

```text
Bootstrap: whole-session, block sensitivity, dual estimand
Gate: §13 test 8
```

Minimum Phase 5 deliverables:

1. A market-free whole-group stationary-block resampling primitive whose groups
   represent sessions to later callers but remain opaque labels in `core/`.
2. An immutable resample plan or equivalent representation that records the
   selected group sequence and integer multiplicity of every original group.
3. Exact selection of the original **group count**, never an original row count.
   The final block may be shortened by group count; no group may be sliced by
   rows.
4. One plan reusable across every row-aligned outcome, horizon, statistic, and
   cell mask in a tidy frame.
5. Composition of group multiplicities with Phase 4 baseline weights on the
   same `weighted_quantile(s)` code path.
6. Primary mean block length `5` and sensitivity lengths `[1, 5, 10, 20]`,
   loaded fail-closed from the YAML.
7. The frozen §13 test 8 properties:
   - all-ones multiplicities reproduce the point estimate exactly;
   - 95% interval coverage of a known synthetic median is judged against a
     preregistered binomial acceptance interval over 300 replications;
   - AR(1)-within-session data yield materially wider session-block intervals
     than an i.i.d. row-bootstrap negative oracle.
8. Tests and adversarial mutations proving every mechanism.
9. `docs/PHASE5_PREREGISTRATION.md`, ratified and committed before the first
   stochastic acceptance run, containing the exact RNG, CI, coverage, AR(1),
   and materiality parameters.
10. `docs/PHASE5.md` separating measured, inferred, and not verified.

Phase 5 should normally add:

```text
mnq_lab/core/bootstrap.py
tests/test_bootstrap_properties.py
docs/PHASE5_PREREGISTRATION.md
docs/PHASE5.md
```

Add other files only when the ratified API and a real Phase 5 consumer justify
them. Do not create market cells, result surfaces, or report schemas merely to
exercise bootstrap.

The phrase “dual estimand” in §15 row 5 is not executable by itself. It could
refer to the two path estimands in §6, the primary/companion weightings in §7.1,
or another pairing. Do not silently choose a reading. Opus must tie the term to
frozen text or declare a discrepancy requiring a user ruling.

## 7. Frozen bootstrap requirements

Frozen spec §7.3 states:

```text
Whole-session stationary block resample.

Sample whole session IDs until the original session count is reached.
The final block may be truncated by session count, never an individual
session by rows.

One resample serves the entire tidy frame.

Block-length sensitivity at 1, 5, 10, and 20 sessions.
```

Consequences already determined by the frozen text:

- the resampling unit is a whole session/group;
- the target size is a session/group count;
- duplicates are allowed and must be represented honestly;
- a selected group contributes all of its rows wherever those rows are
  eligible for a downstream statistic;
- per-cell anchor and session counts naturally vary by draw;
- filtering to “sessions containing this cell” before resampling is forbidden;
- drawing separately for each cell, horizon, outcome, or statistic is forbidden;
- individual rows are never the production resampling unit;
- the original row/value/weight/group arrays are never mutated.

Every eventual interval must carry the frozen interpretation:

> This measures uncertainty within the historical mixture, not uncertainty
> about future regime change.

Phase 5 intervals condition on whatever row labels and baseline weights the
caller supplies. Conditioner-estimation uncertainty, alternative conditioner
definitions, horizon-specific/common market support, and cell migration belong
to later phases. Do not imply that a generic Phase 5 interval includes them.
When intervals eventually enter result tables, `n_anchors`, `n_sessions`, and
`weight_ess` must appear together beside the interval; Phase 5 does not need to
invent that market result table.

The frozen text does **not** fully determine the stationary-block transition,
RNG contract, CI endpoint convention, calibration fixture, “materially wider”
threshold, undefined-replicate handling, or “dual estimand.” Those are Stage B
preflight questions, not implementer choices.

## 8. Quant preflight required before production code

Give Opus the following complete question before implementation:

```text
Does frozen spec §7.3 authorize this executable Phase 5 contract?

RESAMPLE POPULATION
1. Input is a non-empty one-dimensional row-aligned vector of opaque group
   labels in chronological group order. A label must occupy one contiguous row
   region; a label reappearing after another label fails closed.
2. Let S be the number of ordered unique groups. One draw contains exactly S
   selected whole-group occurrences, including duplicates.
3. No selected group is ever sliced by rows. “Truncate the final block” means
   stop the selected group sequence after occurrence S, even if the stationary
   block would otherwise continue.

STATIONARY TRANSITION
4. For mean block length L, require finite non-bool L >= 1 and set restart
   probability p = 1/L.
5. Choose the first group position uniformly from {0,...,S-1}.
6. After each selected occurrence except the last, restart at a new uniformly
   selected group position with probability p; otherwise advance to the next
   chronological group, wrapping circularly from S-1 to 0.
7. L=1 therefore restarts before every next occurrence. L in {1,5,10,20}
   is the frozen sensitivity grid; L=5 is primary.

OUTPUT AND JOINT COHERENCE
8. Return an immutable plan containing the length-S selected position sequence,
   integer multiplicities aligned to the original ordered groups, and sufficient
   restart/block metadata to test the mechanism.
9. A single plan is applied jointly to the entire row-aligned frame. Cell masks
   are applied after the global plan; a cell’s contributing counts may vary.
10. Group/value/weight inputs are not mutated. The caller-supplied RNG state
    advances and that state change is explicit, not hidden.

WEIGHT COMPOSITION
11. Construct each point-estimate baseline weight vector once using the ratified
    Phase 4 constructors. For a bootstrap draw, multiply every row’s unchanged
    baseline weight by its group’s integer multiplicity.
12. Feed those fractional bootstrap weights directly to the existing Phase 4
    weighted_quantile(s) path. Do not pre-normalize, expand repeated rows in
    production, use a second quantile algorithm, or rebuild session-equal weights
    over only the distinct groups selected at least once.
13. An all-ones multiplicity vector therefore passes the exact baseline weights
    back to Phase 4 and must reproduce the point estimate exactly for both
    session-equal primary and anchor-equal companion weighting.
14. A draw with zero positive mass for a requested statistic fails closed or
    emits an explicit status at the future result boundary; it is never silently
    dropped from the bootstrap distribution.

INTERVAL
15. A “95% CI” is a percentile interval at q=(0.025,0.975), with endpoints
    selected as an equal-replicate discrete inverse CDF through the Phase 4
    weighted path. Endpoints are observed bootstrap statistics; default linear
    interpolation is forbidden.
16. Non-finite replicate statistics, missing draws, and a requested draw count
    less than the preregistered minimum fail closed. No finite-only filtering
    and no early stopping.

RNG AND DETERMINISM
17. No module-global RNG and no unrecorded default seed. The public API accepts
    either an explicitly supplied numpy Generator or an explicitly supplied
    seed, with the exact accepted form ratified here. If a canonical bit
    generator is required, identify it; do not borrow the inference seed
    silently because the YAML’s PCG64/20260728 fields are under inference.
18. Same inputs plus the same initial RNG state produce the same plan and
    bootstrap statistics. Cross-environment semantic determinism, not
    unconditional byte identity, is claimed.

CALIBRATION TEST
19. Before running the §13 test 8 coverage experiment, preregister the synthetic
    session generator, true median, sessions per dataset, rows per session,
    bootstrap draw count, 300 outer replications, seed schedule, interval method,
    exact binomial acceptance bounds, and handling of discrete ties.
20. Before running the AR(1) discriminator, preregister the AR coefficient,
    innovations, sessions, rows/session, draw count, seed schedule, width
    aggregation, and an exact numerical threshold for “materially wider.”
    The i.i.d. row bootstrap exists only as a negative test oracle, not as a
    production alternative.

DUAL ESTIMAND
21. Identify exactly what “dual estimand” in §15 row 5 means from frozen text.
    If it cannot be uniquely tied to §6 or §7.1, return DISCREPANCY and request a
    user ruling rather than choosing whichever interpretation is convenient.

Also answer these boundary questions explicitly:

A. Is the circular wrap in item 6 binding, as in the retained reference, or
   should a block reaching the final chronological group be forced to restart?
B. Must row-aligned group labels be contiguous, or should the plan accept a
   separately supplied ordered unique-group vector and a noncontiguous row map?
C. Are percentile endpoints and equal-replicate inverse-CDF selection in item
   15 the intended CI convention?
D. What exact RNG input and bit-generator contract is authorized?
E. What exact coverage fixture/bounds and AR(1) width threshold satisfy §13
   test 8 without being tuned after results?
F. How must a zero-mass or otherwise undefined replicate be represented before
   Phase 8 introduces complete result statuses?
G. What exactly is the frozen “dual estimand” deliverable?

Return RATIFIED WITH THE COMPLETE CONTRACT, or DISCREPANCY naming the frozen
text that cannot determine it. Do not implement production code until every
item is resolved or the user supplies a binding ruling.
```

The suggested contract above is a preflight proposal, not an authorization.
Record the returned contract verbatim in
`docs/PHASE5_PREREGISTRATION.md` and commit it before the first implementation
unit or stochastic acceptance run.

## 9. Recommended minimal API boundary

Preregister the smallest API with Opus. A reasonable starting shape is:

```text
stationary_group_resample(group_ids, mean_block_groups, rng)
    -> immutable plan with selected positions and multiplicities

apply_group_multiplicities(group_ids, baseline_weights, plan)
    -> row-aligned fractional bootstrap weights

bootstrap_weighted_quantiles(
    values,
    baseline_weights,
    group_ids,
    quantiles,
    draws,
    mean_block_groups,
    rng,
)
    -> bootstrap statistics and generic interval diagnostics
```

Names and decomposition are not frozen. The important boundary is:

- `core/` sees numeric arrays, ordered opaque groups, weights, probabilities,
  and RNG state;
- it does not know MNQ, CME calendars, market phases, horizons, volatility
  states, holidays, excursions, studies, or profitability;
- it imports the existing Phase 4 weighted primitives and does not import
  spine, outcomes, conditioners, studies, reports, nulls, or ledger;
- no market result object is introduced in Phase 5.

If a plan primitive plus weight application is sufficient to pass the frozen
gate honestly, prefer it over a premature general framework.

## 10. Required implementation order

### Stage A — branch and baseline

1. Verify exact handoff tip and clean tree.
2. Create `phase-5-bootstrap`.
3. Replay 443/5, gates 4/4, completion, S00, hashes, and ledger/YAML agreement.
4. Confirm the bootstrap YAML block loads exactly:

   ```python
   {
       "scheme": "whole_session_stationary",
       "mean_block_sessions_primary": 5,
       "block_sensitivity": [1, 5, 10, 20],
       "truncate_partial_session": False,
   }
   ```

5. Confirm `mnq_lab/core/bootstrap.py`,
   `tests/test_bootstrap_properties.py`,
   `docs/PHASE5_PREREGISTRATION.md`, and `docs/PHASE5.md` do not already exist.
6. Inspect the external reference defect without calling or importing it.

### Stage B — bootstrap preregistration

1. Send the complete §8 preflight to Opus.
2. Resolve the stationary transition, wrap, RNG, interval, undefined draw,
   calibration, AR(1), API, and dual-estimand contracts.
3. If frozen text is insufficient, add a discrepancy and obtain a user ruling.
4. Write the complete ratified contract and numerical acceptance parameters to
   `docs/PHASE5_PREREGISTRATION.md`.
5. Commit that preregistration before implementing or running either stochastic
   acceptance experiment. Do not edit its parameters after seeing a result.

### Stage C — whole-group resample plan

1. Implement the smallest market-free plan primitive.
2. Select exactly the original group count.
3. Preserve every selected group whole.
4. Record sequence, multiplicities, blocks/restarts, and input count honestly.
5. Prove circular/restart behavior with deterministic discriminating fixtures.
6. Commit and have Opus mutation-audit the unit.

### Stage D — Phase 4 weight integration and joint coherence

1. Apply one plan to row-aligned baseline weights by group multiplicity.
2. Prove all-ones exact point reproduction.
3. Prove one plan is shared across multiple aligned value arrays and masks.
4. Prove per-cell support can vary instead of being pinned by pre-filtering.
5. Prove both ratified “dual estimand” paths without adding market concepts.
6. Benchmark the real-scale shape synthetically or with counts only; do not
   open market stores from `core/`.
7. Commit and obtain a mutation audit.

### Stage E — interval and §13 test 8

1. Implement only the ratified interval API.
2. Use the Phase 4 inverse-CDF path for point and interval statistics.
3. Run the preregistered 300-replication coverage experiment only after the
   preregistration commit. Exact subsequent replays are expected; do not tune
   the fixture or bounds after observing the first result.
4. Run the preregistered AR(1) versus i.i.d.-row discriminator.
5. Ensure the row bootstrap remains test-only.
6. Commit and obtain a mutation audit.

### Stage F — closeout

1. Run the full suite, four gates, completion CLI, and S00 CLI twice.
2. Prove S00, YAML, spec, and ledger are unchanged.
3. Run the required mutation battery in a disposable clone.
4. Write `docs/PHASE5.md` with Measured, Inferred, and Not verified sections.
5. Obtain final Opus verdict `CLOSED`.
6. Stop before Phase 6.

## 11. Required tests and mutation targets

At minimum, every test below needs a negative case or named mutation proving it
can fail.

### Whole-group plan

- Exactly `S` group occurrences are drawn from `S` original groups.
- Multiplicities are nonnegative integers and sum to `S`.
- Multiplicities exactly match the selected position sequence.
- Every selected group is whole; unequal group sizes cannot cause a row slice.
- The last stationary block is shortened only by group occurrence count.
- A planted copy of the external “stop at N rows, then slice” defect is killed.
- Continuation advances to the next chronological group.
- The ratified end-of-series wrap/restart rule is discriminated.
- `L=1` follows the ratified restart-every-time behavior.
- `L=5` uses restart probability `1/5`, not continuation probability `1/5`.
- Primary and sensitivity lengths load from YAML, not inline fallbacks.
- Same initial RNG state reproduces the plan.
- No hidden global RNG or implicit seed exists.
- Inputs are not mutated.
- Empty, multidimensional, malformed-label, noncontiguous-label (if ratified),
  invalid-`L`, and invalid-RNG inputs fail closed.

### Weight composition and coherence

- An all-ones multiplicity vector returns the exact original baseline weights.
- All-ones weights reproduce the Phase 4 point estimate exactly.
- Integer multiplicities match an explicit repeated-whole-group oracle.
- A zero-multiplicity group contributes no mass.
- Fractional baseline weights are not pre-normalized.
- Session-equal and anchor-equal baselines remain distinguishable on an
  unbalanced synthetic corpus.
- The baseline and bootstrap-weight arrays are not mutated.
- One plan drives at least two aligned outcomes and two cell masks.
- A cell’s contributing anchor/session counts vary across plans when its groups
  are resampled with different multiplicity.
- Resampling separately inside each filtered cell is killed by a named test.
- Drawing a fresh plan per outcome/horizon/statistic is killed by a named test.
- An all-zero requested support fails closed; it is never finite-filtered away.

### Interval and calibration

- Interval endpoints follow the ratified probabilities and are observed
  bootstrap support values.
- Default NumPy `linear` endpoints are detectably different on a fixture.
- Replicate order does not change interval endpoints.
- Non-finite/undefined replicate statistics are not silently dropped.
- Draw count and confidence-level boundaries fail closed.
- The preregistered synthetic median coverage count falls within the exact
  preregistered binomial interval over 300 replications.
- The preregistered AR(1) session-block width exceeds the i.i.d.-row-bootstrap
  width by the exact ratified materiality rule.
- A row-bootstrap production mutation is killed.
- The coverage seed, DGP, acceptance bounds, and AR threshold match the
  pre-experiment `docs/PHASE5_PREREGISTRATION.md` commit exactly.

### Regression and scope

- The complete Phase 4 weighted suites still pass.
- `tests/test_no_selection.py` still passes.
- No core module imports or names market-aware packages or the locked tier.
- No production module imports or calls external `lora_statistics.py`.
- No bootstrap code opens a market-data store.
- S00 remains 7,636 bytes with SHA-256
  `725df33a00e53c6c356c4348df2a02fe9ed309d9d4e4118216894a70ef8a479d`.
- YAML remains
  `1c95aa595c30c48b853303291a7dbaabceaf5b7331bca565a30863e8dcf138d4`.
- Spec remains
  `70dae16c8b12fe26d38a7bfdabf0202066fe7149f790d0d2942279d9c3b8ff50`.
- Ledger/YAML validation and threshold loading remain exact.

Required adversarial mutations include:

- terminate by row count and slice the final group;
- sample `S` rows instead of `S` groups;
- use `p = 1 - 1/L` as restart probability;
- fail to wrap or restart at the final group contrary to the ratified rule;
- draw `S-1` or `S+1` occurrences;
- convert group multiplicities to booleans, losing duplicate draws;
- redraw independently for every cell or outcome;
- pre-filter to sessions containing the requested cell before resampling;
- recompute session-equal weights over only distinct selected sessions;
- pre-normalize fractional bootstrap weights;
- use a new/default/linear quantile implementation;
- let an all-ones plan differ from the point estimate;
- truncate or mutate caller arrays;
- silently discard undefined replicates;
- use an unrecorded default RNG seed;
- run an i.i.d. row bootstrap as production;
- read the locked tier;
- import outcomes, conditioners, studies, reports, nulls, or ledger into core;
- begin Phase 6 or S01A work.

Every required mutation must be killed by a named test or fail-closed guard.

## 12. Prohibitions and stop conditions

Do not:

- access locked-confirmation data from Phase 5 code;
- rebuild or replace canonical `data/`;
- change the frozen spec, YAML thresholds, S00 artifact, or ledger entry;
- call the defective external stationary resampler;
- truncate an individual session/group by rows;
- resample inside a pre-filtered cell;
- generate separate plans for separate outputs in one replication;
- add a production i.i.d. row bootstrap;
- add a second weighted-quantile implementation;
- pre-normalize weights or soften Phase 4 boundaries;
- silently drop invalid groups, rows, weights, or replicates;
- use a default/unrecorded random seed;
- reuse the null-engine seed without explicit ratification;
- implement conditioners, dependency witnesses, excursions, contrasts,
  positivity, prevalence, nulls, surfaces, reports, or S01A;
- emit profitability, P&L, Sharpe, expectancy, ranking, or a trading
  recommendation;
- claim bootstrap intervals cover future regime change;
- claim `weight_ess` corrects dependence;
- tune calibration fixtures or acceptance bounds after seeing results;
- rewrite the Phase 5 preregistration parameters after their first acceptance
  run;

Stop and report immediately if:

- HEAD or tree state differs from the supplied starting commit;
- any Phase 1 gate fails;
- the 443/5 baseline regresses before explained Phase 5 test additions;
- S00, YAML, spec, or ledger provenance changes;
- the sealed store is absent or a rebuild is proposed in canonical `data/`;
- the §8 boundary contract remains unresolved;
- “dual estimand” cannot be identified without a user ruling;
- all-ones multiplicities do not reproduce the point estimate exactly;
- any plan cuts a group or does not draw exactly `S` occurrences;
- a joint-frame test reveals separate resamples by output;
- the preregistered coverage or AR(1) acceptance check fails;
- a required mutation survives;
- acceptable performance would require changing Phase 4 behavior without
  reopening its audit;
- any new code path touches the locked tier;
- a proposed API requires Phase 6+ concepts.

## 13. Definition of done

Phase 5 is complete only when:

- Opus ratifies the full executable bootstrap and calibration contract.
- Any genuine frozen-text ambiguity has a recorded user ruling.
- Whole-session/group stationary resampling never truncates rows.
- One resample coherently serves the entire aligned frame.
- Fractional bootstrap weights use the Phase 4 weighted-statistics path.
- All-ones multiplicities reproduce every ratified Phase 5 point-estimate path
  exactly.
- Block sensitivities `[1, 5, 10, 20]` are implemented and discriminated.
- The §13 test 8 coverage and AR(1) properties pass their preregistered bounds.
- Every required adversarial mutation is killed.
- Core remains market-free.
- Full suite and all four Phase 1 gates pass.
- Phase 3 artifact, YAML, ledger, and thresholds remain unchanged.
- `docs/PHASE5.md` separates measured, inferred, and not verified.
- The committed Phase 5 preregistration predates its stochastic acceptance
  measurements and remains unchanged.
- Final Opus verdict is `CLOSED`.
- No Phase 6 module or S01A result has been created.

## 14. First new-session behavior

The first Phase 5 turn must:

1. verify the exact starting commit and clean tree;
2. create `phase-5-bootstrap`;
3. replay the entire signed-off baseline and frozen hashes;
4. confirm ledger/YAML agreement and bootstrap constants;
5. read every required source listed in §3;
6. confirm no Phase 5 production/test/document modules already exist;
7. inspect—but never call—the retained defective reference;
8. inspect the proposed API without implementing it;
9. prepare the exact §8 preflight for Opus;
10. stop before production code until Opus ratifies the complete contract or
    identifies a discrepancy requiring a user ruling.
