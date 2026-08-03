# Audit-verdict ledger

Each `*.json` file is one immutable canonical `unit_audit_verdict_v1` entry.
Entries record the unit, exact audited commit and tree, verdict, date, findings,
auditor identity, producer identity, and hashes of reviewed evidence. Append a
new file to correct or supersede a verdict; never edit or delete an entry.

`mnq_lab.ledger.ratification.load_audit_entries` is the fail-closed validator.
Only a scoped `CLOSED` Unit O entry can support C7, which remains a human
attestation rather than mechanically proved blindness or independence.
