# Session availability v2 — frozen input contract

Stage 6 of the D32/D33 repair. This document **freezes** the inputs, definitions,
schemas and expectations that the Phase 7 + Unit O v2 rebuild will be run
against, before any real production run occurs.

It is a **new versioned specification**. It edits no frozen v1 document. Where it
differs from `docs/SESSION_AVAILABILITY_V2_DESIGN.md`, this contract governs.

Authorising rulings: D32, D33, D34, D35 in `docs/DISCREPANCIES.md`.
Nothing here authorises a production run.

**Revision 2.** Revision 1 did not pass audit. Three statements were wrong or
unsupported and are corrected here: §6 undercounted the Phase 7 relabelling as
six sessions when 39 session identities change classification; §6 stated the
outcome-status change as 1,344 without counting the 34,920 renames; and §5.1
justified itself with Phase 8 behaviour that exists only in uncommitted source.
§7's "verified end-to-end" is downgraded to a required preflight invariant, and
§11 is widened to permit equality-only comparison of conditioner values. The
corrections are recorded rather than silently applied: revision 1 is superseded
in place because it never achieved a CLOSED audit, so there is no ratified
document to supersede.

---

## 1. Frozen input identities

| input | identity | bytes | sha256 |
|---|---|---:|---|
| accepted calendar | `mnq-cme-equity-index-calendar-v1` | 447,577 | `b86e112c16112bf11a6a548ca8b3f21d28a08f90442b4dde84098f9d3f6eb069` |
| session-exclusion registry | `mnq-session-exclusion-registry-v1` | 1,353 | `0a37822f05a9bb895c8ac421c64bc1849b644985e5f6cd016658bbf479055e75` |
| exclusion registry manifest | — | 405 | `f6e8b15c34400c3793c7d5a991b33141a15cce986c173755790fc84582668f66` |

**There is no calendar v2.** Calendar v1 already carries
`scheduled_rth_open_ct`, `scheduled_rth_close_ct` and `scheduled_rth_status` for
all 1,018 sessions (populated on 1,008; the ten blanks are 9 holidays plus
20210402, which the validator requires to be empty). Minting a v2 with identical
scheduled-session content would create a second calendar identity for no
scientific gain. User ruling; recorded in the design document §12.

**There is no registered interruption input.** Authoritative CME/MNQ halt and
resumption boundaries were not established (D33). The `StructuralInterruption`
machinery exists and is tested, but carries no record. The four affected
sessions are handled by whole-session exclusion instead.

**Exclusion registry contents**, frozen: `20200309`, `20200312`, `20200316`,
`20200318`, each with reason `excluded_unresolved_official_interruption`,
source `docs/DISCREPANCIES.md#D33`, ruling `D33`. The registry references
calendar v1 by sha256 and does not modify it; calendar v1 still classifies all
four as `regular` / `full_rth`.

---

## 2. Structural availability definition

Contract version `session-availability-v1`
(`mnq_lab/spine/availability.py`).

An outcome window is **structurally available** when every timestamp the horizon
requires is observable according to the *schedule*. Availability is never a
function of what was observed: the decision function accepts no bars, no store
and no observed data of any kind, so inferring a close from absent data is not
expressible.

Evaluation order, and each rank's reason for sitting where it does:

1. **session excluded** → raises. An excluded session has no admissible window at
   all, so it never reaches the schedule arithmetic.
2. **no scheduled RTH** → unavailable, reason `no_scheduled_rth`.
3. **window exceeds the scheduled close** → unavailable, reason `scheduled_close`.
4. **window intersects a registered interruption** → unavailable, reason
   `registered_interruption`.
5. otherwise → available, reason `not_applicable`.

## 3. Boundary convention

- The outcome window is half-open `[τ, τ + Δ)`, consistent with `ts_event` being
  the bar OPEN and the interval `[t, t + bar_seconds)`.
- Available requires `τ ≥ scheduled_rth_open_ct` and
  `τ + Δ ≤ scheduled_rth_close_ct`. **Equality at the close is AVAILABLE.** This
  reproduces the v1 rule exactly on a full 15:00 session.
- An interruption `[s, e)` blocks the window iff `τ < e AND s < τ + Δ`. A window
  ending exactly at `s`, and one beginning exactly at `e`, both remain available.
- Wall-clock semantics are preserved. Trading time is never compressed across an
  interruption and no later bar is substituted for a missing scheduled timestamp.
- There is **no fallback close**. An absent or wrong-typed schedule raises.

**Measured equivalence to v1**, over all 1,018 sessions × 78 τ × 3 horizons:

