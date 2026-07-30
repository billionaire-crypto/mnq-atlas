# Phase 5 preregistration v2 — coverage calibration and acceptance

This document replaces **only** the Phase 5 v1 coverage acceptance gate. The
v1 RNG contract, interval convention, 999 bootstrap draws, data-generating
process, one-shot protocol, AR(1) fixture, and every other v1 requirement
remain binding and unmodified.

The v1 coverage gate executed exactly once on 2026-07-30 and permanently
failed with 267/300 against [277, 292]. Its evidence is append-only in
`docs/PHASE5_ACCEPTANCE_RECORD.md`, and D15 records the independent forensic
classification as a preregistered acceptance-design defect rather than an
implementation defect. The v1 coverage fixture and its spent entropy must
never execute again.

This v2 recovery is authorized by the user's 2026-07-30 ruling under the
pre-agreed Amendment P5-2 failure clause: a new explicit user ruling plus
independent audit. No production-code change, frozen-file change, or edit to
`docs/PHASE5_PREREGISTRATION.md` is authorized.

## A. Calibration study

This is explicitly a **CALIBRATION** study, not an acceptance experiment. It
has no pass/fail bar.

The calibration procedure is byte-for-byte the v1 coverage procedure except
for the outer replication count and the new calibration seed schedule:

- 3,000 outer replications;
- 80 sessions per outer replication;
- four identical rows per session;
- one iid standard-Normal value per session, repeated across its four rows;
- true superpopulation median 0;
- one `session_equal_weights` baseline constructed for the aligned frame;
- one all-true eligibility mask;
- weighted median at `q = 0.5`;
- mean block length 5, loaded fail-closed from
  `analysis_constants_v1.yaml`;
- exactly 999 draws through
  `bootstrap_weighted_quantile_replicates`;
- `percentile_interval` at confidence level 0.95;
- inclusive coverage, `lower <= 0 <= upper`;
- no retry, redraw, filtering, early stop, replacement result, or write to
  disk.

The calibration seed is preregistered as:

```text
label:
  mnq-atlas-phase5-preregistration-v2|coverage-calibration
SHA-256:
  d444a74fb17956abd4155c2d118d7925481cc68ec6cdd1736ad6083e6874ddfa
root entropy (first 128 bits, big-endian):
  282152804769136717845935072558193670437
```

The exact schedule is:

```text
SeedSequence(282152804769136717845935072558193670437).spawn(3000)
```

Each outer child calls `spawn(2)` exactly once, yielding `(data, bootstrap)`
children in that order. Each child is instantiated as
`Generator(PCG64(child))`. There is no `default_rng`, fallback seed, global
generator, or additional random consumption.

The calibration output records exactly:

```text
K = number of inclusive covering intervals among 3000
p_hat = K/3000, retained as an exact fraction
```

Its final evidence line is:

```text
PHASE5_COVERAGE_CALIBRATION={"covered": K, "replications": 3000, "p_hat": "K/3000"}
```

The planned calibration has one execution. Expected runtime is approximately
100 minutes, extrapolated from the v1 runtime of 582.39 seconds for 300 outer
replications. A deterministic crash is diagnosed normally because calibration
has no statistical acceptance bar. It is nevertheless never rerun or reseeded
without a new explicit user ruling and independent audit.

## B. Mechanical gate-derivation formula

This formula is frozen before calibration executes. No v2 acceptance bound may
be derived, previewed, estimated, or chosen before the calibration output
exists.

Let the registered calibration result be `K`, and let

```text
p = K/3000
```

be used in exact rational arithmetic. For
`C ~ Binomial(300, p)`, define:

```text
L = the smallest integer c such that P[C <= c] >= 0.025
U = the smallest integer c such that P[C <= c] >= 0.975
```

Every binomial probability, cumulative probability, and comparison is
computed in exact rational arithmetic with `p = K/3000`. There is no
floating-point conversion, discretionary rounding, tolerance, continuity
correction, interpolation, bound widening, or post-result adjustment.

The v2 inclusive acceptance region is exactly:

```text
L <= coverage_count <= U
```

When derived, the record must include `K`, the exact fraction `K/3000`, the
exact resulting `[L, U]`, and the exact lower and upper tail probabilities.
The formula and its inputs may not be changed after calibration for any
reason.

## C. V2 one-shot coverage experiment

The v2 one-shot coverage experiment is identical to the v1 coverage fixture
in every respect except that it uses the v2 coverage entropy and the
mechanically derived inclusive bounds `[L, U]`:

- 300 outer replications;
- 80 sessions per outer replication;
- four identical rows per session;
- iid standard-Normal session values;
- true superpopulation median 0;
- `session_equal_weights` baseline;
- all-true eligibility mask;
- weighted median at `q = 0.5`;
- YAML-loaded primary mean block length 5;
- exactly 999 bootstrap draws;
- `percentile_interval` at confidence level 0.95;
- inclusive coverage, `lower <= 0 <= upper`;
- acceptance if and only if `L <= coverage_count <= U`.

