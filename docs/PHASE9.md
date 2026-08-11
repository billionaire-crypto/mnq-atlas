# Phase 9 Implementation Closeout - Prevalence on Its Own Support

**Program:** `mnq-atlas-001`  
**Specification:** `REV6_FROZEN_SPEC.md`, revision 6  
**Implementation date:** 2026-08-10  
**Branch:** `phase-7b-outcome-layer`  
**Producer identity:** `Codex implementation session`  
**Status:** implementation complete; production not run; independent audit pending

## 1. Authorization chronology

Implementation began only after the operator's authorization was recorded
verbatim in `docs/PHASE9_PREREGISTRATION.md`. The authorization record was the
first and only file in commit
`f375c68cb27739ab5ded2018e8de144c86d62593`.

The authorization was implementation-only. No production/corpus run, artifact
emission, or `data/` write was authorized or performed.

## 2. Implemented scope

Commit `9fa96a9e3f8337b6875d777c0aa162b7739d1f77` adds:

- an aligned Phase 7 assignment / existing completion-support input contract;
- horizon-invariant state-anchor prevalence;
- both path-estimand eligibility count families at 15, 30, and 60 minutes;
- bar occupancy, episode count, descriptive episode lengths, session presence,
  entry transitions, and exit transitions;
- complete declared arm-category emission with explicit empty and unsupported
  statuses;
- `n_anchors`, `n_sessions`, and reserved NaN `weight_ess` companions;
- observation-time validation from the bar open plus 300 seconds, localized in
  `America/Chicago`;
- immutable result table schemas; and
- deterministic `.npy` column stores validated and loaded read-only with
  `mmap_mode="r"`.

There is no Phase 9 corpus runner. The implementation serializer rejects a
repository `data/` destination and cannot overwrite an existing output root.

Commit `837de49c94f0eb81c5e52515537c0024b12cf385` converts
`prevalence_results` from a deferred xfail to a real prefix-invariance test.
It retains `consumed_vintage_artifacts` as the one Phase 11 xfail.

## 3. Episode predicate

For consecutive supplied rows within an arm, the implementation permits an
episode/transition edge exactly when:

1. the previous row is a supplied state anchor with assignment status `ok`;
2. the current row is a supplied state anchor with assignment status `ok`;
3. session identifiers are equal;
4. current `tau_ns` equals previous `tau_ns + BAR_NS`;
5. the current reset reason is not `gap_reset`; and
6. the current reset reason is not `roll_reset`.

These expose the section 10.2 reset terms independently:

- a session boundary fails item 3;
- an absent timestamp step fails item 4, while an observed gap reset fails item
  5;
- a contract roll fails item 6; and
- warmup/undefined assignment fails item 1 or 2 and closes the active run.

`session_phase` is not an adjacency term. Therefore a same-category run remains
one episode across a contiguous within-session phase boundary.

Phase 7's `_runs_and_transitions` additionally requires equal session phase and
uses the combined `diagnostic.reset_before`. That predicate remains unchanged
because it serves the within-phase section 10.1 diagnostic. Applying it here
would over-segment section 10.2 episodes and understate their lengths.

## 4. Outcome-eligible naming reconciliation

The section 10.2 singular schematic name is not introduced as a new or
collapsed quantity. Phase 9 carries both already-implemented completion columns
through under their exact estimand-qualified names:

```text
outcome_eligible_fully_labeled_1m_grid_h15/h30/h60
outcome_eligible_observed_bar_path_h15/h30/h60
```

No existing column was renamed, no estimand was selected, and the two series
were not combined.

## 5. Test 14 witnesses and negative controls

Every acceptance assertion has a deterministic named control that is expected
to fail the positive assertion:

- **A:** the positive fixture reports `(5, 5, 5)` state anchors. The named
  horizon-dependent mutant substitutes eligible counts `(5, 4, 2)` and is
  rejected with `state-anchor prevalence depends on outcome horizon`.
- **B:** both estimands are non-increasing, with strict decreases in the
  fixture. The named increasing mutant `(2, 3, 3)` is rejected with
  `outcome eligibility increases with horizon`.
- **C:** two contiguous rows with different session identifiers form two
  episodes. Omitting the session term joins them into one, and the episode-count
  assertion rejects the joined result.
- **D:** a contiguous row carrying `gap_reset` starts a second episode. Omitting
  the gap term joins it, and the assertion rejects the joined result.
- **E:** a contiguous row carrying `roll_reset` starts a second episode.
  Omitting the roll term joins it, and the assertion rejects the joined result.
- **F:** an explicit warmup row between equal states closes the first episode.
  Carrying state through warmup joins the runs, and the assertion rejects the
  joined result.
- **G:** contiguous equal states across the `open` to `morning` boundary remain
  one length-two episode. Adding the Phase 7 phase-equality term splits it into
  two, and the assertion rejects the split result.

The authorized suite executed all seven controls. Each control passed only
because its expected `SpineError` or `AssertionError` was observed. No random
in-window mutation was used.

The timestamp witness separately proves an 08:30 CT bar-open label produces an
08:35 CT observation bucket and rejects 08:30 as the bucket.

## 6. Verification result

The sole authorized suite invocation was run exactly as registered:

```text
python -m pytest tests --ignore=tests/test_bootstrap_acceptance.py -q
```

Result:

```text
1488 passed, 2 skipped, 1 xfailed in 357.48s (0:05:57)
```

Relative to the verified baseline, passing tests increased from 1468 to 1488,
the two Windows platform skips were unchanged, and xfails decreased from two to
one. The remaining xfail is `consumed_vintage_artifacts` for Phase 11.
`tests/test_bootstrap_acceptance.py` was excluded by the command and was never
collected, imported, or executed. No bare pytest command was run.

## 7. Implemented file identities

| SHA-256 | File |
|---|---|
| `662020d59c91e9a4b9201457a3f8e95dbc54712ace2595de46d32d46d1e90b82` | `docs/PHASE9_PREREGISTRATION.md` |
| `bfc3d118d05f80002abb4d45dab882a9745bdee5a8927e0d63793d1fc456d640` | `mnq_lab/phase9/__init__.py` |
| `b173ed3a8ce7fbc5924ad908464986e942cba6628dd706887655bf60ec5102e5` | `mnq_lab/phase9/prevalence.py` |
| `d9e2a0acb61a5daeb15f9716d7b6716db55ac07343cd3f3b212c18f7360005df` | `mnq_lab/phase9/artifacts.py` |
| `508902e80171636bd22b4c4119ef857c162fd1a76f172d6d6d38ce033a4213d0` | `tests/test_prevalence_support.py` |
| `79e344a9b0e9ffcb8ef2a4097e736f9d2652b7ee5f7f403930c7a1931e1487b9` | `tests/test_prefix_invariance.py` |

This closeout file is committed separately after those identities and is
reported at its final hash in the producer handoff.

## 8. Work explicitly not performed

No production or corpus prevalence run was executed. No production artifact or
generated corpus array was emitted. Phase 9 code did not access a `data/` path,
and nothing under `data/` was written. The locked confirmation tier was not
accessed. No Phase 7, Phase 8, ledger, constants, protected receipt,
discrepancy, calendar-corroboration, or production file was modified. The
protected stash was not inspected or changed. Phase 10 was not begun.

No selection, ranking, optimization, parameter choice, strategy search,
composite state score, state pass/fail verdict, expectancy, Sharpe ratio, P&L,
or currency figure was produced. Nothing was pushed, tagged, published, or
merged to main.

This producer closeout does not audit or ratify the implementation. Independent
audit remains required.
