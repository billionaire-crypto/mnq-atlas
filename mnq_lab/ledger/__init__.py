"""Minimal append-only freeze ledger.

Phase 3 introduces only the mechanism needed to authorize the S00 completion
threshold freeze. Each entry is a separate immutable canonical JSON file under
``entries/``. Later governance phases may extend the mechanism; this package
does not claim to implement the full Phase 11 ledger.
"""