| status | agree | differ | sessions |
|---|---:|---:|---:|
| `full_rth` | 228,384 | **0** | 976 |
| `shortened_rth` | 4,095 | 3,393 | 32 |
| `no_scheduled_rth` | 18 | 216 | 1 |
| `full_exchange_holiday` | 162 | 1,944 | 9 |

Zero differences on full sessions is the load-bearing property: the v1 boundary
is preserved by construction wherever the schedule closes at 15:00.

---

## 4. Phase 7 session-quality vocabulary

Closed, seven values, in precedence order
(`mnq_lab/spine/session_quality.py`):

1. `excluded_unresolved_official_interruption`
2. `no_scheduled_rth`
3. `registered_structural_interruption`
4. `observed_unexplained_mid_session_gap`
5. `scheduled_early_close`
6. `observed_unresolved_early_termination`
7. `ok`

Rank 4 sits **above** rank 5 deliberately: an early close explains a session
*ending* early, it does not explain a hole in the middle of one, and the opposite
ranking would let a scheduled close swallow an unexplained gap.

`unresolved_truncated_session` is **retired**. It asserted that the whole day was
truncated, which was false for the four sessions carrying only a temporary
intraday gap.

**Frozen expected partition** of the 1,009 exploration sessions:

| quality | n |
|---|---:|
| `ok` | 970 |
| `scheduled_early_close` | 32 |
| `excluded_unresolved_official_interruption` | 4 |
| `observed_unresolved_early_termination` | 2 |
| `no_scheduled_rth` | 1 |

The groups are disjoint. Any departure from this partition halts the rebuild and
is reported, not accommodated.

---

## 5. Unit O v2 schema and status precedence

Artifact schema `unit-o-outcomes-v2`. Phase 7 artifact schema
`phase7-conditioner-artifacts-v2`. The v1 identifiers remain attached to the v1
artifacts and are not reused.

**Schema change:** one column added, `structural_unavailability_reason`
(`<U24`), immediately after `outcome_status`. Column count 25 → 26. The Phase 7
column set is unchanged; its identifier changes because `data_quality_status`
carries a new closed vocabulary and excluded sessions contribute no rows.

**Outcome status vocabulary**, closed, in precedence order:

1. `anchor_bar_missing`
2. `structurally_unavailable` — renamed from `window_outside_rth`
3. `path_timestamp_missing`
4. `path_session_mismatch`
5. `path_symbol_mismatch`
6. `insufficient_components` (fully-labeled estimand only)
7. `ok`

`structurally_unavailable` is 24 characters and fits the existing `<U25` dtype.
The rename is required: `window_outside_rth` asserts the window left RTH, which
is false for a scheduled early close and actively false for an intraday
interruption.

**Reason vocabulary**, closed: `not_applicable`, `no_scheduled_rth`,
`scheduled_close`, `registered_interruption`. Invariant, enforced both ways: the
reason is non-`not_applicable` **iff** the status is `structurally_unavailable`.
A structurally unavailable row can never report `window_fits_rth = True`.

### 5.1 Binding consumer rule

**`anchor_bar_missing` outranks `structurally_unavailable`.** A row whose anchor
bar is absent *because the session had already closed* therefore displays
`anchor_bar_missing` with reason `not_applicable`. Approximately 5,874 rows are
in this position.

Consequently:

- **Every completion, eligibility or denominator calculation MUST use the fit
  predicate `window_fits_rth`, never `outcome_status`.** The status axis is a
  display and diagnostic axis; the fit axis is the structural one.
- `outcome_status` MUST NOT be rendered as a *cause* without `window_fits_rth`
  beside it.
- A future consumer MUST NOT infer structural eligibility from the status string.

This ranking was chosen to reproduce the pinned witness and keep the v1↔v2 diff
narrow, and was independently ruled defensible. The residual is recorded here
rather than resolved silently, and rank 1 is **not** frozen as permanently
correct — it may be revisited under a later ruling.

**State of compliance, stated precisely.** No completion, eligibility or
denominator surface reads `outcome_status` anywhere: verified against *committed*
source in `outcomes/completion.py`, `phase8/diagnostics.py`,
`phase8/production.py`, `phase8/day_types.py` and `phase8/contrasts.py`, all
zero references. `outcomes/completion.py` builds its denominator from
`state_anchor AND` its fit predicate.

**Committed Phase 8 does NOT yet consume the fit predicate.** It passes
`arm.active` directly as `structurally_eligible` in all three completion paths
(contrast, day-type, interaction) and loads `window_fits_rth` into its input
schema without using it there. Making Phase 8's denominator fit-aware is
**Stage 11 work and is not part of this contract**. Revision 1 wrongly justified
§5.1 by describing that behaviour as present; it exists only in uncommitted
source, which is not contract evidence.

