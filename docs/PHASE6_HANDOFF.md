# Phase 6 handoff — dependency locality and conditioner registries

This is the continuity document for the Codex implementation session after
Phase 5. It explains the current repository, how the atlas is intended to work,
the exact Phase 6 boundary, and the independent-audit procedure used throughout
the project.

Phase 5 implementation and every registered stochastic execution are complete.
The closeout document was corrected at commit
`fef5b165241f48681630f959232ecdaa6e41dc5f` to record honestly that the v2
derivation audit first returned `OPEN` before its guard defects were fixed.
That one-sentence correction still requires a final independent `CLOSED`
re-audit. Preparing and reviewing this handoff is permitted, but **Phase 6
production implementation must not begin until that verdict is CLOSED**.

Frozen spec §15 row 6 defines Phase 6 as:

```text
Dependency-window harness + witness fixtures + registries
Gate: §13 test 6, test_dependency_locality
```

Phase 6 is infrastructure for later conditioners. It is **not** the volatility
conditioner, seasonal estimator, tercile assignment, state-validity panel, or a
market study; those begin in Phase 7. It must not compute an S01A result.

## 1. Roles and working agreement

- **User:** owns scientific rulings, repository-visibility decisions, and any
  authorization that changes frozen or externally visible state.
- **Codex:** developer. It inspects, plans, implements, tests, documents, and
  fixes one bounded unit at a time.
- **Claude Code / Opus:** independent quant and adversarial auditor. It reviews
  committed artifacts in a separate session and returns `CLOSED` or `OPEN`.
- A second auditor is an escalation path for a genuinely unresolved scientific
  ambiguity or high-risk disagreement, not a routine extra vote.

Developer-authored code, tests, fixtures, prose, and command output are claims,
not independent evidence. The auditor must verify them. Auditor mutations run
only in a disposable clone or against in-memory copies; never mutate the live
working repository to demonstrate that a test can fail.

After every Atlas coding task, plan, fix, or evidence-recording step, Codex must
give the user a ready-to-paste Claude Code audit prompt as a literal four-space
indented block. Do not use a fenced code block. The prompt must state:

1. repository, branch, exact commit, and expected parent;
2. exactly what Codex changed and why;
3. authorized paths and expected diff size or shape;
4. the scientific and implementation claims to test;
5. safe commands and expected results;
6. protected artifacts and hashes;
7. explicit prohibitions, including data and one-shot restrictions;
8. the required `VERDICT: CLOSED` / `VERDICT: OPEN` response format; and
9. a final `STOP` instruction preventing the auditor from fixing findings.

When an audit returns `OPEN`, Codex fixes only the verified findings in a new,
small commit, preserves the failed audit in the history, and supplies a focused
re-audit prompt. Never erase an `OPEN`, failed experiment, or failed launch from
the permanent account. When an audit returns `CLOSED`, only the next explicitly
sequenced stage is authorized.

## 2. Immutable starting state

Repository continuity before this handoff commit:

```text
repository                 C:\mnq-atlas
branch                     phase-5-bootstrap
Phase 5 closeout fix       fef5b165241f48681630f959232ecdaa6e41dc5f
next branch                phase-6-dependency
worktree                   clean
```

The next Codex session must branch from the exact handoff tip reported in the
user-facing prompt accompanying this document, not from a remote-tracking ref
and not directly from `fef5b16` if this handoff commit follows it.

Remote state is an explicit operational caveat:

- `origin` is `https://github.com/billionaire-crypto/mnq-atlas.git`.
- The GitHub repository is public.
- Only the Phase 1 and Phase 2 branch names were anonymously visible when this
  handoff was written.
- Phase 3, 4, and 5 remain local-only and unpushed.
- The user deliberately declined a visibility change or backup push for now.

Do not change repository visibility, add a remote, push a branch, create a PR,
or otherwise revisit that decision without new explicit user authorization.
The absence of a remote backup is a known operational risk, especially because
the Phase 5 one-shot evidence cannot be regenerated, but it is not permission
to perform an external write.

Local phase refs before this handoff commit:

