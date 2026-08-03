# Unit O ratification preregistration

**Fixed 2026-08-02 before visibility of the concurrent corpus run.** This
document defines the previously undefined requirement in
`docs/PHASE8_PREREGISTRATION.md` for "a ratified Unit O outcome table and
manifest." The definition is prospective. It neither changes nor erases any
producing artifact, manifest, historical snapshot, audit, or exclusion.

## 1. Scope and claim boundary

A Unit O outcome table and manifest are **RATIFIED if and only if all seven
conditions C1-C7 hold for that exact tree at that exact producing commit**.
Ratification is never partial, retroactive, inferred from a neighboring tree,
or transferable to another path, byte sequence, manifest, environment, or
commit.

C1-C6 are mechanically checked and fail closed. C7 is attested, not proven.
Every certificate and every consumer claiming ratification must state:

> C1-C6 passed mechanical validation. C7 is a recorded human attestation; code
> cannot prove that no person inspected outcomes before the criteria were fixed
> or that the audit was genuinely blind and independent.

The validator proves agreement among recorded evidence and bytes available to
it. It does not elevate human statements into facts.

## 2. Necessary and jointly sufficient conditions

### C1 - Sealed provenance (mechanical)

The tree was produced from the canonical exploration corpus. Its run and Unit O
manifests must name, and validation must byte-check, these pinned inputs:

| Input | Required SHA-256 |
|---|---|
| Canonical source-store manifest | `1cf6ec5ce7822ce1333984909b52d5c937e4ccc06e280030bcacda22620ffd73` |
| `REV6_FROZEN_SPEC.md` | `70dae16c8b12fe26d38a7bfdabf0202066fe7149f790d0d2942279d9c3b8ff50` |
| `analysis_constants_v1.yaml` | `1c95aa595c30c48b853303291a7dbaabceaf5b7331bca565a30863e8dcf138d4` |
| `docs/PHASE8_PREREGISTRATION.md` | `d07174ed0acc9e60ab6b255f4b33fc08141969c64e04f66e1e08c0aca98b4680` |
| `docs/OUTCOME_LAYER_PREREGISTRATION.md` | `4b5bc97fdfd4b0219c69e6a8adf76f18072091a9389700191d3ddcd10f8207c8` |

A missing field, missing file, noncanonical manifest, or mismatch fails C1.

### C2 - Criteria precede visibility (mechanical over recorded evidence)

The certificate records the full SHA of the commit containing this document
and D22, plus the immutable run-completion record for the producing run. A
result becomes **visible** when the completed staging tree is first renamed or
otherwise exposed at its final path, not when somebody later opens it. The
criteria commit's recorded Git commit time must be strictly earlier than the
completion record's `visible_at_utc`, and the completion record must identify
the same final tree and run-manifest SHA-256 as the certificate.

This is an ordering check, not an ancestry check against the run commit. A
missing, malformed, ambiguous, or non-strict ordering fails C2. Mechanical
validation establishes consistency of the recorded timestamps and identities;
the truthfulness of an externally recorded visibility time remains within the
auditor's C7 responsibility.

### C3 - Clean committed code state (mechanical)

The run manifest's environment fingerprint must contain one full producing
commit SHA and `dirty: false`. The certificate's `run_commit` must equal that
SHA. Missing, abbreviated, inconsistent, or dirty state fails C3.

### C4 - All gates passed without relaxation (mechanical)

Every fail-closed gate declared by the producing code must appear exactly once
in the run evidence with `passed: true`. The validator compares gate names,
thresholds, tolerances, fallback policy, and the six-GiB peak-memory ceiling to
the committed producing code or its independently pinned policy record. A
missing gate, lowered threshold, added tolerance, fallback, exceeded ceiling,
or changed policy fails C4. A summary boolean alone is insufficient.

### C5 - Reproducible scientific bytes (mechanical)

