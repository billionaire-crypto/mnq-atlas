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

