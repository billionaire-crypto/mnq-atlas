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

## V2 coverage gate — `PASSED`

**Execution date:** 2026-07-31

**Command:**

```text
python -m pytest tests/test_bootstrap_acceptance.py::test_preregistered_synthetic_median_coverage_v2_once -q -s
```

This was the first and only execution of the v2 coverage fixture. The initial
audit at `588f3eb` returned `VERDICT: OPEN` only for guard hygiene; the
guard-correction re-audit then returned `VERDICT: CLOSED` at commit `2c709aa`.

**Complete pytest output:**

```text
PHASE5_COVERAGE_V2_RESULT={"acceptance_bounds_inclusive": [268, 286], "coverage_count": 283, "outer_replications": 300}
.
1 passed in 590.26s (0:09:50)
```

**Process result:**

```text
PHASE5_V2_EXIT_CODE=0
```

**Wrapper wall-clock runtime:** 591.3985 seconds (0:09:51.3985)

**Environment fingerprint:**

```text
OS: Windows-10-10.0.19045-SP0
Python: 3.13.2 (tags/v3.13.2:4f8bb39, Feb  4 2025, 15:23:48) [MSC v.1942 64 bit (AMD64)]
NumPy: 2.2.3
pytest: 9.1.1
```

**Commits:**

```text
V1 preregistration:            49091f49dc90c411609543d43abe32effc05c1da
Bootstrap production:          d6eb390836079fe7498ce540f30bd0fbef440916
Mutation-guard tip:            35b89b0eea9a7707df54def9ee23cf34d659eca4
Original acceptance fixtures:  857ed632539a72e0f02f190578515785edea3e2f
V2 preregistration:            b89b2ce717aecdfebf944f8e2c918426836ebfd8
V2 preregistration pin:        594d53cb2da2499c3fb14f798a2572de3ce0a826
Calibration runner:            809f41dfa0e46f68350e7dc339302e85a6566319
Launch-failure record:         af5f1c3736f6e325295edf7e9c4929d294fffe06
Amendment 1 and preflight:     988b06141c29fa84ab5f0c18e43af8ec42fbc030
Calibration evidence:          cb023c3f41ca96b84d3ec82a71904e1c0f575229
Derived gate and v2 fixture:   588f3eb5177560b3209a1fd6876bc3386cfa507e
Derivation guard correction:   2c709aa8b3cd19d0245e76d2c8da2972dcab3703
V2 acceptance fixture SHA-256:
bb239fc97f7823544a3c39748e808a42f0e529c28f9074736f7ce8f7a41da71c
```

The observed `coverage_count = 283` is inside the preregistered mechanically
derived inclusive region `[268, 286]`; the v2 coverage gate therefore
**PASSED**. This verifies consistency with the measured finite-sample coverage
behavior. It does **not** establish nominal 95% coverage, and no such claim is
made.

The v2 coverage entropy `329373099305365003560734362733578893222` is now
**SPENT** by this completed execution and must never be used again. The fixture
must never be rerun. The AR(1) fixture was **NOT EXECUTED OR COLLECTED**; its
registered entropy `157484425038737148717780864763684278439` remains
**UNCONSUMED**. The sequence condition requiring a v2 coverage pass before
AR(1) is now satisfied, but AR(1) is held for the separate post-result review.

## AR(1) session-width discriminator — `PASSED`

**Execution date:** 2026-07-31

**Command:**

```text
python -m pytest tests/test_bootstrap_acceptance.py::test_preregistered_ar1_session_width_discriminator_once -q -s
```

This was the first and only execution of the unchanged preregistered AR(1)
fixture, after the v2 coverage gate passed and its independent post-result
audit returned `VERDICT: CLOSED` at commit `e9d9df3`.

**Complete pytest output:**

