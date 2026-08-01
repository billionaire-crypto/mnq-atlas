# Phase 6 — dependency locality and conditioner registries

Phase 6 implements the market-free dependency-locality admission infrastructure
required by frozen specification §13 test 6 and §15 row 6. It provides generic
dependency-window declarations, deterministic adversarial mutations,
independently specified witnesses, and separate causal and descriptive
conditioner registration. It does not implement a real conditioner, calculate a
market result, consume confirmation or forward data, or begin Phase 7.

The executable contract was preregistered before production implementation in
`docs/PHASE6_PREREGISTRATION.md`. Its 12,079 raw bytes are pinned at SHA-256
`e800e446ecd23fdb416c499603d086c50b1754c99106279284e3277a33b4ccb9`.
The permanent contract and implementation audit history, including every
`OPEN` verdict, remains recorded in `docs/DISCREPANCIES.md` D17 and D18.

## Implemented contract

The generic Phase 6 boundary is split between
`mnq_lab/core/dependency.py` and `mnq_lab/conditioners/registry.py`.

### Dependency locality

- `DependencyInputs` fixes an immutable, strictly increasing event-time
  coordinate vector, an immutable boolean allowed-dependency mask, and aligned
  immutable value arrays. Both an all-allowed mask and an all-forbidden mask
  fail closed.
- `run_dependency_locality` holds coordinates and window membership fixed while
  mutating values in every contiguous forbidden region, separately for every
  named input. Each counted trial must change at least one value and may change
  nothing outside the selected region.
- Every run begins with the preregistered ordinary software-test generator
  `Generator(PCG64(0))`. Deterministic zero and finite dtype-minimum/maximum
  landmarks supplement that original mutation. The landmarks add coverage for
  far-threshold dependencies without replacing or consuming the generator.
- Exact tick, integer-category, and boolean output requires shape, dtype, and
  byte identity. Floating output first requires exact shape and dtype and then
  applies the declared finite nonnegative rule
  `abs(actual - expected) <= atol + rtol * abs(expected)`.
- Supplied arrays are backed by immutable bytes, snapshotted around invocation,
  and reconstructed for repeated identical calls. Direct input mutation,
  malformed declarations, nondeterministic output, missing output, wrong
  shape/dtype, and disallowed non-finite output fail closed.
- `run_deterministic_witness` requires a hand-built in-window change, an
  independently specified baseline response, an independently specified changed
  response, and a required affected output element. Exact witnesses must change
  that element. Floating witnesses must make the two closed tolerance bands
  disjoint:

  ```text
  abs(E_changed - E_baseline)
      > (atol + rtol * abs(E_changed))
      + (atol + rtol * abs(E_baseline))
  ```

  The callable is asserted against both responses. A constant or insensitive
  callable therefore cannot satisfy a valid witness at the affected element.
- Comparison failures carry structured check and failure identities. Registry
  evidence dispatch does not parse caller-controlled exception prose.

### Registries

- `ConditionerRegistry` owns one shared identifier namespace for causal and
  descriptive entries. Duplicate identifiers, callable aliases, overwrites,
  unregistering, downgrades, and reclassification fail closed or have no API.
  A distinct wrapper has a distinct identity and requires its own executed
  suite.
- Metadata and returned descriptors are deeply immutable. Iteration preserves
  insertion order and is never sorted by measured output.
- `register_causal_conditioner` has one admission path. Its insertion choke
  point validates nonempty locality cases, witnesses, and both required
  negative-control families; verifies exact callable and witness linkage;
  executes every declaration inside the registration call; and inserts
  atomically only after all checks pass. A failure leaves the registry
  unchanged.
- No caller-supplied boolean, string, token, report, cached result, serialized
  object, dataclass, duck-typed certificate, or alternate method can substitute
  for the in-call execution. Direct access to the name-mangled insertion method
  reaches the same validation choke point.
- Causal descriptors carry the permanent label
  `CAUSAL — EMPIRICAL ADMISSION EVIDENCE, NOT PROOF OF CAUSALITY`.