```text
phase-1-spine       de73fa4e64ee23c84d6c16c8f5b32329ee173cad
phase-2-time-model  ec826925b77dac86a5bc44a7dd9af632486c329e
phase-3-s00         fd34a433cc672d6c857432b2415f92269585c016
phase-4-kernel      a155ae58498b37dbbce195dfa8820e6fc073b8be
phase-5-bootstrap   fef5b165241f48681630f959232ecdaa6e41dc5f
```

Starting deterministic replay:

```powershell
git status --short --branch
git log -12 --oneline
python -m pytest tests --ignore=tests/test_bootstrap_acceptance.py -q
python -m mnq_lab.spine.gates --store data
python -m mnq_lab.outcomes.completion --store data
python -m mnq_lab.outcomes.s00 --store data
```

Expected baseline:

```text
safe tests               614 passed, 5 xfailed
Phase 1 gates            4/4 pass
exploration sessions     1,009
completion gridpoints    78,702
S00 artifact bytes       7,636
S00 artifact sha256      725df33a00e53c6c356c4348df2a02fe9ed309d9d4e4118216894a70ef8a479d
```

Never run bare `python -m pytest tests -q`. The acceptance module contains
spent one-shot fixtures. It must be excluded as a whole with:

```text
--ignore=tests/test_bootstrap_acceptance.py
```

The signed-off spine gate command retains its narrowly audited access boundary.
Do not manually inspect, import, enumerate, hash, or mmap
`data/locked_confirmation/`. Do not rebuild or replace canonical `data/`.

## 3. Protected artifacts

These bytes must remain unchanged unless a future task supplies explicit user
authorization under the applicable ledger or amendment procedure:

```text
REV6_FROZEN_SPEC.md
70dae16c8b12fe26d38a7bfdabf0202066fe7149f790d0d2942279d9c3b8ff50

analysis_constants_v1.yaml
1c95aa595c30c48b853303291a7dbaabceaf5b7331bca565a30863e8dcf138d4

docs/PHASE5_PREREGISTRATION.md
22b82e3aef8a8dfb1410e3ad4ab5781fcef343371de3f156ec678c19d2a5b87c

docs/PHASE5_PREREGISTRATION_V2.md
37c94a1e9bae9f406dfac7e374cc9edacb5231ac2710f2baeecf1ce4a5b189ec

tools/phase5_coverage_calibration.py
f383ae3268772e522ee9e4b0ba1e6df6c900749e27042badcf8d86a154cddef1

docs/PHASE5_PREREGISTRATION_V2_AMENDMENT_1.md
8c2af57b3da0939c5ba057d788500624c2a5dacc4577e4bafb3f6ae2a48df886

tests/test_bootstrap_acceptance.py
bb239fc97f7823544a3c39748e808a42f0e529c28f9074736f7ce8f7a41da71c

docs/PHASE5.md at fef5b16
27093df7e9dbfda66d9abbe8a5fbb77a3de47fc94779116fc4a9f5cb0faf9b3d
```

The sealed exploration artifact remains:

```text
data/exploration/s00/s00_threshold_input_v1.json
bytes    7,636
sha256   725df33a00e53c6c356c4348df2a02fe9ed309d9d4e4118216894a70ef8a479d
```

The store manifest's historical YAML hash differs intentionally from the
current threshold-bearing YAML hash. Never rewrite the manifest to make the
hashes agree. Follow `docs/SEALED_STORE_REBUILD.md` if the preserved store is
missing or its provenance is questioned.

## 4. How the atlas works

The project is a measurement instrument, not a strategy search.

```text
raw Databento one-minute bars
        |
        v
causal active-contract selection and resampling
        |
        v
sealed .npy BarStore + manifests + four fail-closed gates
        |
        v
event-time masks, session phases, and completion accounting
        |
        v
S00 completion atlas and frozen horizon thresholds
        |
        v
market-free weights, inverse-CDF statistics, and weight_ess
        |
        v
whole-session bootstrap plans and percentile intervals
        |
        v
Phase 6 dependency-locality admission infrastructure
        |
        v
later conditioners, contrasts, prevalence, nulls, and S01A reports
```

The responsibility boundary is binding:

```text
core/          arrays, values, weights, timestamps, masks; no market meaning
spine/         source construction, sealing, stores, and fail-closed gates
conditioners/  market mechanics for state inputs; no study selection
outcomes/      market mechanics for future paths; no study selection
studies/       declarative configuration only
report/        consumes frozen tidy result frames only
ledger/        immutable decisions, thresholds, and later provenance
```

