# Phase 5 — market-free whole-group bootstrap

Phase 5 implements the market-free whole-group stationary bootstrap required by
the frozen specification. It adds immutable resample plans, coherent reuse of
one plan across aligned requests, composition with the Phase 4 weighting path,
and discrete percentile intervals. It does not create market cells, run S01A,
consume confirmation data, or begin Phase 6.

The executable contract was preregistered before implementation and before any
stochastic acceptance execution. The complete one-shot history, including the
v1 coverage failure and deterministic calibration-launch failure, remains
append-only in `docs/PHASE5_ACCEPTANCE_RECORD.md`.

## Implemented contract

The public Phase 5 boundary is in `mnq_lab/core/bootstrap.py`:

```text
stationary_group_resample(...)
apply_group_multiplicities(...)
bootstrap_weighted_quantile_replicates(...)
percentile_interval(...)
```

- `stationary_group_resample` selects exactly the original ordered group count.
  It samples whole opaque groups, permits duplicate occurrences, advances or
  restarts with probability `1/L`, wraps chronologically, and never establishes
  a row target or slices a group.
- `StationaryGroupResamplePlan` records immutable selected positions, exact
  integer multiplicities, block-start flags, and restart metadata. Its
  invariants fail closed when the fields disagree.
- `apply_group_multiplicities` multiplies unchanged row-aligned Phase 4 baseline
  weights by group multiplicities. It neither pre-normalizes nor reconstructs
  weights over distinct selected groups. An all-ones plan preserves baseline
  weight bytes and the weighted point estimate.
- `bootstrap_weighted_quantile_replicates` creates one plan per replicate and
  applies it to every aligned value and eligibility-mask request. Masks are
  applied only after the global plan. Failed requests abort with their replicate
  and request indices; no replicate is discarded, redrawn, or retried.
- `percentile_interval` requires at least 999 finite replicate statistics and an
  explicit confidence level. It delegates to the Phase 4 discrete weighted
  inverse CDF with literal unit replicate weights; it does not interpolate or
  finite-filter.
- The production boundary accepts only an explicit
  `numpy.random.Generator`. It creates no hidden generator and offers no integer
  seed or default-seed overload.
- The fail-closed constants loader requires the frozen whole-session scheme,
  primary mean block length `5`, sensitivities `[1, 5, 10, 20]`, and
  `truncate_partial_session: false` directly from
  `analysis_constants_v1.yaml`.
- The binding dual-estimand interpretation is the pair of path estimands
  `fully_labeled_1m_grid` and `observed_bar_path`. Phase 5 proves the market-free
  mechanism by driving two aligned value/mask paths with one global plan.
  Session-equal and anchor-equal are separate weighting paths, not the two
  estimands.

## Measured

- The deterministic closeout suite produced `614 passed, 5 xfailed` while
  excluding `tests/test_bootstrap_acceptance.py` in full. That module contains
  spent one-shot fixtures and must never again be collected or executed.
- The focused deterministic Phase 5 and specification-guard suite produced
  `184 passed`.
- All four signed-off spine gates passed at closeout. The completion CLI
  remained at 1,009 exploration sessions and 78,702 gridpoints.
- Two consecutive closeout executions of the S00 CLI, as well as the artifact
  present before them, produced exactly 7,636 bytes with SHA-256
  `725df33a00e53c6c356c4348df2a02fe9ed309d9d4e4118216894a70ef8a479d`.
- Deterministic tests and adversarial mutation audits established exact group
  count, whole-group selection, transition and RNG-consumption order, immutable
  plan consistency, coherent multi-request reuse, post-plan masking, exact
  multiplicity/weight composition, Phase 4 quantile reuse, non-interpolated
  interval endpoints, and fail-closed handling of malformed or undefined
  inputs. The required row-slicing, wrong-probability, hidden-RNG, redraw,
  pre-filtering, pre-normalization, retry, denominator-reduction, production
  row-bootstrap, locked-tier, and scope mutations were killed.

The registered stochastic sequence completed as follows:

| Evidence | Fixed decision rule | Observed result | Status |
|---|---|---|---|
| v1 synthetic coverage | `277 <= C <= 292` | `C = 267` of 300 | `FAILED` permanently |
| v2 calibration | no pass/fail rule | `K = 2771` of 3000 | `COMPLETED` |
| v2 synthetic coverage | `268 <= C <= 286` | `C = 283` of 300 | `PASSED` |
| AR(1) discriminator | lower median ratio at least `1.50` and at least 20 of 24 directional wins | ratio `2.1683133477836822`; 24 of 24 wins | `PASSED` |

- The calibration measured `2771/3000 = 0.923666...`, approximately 92.37%,
  which is approximately 2.63 percentage points below 0.95. This is a Phase 5
  finding about the fixed synthetic finite-sample procedure. Phase 5 does not
  claim that its intervals are calibrated to nominal 95% coverage.
- Exact rational arithmetic applied to `Binomial(300, 2771/3000)` uniquely
  derived the v2 inclusive region `[268, 286]`. Direct PMF summation and an
  adjacent-PMF recurrence agreed on all 301 cumulative probabilities, and the
  exact recorded tail formulas are machine-guarded.
- The v2 count `283` lies inside `[268, 286]`. The result is evidence of
  consistency with the measured finite-sample coverage behavior, not evidence
  of nominal 95% coverage.
