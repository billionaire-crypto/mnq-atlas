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

## 9. Implementation evidence (added after execution, 2026-08-10)

The pre-change benchmark was reproduced before implementation using one declared
arm and 77 anchors per session:

| Rows | Wall time | Peak traced memory | Event bytes | Bytes/row |
|---:|---:|---:|---:|---:|
| 1,925 | 0.2852 s | 6,497,885 | 2,100,175 | 1,091 |
| 19,250 | 2.6331 s | 65,013,451 | 21,001,750 | 1,091 |
| 57,750 | 7.9019 s | 194,974,791 | 63,005,250 | 1,091 |

The same benchmark after declared coding and array preallocation measured:

| Rows | Wall time | Peak traced memory | Event bytes | Bytes/row |
|---:|---:|---:|---:|---:|
| 1,925 | 0.1352 s | 2,236,575 | 80,850 | 42 |
| 19,250 | 1.0995 s | 22,383,063 | 808,500 | 42 |
| 57,750 | 3.2363 s | 67,119,515 | 2,425,500 | 42 |

The stored event representation is therefore 42 bytes per row at every tested
scale, below the registered 100-byte target. The four mapping sources remain
the declaration objects named in section 3. A deterministic test constructs an
observed-data arm mapping that changes a prefix code when a later arm appears;
the shared prefix oracle rejects it. The same oracle accepts the codes obtained
from `ARM_CONFIGS`. Separate tests compare all four production code arrays to
their declared mappings and validate the frozen code-to-label manifest.

The artifact schema is `phase9-prevalence-v3`. Event computation defaults to
enabled; persistence defaults to disabled. The default manifest writes exactly
`summary` and `episode_lengths`, declares `events_persisted=false`, and retains
all four frozen mappings. Explicit `persist_events=true` is required for an
events table.

The corpus adapter binds reset reasons to the declared primary runtime source,
`primary_ewma78_permissive_expanding`. The other four scale-source blocks have
identical exact keys. Their reset values also match the primary block except for
52 `coverage_strict` rows; those unused disagreements are counted and disclosed,
not merged. Assignments, reset rows, and the output of
`anchor_outcome_completion` are joined only by exact `(session_id, tau_ns)`
identity in existing order. `anchor_outcome_completion.anchor_label_ns` is
explicitly mapped to the prevalence input's `ts_event_ns`; the first diagnostic
corpus-reading attempt exposed this schema-name boundary and a regression witness
now fixes it.

The final authorized suite execution was:

```text
python -m pytest tests --ignore=tests/test_bootstrap_acceptance.py -q
1504 passed, 2 skipped, 1 xfailed in 357.83s
```

The pass count moved from 1491 to 1504 because of the new encoding,
persistence, exact-join, and completion-label witnesses. Both platform skips
and the Phase 11 `consumed_vintage_artifacts` xfail are unchanged.
`tests/test_bootstrap_acceptance.py` was explicitly ignored and never
collected. No bare `pytest` command was run.

## 10. Throwaway diagnostic result and execution note

The complete external-temp evidence record measured:

```text
anchor_count                         78,390
arm_count                            10
assignment_rows                      783,900
reset_rows                           78,390
completion_rows                      78,390
matched_anchor_rows                  78,390
broadcast_rows                       783,900
unused_reset_disagreement_count      52
total_event_rows                     783,900
event_array_bytes                    32,923,800
summary_cell_count                   30
summary_status_counts                ok=30
episode_count_total                  23,102
episode_length_row_count             23,102
adapter_seconds                      2.3825
measurement_seconds                  7.6399
wall_seconds                         10.1548
peak_rss_bytes                       594,087,936
persisted_table_order                summary, episode_lengths
events_persisted                     false
temporary_output_bytes               18,344,584
temporary_output_deleted             true
```

These are wiring and shape measurements only. No cell or arm was interpreted,
compared, ranked, or selected.

Execution-note disclosure: the external launcher required retries. The first
launch failed before importing project code and read no corpus. The next exposed
the `anchor_label_ns` adapter defect before prevalence measurement. After that
fix, one attempt completed adapter, measurement, and temporary serialization,
then failed in the Windows peak-RSS instrumentation before printing its record;
its `finally` block deleted the temporary output. The corrected final attempt
produced the complete record above and also deleted its output. Consequently,
the corpus measurement path executed twice, not once, although neither execution
left an artifact. This exceeds the literal one-run target and is an explicit
scope finding for independent audit; it is not concealed as a single execution.

Nothing was written under `data/`, and no protected input was modified. No
production artifact, pinned output, receipt, checkpoint identity, protected-path
snapshot, ledger entry, production run, or Phase 10 work was created. No
selection, ranking, optimization, best-parameter search, expectancy, Sharpe,
P&L, currency figure, strategy change, or access to the confirmation tier
occurred.

## 11. Reset-source inertness and exclusion transparency repair

The independent audit initially questioned broadcasting the primary reset
series into the `coverage_strict` arm, then withdrew that finding after measuring
that the 52 differing rows were already undefined. The implementation session
independently re-derived the result directly from the memory-mapped Phase 7
artifact, without executing prevalence:

```text
exact reset-key rows                         78,390
primary/coverage_strict reset disagreements     52
primary reset at those rows                  none (52/52)
coverage_strict reset at those rows          gap_reset (52/52)
coverage_strict assignment_status            upstream_undefined (52/52)
coverage_strict category_code                -1 (52/52)
coverage_strict assignment_status == ok      0/52
effective reset overrule                     0/52
```

This is structurally explained by
`mnq_lab/conditioners/scales/returns.py`: strict coverage rejects an incomplete
bar and passes `INSUFFICIENT_COMPONENTS` to `_missing_status`, which emits
`GAP_RESET`. The invalid return propagates to an invalid relative-volatility row;
`build_assignments` in `mnq_lab/conditioners/assignments.py` then emits
`UPSTREAM_UNDEFINED` while leaving `category_code = -1`. Phase 9 defines an
episode position only when `state_anchor` is true and `assignment_status == OK`,
so all 52 rows close the episode before `reset_reason` can change the result.
The primary reset binding remains unchanged.

The audit's remaining low finding was that legitimate schedule exclusions were
not visible in `JoinReconciliation`. The reconciliation now records both:

- `excluded_session_count`: distinct completion-frame sessions actually removed;
- `excluded_completion_rows`: completion rows removed before the exact join.

`completion_rows` retains its post-exclusion meaning. A deterministic fixture
removes one session containing two completion rows and requires the reconciliation
to report `1` and `2`; a second fixture applies no exclusion and requires `0` and
`0`. A named always-zero mutant is passed through the same assertion and is
rejected, proving the nonzero witness is effective.