Production or execution code must not import this research package. `core/`
must not import or name market-aware layers, YAML, ledger, stores, MNQ, RTH,
holidays, profitability, or the locked tier.

The event-time rule is foundational:

```text
At observation time tau, a conditioner may use every return whose ending
timestamp is <= tau and none ending after tau. An outcome uses only the path
strictly after tau.
```

`ts_event` is a bar-open label. For a five-minute bar, observation occurs at
`ts_event + 5 minutes`. The anchor bar's return is available to a conditioner;
the anchor bar's high and low are already known and must not enter its future
excursion. A positional `shift()` may implement a case but is never the rule.

Data and inference discipline:

- Exploration: 2019-05-05 through 2023-03-29; free for exploration work.
- Locked confirmation: 2023-03-30 through 2026-03-29; not available to the
  exploration runtime and already contaminated by prior work.
- Forward vintages: the only untouched future evidence.
- Every declared cell must eventually be emitted, including unsupported cells,
  with an explicit status.
- Never rank cells by profitability, search for a best parameter, compute P&L,
  expectancy, Sharpe, or issue a trading recommendation.
- `n_anchors` is never rendered without `n_sessions` and `weight_ess`.
- `weight_ess` measures weight concentration only and corrects no dependence.
- Bootstrap intervals measure uncertainty within the historical mixture, not
  uncertainty about future regime change.

## 5. What is signed off through Phase 5

### Phase 1 — spine

- Deterministic `.npy` BarStore and manifests.
- Causal active-contract chain and exact 28-roll fixture.
- One-minute component coverage carried into five-minute bars.
- Four fail-closed gates: roll list, five-minute oracle equality, symbol
  classification, and roll causality.
- Physical exploration/confirmation separation.

### Phase 2 — time model and completion

- UTC-nanosecond event-time primitives.
- Observation time equals bar-open label plus bar duration.
- RTH phase assignment is keyed on observation time.
- Conditioner input includes the anchor return ending at `tau`; outcome paths
  exclude the anchor interval.
- Complete clock-window and dual path-presence accounting.
- Honest session flags without an unverified holiday classification.

### Phase 3 — S00 freeze

- S00 completion artifact over 1,009 exploration sessions and 78,702 points.
- Horizon thresholds frozen ledger-before-YAML:

  ```text
  h15 = 0.99
  h30 = 0.99
  h60 = 0.98
  ```

- No-default threshold loading and immutable ledger provenance.

### Phase 4 — weighted statistics

- Discrete inverse-CDF `weighted_quantile` and `weighted_quantiles`.
- No default linear interpolation, tolerance repair, or silent filtering.
- Session-equal and anchor-equal weight constructors.
- `weight_ess` and group-mass concentration diagnostics.
- Market-free `core/` boundary.

### Phase 5 — bootstrap

- Immutable whole-group stationary resample plans.
- Exactly the original group count selected, with no row slicing.
- One global plan shared across aligned values and masks.
- Integer group multiplicities composed with Phase 4 baseline weights.
- Minimum 999-draw, discrete percentile intervals through the Phase 4 path.
- Explicit `numpy.random.Generator` boundary with no hidden seed.
- Frozen block sensitivities `[1, 5, 10, 20]`.
- v1 synthetic coverage permanently failed: `267/300` against `[277, 292]`.
- Calibration measured `2771/3000`, approximately 92.37%, below nominal 95%.
- Exact v2 region `[268, 286]`; fresh v2 result `283/300`, passed as
  consistency with measured behavior, not nominal calibration.
- AR(1) discriminator passed with lower median width ratio
  `2.1683133477836822` and 24 of 24 directional wins.
- All four registered Phase 5 stochastic entropies are spent. No Phase 5
  stochastic fixture or calibration may ever be rerun.

The Phase 5 acceptance fixtures do not validate chronological cross-session
dependence or identify an empirically correct block length for MNQ. That
limitation carries into all later work.

## 6. Read in this order

The next Codex session must read each selected source completely before coding:

