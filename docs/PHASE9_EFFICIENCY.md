# Phase 9 Efficiency and Corpus-Adapter Contract

**Program:** `mnq-atlas-001`  
**Specification:** `REV6_FROZEN_SPEC.md`, revision 6  
**Contract date:** 2026-08-10  
**Base:** `88ab51efb9cee5b3dcdfb70d605bdfc6e1091624`  
**Branch:** `phase-7b-outcome-layer`  
**Producer identity:** `Codex implementation session`  
**Status:** efficiency fix, corpus adapter, and one throwaway diagnostic authorized; production not authorized

## 1. Operator authorization and boundary

The operator authorized exactly the costed efficiency fix, corpus adapter, and
one throwaway diagnostic run on 2026-08-10 with this response:

> okay let's do it, fix it

This document records that authorization before any corresponding code is
written and is not retro-dated. The authorized scope is:

1. encode the four closed-vocabulary event fields and replace per-row Python
   dictionaries with preallocated arrays;
2. make event persistence an explicit declared choice;
3. implement and test the exact Phase 7/completion/runtime corpus adapter; and
4. execute one read-only throwaway wiring diagnostic with temporary output
   outside the repository and no permanent artifact.

No production run, pinned artifact, receipt, checkpoint identity, protected
snapshot, ledger entry, write under `data/`, Phase 10 work, strategy work, or
self-ratification is authorized. The producer will not name itself as auditor.

## 2. Evidence to reproduce before changing implementation

The independent auditor measured the existing synthetic single-arm path at 77
anchors per session:

| Rows | Wall time | Peak traced memory | Events table bytes |
|---:|---:|---:|---:|
| 1,925 | 0.27 s | 6.3 MB | 2.1 MB |
| 19,250 | 2.43 s | 63.6 MB | 21.0 MB |
| 57,750 | 7.31 s | 190.6 MB | 63.0 MB |

These values are external evidence until reproduced locally. The implementation
session will run the same three scales before modifying code and will report its
own wall time, peak traced memory, event bytes, and bytes per row. It will then
repeat the same benchmark after the change.

## 3. Frozen event encodings

All codes derive only from already-declared closed vocabularies. Observed rows
never determine a code or reorder a mapping.

### 3.1 Arm codes — `ARM_CONFIGS` order

```text
0 primary_ewma78_permissive_expanding
1 coverage_strict
2 ewma39
3 ewma156
4 mad78
5 threshold_rolling60
6 threshold_shift_m05
7 threshold_shift_m02
8 threshold_shift_p02
9 threshold_shift_p05
```

### 3.2 Session-phase codes — `PHASE_ORDER`

```text
0 open
1 morning
2 midday
3 afternoon
4 close
```

### 3.3 Assignment-status codes — `AssignmentStatus` declaration order

```text
0 ok
1 warmup
2 upstream_undefined
```

### 3.4 Reset-reason codes — `ResetReason` declaration order

```text
0 none
1 roll_reset
2 gap_reset
```

The events schema replaces `arm_id`, `session_phase`,
`assignment_status`, and `reset_reason` Unicode arrays with `arm_code`,
`session_phase_code`, `assignment_status_code`, and `reset_reason_code` small
integer arrays. `phase9-prevalence-v3` manifests carry the complete ordered
code-to-label mappings even when events are not persisted. A test must show a
mapping derived from observed labels breaks the prefix oracle while the
declared mappings do not.

## 4. Preallocation and storage target

The computation continues to emit the same summary and completed-episode
schemas and semantics. Only the causal events representation changes.

The event engine preallocates one typed NumPy array per event column at the
validated input row count and fills positions directly. It does not accumulate
one Python dictionary per input row. Exact narrow event dtypes are part of the
closed schema. The registered target is less than 100 stored bytes per event
row at each benchmark scale, excluding only fixed manifest/directory overhead
when reported separately.

## 5. Event computation versus persistence

Event computation and artifact persistence are separate controls:

```text
compute_events = true     default for measure_prevalence
persist_events = false    default for write_phase9_artifacts
```

`compute_events=true` preserves the causal per-row witness required by prefix
invariance and is the implementation default. A caller may explicitly disable
event computation only when no prefix-attributable result is requested; the
summary and episode-length tables remain available.

`persist_events=false` is the artifact default because causal diagnostics can
contain millions of rows and are not part of the compact prevalence report.
When false, the manifest declares `events_persisted=false`, retains the frozen
code mappings, and writes only summary plus episode lengths. Persisting events
requires the explicit keyword `persist_events=true`; it is never inferred from
the presence of an events table.

## 6. Exact corpus-adapter contract

The adapter combines three already-computed sources:

- Phase 7 assignment rows keyed by `(arm_id, session_id, tau_ns)`;
- runtime reset reasons keyed by `(session_id, tau_ns)`; and
- completion support keyed by `(session_id, tau_ns)`.

Reset and completion columns broadcast across declared arms only after exact
key reconciliation. There is no tolerance, nearest match, as-of match,
reindex-and-fill, silent drop, or fallback.

The adapter fails closed unless all of the following hold:

1. each source key is unique and in canonical chronological order;
2. runtime and completion key sequences are exactly identical;
3. each arm's assignment key sequence is exactly identical to that shared
   anchor sequence;
4. every assignment arm belongs to the frozen `ARM_CONFIGS` inventory and
   appears in that order;
5. row counts after broadcast equal `anchor_count * arm_count`; and
6. the final `(arm_id, session_id, tau_ns)` order equals the assignment order
   exactly.

On disagreement the adapter reports the first mismatching session/key and a
closed cause classification: duplicate, timestamp/order mismatch, missing
anchor, extra anchor, arm inventory/version mismatch, or source revision
requiring operator diagnosis. It returns no partial input.

The adapter is read-only and exploration-only. It writes nothing. It does not
accept a corpus-tier fallback and does not bridge pipeline versions.

## 7. Throwaway diagnostic contract

After tests pass, one diagnostic may read the existing exploration artifacts
and run the adapter plus prevalence measurement. Any diagnostic serialization
goes to a newly created temporary directory outside the repository and is
deleted or left as explicitly throwaway external evidence; nothing is written
under `data/`.

The diagnostic runs in a hidden background process and is polled. It records
only wiring/scale facts: anchor count, arm count, total event rows, exact join
counts, wall time, peak RSS, temporary output bytes, result table shapes,
status counts, and episode counts. It does not rank, compare, interpret, or
select arms or cells. If peak RSS approaches 4 GiB, the process is stopped and
the partial operational finding is reported rather than forcing completion.

## 8. Validation and closeout

The only authorized suite command is:

```text
python -m pytest tests --ignore=tests/test_bootstrap_acceptance.py -q
```

The verified baseline is `1491 passed, 2 skipped, 1 xfailed`; passes should
increase, both skips must remain, and the sole Phase 11 xfail must remain.
`tests/test_bootstrap_acceptance.py` is never collected or run.

The closeout will report all commits and hashes, both benchmark passes, mapping
proofs, exact adapter reconciliation counts, throwaway diagnostic measurements,
protected hashes, and all work explicitly not performed. Independent audit is
required; this document is not a ratification or audit entry.