The rule above is therefore **normative for Stage 11 and beyond**, not a
description of current Phase 8 behaviour. It is enforced mechanically by
`tests/test_completion_uses_fit_not_status.py`, which runs against committed
source so that uncommitted work cannot mask a violation.

---

## 6. Expected changed fields

All counts below are over **retained** rows, i.e. after the four excluded
sessions are removed. Every figure is an exact tripwire: production must
reproduce it, and any departure halts the rebuild.

| field | expectation |
|---|---:|
| `window_fits_rth` | 7,218 rows change (3,609 per path estimand) |
| `outcome_status` — rename | 34,920 rows: `window_outside_rth` → `structurally_unavailable` |
| `outcome_status` — precedence | 1,344 **additional** rows, all currently `path_timestamp_missing` |
| `outcome_status` — **total** | **36,264** string changes on shared rows |
| `structural_unavailability_reason` | new column |
| `data_quality_status` | **39 sessions** change classification; **27,300** retained assignment rows |
| Unit O row count | 472,212 → 470,340 (−1,872) |
| Phase 7 assignment rows | 787,020 → 783,900 (−3,120, the four excluded sessions) |
| distinct sessions | 1,009 → 1,005 |

Of the 7,218 fit changes, 5,874 are currently `anchor_bar_missing` and **keep**
that status; 1,344 are currently `path_timestamp_missing` and become
`structurally_unavailable`. The 34,920 renames are mechanical and independent of
the fit changes.

**Phase 7 relabelling in full.** Revision 1 said "6 sessions", counting only
those previously flagged `unresolved_truncated_session`. That was an undercount:
32 sessions previously labelled `ok` become `scheduled_early_close`, and one
becomes `no_scheduled_rth`. The complete transition census is:

| v1 label | v2 label | sessions |
|---|---|---:|
| `ok` | `ok` | 970 |
| `ok` | `scheduled_early_close` | 32 |
| `ok` | `no_scheduled_rth` | 1 |
| `unresolved_truncated_session` | `observed_unresolved_early_termination` | 2 |
| `unresolved_truncated_session` | `excluded_unresolved_official_interruption` | 4 |

39 sessions change label. 35 of them are retained and carry 780 assignment rows
each, so 27,300 rows change `data_quality_status`; the remaining 4 are excluded
and their 3,120 rows disappear entirely.

## 7. Expected unchanged fields

These must be **byte-identical** on every shared row, and a difference halts the
rebuild rather than being explained afterwards:

- `n_present_bars`, `n_required_bars`, `n_fully_labeled_bars`
- all four outcome magnitude columns, on every shared **defined** row
- `outcome_valid` and `common_support`, unless the corrected registered contract
  independently proves otherwise
- every Phase 7 conditioner value: `scale_value`, `seasonal_profile`, `vol_rel`,
  thresholds, `category_code`, `category_name`
- calendar classifications for all 1,018 sessions

**Measured basis for the conditioner expectation:** the four excluded sessions
carry **zero valid scale rows across all five arms** (1,560 rows, 312 per arm,
none valid), so they never entered the seasonal reference pool. The seasonal and
threshold dependency pools admit only valid scale and `vol_rel` rows, so removing
them cannot move a median.

**Status of the end-to-end figure.** A run through seasonal → vol_rel →
thresholds → assignments returned 0 differences in 78,702 rows. That measurement
is **not reproducible from these commits**: no v2 artifact exists and no
committed comparison witness reproduces it. It is therefore recorded as a
**required preflight invariant**, not as a verified result. Stage 7 preflight
must reproduce it and halt on any difference. Revision 1 stated it as "verified
end-to-end", which was stronger than the evidence available from the repository.

If any existing defined outcome magnitude changes, work stops and reports the
first row identity and its dependency **without printing the magnitude**.

---

## 8. S00 re-derivation procedure

1. Reproduce S00 v1 exactly under its original definition first, confirming
   h15 `0.9942923801191518`, h30 `0.9900012498437696`, h60 `0.9818772653418323`
   → 0.99 / 0.99 / 0.98.
2. Re-derive from the corrected structural population using the **unchanged**
   registered rule `max(0.90, floor(s00_p05 * 100) / 100)`.
3. Expected h15 → 0.99, h30 → 0.99, h60 → 0.99. **Do not force these values.** If
   independent reproduction differs, stop and report.
4. Record every cell numerator and denominator, the exact fifth-percentile value,
   the floor calculation, the input hashes, the Unit O v2 certificate hash, the
   code commit, the environment and the limitations.
5. Write `data/exploration/s00/s00_threshold_input_v2.json`. Never edit the v1
   record. Never edit `analysis_constants_v1.yaml`; corrected values go to a new
   versioned constants file.