1. This handoff.
2. `CLAUDE.md`.
3. `REV6_FROZEN_SPEC.md` §14 (STRUCK) before any other design work.
4. Frozen spec §4.1, §11, §13 test 6, §15 rows 5–7, and §16.3–§16.7.
5. `analysis_constants_v1.yaml`.
6. `docs/PHASE5.md` and the complete append-only
   `docs/PHASE5_ACCEPTANCE_RECORD.md`.
7. Both Phase 5 preregistrations and Amendment 1.
8. `docs/PHASE5_HANDOFF.md`, especially its audit and mutation discipline.
9. `docs/DISCREPANCIES.md`, including D13–D16.
10. `docs/SEALED_STORE_REBUILD.md`.
11. `mnq_lab/core/causality.py` and all of
    `tests/test_event_time_conditioner.py`.
12. `tests/test_prefix_invariance.py`, especially the deferred Phase 7, 9, and
    11 targets.
13. `tests/test_no_selection.py`, `tests/test_seal_guard.py`, and
    `tests/test_spec_consistency.py`.

Older revisions, chat summaries, skill baselines for other trading systems, and
external snippets are not authoritative over the frozen spec, recorded user
rulings, immutable ledgers, and closed phase contracts.

## 7. Exact Phase 6 scope

Minimum deliverables, subject to independent ratification before production
code:

1. A generic dependency-window declaration that describes which input
   observations a callable is allowed to depend on for a specified output.
2. A deterministic harness that establishes locality by mutating data outside
   that declared window and comparing the output under the appropriate policy.
3. A deterministic witness fixture per admitted callable proving that a
   deliberately chosen in-window change produces the exact expected response.
4. Exact comparison for tick-valued, integer-category, and boolean-mask output.
5. An explicit, finite, nonnegative, function-specific tolerance only where a
   floating estimator mathematically requires it. No tolerance applies to
   integer or boolean output, and no tolerance may repair a wrong boundary.
6. A causal-conditioner registry whose admission requires the declared
   adversarial locality suite to succeed.
7. A descriptive-conditioner registry whose entries are permanently marked
   `NONCAUSAL — NOT ELIGIBLE FOR CONFIRMATION`.
8. An interface ensuring that only causal-registry entries can later serve
   confirmation or forward studies.
9. Negative tests and adversarial mutations proving each mechanism can fail.
10. A Phase 6 preregistration/contract document committed before production
    implementation, plus a Phase 6 closeout document separating measured,
    inferred, and not verified.

Likely files, only if the ratified API justifies them:

```text
docs/PHASE6_PREREGISTRATION.md
mnq_lab/core/dependency.py
mnq_lab/conditioners/__init__.py
mnq_lab/conditioners/registry.py
tests/test_dependency_locality.py
tests/test_conditioner_registry.py
docs/PHASE6.md
```

These names are proposals, not authorization to create architecture for its own
sake. A smaller boundary is preferred if it fully satisfies the contract.

Phase 6 must not implement:

- EWMA RMS, seasonal profiles, MAD sensitivity, tercile thresholds, or actual
  conditioner assignments;
- state validity, prevalence, contrasts, positivity, outcomes, nulls, report
  surfaces, hypothesis selection, or S01A;
- market-store loading or any inspection of MNQ values;
- confirmation or forward-vintage consumption;
- a claim that registry admission proves causality. Passing the suite is
  empirical evidence against the declared adversarial cases, not a proof.

## 8. Mandatory preflight questions for Claude Code

Frozen text does not fully specify the executable admission mechanism. Before
production code, Claude Code must ratify or reject a complete proposal covering
all of the following:

1. **Window representation:** event-time bounds, an explicit allowed-dependency
   mask, or another exact form. A positional row offset alone is insufficient on
   gapped or irregular data.
2. **Coordinates versus values:** which arrays define window membership and
   which arrays may be mutated without accidentally moving observations across
   the boundary.
3. **Out-of-window mutation:** fixed seed, mutation count, distribution, and a
   guard proving that the mutation actually changed at least one forbidden
   input. A no-op mutation cannot count as evidence.
4. **Witness semantics:** a hand-built in-window change targeted to a value that
   must affect the result, with an independently written exact expectation. A
   random change and a bare `output != baseline` assertion are insufficient.
5. **Comparison policy:** bit identity for ticks, integer categories, and masks;
   explicit tolerance rules for floating estimators; shape, dtype, NaN, signed
   zero, and scalar/array treatment.
