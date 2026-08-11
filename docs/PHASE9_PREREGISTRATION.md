# Phase 9 Preregistration - Prevalence on Its Own Support

**Program:** `mnq-atlas-001`  
**Specification:** `REV6_FROZEN_SPEC.md`, revision 6  
**Contract date:** 2026-08-10  
**Base:** `0345f16b8b3557150e0df48b249b6b8acce52232`  
**Branch:** `phase-7b-outcome-layer`  
**Producer identity:** `Codex implementation session`  
**Status:** implementation authorized; production run not authorized

## 1. Operator authorization and scope

The operator gave the following authorization in the Codex conversation on
2026-08-10, before this document and before any Phase 9 implementation code was
written:

> YES I AUTHORIZED. Also when u are done with any fixes, builds, implementations, u should always give me an audit prompt in indented block for claude code to share ur fixes, findings and audit questions. Then after the indented block, u should give me a short summary of what u did, what u are asking in simple easy to understand english. Applies for this whole session.

This authorization is interpreted narrowly as **implementation only**. It
authorizes creation of `mnq_lab/phase9/`, its tests, this preregistration, a
Phase 9 implementation closeout, the one authorized test suite, and small
commits on the named branch.

No production run is authorized. In particular, this authorization does not
permit executing the prevalence layer over the corpus, emitting a production
artifact, writing anywhere under `data/`, accessing locked confirmation data,
or beginning Phase 10. Production requires a separate future authorization,
preflight, receipt, checkpoint identity, and protected-path snapshot.

This document is a producer-authored implementation contract, not an audit or
ratification entry. The producer will not name itself as auditor and will not
issue an audit-ledger entry.

## 2. Frozen phase boundary

Phase 9 implements only frozen-spec section 10.2 and build-order row 9:
prevalence on horizon-invariant state support and descriptive occurrence
decomposition. It measures, for every declared arm and category:

- state-anchor count;
- outcome-eligible count for each declared estimand and horizon;
- bar occupancy;
- continuous episodes and their run-length distribution;
- session presence;
- entry transitions; and
- exit transitions.

State validity remains descriptive only. Phase 9 emits no pass/fail state
verdict, composite score, threshold, contrast, hypothesis, null, p-value,
strategy, ranking, selection, optimization, or trading result. Phase 10 and
later phases remain out of scope.

## 3. Inputs and support identity

Phase 9 consumes aligned, already-computed Phase 7 assignment fields and the
following columns from `anchor_outcome_completion`; it does not recreate any
of them:

```text
state_anchor
outcome_eligible_fully_labeled_1m_grid_h15
outcome_eligible_fully_labeled_1m_grid_h30
outcome_eligible_fully_labeled_1m_grid_h60
outcome_eligible_observed_bar_path_h15
outcome_eligible_observed_bar_path_h30
outcome_eligible_observed_bar_path_h60
```

`state_anchor` is the sole prevalence support and remains independent of every
future-window horizon. A category occurrence is a supplied `state_anchor` row
whose supplied Phase 7 assignment is defined and equals that category.
Undefined and warmup assignments are not silently recategorized.

### 3.1 Outcome-eligible naming reconciliation

Frozen section 10.2 uses the singular schematic name
`outcome_eligible_anchors_h{15,30,60}`. Frozen sections 6 and 14, and the
implemented completion layer, define two path estimands. Phase 9 therefore
carries both implemented boolean series through unchanged and summarizes each
under its full name:

```text
outcome_eligible_fully_labeled_1m_grid_h{15,30,60}
outcome_eligible_observed_bar_path_h{15,30,60}
```

The series are never collapsed, combined, or renamed to the singular schematic
name. This is a visible reconciliation, not a silent choice between estimands.

## 4. Observation-time and ordering contract

Input timestamps are UTC int64 nanoseconds. `ts_event` is the bar open, and a
five-minute bar covers `[t, t + 300 seconds)`. Phase 9 derives
`anchor_observation_time = ts_event + 300 seconds` and keys any time-of-day
label from that observation time in `America/Chicago`, never from the bar-open
label. Tests use the frozen 08:30 CT label / 08:35 CT observation witness.

Rows must already be unique and strictly chronological within the declared
arm order. Structural input disagreement fails closed. Phase 9 does not sort
on any measured value and does not repair duplicates, ordering, missing
identities, unknown statuses, or unknown reset reasons.

## 5. Section 10.2 episode and transition predicate

For consecutive supplied rows within one arm, a transition edge exists only
when all of the following are true:

```text
previous and current assignments are defined (not warmup/undefined)
previous.session_id == current.session_id
current.tau_ns == previous.tau_ns + BAR_NS
current.reset_reason != gap_reset
current.reset_reason != roll_reset
```

The four section 10.2 reset mechanisms are represented independently:

1. **session boundary:** session identifiers differ;
2. **missing interval:** the expected timestamp step is absent or the current
   row carries `gap_reset`;
