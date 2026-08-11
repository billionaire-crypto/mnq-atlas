# Phase 8 v2 Closeout — Session-Aware Descriptive Measurement

Status: production and evidence closeout recorded; focused independent audit of
this document pending.

This record applies only to `phase8-session-aware-v2`, produced by Phase 8 v2
attempt-009. It is separate from the protected v1 closeout in `docs/PHASE8.md`.
It records no selection, ranking, optimization, or scientific result.

## 1. Production authorization and chronology

Repository entries D19 and D36 did not authorize this production. D36 says
expressly that it does not authorize Phase 8 or Phase 9, and D37 addresses
runtime projection only. The operator has confirmed that authorization for the
Phase 8 v2 production run was given directly to the Codex implementation
session in conversation, outside the repository, before attempt-009.

The chronology retained by this implementation session is:

- The handoff into this session records that attempt-007 was launched as one
  fresh Phase 8 v2 invocation at commit `f523c8f`, with six Stage 1 workers,
  32 bootstrap workers, and `fork`. The operator later directed that invocation
  to stop. Its completed Stage 1 and plan evidence was preserved, while its
  incomplete bootstrap chunk was not promoted. The handoff does not retain the
  original authorization wording or timestamp for attempt-007, so this record
  does not invent either.
- Later in the Codex conversation, the operator explicitly authorized one clean
  full Phase 8 invocation, including Stage 1, and repeated that authorization.
  Before that planned invocation began, the operator explicitly said to stop
  and decided to retire that pod. That particular authorization therefore
  produced zero invocations.
- The operator then directed a fresh start on a newly rented pod and supplied
  the new connection. One fresh full invocation followed and became
  attempt-009. The operator monitored it through completion and has now
  reaffirmed in the closeout instruction that the run had been approved in the
  Codex conversation. The exact pre-launch timestamp and exact wording of the
  fresh-pod authorization, beyond its ordering before the run, are not retained
  in this session record; nor does the record determine whether it was a new
  grant or continuation of the earlier singular authorization.
- The execution receipt cites attempt-003 as an earlier memory-stopped run, and
  retained project context says other failed attempts preceded attempt-009.
  This session does not hold their complete invocation list or their individual
  operator-authorization wording and timestamps. It does not infer an
  attempt-008 invocation merely from the final attempt number. Positively held
  invocation evidence covers attempt-007 and attempt-009; the total count and
  authorization chronology of all other failed attempts remain unspecified for
  the operator to supply if a more exhaustive record is required.

The conversational authorization existed outside the repository before
attempt-009. This repository record is intentionally post-run and is not
retro-dated. It does not claim that a repository-visible authorization preceded
the run.

This authorization chronology is recorded here rather than in
`docs/DISCREPANCIES.md`. The latter remains byte-pinned by the effective Unit O
v2 audit-ledger chain, so changing it would create an unrelated evidence-pin
amendment obligation.

## 2. Artifact identity and provenance

| Field | Recorded value |
|---|---|
| Artifact | `phase8-session-aware-v2` |
| Run commit | `c62b2e4b732d20a356345c0e022c21a3ea627c79` |
| Branch | `phase-7b-outcome-layer` |
| Output manifest SHA-256 | `e2d556f863b82b5f60989d58b773dbf3b55ffd92ad4f566af5b35c0ceb7e624c` |
| Execution receipt SHA-256 | `269250e92b02cacd87decd23799cf4c0ca5be68a99c23c1a24695cb9ae33f668` |
| Progress-log SHA-256 | `3de2e4591d143c2990d48a19fe0e54cded31189fc956b483f81a782a583210ba` |
| Checkpoint-identity SHA-256 | `13a23b8ff92db32f4c2406f787beebb2ab3be8141b0b52133a92f8c5acfa9560` |
| Frozen-spec SHA-256 | `70dae16c8b12fe26d38a7bfdabf0202066fe7149f790d0d2942279d9c3b8ff50` |
| Analysis-constants SHA-256 | `1c95aa595c30c48b853303291a7dbaabceaf5b7331bca565a30863e8dcf138d4` |
| Corpus seal | `1cf6ec5ce7822ce1333984909b52d5c937e4ccc06e280030bcacda22620ffd73` |
| Ratified input | `phase7-unit-o-session-aware-v2` |
| Input certificate | `2026-08-09-phase7-unit-o-session-aware-v2-ratification` |
| Platform | `Linux-5.15.0-186-generic-x86_64-with-glibc2.35` |
| Python | `3.13.2` |
| pandas | `3.0.1` |
| NumPy | `2.2.3` |

The four artifact-evidence files above were read as raw bytes from the verified
off-pod archive. Their lengths and SHA-256 values were independently
recomputed. The frozen specification and constants were also re-read from the
repository. The environment, corpus seal, contract, commit, branch, and input
manifest identities were re-read from the verified output manifest. No value
in this table was copied without an evidence read.

## 3. Execution record