6. **Purity and mutation:** whether the harness detects callable mutation of
   caller arrays, dependence on module globals, hidden RNG, corpus length, or
   undeclared companion inputs.
7. **Admission evidence:** how `register_causal_conditioner` can require a
   successfully executed suite without accepting a self-attested boolean or a
   forgeable “passed” token.
8. **Registry lifecycle:** unique identifiers, duplicates, overwrite behavior,
   ordering, immutability, unregister/downgrade behavior, and metadata returned
   to future consumers.
9. **Descriptive permanence:** how the noncausal label survives retrieval and
   prevents confirmation/forward eligibility without being merely decorative.
10. **Test-only versus production boundary:** which harness components belong
    in `core/`, the conditioner registry, or tests, while keeping `core/`
    market-free.
11. **Prefix invariance:** what Phase 6 can test generically now and what remains
    deferred until actual Phase 7 conditioner assignments exist.
12. **No new randomness contract:** whether deterministic test randomness needs
    a fixed ordinary test seed, and confirmation that it is not a scientific
    one-shot or registered study entropy.

If these questions cannot be answered uniquely from frozen text, record a new
entry in `docs/DISCREPANCIES.md` and obtain a user ruling. Do not select the API
that is easiest to test.

## 9. Proposed ratification contract

The first Claude Code session should review this proposal rather than writing
code:

```text
Does frozen spec §13 test 6, §11, and §15 row 6 authorize the following
Phase 6 executable contract?

BOUNDARY
1. Phase 6 provides only a market-free dependency-locality harness, synthetic
   witness fixtures, and causal/descriptive registry mechanics. Actual market
   conditioners and state assignments remain Phase 7. The generic declaration,
   comparison, and harness primitives belong in `core/`; registry mechanics
   belong in `conditioners/`; deterministic witness callables remain test-only.
2. A dependency case supplies immutable baseline inputs, immutable dependency
   coordinates, a declared allowed-dependency mask for the requested output,
   and an explicit callable invocation. Shapes align and inputs are never
   silently coerced, truncated, filtered, or mutated.
3. Dependency coordinates determine membership. Out-of-window mutation changes
   values only and cannot alter coordinates or mask membership.

LOCALITY
4. A fixed ordinary test-only `Generator(PCG64(0))` mutates every declared
   out-of-window region through a non-no-op mutation whose changed indices are
   verified. Seed 0 is an ordinary deterministic software-test seed, not
   scientific entropy, a one-shot seed, or a registered Phase 5 entropy.
5. The baseline and out-of-window-mutated calls must compare bit-identically
   for ticks, integer categories, and boolean masks. Floating estimators use
   only function-specific finite nonnegative absolute and relative tolerances
   fixed in immutable registration metadata. Floating comparison is elementwise
   `abs(actual - expected) <= atol + rtol * abs(expected)` after exact shape and
   dtype agreement. Undeclared, negative, NaN, infinite, or categorical-output
   tolerances fail closed and no tolerance may repair a wrong time boundary.
6. Missing outputs, changed shapes or dtypes, non-finite values not explicitly
   allowed by the contract, input mutation, or a no-op adversarial mutation fail
   closed. The harness makes supplied arrays read-only, preserves exact pre-call
   snapshots, and repeats identical invocations on fresh inputs to detect direct
   caller-array mutation and nondeterministic output. Planted hidden-RNG,
   module-global, corpus-length, and undeclared-companion dependencies must be
   killed where declared adversarial controls expose them; this is empirical
   coverage of those cases, not a general proof that no hidden dependency exists.

WITNESS
7. Every causal admission carries at least one deterministic hand-built witness
   whose selected in-window change and expected output are specified
   independently of the implementation under test.
8. The witness must produce the exact expected response. “Different from
   baseline” alone is not enough, and random in-window mutation is not a
   substitute for a witness. For floating output, the independently specified
   expected changed response must differ from the independently specified
   baseline response, at least at one required affected output element, by
   strictly more than `atol + rtol * abs(expected_changed)`. A floating witness
   that does not clear that separation is vacuous and fails before admission.
9. Every test includes a negative mutation proving the locality comparison or
   witness assertion can fail.

REGISTRIES
10. Causal and descriptive entries share one identifier namespace and expose
    immutable metadata. Every duplicate identifier fails closed, including an
    otherwise identical repeat; no overwrite, unregister, downgrade, or
    reclassification exists. The same callable object cannot be registered under
    an alias or in the other registry; a distinct wrapper is a distinct callable
    requiring its own identity and, for causal admission, its own executed suite.
    Retrieval cannot mutate stored state, and iteration preserves insertion order
    rather than sorting by any measured output.
11. `register_causal_conditioner` has exactly one admission path: it executes
    the complete declared locality cases, deterministic witnesses, and required
    negative controls inside the registration call, validates all evidence, and
    only then atomically inserts the immutable entry. No caller-supplied boolean,
    string, token, dataclass, protocol or duck-typed object, serialized or cached
    result, prior-run result, alternate constructor, or other certificate can
    cause admission. Failure leaves the registry unchanged. No alternate causal
    admission mechanism exists in Phase 6.
12. register_descriptive_conditioner does not require causal-locality evidence,
    but every returned descriptor is permanently labelled
    NONCAUSAL — NOT ELIGIBLE FOR CONFIRMATION.
13. A single eligibility query used by future confirmation/forward code returns
    true only for causal entries. Descriptive entries cannot opt in through an
    argument, alias, metadata edit, or re-registration under the same identity.
14. Passing the causal suite is described as empirical admission evidence, not
    proof of causality.

SCOPE
15. No registry or harness reads a store, names the locked tier, imports study
    or report modules, creates a market result, or consumes scientific entropy.
16. No Phase 7 conditioner, Phase 8 contrast, Phase 9 prevalence result, Phase
    10 null, Phase 11 vintage, Phase 12 S01A output, or trading strategy is
    implemented.

The design-latitude resolutions in items 1–6 and 10–11 are recorded in
`docs/DISCREPANCIES.md` D17 and must be incorporated unchanged into the audited
`docs/PHASE6_PREREGISTRATION.md` before production implementation. Phase 6 can
test a declared window but cannot prove that a future real conditioner declared
the semantically correct, minimally sufficient window; over-wide declaration
review remains an explicit Phase 7 obligation.

For every item, return RATIFIED, AMEND, or UNRESOLVED with exact frozen-text
basis. Identify every ambiguity requiring a user ruling. Do not implement or
modify the repository during this review.
```

