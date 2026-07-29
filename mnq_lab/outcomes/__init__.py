"""Outcome-side machinery: windows, completion accounting, (later) excursions.

Modules here know market mechanics — bars, RTH, horizons — but nothing about
studies (spec §16.3).

They must not reach the locked confirmation tier. That is not a promise made here:
`tests/test_seal_guard.py` scans this package by AST and fails if any module outside
the permitted set (`spine/build.py`, `spine/gates.py`, `spine/seal.py`) names the
locked store in a non-docstring string literal, and `assert_exploration_safe` refuses
such a path at runtime, including via relative traversal (spec §16.4.1).
"""
