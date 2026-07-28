"""Data spine: source ingestion, causal contract selection, bar stores, fail-closed gates.

Spec §5. This subpackage knows market mechanics. It is the only place permitted to name
`data/locked_confirmation/`, and only in `build.py`, `gates.py` and `seal.py` — see
§16.4.1 and docs/DISCREPANCIES.md D6.
"""