The v2 coverage seed is preregistered as:

```text
label:
  mnq-atlas-phase5-preregistration-v2|coverage
SHA-256:
  f7caf394602d09ad7181b76b6ae137a64ad5d907693c86cb75a73361ce4ba0a1
root entropy (first 128 bits, big-endian):
  329373099305365003560734362733578893222
```

The exact schedule is:

```text
SeedSequence(329373099305365003560734362733578893222).spawn(300)
```

Each outer child calls `spawn(2)` exactly once, yielding `(data, bootstrap)`
children in that order. Each child is instantiated as
`Generator(PCG64(child))`.

Before its assertion, the fixture prints:

```text
PHASE5_COVERAGE_V2_RESULT={"acceptance_bounds_inclusive": [L, U], "coverage_count": coverage_count, "outer_replications": 300}
```

The experiment has one execution ever. On failure, execution stops
immediately and records:

1. the v1 and v2 preregistration commits;
2. the implementation, guard, calibration, derived-gate, and fixture commits;
3. the environment fingerprint;
4. the complete command;
5. exact test output, including the printed evidence line;
6. exception details;
7. the v2 coverage count and inclusive bounds; and
8. all paired AR widths and ratios if applicable.

There is no rerun, reseed, bound adjustment, or change to the fixture, DGP,
draw count, block length, seed schedule, interval convention, derivation
formula, AR coefficient, aggregation rule, or materiality threshold. Neither
preregistration may be edited. A later rerun requires another explicit user
ruling and independent audit, and the original failure remains permanently
recorded.

Under exact `p_hat`, the central discrete region's ideal-null content is
expected to be approximately 0.96–0.97. Calibration error has approximate
standard deviation 0.005 at 3,000 replications and adds inferred one-shot
risk. The total false-failure risk is inferred to be approximately 4–8%;
this is unmeasured and is a property of the gate, not permission to retry.

## D. Sequencing and governance

The binding order is:

1. Commit the permanent v1 failure record, resolved D15, and permanent v1
   coverage skip marker.
2. Commit this v2 preregistration.
3. Commit a test pinning this document's exact SHA-256 bytes.
4. Stop for an independent Opus static pre-execution audit of those three
   commits.
5. Only after that audit closes, commit
   `tools/phase5_coverage_calibration.py` outside `tests/` and `mnq_lab/`.
6. Stop for an independent Opus static audit of the calibration runner.
7. Only after that audit closes, execute the calibration command exactly
   once:

   ```text
   python tools/phase5_coverage_calibration.py
   ```

8. Commit the verbatim calibration output, runtime, environment, exact
   derivation arithmetic, derived `[L, U]`, and the v2 one-shot test.
9. Stop for an independent Opus audit of both the exact derivation and the
   static v2 fixture.
10. Only after that audit closes, execute the v2 coverage fixture exactly
    once:

    ```text
    python -m pytest tests/test_bootstrap_acceptance.py::test_preregistered_synthetic_median_coverage_v2_once -q -s
    ```

11. Append its complete result to
    `docs/PHASE5_ACCEPTANCE_RECORD.md`.
12. Only if v2 coverage passes, execute the unchanged v1 AR(1) fixture
    exactly once:

    ```text
    python -m pytest tests/test_bootstrap_acceptance.py::test_preregistered_ar1_session_width_discriminator_once -q -s
    ```

13. Append the complete AR(1) result to the acceptance record immediately.

The AR(1) one-shot is re-authorized unchanged under the user's 2026-07-30
ruling, but it remains sequenced after a v2 coverage pass. Its original v1
definition, entropy, command, evidence requirements, and failure protocol
remain binding.

Routine suites must exclude the acceptance file:

```text
python -m pytest tests --ignore=tests/test_bootstrap_acceptance.py -q
```

No full-suite invocation may collect or execute
`tests/test_bootstrap_acceptance.py`.

## Prohibited throughout

- Editing the v1 preregistration bytes, v1 result records, or frozen files.
- Erasing, reinterpreting, or overwriting the permanent 267/300 v1 result.
- Reusing a spent or registered entropy for a new purpose.
- Passing the spent v1 coverage entropy through `SeedSequence` again.
- Executing calibration or either one-shot more than once.
- Deriving, previewing, or estimating v2 bounds before calibration output
  exists.
- Changing the frozen derivation formula after calibration.
- Any production change under `mnq_lab/`.
- Any suite run that includes `tests/test_bootstrap_acceptance.py`.
- Executing AR(1) before a v2 coverage pass.
- Beginning Phase 6, S01A, or any out-of-scope market-aware work.

On any failure at any step: stop, preserve the applicable evidence, and
report. Nothing in this v2 contract retroactively changes the v1
preregistration or result.