- `register_descriptive_conditioner` requires no causal-locality evidence, but
  its entries are permanently labelled
  `NONCAUSAL — NOT ELIGIBLE FOR CONFIRMATION`. The one eligibility query returns
  true only for a stored causal entry; no override, alias, metadata edit, or
  re-registration promotes a descriptive entry.

## Measured

- The final safe deterministic suite, with
  `tests/test_bootstrap_acceptance.py` excluded as a whole, produced
  `750 passed, 5 xfailed` in 26.75 seconds. The five expected failures remain
  exactly the deferred prefix-invariance targets for seasonal profiles, tercile
  thresholds, conditioner assignments, prevalence results, and consumed
  vintage artifacts.
- The Stage E checkpoint produced `11 passed` for the integrated gate,
  `135 passed` for the dependency/registry/gate set, `208 passed` for the
  seven-module focused set, and `750 passed, 5 xfailed` for the safe suite,
  with no warnings under `-W error`, skips, or deselections.
- The signed-off spine CLI passed all four fail-closed gates:
  roll-list equality with 28 rolls; five-minute equality over 211,968 rows;
  symbol classification with source hash and per-symbol counts verified; and
  roll causality over 1,009 sessions and 28 rolls, including detection of the
  registered same-day-volume defect fixture.
- The completion CLI reproduced 1,009 exploration sessions and 78,702
  gridpoints.
- The S00 artifact measured before and after its authorized deterministic CLI
  replay was exactly 7,636 bytes with SHA-256
  `725df33a00e53c6c356c4348df2a02fe9ed309d9d4e4118216894a70ef8a479d`.
- Tests and independent adversarial probes established the inclusive
  conditioner boundary at `tau`, exclusion at `tau + 1 ns`, gapped-coordinate
  behavior, separate companion-input mutation, every-forbidden-region coverage,
  non-no-op trials, exact and floating comparisons, two-band witness
  separation, immutable input and metadata boundaries, atomic insertion,
  insertion-order iteration, permanent descriptive ineligibility, and
  structured negative-control identities.
- The Stage E mutation battery killed all eleven declared mutants in a
  disposable source-only copy: landmark removal, all-true mask admission,
  ignored exact mismatches, vacuous exact witness admission, arbitrary
  `SpineError` as evidence, bypassed suite validation, descriptive eligibility,
  duplicate overwrite, a market-store path in the registry, shape mismatch as
  comparison evidence, and restoration of the one-band floating-witness rule.
  The pristine dependency/registry/gate set produced `135 passed` before and
  after the battery.
- Landmark trials killed the planted integer dependency
  `bool(x[2] > -1_000_000_000)` and the planted floating dependency
  `bool(x[2] > 1e300)`. Removing the landmarks made those two integrated tests
  fail, demonstrating that the strengthening is load-bearing.
- A scoped Phase 6 path and history scan found no real conditioner, volatility
  estimator, seasonal profile, MAD calculation, tercile assignment, state
  validity implementation, contrast, prevalence result, null, report, S01A
  output, confirmation result, or forward-vintage artifact.

## Inferred

- The locality reports provide empirical evidence that a callable's output is
  invariant to the declared deterministic mutations outside its declared
  window. The witness reports provide empirical evidence that the same callable
  responds as independently expected to at least one declared in-window change.
  Together, the matched pair rejects the planted constant, insensitive,
  wrong-direction, future-read, and far-threshold defect classes exercised by
  the suite.
- Requiring registration to execute the complete suite at the insertion choke
  point makes stored causal eligibility depend on the validated path throughout
  the Phase 6 API surface. Structured failure identities prevent caller-owned
  names and exception text from being mistaken for the required comparison
  failure families.
- The strict two-band rule makes wider floating tolerances harder, rather than
  easier, to use for witness admission: widening either band raises the required
  independent separation.
- The shared immutable namespace and single eligibility query preserve the
  causal/descriptive classification made at registration and prevent a
  descriptive entry from silently acquiring confirmation eligibility.
- Keeping generic arrays, masks, coordinates, comparison rules, and mutation
  mechanics in `core/`, while keeping registry lifecycle mechanics in
  `conditioners/`, preserves the intended market-free responsibility boundary.

## Not verified