| Field | Recorded value |
|---|---|
| Started | `2026-08-10T07:33:10.410204+00:00` |
| Finished | `2026-08-10T15:37:57.316302+00:00` |
| Elapsed | `29,086.906 s` |
| Workers | Stage 1: 6; bootstrap: 32 |
| Process start method | `fork` |
| Request chunk size | 4,096; scheduling and checkpoint granularity only, proven output-neutral |
| Bootstrap chunks | 8; final chunk carried 74 requests |
| Requests and intervals | 28,746 requests × 4 block lengths = 114,984 interval rows |
| Peak process-tree PSS | 27,757,776,896 B |
| Process-tree PSS ceiling | 206,158,430,208 B |
| Exit codes | child 0; wrapper 0 |
| Protected snapshot SHA-256 | `6b7872c3d138d2d19964499bdff555eb9aa7af64574d340aeb23f97e416af18b` before and after |

The receipt records `output_complete = true`, no memory-stop evidence, no
staging residue, an unchanged repository commit, and unchanged protected paths.
All eight chunks and all Stage 1 and plan units were newly promoted by this
fresh invocation.

The request chunk size changes scheduling, recomputation, checkpoint cadence,
and transient resource use only. Synthetic shared-support tests and independent
review established byte-identical assembled interval tables across chunk sizes;
it does not alter the scientific contract.

## 4. Bootstrap contract as executed

- 4,999 draws per block length;
- block lengths 1, 5, 10, and 20, with primary block length 5;
- `PCG64`;
- confidence level 0.95;
- `whole_session_stationary` resampling;
- no early stopping and no partial-session truncation;
- frozen root entropy `[20260801, 8, 13, 1]`; and
- frozen child spawn keys `[0]`, `[1]`, `[2]`, and `[3]`.

The one-shot acceptance evidence is not repeated here.
`docs/PHASE5_ACCEPTANCE_RECORD.md` records that the v2 coverage gate PASSED and
the AR(1) session-width discriminator PASSED, each on its first and only
execution on 2026-07-31. It also records that the v1 gate FAILED on 2026-07-30
and that D15 explains why the v1 gate was mis-specified. These stochastic
fixtures and their spent entropy must never execute again.

## 5. Output surface — structure only

| Table | Declared and emitted rows |
|---|---:|
| Contrasts | 29,430 |
| Intervals | 114,984 |
| Day-type descriptives | 216 |
| Interactions | 720 |

Every declared cell was emitted with a status; no cell was dropped. This record
does not reproduce any tick, quantile, contrast, interaction, interval endpoint,
or other scientific measurement.

## 6. Completion-threshold disclosure — D32 §5

The run used `min_completion_h60 = 0.98` from the frozen
`analysis_constants_v1.yaml`. D32 §5 expects the corrected session-aware value
to be 0.99 and requires independent re-derivation and ratification as S00 v2 in
a new versioned constants file, never by editing v1. That derivation has not
been performed; the repository has `s00_threshold_input_v1.json` and no v2
counterpart.

The focused exposure audit measured a minimum completion of 0.996672 across the
artifact. It found zero observations below 0.99, zero below 0.98, and zero rows
in `[0.98, 0.99)` at any horizon. Maximum completion imbalance was 0.003328
against the frozen 0.05 bound. Raising the h60 gate to 0.99 would therefore
change zero rows in this artifact.

This establishes only that the stale threshold was inert here. It does not
derive or ratify the expected corrected value. S00 v2 remains owed for the
record and gates nothing in this artifact.

## 7. Unit O ledger evidence history

The 2026-08-10 Unit O v2 amendments withdrew six external run-receipt evidence
pins without disclosure. Independent audit found the withdrawal. Append-only
entries dated 2026-08-11 restored the six pins, the 2026-08-12 entry restored
the direct predecessor pin needed by the evidence-set guard, and the
2026-08-13 entry completed the raw-byte predecessor chain. No earlier entry was
edited, amended in place, or withdrawn. The audit ledger now contains nine
entries, and independent audit returned CLOSED on the completed chain.

## 8. Verification and claim boundary

Independent review returned CLOSED for attempt-009 artifact checks A1–A6, the
completion-threshold exposure, and the completed Unit O predecessor-pin chain.
The artifact archive, output files, checkpoints, receipt, progress log,
identities, schemas, shapes, dtypes, declared ordering, and protected snapshots
were verified without inspecting or reporting scientific result magnitudes.

This document closes Phase 8 v2 production and its evidence. It does not:

- authorize Phase 9, publication, selection, ranking, or optimization;
- issue, amend, or replace a ratification certificate;
- change a formula, threshold, tolerance, mask, weight, resampler, entropy,
  spawn key, interval definition, or artifact byte;
- claim that any measurement is scientifically correct; or
- convert an attestation or corroboration into mechanical proof.

Residual limitations remain:

- D18 and D19 remain OPEN.
- Single-source calendar acceptance is corroboration, not proof.
- The session-aware correction itself has not received an independent audit of
  scientific correctness.
- Empirical byte identity is scoped to a matching complete environment
  fingerprint; cross-environment reproduction is semantic within declared
  policies.
- S00 v2 remains to be independently derived and ratified in new versioned
  inputs for future work.
- This closeout document requires its own focused independent audit.

Phase 9 remains unauthorized.
