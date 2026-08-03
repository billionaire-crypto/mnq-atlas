# Unit O ratification-certificate ledger

Each `*.json` file is one immutable canonical
`unit_o_ratification_certificate_v1` certificate. The producing run cannot
write this namespace. A certificate binds one exact tree and producing commit
to its 109 scientific-column hashes, criteria commit, completion record, gate
evidence, reproduction, non-admissible override, and CLOSED audit-verdict
entry. Corrections are new entries; existing bytes are never edited or deleted.

Phase 8 must enter through `mnq_lab.ledger.ratification.require_ratified_unit_o`,
which fails unless exactly one applicable certificate passes C1-C6 and carries
the explicitly limited C7 attestation.
