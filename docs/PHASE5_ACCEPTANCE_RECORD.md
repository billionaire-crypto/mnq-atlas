# Phase 5 stochastic acceptance record

This file is append-only. Registered stochastic results are permanent evidence:
they are never erased, reinterpreted, overwritten, or replaced by a later
experiment.

## V1 coverage gate — `FAILED`

**Execution date:** 2026-07-30

**Command:**

```text
python -m pytest tests/test_bootstrap_acceptance.py::test_preregistered_synthetic_median_coverage_once -q -s
```

**Evidence line:**

```text
PHASE5_COVERAGE_RESULT={"acceptance_bounds_inclusive": [277, 292], "coverage_count": 267, "outer_replications": 300}
```

**Failure output:**

```text
assert 277 <= 267
1 failed in 582.39s (0:09:42)
```

**Environment fingerprint:**

```text
OS: Windows-10-10.0.19045-SP0
Python: 3.13.2 (MSC v.1942 64 bit (AMD64))
NumPy: 2.2.3
pytest: 9.1.1
```

**Commits:**

```text
Phase 5 preregistration: 49091f4
Bootstrap production:   d6eb390
Mutation-guard tip:     35b89b0
Acceptance fixture:     857ed63
```

The AR(1) acceptance fixture was **NOT EXECUTED**. Its registered entropy was
unconsumed as of this failure and the subsequent read-only forensic audit.

The v1 coverage result is permanently registered as 267/300 against the
inclusive acceptance bounds [277, 292]. The 2026-07-30 forensic audit
classified the result as a preregistered acceptance-design defect rather than
an implementation defect. The v1 coverage fixture must never execute again.

## V2 calibration runner — deterministic launch failure

**Execution date:** 2026-07-30

**Command:**

```text
python tools/phase5_coverage_calibration.py
```

**Exact output and exception:**

```text
Traceback (most recent call last):
  File "C:\mnq-atlas\tools\phase5_coverage_calibration.py", line 14, in <module>
    from mnq_lab.constants import load_bootstrap_constants
ModuleNotFoundError: No module named 'mnq_lab'
```

**Runtime:** 0.1359 seconds

**Environment fingerprint:**

```text
OS: Windows-10-10.0.19045-SP0
Python: 3.13.2 (MSC v.1942 64 bit (AMD64))
NumPy: 2.2.3
pytest: 9.1.1
```

**Commits:**

```text
C1 permanent record:       eeda752b1f95f5c902ff542357b1b73f833a5772
C2 v2 preregistration:     b89b2ce717aecdfebf944f8e2c918426836ebfd8
C3 v2 byte pin:            594d53cb2da2499c3fb14f798a2572de3ce0a826
C4 calibration runner:     809f41dfa0e46f68350e7dc339302e85a6566319
Calibration runner SHA-256:
f383ae3268772e522ee9e4b0ba1e6df6c900749e27042badcf8d86a154cddef1
```

The process failed while importing `mnq_lab`, before constructing
`SeedSequence` or any Generator. The registered v2 calibration entropy was
therefore **not consumed**. No calibration replication ran, no
`PHASE5_COVERAGE_CALIBRATION` evidence line was produced, and `K` and
`K/3000` are unavailable. No v2 acceptance bound was derived or previewed.
The v2 coverage and AR(1) fixtures were **NOT EXECUTED**; no AR widths or
ratios exist.

The deterministic cause is the script-path import boundary: under the exact
command above, Python placed `C:\mnq-atlas\tools` rather than the repository
root on the import search path, so the local `mnq_lab` package was not
importable. The command was not retried. A corrected launch path or runner
requires a new explicit user ruling and an independent audit before another
attempt.

## V2 coverage calibration — `COMPLETED`

**Execution date:** 2026-07-31

**Command:**

```text
python -m tools.phase5_coverage_calibration
```

This was the single corrected execution authorized by the user's 2026-07-30
ruling under Amendment P5-2 after the independent static audit of Amendment 1
returned `VERDICT: CLOSED` at commit `988b061`.

**Verbatim evidence line:**