```text
PHASE5_AR1_RESULT={"directional_count": 24, "minimum_directional_count": 20, "minimum_median_ratio": 1.5, "ratios": [1.5041097369205838, 1.9393590645713366, 2.984345248466931, 1.9993516202930928, 2.127241610990348, 2.0731434011298218, 2.3986324920736486, 2.5762037989460382, 2.35696637500994, 2.5105212092082407, 2.0360519488759135, 3.5121144854132367, 2.567376206956976, 3.3148881912366814, 2.1741594649651996, 2.356012041610303, 3.092233407548194, 1.895436087365999, 2.115782408445095, 2.0328580074428078, 2.095817278032364, 2.1683133477836822, 2.076912559424286, 2.843033436817611], "row_widths": [0.11705976445401076, 0.09323562624948317, 0.11286064881422897, 0.10015108693726177, 0.10727383542435245, 0.11025943746828223, 0.12136475144747755, 0.11877298143184495, 0.1100904544025062, 0.10573777871866358, 0.09541159918920589, 0.0992289549808176, 0.09011222003218862, 0.12171083384985465, 0.11092129640293377, 0.08733097330488815, 0.09183725090846931, 0.10523311234196443, 0.11034016406049418, 0.12094864623696494, 0.13582328990589884, 0.10219620423534015, 0.1030735402230386, 0.10139564565263834], "session_widths": [0.17607073151690764, 0.18081735690792045, 0.33681514102763915, 0.20023723794212872, 0.22819736648521294, 0.22858362519965555, 0.291109436214362, 0.30598340597686624, 0.2594794992362721, 0.26545693608777265, 0.19426297247455016, 0.34850345016054746, 0.23135196966671284, 0.40345780587445296, 0.2411605864406488, 0.2057528247118644, 0.28398221531655454, 0.19946263871879968, 0.2334557780641393, 0.2458714239921816, 0.28466079774398156, 0.22159339373631534, 0.2140747302335532, 0.28827121093816105], "weighted_lower_median_ratio": 2.1683133477836822}
.
1 passed in 565.84s (0:09:25)
```

**Process result:**

```text
PHASE5_AR1_EXIT_CODE=0
```

**Wrapper wall-clock runtime:** 566.9311 seconds (0:09:26.9311)

**Environment fingerprint:**

```text
OS: Windows-10-10.0.19045-SP0
Python: 3.13.2 (tags/v3.13.2:4f8bb39, Feb  4 2025, 15:23:48) [MSC v.1942 64 bit (AMD64)]
NumPy: 2.2.3
pytest: 9.1.1
```

**Commits:**

```text
V1 preregistration:            49091f49dc90c411609543d43abe32effc05c1da
Bootstrap production:          d6eb390836079fe7498ce540f30bd0fbef440916
Mutation-guard tip:            35b89b0eea9a7707df54def9ee23cf34d659eca4
Acceptance fixture:            857ed632539a72e0f02f190578515785edea3e2f
V2 preregistration:            b89b2ce717aecdfebf944f8e2c918426836ebfd8
Derived gate and v2 fixture:   588f3eb5177560b3209a1fd6876bc3386cfa507e
Derivation guard correction:   2c709aa8b3cd19d0245e76d2c8da2972dcab3703
V2 coverage-pass evidence:     e9d9df3144a90f7afcade75febd52056e5387835
Acceptance fixture SHA-256:
bb239fc97f7823544a3c39748e808a42f0e529c28f9074736f7ce8f7a41da71c
```

Both preregistered conditions passed:

```text
weighted_lower_median_ratio = 2.1683133477836822 >= 1.50
directional_count = 24 >= 20
```

All 24 paired session-bootstrap widths exceeded their i.i.d. row-bootstrap
counterparts. The AR(1) session-width discriminator therefore **PASSED**.

This result verifies preservation of within-session dependence against the
test-only i.i.d. row-bootstrap negative oracle. It does not validate that
stationary session blocks capture dependence between chronological sessions,
and it does not identify an empirically correct block length for MNQ.

The AR(1) entropy `157484425038737148717780864763684278439` is now **SPENT**
by this completed execution and must never be used again. The fixture must
never be rerun. All registered Phase 5 stochastic executions are now complete;
Phase 5 closeout documentation remains a separate, subsequently audited task.