- In the AR(1) fixture, all 24 session-bootstrap widths exceeded their paired
  test-only i.i.d. row-bootstrap widths. The weighted lower median of the 24
  exact recorded ratios was `2.1683133477836822`, above the preregistered `1.50`
  threshold, and the directional count was 24, above the threshold of 20.
- All four registered Phase 5 stochastic entropies are spent. The v1 coverage,
  calibration, v2 coverage, and AR(1) executions must never be rerun.

## Inferred

- The permanent v1 result and the subsequent 3,000-replication calibration
  support the audit classification that the v1 failure arose from an
  acceptance-design mismatch: its region assumed 0.95 rather than centering on
  the measured finite-sample behavior. This does not erase or reinterpret the
  v1 failure.
- The v2 pass shows that a fresh 300-replication fixture was consistent with the
  calibrated finite-sample rate under the frozen synthetic procedure and seed
  schedule. It establishes reproducibility around measured behavior, not the
  scientific correctness of that behavior.
- The AR(1) discriminator shows that the implemented whole-session mechanism is
  sensitive to the within-session dependence planted in that test relative to
  its deliberately naive row-bootstrap negative oracle.
- Reusing a single immutable plan and row-aligned multiplicity vector makes
  joint coherence structural for any aligned requests passed through the Phase
  5 orchestration boundary.
- Returning to the Phase 4 weighted-statistics implementation for point and
  interval calculations avoids a second quantile convention inside Phase 5.

## Not verified

The Phase 5 acceptance fixtures do not validate that stationary session blocks
capture dependence between chronological sessions. The coverage fixture has
independent groups, and the AR(1) discriminator resets independently between
groups and tests only preservation of within-group dependence against an i.i.d.
row-bootstrap negative oracle. Block-transition mechanics are established by
deterministic tests and mutations. The frozen study-time sensitivity at block
lengths 1, 5, 10, and 20 is the mitigation for unverified cross-session
dependence; Phase 5 makes no empirical claim about which block length captures
MNQ dependence.

- No Phase 5 bootstrap primitive has been applied to MNQ observations. No
  conditional market result, result surface, report, S01A output, confirmation
  result, profitability measure, or trading recommendation was produced.
- The measured synthetic coverage rate does not establish nominal 95% coverage
  on MNQ or any other population. The v2 gate tests consistency with the
  measured synthetic finite-sample behavior only.
- Bootstrap intervals, when eventually used, measure uncertainty within the
  historical mixture. They do not measure uncertainty about future regime
  change, and `weight_ess` corrects no dependence.
- The S01A production bootstrap draw count was not chosen; it requires a
  separate preregistration outside Phase 5.
- The one-shot stochastic counts and arrays cannot be independently reproduced
  without violating the registered entropy and rerun prohibitions. Their
  internal consistency, fixture immutability, provenance, runtimes, and
  surrounding deterministic mechanisms were independently audited instead.
- No unconditional cross-version or cross-environment byte-identity claim is
  made for stochastic output.

## Closeout validation

The safe deterministic closeout commands were:

```powershell
python -m pytest tests --ignore=tests/test_bootstrap_acceptance.py -q
python -m pytest tests/test_bootstrap_properties.py tests/test_bootstrap_weights.py tests/test_bootstrap_interval.py tests/test_bootstrap_replicates.py tests/test_phase5_calibration_preflight.py tests/test_phase5_v2_gate_derivation.py tests/test_spec_consistency.py -q
python -m mnq_lab.spine.gates --store data
python -m mnq_lab.outcomes.completion --store data
python -m mnq_lab.outcomes.s00 --store data
python -m mnq_lab.outcomes.s00 --store data
```

The frozen specification remained SHA-256
`70dae16c8b12fe26d38a7bfdabf0202066fe7149f790d0d2942279d9c3b8ff50`.
The frozen YAML remained SHA-256
`1c95aa595c30c48b853303291a7dbaabceaf5b7331bca565a30863e8dcf138d4`.
The Phase 5 preregistration remained SHA-256
`22b82e3aef8a8dfb1410e3ad4ab5781fcef343371de3f156ec678c19d2a5b87c`.
The v2 preregistration remained SHA-256
`37c94a1e9bae9f406dfac7e374cc9edacb5231ac2710f2baeecf1ce4a5b189ec`.
The calibration runner remained SHA-256
`f383ae3268772e522ee9e4b0ba1e6df6c900749e27042badcf8d86a154cddef1`.
Amendment 1 remained SHA-256
`8c2af57b3da0939c5ba057d788500624c2a5dacc4577e4bafb3f6ae2a48df886`.
The acceptance fixture remained SHA-256
`bb239fc97f7823544a3c39748e808a42f0e529c28f9074736f7ce8f7a41da71c`.

## Audit status

Independent audits of the implementation and stochastic evidence ultimately
returned `CLOSED`. The v2 derivation audit at `588f3eb` first returned `OPEN`
for two guard-hygiene defects: a tautological partition assertion and
unguarded permanent-record tail formulas. Both were corrected at `2c709aa`,
whose re-audit returned `CLOSED`. This document was prepared from clean parent
commit `b3009a23db89cdd8c61775fb7183df79e8d29e60` and is the artifact submitted
for the final independent Phase 5 closeout audit. Phase 6 and S01A remain out
of scope until that audit returns `CLOSED`.