- Causal registration is empirical admission evidence against the declared
  cases, witnesses, controls, and finite mutation schedule. It is not proof of
  causality, purity, or absence of every undeclared dependency.
- Hidden-RNG, module-global, corpus-length, and undeclared-companion behavior is
  covered only where planted controls exercise those defect classes. The
  repeated-call and immutability mechanisms do not prove their universal
  absence.
- The finite mutation schedule cannot reach every possible trigger. In
  particular, it cannot guarantee discovery of an arbitrary interior-equality
  dependency such as `int(x[2] == 12345)` when none of the deterministic trials
  sets that forbidden element to the trigger value. Zero and dtype extrema
  strengthen coverage but do not convert a finite test battery into proof.
- Phase 6 verifies locality relative to the window a callable declares. It does
  not establish that a future real conditioner's declared window is
  semantically correct or minimally sufficient. That review, including an
  over-wide declaration mutation tied to real conditioner semantics, remains a
  Phase 7 obligation.
- No actual volatility conditioner, EWMA, seasonal profile, MAD estimator,
  tercile assignment, or state-validity calculation exists. No Phase 6
  primitive has been applied to MNQ observations to create a conditional market
  result.
- No confirmation result, forward vintage, contrast, prevalence estimate,
  null, report, or S01A output was produced or consumed. Phase 6 provides no
  profitability, P&L, expectancy, Sharpe, strategy, or trading conclusion.
- The authorized closeout spine, completion, and S00 CLIs verify unchanged
  earlier-phase deterministic artifacts. Their success is not evidence about a
  real conditioner's scientific correctness.

## Closeout validation

The Stage F commands were:

```powershell
python -m pytest tests --ignore=tests/test_bootstrap_acceptance.py -q
python -m mnq_lab.spine.gates --store data
python -m mnq_lab.outcomes.completion --store data
python -m mnq_lab.outcomes.s00 --store data
```

The following protected raw-byte hashes remained unchanged:

```text
docs/PHASE6_PREREGISTRATION.md
e800e446ecd23fdb416c499603d086c50b1754c99106279284e3277a33b4ccb9

docs/PHASE6_HANDOFF.md
bd8f8263587c5b8abb5759b55dec993874b487d682798aa31c1ac1fac755c5dd

docs/DISCREPANCIES.md
f5efc22dde471d522d22d7ecf7d15963746fdff3b1d6b39e105ec04791de5faa

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

docs/PHASE5.md
27093df7e9dbfda66d9abbe8a5fbb77a3de47fc94779116fc4a9f5cb0faf9b3d
```

The acceptance fixture was hashed as raw bytes only. It was not imported,
collected, or executed. No registered Phase 5 entropy was referenced or
instantiated; no Phase 5 calibration, coverage, or AR(1) fixture was rerun. The
locked confirmation directory was not manually read, imported, enumerated,
hashed, or mapped. The existing canonical store was not rebuilt.

## Audit status

- The original handoff contract audit at `8e68095` returned `OPEN`. Its first
  correction at `a51c35c` also returned `OPEN` because the floating witness left
  overlapping comparison bands. Commit `77af37e` required both baseline and
  changed assertions and strict two-band separation; its audit returned
  `CLOSED` and `CONTRACT: RATIFIED`.
- The preregistration at `533ee91` returned `CLOSED` and
  `PREREGISTRATION: RATIFIED`; its byte pin at `9a61acc` returned `CLOSED`.
- The Stage C harness and witness checkpoint through `48920967` returned
  `CLOSED`.
- The Stage D registry checkpoint through `4a3db01` returned `OPEN` for
  caller-controlled prose recognition and a zero-evidence insertion bypass.
  Commit `fe47f8e` replaced prose dispatch with structured identities and moved
  validation into the insertion choke point. Its focused re-audit returned
  `CLOSED`.
- The integrated Stage E gate at `8118a9c` returned `CLOSED` after independent
  reproduction of the eleven-mutant battery. That verdict authorized this
  Stage F closeout only.

This document is the sole Stage F repository change submitted for the final
independent Phase 6 audit. Phase 6 is not finally closed until that audit
returns `CLOSED`. Phase 7 and S01A remain unauthorized and have not begun.
