# Run-completion ledger

Each `*.json` file is one immutable canonical `run_completion_record_v1`
recording when an exact completed tree first became visible. The record binds
the final tree digest, run-manifest hash, and producing commit. Corrections are
new entries; existing bytes are never edited or deleted.