Claude may amend this proposal. Codex must record the final ratified contract
before implementation and must not treat this draft as already authorized.

## 10. Required implementation sequence

### Stage A — close Phase 5 and establish the branch

1. Obtain a final independent `CLOSED` verdict for the Phase 5 closeout
   correction and this continuity handoff.
2. Verify the exact handoff tip and clean worktree.
3. Replay the safe deterministic baseline; never collect the acceptance module.
4. Verify protected hashes and S00 bytes.
5. Create `phase-6-dependency` from the exact audited handoff tip.
6. Confirm no Phase 6 production, test, or closeout artifacts already exist.

### Stage B — contract ratification

1. Send Claude Code the complete §9 proposal.
2. Resolve every item in §8, especially non-forgeable causal admission.
3. Record a discrepancy and obtain a user ruling for any genuine frozen-text
   ambiguity.
4. Commit `docs/PHASE6_PREREGISTRATION.md` before production code.
5. Independently audit and byte-pin that preregistration if the ratified
   governance requires a permanent pin.

### Stage C — dependency locality harness

1. Implement only the ratified generic boundary.
2. Use synthetic arrays and timestamps; do not open a market store.
3. Implement exact output comparison plus only ratified floating tolerance.
4. Detect no-op mutation, input mutation, malformed masks, and mismatched output.
5. Add deterministic witness infrastructure.
6. Commit the unit and obtain a mutation audit.

### Stage D — registries

1. Implement causal and descriptive registration exactly as ratified.
2. Make identifiers and metadata immutable and collision-safe.
3. Make descriptive non-eligibility permanent and mechanically enforced.
4. Prove causal admission cannot be self-attested or bypassed.
5. Register only synthetic test conditioners; real conditioners remain Phase 7.
6. Commit the unit and obtain a mutation audit.

### Stage E — integrated adversarial gate