A separately recorded rerun at the identical complete environment fingerprint
must yield bit-identical scientific columns. The certificate records both
trees' manifests and the complete ordered set of 109 `(relative_path, column,
sha256)` identities. Any missing, extra, reordered, duplicated, or unequal
scientific-column record fails C5. Manifest bytes may differ only in declared
non-scientific provenance fields.

For the 2026-08-02 ruling, the preserved first-run baseline supplies this
reproduction comparison but remains excluded as a Phase 8 input under C2 and
C6. Comparison is not ratification.

### C6 - Self-stamped diagnostic requires a recorded override (mechanical)

A producing tree stamped `NON-ADMISSIBLE DIAGNOSTIC ARTIFACTS` is not
automatically disqualified. It can be consumed only when the certificate has a
nonempty `non_admissible_override` naming the exact stamp, decision date,
decider, audited basis, audit-verdict entry, and explicit scope limited to the
exact certified tree and run commit. The source tree and every source manifest
remain byte-for-byte untouched; the override exists only in the certificate.

For the run already in progress on 2026-08-02, the audited basis must record the
user ruling in section 4. This override is a **judgment call placed on the
record, not a mechanical derivation**. A blank, generic, unaudited, mismatched,
or transferable basis fails C6.

### C7 - Blind and independently audited (attested, not proven)

An auditor other than the producer must attest that no outcome value was
inspected before these criteria were fixed, verify C1-C6 against raw bytes, and
record `CLOSED` in the append-only audit-verdict ledger. The audit entry names
the auditor, producer, exact audited commit, exact tree, findings, and date.

**C7 cannot be mechanically enforced.** Code can require a well-formed CLOSED
entry, link it by hash, and reject producer/auditor identity equality. It cannot
prove a human did not see numbers, that identities correspond to different
people, or that an audit was competent or independent. Ratification must never
be described as structural proof of blindness or independence.

## 3. Certificate schema and ownership

The producing run cannot create, modify, or nominate its own certificate.
Certificates are canonical sorted UTF-8 JSON files in a tracked, append-only
ratification-ledger namespace and are written only after an audit verdict. Git
history provides append-only ordering: correction means a new entry; existing
entry bytes are never edited or deleted.

Each certificate contains exactly these logical records:

- `ledger_format`, `certificate_id`, `program_id`, `unit`, `decision_date`;
- `tree`: repository-relative path, tree identity digest, Unit O table path and
  SHA-256, Unit O manifest path and SHA-256, run-manifest path and SHA-256;
- `scientific_columns`: the complete ordered 109-entry list of relative path,
  column name, byte-level column hash, and hashing protocol version;
- `run_commit` and the complete `environment_fingerprint` recorded at start;
- `criteria_commit`, its commit timestamp, and hashes of this document and D22;
- `run_completion_record`: path, SHA-256, `visible_at_utc`, final-tree identity,
  and run-manifest SHA-256;
- `pinned_inputs`: the five C1 path/hash pairs;
- `gate_evidence`: exact policy version, every named gate and pass record,
  thresholds, tolerances, fallback status, peak-memory bytes and ceiling;
- `reproduction`: comparison-tree identity, environment fingerprint, both
  ordered scientific-column lists, and equality result;
- `non_admissible_override`: original stamp, exact scope, decision date,
  decider identity, nonempty basis, and linked CLOSED audit entry;
- `audit_entry`: ledger-relative path and SHA-256;
- `conditions`: explicit C1-C6 `passed: true` records and C7
  `attested_closed: true`, each with evidence references;
- `claim_boundary`: the mandatory C1-C6 mechanical/C7 attested statement from
  section 1.

Unknown keys, missing keys, noncanonical JSON, invalid hashes, path escape,
symlinks/reparse points, duplicate identities, or circular/self-reference fail
closed. Phase 8 must halt unless exactly one applicable certificate validates
and its recorded hashes match the raw bytes at the certified tree. A
certificate for another tree or another commit is irrelevant and rejected.

The audit-verdict entry is a separate canonical append-only JSON object with:
`ledger_format`, `entry_id`, `program_id`, `unit`, `audited_commit`,
`audited_tree`, `verdict`, `date`, `findings`, `auditor_identity`,
`producer_identity`, and byte hashes of the evidence reviewed. Only `CLOSED`
satisfies C7; `OPEN`, `REJECTED`, unknown, or missing verdicts halt.

## 4. User ruling and C6 basis - 2026-08-02

The corpus run in progress when these criteria were committed **will be Phase
8's input. No further run is required.** The pipeline is deterministic over a
sealed corpus, and every analysis decision - quantiles, the five contrasts,
three estimands, thresholds, bootstrap entropy, and block lengths - was frozen
and pinned on 2026-08-01 before any outcome existed. A further run would be
byte-identical and yield no new information. Requiring one was ceremony, not
protection.

Allowing the permanent diagnostic stamp to be overridden is nevertheless the
weakest joint in this design. C6 is a recorded judgment call. The stamp is not
removed or reinterpreted, and the source tree and manifests are never edited.
The certificate must quote this bounded rationale by reference and an
independent auditor must close it.

The preserved first-run baseline remains excluded. Its prior audit is not
reopened. It may serve only as the required byte-identity comparator; it cannot
serve as Phase 8 input because it does not satisfy C2 and has no valid C6
override under this preregistration.

## 5. Tie-break fixed before outcome hashes are known

The in-progress run's 109 scientific-column hashes must match the preserved
baseline exactly. Only manifest provenance may differ because `code_commit`
changed.

If **any** column hash differs, validation halts. The first mismatching session
must be located and classified under frozen specification section 16.6, and
**neither tree is usable** until the cause is explained in a new audited record.
No tree is selected over the other; no ranking, optimization, outcome-based
choice, or winner-picking is permitted. A later explanation cannot silently
repair this certificate or either source tree.

## 6. Required negative controls

Acceptance tests must independently make each claimed check fail: changed
source-store hash; criteria after visibility; dirty producing state; lowered
threshold or added tolerance; non-admissible override without a recorded basis;
scientific bytes differing from certificate hashes; certificate for another
tree or commit; and the preserved baseline failing through C2 and C6 rather
than through a directory-name blacklist. A check without a demonstrated
failing input is not accepted as a check.

No ranking, selection, optimization, P&L, expectancy, Sharpe ratio, or p-value
is authorized by this preregistration.
