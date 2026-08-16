"""Verbatim operator authorization recorded before implementation."""

AUTHORIZATION_QUESTION = """Do you authorize exactly these two pre-run fixes on `phase-7b-outcome-layer`?

1. Add a fail-closed check in `calibration_execution.py` requiring `OMP_NUM_THREADS`, `MKL_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, and `NUMEXPR_NUM_THREADS` to each equal `"1"` before scientific work whenever worker count is greater than one. The code will refuse with instructions to export them before launch; it will not set them internally. Single-worker runs remain permitted when unset.

2. Add a fast synthetic end-to-end test of the real `execute_calibration_request` wrapper across all 300 indices, using a stubbed `_compute_verified`, asserting 300 payload hashes, denominator 300, complete inventory validation, and 300 committed checkpoint replications.

Only `calibration_execution.py` and test files will change. No calibration, real-corpus work, B=4999 execution, push, or protected-path modification will occur.

Please answer with an explicit authorization or refusal."""

AUTHORIZATION_ANSWER = "YES"
