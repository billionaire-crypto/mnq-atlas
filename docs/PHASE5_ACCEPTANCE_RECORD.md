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