1. Implement `test_dependency_locality` with independently written witnesses.
2. Prove out-of-window invariance and in-window sensitivity are both non-vacuous.
3. Exercise exact and floating-output comparison modes.
4. Prove registry eligibility uses the validated admission path.
5. Run the full ratified mutation battery in a disposable clone.
6. Commit and obtain an independent audit.

### Stage F — closeout

1. Run the safe suite excluding the acceptance module.
2. Run all four gates, completion CLI, and S00 CLI as authorized deterministic
   checks; verify the frozen S00 bytes and hashes remain unchanged.
3. Verify no real market result and no Phase 7 artifact exists.
4. Write `docs/PHASE6.md` with separate Measured, Inferred, and Not verified
   sections.
5. Obtain final independent `CLOSED` verdict.
6. Stop before Phase 7.

## 11. Required tests and mutation targets

At minimum, each claim needs a named negative test or adversarial mutation that
proves the guard can fail.

### Dependency declaration and validation

- Empty, multidimensional, length-mismatched, non-boolean, object, or mutable
  dependency masks fail closed.
- Coordinates and value arrays must align exactly.
- Boundary membership is event-time based where timestamps are involved.
- Ending exactly at `tau` is admitted; ending one nanosecond later is not.
- Gapped and irregular coordinates do not collapse into positional windows.
- Inputs and declared masks are not mutated or aliased.

### Out-of-window locality

- At least one out-of-window value actually changes.
- All declared out-of-window regions are exercised under the ratified schedule.
- A planted future-value read changes output and is caught.
- A planted one-row boundary expansion is caught.
- A callable depending on corpus length, a hidden global, or undeclared
  companion input is caught where the ratified contract claims coverage.
- Exact-output paths require bit identity rather than approximate equality.
- Floating comparison refuses undeclared, negative, infinite, NaN, or overly
  broad tolerance.
- Mutation of coordinates cannot masquerade as a value-locality test.

### Deterministic witnesses

- Each witness changes an input inside the declared window.
- The changed input is one that deterministically affects the result.
- Expected output is written independently, not computed through the callable.
- Median witnesses target the order statistic; category witnesses cross a
  threshold; mask witnesses flip a specified element.
- A witness that changes a non-central median input is rejected as vacuous.
- A witness expecting only inequality rather than an exact result is rejected
  unless the auditor ratifies a narrowly justified exception.
- Planted insensitive and wrong-direction callables are killed.

### Registries

- Causal admission without executed evidence fails.
- A boolean, string, dataclass, or duck-typed fake “passed” certificate fails.
- Missing witness, missing locality case, or failed negative control prevents
  causal admission.
- Descriptive registration always exposes the exact permanent noncausal label.
- Descriptive entries fail confirmation/forward eligibility checks.
- Re-registering a descriptive callable as causal cannot erase its historical
  classification without the ratified new-identity procedure.
- Duplicate identifiers and conflicting metadata fail closed.
- Registry retrieval cannot mutate stored metadata.
- Callable aliases cannot evade identifier or eligibility rules.
- Registry iteration order is deterministic and never sorted by measured output.

### Regression and scope

- Existing event-time, no-selection, seal, weighted-statistics, and bootstrap
  deterministic suites still pass.
- No `core/` module imports market-aware packages, YAML, ledger, or stores.
- No new production module names or opens the locked tier.
- No actual Phase 7 conditioner or state assignment is added.
- No registered Phase 5 entropy appears in new code or tests.
- No bare suite command can accidentally execute a spent one-shot during the
  documented workflow.
- Frozen spec, YAML, S00 artifact, ledger, preregistrations, runner, acceptance
  fixture, and Phase 5 record remain unchanged.

Required adversarial mutations include:

- invert or shift the allowed dependency mask by one row;
- use positional offsets instead of event-time coordinates;
- mutate zero out-of-window observations and still report success;
- mutate only one conveniently insensitive out-of-window element;
- let the callable read one future value;
- compare integer or boolean output with a tolerance;
- set an arbitrarily broad float tolerance;
- accept NaN equality accidentally;
- let the callable mutate its input;
- use random in-window mutation instead of a deterministic witness;
- choose a median witness value that cannot move the median;
- derive expected witness output by calling the implementation itself;
- admit a causal entry from `passed=True` or a forgeable token;
- label a descriptive entry causal on retrieval;
- allow descriptive confirmation eligibility through an override flag;
- silently overwrite an existing registry identity;
- import market/store/study code into `core/`;
- open exploration or locked market data from Phase 6 code;
- implement a real conditioner or begin Phase 7/S01A.