```text
PHASE5_COVERAGE_CALIBRATION={"covered": 2771, "replications": 3000, "p_hat": "2771/3000"}
```

**Process result:**

```text
PHASE5_CALIBRATION_EXIT_CODE=0
```

**Runtime:** 5683.1178 seconds (1:34:43.1178)

**Environment fingerprint:**

```text
OS: Windows-10-10.0.19045-SP0
Python: 3.13.2 (tags/v3.13.2:4f8bb39, Feb  4 2025, 15:23:48) [MSC v.1942 64 bit (AMD64)]
NumPy: 2.2.3
pytest: 9.1.1
```

**Commits:**

```text
C1 permanent record:           eeda752b1f95f5c902ff542357b1b73f833a5772
C2 v2 preregistration:         b89b2ce717aecdfebf944f8e2c918426836ebfd8
C3 v2 byte pin:                594d53cb2da2499c3fb14f798a2572de3ce0a826
C4 calibration runner:         809f41dfa0e46f68350e7dc339302e85a6566319
Launch-failure record:         af5f1c3736f6e325295edf7e9c4929d294fffe06
Amendment 1 and preflight:     988b06141c29fa84ab5f0c18e43af8ec42fbc030
Calibration runner SHA-256:
f383ae3268772e522ee9e4b0ba1e6df6c900749e27042badcf8d86a154cddef1
```

The registered calibration result is `K = 2771`. Its retained exact fraction
is `K/3000 = 2771/3000`. The registered v2 calibration entropy
`282152804769136717845935072558193670437` is now **spent** by this completed
execution and must never be used again.

No v2 acceptance bound was derived, previewed, estimated, or added during this
recording step. The exact-rational derivation and static v2 fixture remain the
next separately audited stage. The v2 coverage and AR(1) one-shot fixtures
remain **BLOCKED** and were not executed.

## V2 exact gate derivation and static fixture — `NOT EXECUTED`

The registered calibration result is `K = 2771`, and the exact calibration
fraction is `K/3000 = 2771/3000`. For this derivation only,

```text
C ~ Binomial(300, 2771/3000)
```

was evaluated using integer powers, integer binomial coefficients, and exact
`Fraction` arithmetic. No floating-point conversion, rounding, tolerance,
continuity correction, interpolation, discretionary widening, or stochastic
operation was used.

The frozen smallest-quantile definitions give:

```text
L = smallest c with P[C <= c] >= 1/40  = 268
U = smallest c with P[C <= c] >= 39/40 = 286
```

Therefore the mechanically derived inclusive v2 acceptance region is exactly:

```text
[L, U] = [268, 286]
accept if and only if 268 <= coverage_count <= 286
```

With `q = 1 - 2771/3000 = 229/3000`, the exact lower and upper rejection-tail
probabilities are recorded as these finite rational sums over the common
denominator `3000^300`:

```text
P[C < 268] = P[C <= 267]
           = sum(c=0..267) binom(300,c) * 2771^c * 229^(300-c) / 3000^300

P[C > 286]
           = sum(c=287..300) binom(300,c) * 2771^c * 229^(300-c) / 3000^300
```

The exact boundary certificates are:

```text
P[C <= 267] < 1/40  <= P[C <= 268]
P[C <= 285] < 39/40 <= P[C <= 286]
```

The derivation was independently materialized by both direct binomial-PMF
summation and the exact adjacent-PMF recurrence; all 301 cumulative fractions
matched exactly, their final value was exactly 1, and the adjacent mutations
267/269 and 285/287 failed the corresponding smallest-quantile definition.

The static fixture
`test_preregistered_synthetic_median_coverage_v2_once` uses the preregistered
v2 coverage entropy `329373099305365003560734362733578893222`, 300 outer
replications, and the literal inclusive bounds `[268, 286]`. It has **NOT BEEN
EXECUTED OR COLLECTED**. Its registered entropy remains **UNCONSUMED**. The
fixture and derivation remain blocked pending an independent static audit. The
AR(1) one-shot also remains blocked and unexecuted.
