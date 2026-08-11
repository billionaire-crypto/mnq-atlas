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
- immutable summary, completed-episode, and causal per-row event schemas; and
- deterministic `.npy` column stores validated and loaded read-only with
  `mmap_mode="r"`.

The audit repair advances the artifact schema to `phase9-prevalence-v2` by
adding the `events` table. Its prefix-attributable fields are state occurrence,
episode start, episode length so far, and entry/exit transition on the row where
the transition becomes observable. None depends on a later corpus denominator
or the eventual end of an episode.

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

Every acceptance requirement has a deterministic named control:

- **A:** one state-support count is repeated across the three horizons by
  construction, producing `(5, 5, 5)`. `measure_prevalence` has no
  horizon-dependent state-count branch. The named literal `(5, 4, 2)` instead
  proves the separate consistency guard rejects an externally inconsistent
  vector; it is not described as a measured horizon comparison.
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

For C-G, the production result and named mutation now pass through the exact
same `_assert_episode_count` oracle. The mutation must first produce its planted
wrong count, and the shared positive oracle must then raise. A and B exercise
their explicit `SpineError` guards. No random in-window mutation was used.

The timestamp witness separately proves an 08:30 CT bar-open label produces an
08:35 CT observation bucket and rejects 08:30 as the bucket.

## 6. Verification result

The sole authorized suite invocation was run exactly as registered:

```text
python -m pytest tests --ignore=tests/test_bootstrap_acceptance.py -q
```

Initial implementation result:

```text
1488 passed, 2 skipped, 1 xfailed in 357.48s (0:05:57)
```

Relative to the verified baseline, passing tests increased from 1468 to 1488,
the two Windows platform skips were unchanged, and xfails decreased from two to
one. The remaining xfail is `consumed_vintage_artifacts` for Phase 11.
`tests/test_bootstrap_acceptance.py` was excluded by the command and was never
collected, imported, or executed. No bare pytest command was run.

After the independent audit returned `OPEN`, the audit-repair suite ran through
the same authorized command and produced:

```text
1491 passed, 2 skipped, 1 xfailed in 357.76s (0:05:57)
```

The three additional passing cases are the direct repository `data/`,
exploration-child, and locked-confirmation-child write-guard witnesses. The
prefix positive and negative tests were replaced rather than duplicated, so
their count did not inflate. The protected bootstrap acceptance module remained
ignored and uncollected.

## 7. Implemented file identities

| SHA-256 | File |
|---|---|
| `531603cc32c249b5956f8217a558ff3a940323d0a54c04a9dfb887e1d57f999d` | `docs/PHASE9_PREREGISTRATION.md` |
| `6dedf603027c0fe46a30cdb9b2acfdc2d505e6f163a7373671521d8969866ad7` | `mnq_lab/phase9/__init__.py` |
| `996b539e05355493fa79be69f431b9d207ab62b3dde4bd69614023a4ec768215` | `mnq_lab/phase9/prevalence.py` |
| `f9cad3527d14e19b15e34b97157460f3c4d58d2b86b1c3e66a52782094e08322` | `mnq_lab/phase9/artifacts.py` |
| `7af0ba9759f6c0048d3324156c1c2c769c3fd3d3b51f271b850a91238933a01e` | `tests/test_prevalence_support.py` |
| `f6cbae98a21eb78223be5705309b8813bf67bc51b962e79bb19ff121308ddac2` | `tests/test_prefix_invariance.py` |

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

## 9. Independent-audit response

The `independent Claude Code audit session` returned `OPEN` at head
`148f4dafa66e7985768061c4606d058fc8c31f77`. The producer accepted its five
findings without converting them into a self-audit:

- **F1 repaired:** the full seven-row extension now enters
  `measure_prevalence`. Only afterward are causal event rows through the
  four-row cutoff compared with the short build. The test proves the full
  aggregate changed and that nonempty extension event rows remain. A
  corpus-normalized contribution using the full-build denominator is passed
  through the same equality oracle and rejected.
- **F2 repaired:** C-G positive production counts and negative mutant counts
  use the same episode-count assertion.
- **F3 clarified:** state prevalence is invariant by construction; the
  inconsistent-literal check is a separate guard, not a measured production
  branch.
- **F4 repaired:** three tests prove the serializer rejects direct `data/`,
  exploration, and locked-confirmation destinations before path creation.
- **F5 repaired:** the preregistration now records the exact authorization
  question and answer while identifying the addition as post-audit context and
  preserving the original pre-implementation commit identity.

The integration residual identified by the auditor remains accurately open for
any future production authorization: no production adapter or corpus run was
added in this implementation-only repair. Independent re-audit must decide
whether the repair closes Phase 9.