This list is a floor. Claude Code should add mutations wherever a claim is
stronger than the mechanism demonstrated here.

## 12. Prohibitions and stop conditions

Do not:

- begin Phase 6 production code before the Phase 5 closeout re-audit and Phase
  6 contract ratification are both `CLOSED`;
- execute or collect `tests/test_bootstrap_acceptance.py`;
- rerun calibration, v1 coverage, v2 coverage, or AR(1);
- reuse or pass any registered Phase 5 entropy to `SeedSequence`;
- edit the append-only Phase 5 acceptance record;
- alter frozen spec, YAML, S00, ledger, Phase 5 preregistrations, calibration
  runner, or acceptance fixture;
- access `data/locked_confirmation/` outside the already signed-off gate path;
- rebuild canonical `data/`;
- implement actual conditioner values, seasonal profiles, terciles, state
  validity, prevalence, contrasts, nulls, reports, or S01A;
- claim registry admission proves causality;
- use a tolerance on exact categorical output or repair an event-time boundary;
- use hidden randomness, an unrecorded default seed, or stochastic scientific
  evidence in Phase 6;
- rank outputs, search for a profitable cell, compute P&L/expectancy/Sharpe, or
  make a trading recommendation;
- change GitHub visibility or push any ref without new explicit authorization.

Stop and report immediately if:

- the starting commit or worktree differs from the audited handoff;
- the Phase 5 closeout re-audit is not `CLOSED`;
- any safe baseline test or signed-off gate fails;
- a protected hash or S00 artifact changes;
- a locality assertion can pass without changing an out-of-window value;
- an in-window witness can pass without demonstrating the expected response;
- causal admission relies on caller self-attestation;
- the required registry semantics cannot be derived without a user ruling;
- a proposed implementation needs real market data or Phase 7 concepts;
- a required mutation survives;
- any new path reaches the locked tier;
- acceptable behavior would require modifying a closed earlier-phase contract.

## 13. Definition of done

Phase 6 is complete only when:

- Phase 5 closeout has a final independent `CLOSED` verdict.
- The complete executable Phase 6 contract is preregistered and independently
  ratified before production implementation.
- Dependency declarations are exact, validated, and non-positional on irregular
  event-time fixtures.
- Out-of-window mutation is demonstrably non-no-op and leaves permitted outputs
  unchanged under the ratified comparison policy.
- Every causal callable has a deterministic, non-vacuous in-window witness with
  an independent expected result.
- Causal admission cannot be self-attested or bypassed.
- Descriptive entries remain permanently marked noncausal and mechanically
  ineligible for confirmation and forward use.
- Every required mutation is killed by a named test or fail-closed guard.
- Core remains market-free and no market store is opened by Phase 6 code.
- The safe suite and four spine gates pass.
- All protected artifacts and S00 bytes remain unchanged.
- `docs/PHASE6.md` separates measured, inferred, and not verified.
- Final independent Phase 6 audit returns `CLOSED`.
- No Phase 7 conditioner, S01A result, confirmation result, or forward vintage
  has been created or consumed.

## 14. First new-session behavior

The next Codex session must:

1. report branch, exact HEAD, worktree state, and local/remote continuity;
2. confirm the Phase 5 closeout correction and this handoff have a final
   independent `CLOSED` verdict; if not, stop before production code;
3. verify every protected hash and the S00 artifact;
4. replay the safe baseline using the explicit acceptance-module exclusion;
5. run the four signed-off gates and deterministic CLIs only as authorized;
6. read the sources in §6 completely;
7. inspect, but do not implement, the proposed Phase 6 boundary;
8. give the user the §9 Claude Code ratification prompt in a four-space indented
   copyable block;
9. stop until Claude returns `CLOSED`, `RATIFIED`, or identifies a discrepancy
   requiring the user's ruling;
10. only then create `phase-6-dependency` from the exact audited handoff tip.

Do not begin by writing a conditioner. The first Phase 6 deliverable is an
audited executable contract for proving dependency locality without overstating
what the mechanism establishes.