3. **contract roll:** the current row carries `roll_reset`; and
4. **warmup:** the current or immediately preceding assignment is not defined,
   so no edge crosses that row.

The current row's `session_phase` is deliberately absent from this predicate.
A same-category run with contiguous timestamps in one session continues across
a phase change.

This differs intentionally from Phase 7's `_runs_and_transitions` predicate in
`mnq_lab/conditioners/state_validity.py`, which additionally requires
`previous.session_phase == current.session_phase` and uses the conflated
`diagnostic.reset_before`. That Phase 7 predicate is correct for its
within-phase section 10.1 diagnostic. Reusing it for section 10.2 would split
episodes at every phase boundary and understate their lengths. Phase 9 will not
modify that audited file.

An episode is a maximal consecutive run of one category over valid transition
edges. Entry and exit transitions count only defined category changes over
such edges; a reset starts or ends an episode but is not itself counted as an
entry or exit transition.

## 6. Declared cells, quantities, and statuses

The declared inventory is structural arm order crossed with the closed Phase 7
category order. Every declared cell is emitted, including a category with no
occurrence and an arm with no support.

For each arm-category cell:

```text
state_anchors       supplied state-anchor rows assigned to the category
n_anchors           all supplied state-anchor rows in the arm
n_sessions          sessions contributing at least one arm state anchor
weight_ess           NaN; no weights are computed in Phase 9
bar_occupancy        state_anchors / n_anchors
episodes             maximal category runs under section 5
episode_length       one descriptive row per run, in chronological order
session_presence     distinct sessions containing the category
entry_transitions    valid edges from another category into this category
exit_transitions     valid edges from this category to another category
```

Every `n_anchors` is immediately accompanied by `n_sessions` and `weight_ess`.
`weight_ess` carries NaN and `weight_ess_status=not_computed_in_phase9`; this is
an explicit reserved field, not a numerical claim. The closed cell statuses
are descriptive:

```text
ok
empty_state
unsupported_no_state_anchor_support
unsupported_no_arm_rows
```

No status is a state-quality verdict. Episode-length output includes an
explicit status row for an empty or unsupported declared cell, so a thin cell
cannot disappear from either output table.

## 7. Artifact boundary and storage

Phase 9 owns a separate immutable result-table abstraction and deterministic
`.npy` column-store serializer. Loading uses `numpy.load(..., mmap_mode="r")`.
No parquet dependency or fallback is permitted. The serializer may write only
to a caller-supplied non-`data/` path and is not a corpus runner.

No Phase 9 key enters a Phase 7 artifact bundle. The existing literal
`prevalence` guard in `mnq_lab/conditioners/artifacts.py` remains unchanged and
unspecial-cased. Production and execution code will not import `mnq_lab.phase9`.

## 8. Acceptance tests and negative controls

`tests/test_prevalence_support.py` implements frozen Test 14 with deterministic
witnesses:

- **A:** equal state-anchor counts at horizons 15, 30, and 60; negative control
  uses outcome eligibility as prevalence and must be rejected.
- **B:** each estimand's eligible counts are non-increasing by horizon and at
  least one strictly falls; negative control supplies an increasing horizon
  count and must be rejected.
- **C:** a session boundary splits a same-category run; negative control omits
  the session term and joins it.
- **D:** a gap splits a same-category run; negative control omits the gap term
  and joins it.
- **E:** a roll splits a same-category run; negative control omits the roll
  term and joins it.
- **F:** warmup splits a same-category run; negative control skips the warmup
  row and joins the surrounding states.
- **G:** a session-phase change does not split a contiguous same-session run;
  negative control imports the Phase 7 phase term and over-segments it.

Each negative control is named and wrapped by an assertion that proves the
positive property would reject it. No random in-window mutation is used.

`tests/test_prefix_invariance.py` removes only `prevalence_results` from the
deferred list and adds a real short-build/extended-build test. It includes
nonempty prefix and extension guards and a named corpus-normalized negative
control that changes prior prevalence when future rows arrive.
`consumed_vintage_artifacts` remains deferred and xfailed for Phase 11.

## 9. Validation and protected boundaries

The only authorized suite command is:

```text
python -m pytest tests --ignore=tests/test_bootstrap_acceptance.py -q
```

`tests/test_bootstrap_acceptance.py` must never be collected or run. The
expected movement from the verified baseline is increased passing tests, two
platform skips unchanged, and exactly one xfail. Any other movement is a
finding to investigate and report, not a reason to relax a check.

The producer will not modify `docs/DISCREPANCIES.md`,
`analysis_constants_v1.yaml`, any Phase 8 receipt-protected path, the two
untracked D19 files, a protected stash, or any path under `data/`. No dataset,
generated array, cache, secret, production artifact, audit entry, certificate,
push, tag, publication, or main-branch change is authorized.