Only completion and coverage information may be used. No outcome magnitude is
inspected.

## 9. Versioned output roots

| product | path / identifier |
|---|---|
| Phase 7 + Unit O v2 tree | `data/exploration/derived/phase7-unit-o-session-aware-v2/` |
| Unit O v2 certificate | `unit_o_ratification_certificate_v2` |
| S00 v2 record | `data/exploration/s00/s00_threshold_input_v2.json` |
| constants v2 | `analysis_constants_v2.yaml` |
| Phase 8 v2 tree | `data/exploration/derived/phase8-session-aware-v2/` |
| Phase 8 v2 checkpoint | `data/exploration/derived/phase8-session-aware-v2.checkpoint/` |

No v1 path is reused, overwritten or renamed. v1 checkpoints are never resumed.

## 10. Audit and ratification requirements

- A genuinely separate auditor verifies source provenance, calendar and exclusion
  correctness, boundary behaviour, changed and unchanged fields, status
  precedence, manifests, hashes, checkpoints, memory, exit status, v1
  immutability, and that no outcome value was interpreted.
- Claude Code must not invent a separate identity and self-ratify.
- A certificate issues only after a CLOSED verdict, and binds the v2 tree hash,
  run commit, audit-entry hash, calendar v1 hash, exclusion registry hash,
  environment fingerprint, and an honest statement of attestation limits.
- Per D34 and D35, every protected-hash check verifies against **the commit the
  attestation describes**, never the live working tree.

---

## 11. Provenance of instrument choices

Every choice frozen in this document was made using only: schedule information,
the exclusion registry, structural fit, completion counts, coverage counts,
session and row identities, file hashes, source code, and **equality-only
comparison of conditioner values** — that is, counting how many rows differ,
never reading, reporting or interpreting a magnitude.

That last category is stated explicitly because one measurement did touch
conditioner values: confirming the excluded sessions contribute nothing to the
seasonal pool required computing seasonal profiles both ways and counting
differences. Conditioner scales are covariates, not outcomes, and only equality
counts were produced. Revision 1 said "using only" the structural list while
admitting that access in the next sentence; the list is widened here rather than
the admission being dropped.

**No tick, quantile, contrast, interval or any other outcome magnitude informed
any choice recorded here.** No outcome column was read at any point.

## 12. Known limitations

1. **CME interruption boundaries remain unestablished.** The primary-source sweep
   terminated on resource limits rather than exhausting the source space, so the
   negative result is "not established", never "proven absent". Should
   authoritative boundaries later emerge, they enter as a new versioned
   interruption record and a new versioned population, never by editing this
   contract or any artifact built under it.
2. **Whole-session exclusion is conservative, not optimal.** It removes anchors
   that might have been valid. It cannot manufacture a valid outcome from a
   structurally undefined one.
3. **The `anchor_bar_missing` ranking is a recorded residual**, not a settled
   result. See §5.1.
4. **`registered_structural_interruption` is untested against real data**, since
   no interruption is registered. Its behaviour is pinned only by synthetic
   witnesses.
5. **A pre-open window currently reports reason `scheduled_close`**, which is a
   misnomer. The branch is unreachable on calendar v1, where every RTH-bearing
   session opens at 08:30 and the τ grid starts at 08:30. If a later-opening
   session is ever registered, that reason code must be revisited rather than
   reused.
6. **Every v2 count in §6 and §7 is a FORECAST**, derived from v1 plus the
   corrected rules, before any v2 artifact exists. They are exact tripwires for
   the Stage 7 preflight, not observed attestations. If preflight differs, work
   stops and this contract is superseded under a new ruling rather than edited to
   match the output.
7. **The 78,702-row conditioner-invariance result has no committed witness.**
   See §7. It must be reproduced at preflight.
8. **`registered_structural_interruption` is untested against real data.** Beyond
   the synthetic pinning noted above, the first real interruption record will
   require a new versioned input AND end-to-end real-data validation of the
   resolver, the classifier, Unit O and every completion consumer — not merely a
   registry entry.
9. **Hash-pinned prose cannot detect semantic drift.** The pin prevents this
   document being edited; it cannot notice that the code has moved away from what
   the document says. That gap is why §5.1 is enforced by a test rather than by
   this paragraph, and why §12.6 exists.
10. **Commit-diff wording.** For the record, and correcting an imprecision noted in
   audit: commit `08c14ba`'s *diff* contains no D31 Phase 8 change and does not
   add `tests/test_phase8_structural_completion.py`. The `mnq_lab/phase8` package
   is of course present in that tree; the claim is about the diff, not the tree.
