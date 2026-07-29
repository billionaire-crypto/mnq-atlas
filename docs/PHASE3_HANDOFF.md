# Phase 3 handoff — S00 completion atlas and threshold freeze

This is the continuity document for a new implementation session. Phase 1 and
Phase 2 are complete. Phase 3 must build the deterministic S00 completion atlas,
derive horizon-specific completion thresholds, ledger them, and write them into
`analysis_constants_v1.yaml` **before any S01A result is computed**.

Phase 3 is a measurement and preregistration phase. It is not a strategy search,
does not compute conditional excursion results, and must stop after its own audit.

## 1. Roles and working agreement

- **Codex:** developer. Implements code, tests, documentation, and fixes.
- **Opus 5:** quant and routine independent auditor. It must ratify the threshold
  mathematics before implementation and audit each freeze step afterward.
- **Fable 5:** escalation auditor only for the hardest unresolved defects or a
  high-risk final dispute.
- After each completed coding unit, Codex supplies a compact ready-to-paste Opus
  audit prompt.

Developer-authored replay scripts, tests, tables, and prose are claims, not audit
evidence. Mutations for audits run only in external disposable clones.

## 2. Immutable starting state

Repository:

```text
repo                 C:\mnq-atlas
current branch       phase-2-time-model
Phase 2 signed-off   b0ebf472edb1467b79e4009da2377c23604433a4
next branch          phase-3-s00
Phase 1 base         de73fa4 (phase-1-spine)
```

The Phase 3 branch should be created from the commit containing this handoff,
whose parent is the signed-off Phase 2 commit above. Do not branch from
`origin/phase-2-time-model`: the local Phase 2 branch contains audited commits not
yet pushed at handoff time.

Starting replay:

```powershell
git status --short --branch
git log -6 --oneline
python -m pytest tests -q
python -m mnq_lab.spine.gates --store data
python -m mnq_lab.outcomes.completion --store data
```

Expected:

```text
tests                 294 passed, 5 xfailed
Phase 1 gates         4/4 pass
exploration sessions  1,009
completion gridpoints 78,702 = 1,009 × 78
flag census           34 observed_rth_ended_early
                       1 observed_no_rth_bars (20210402)
                       4 observed_mid_rth_gap
                       0 early-plus-mid-gap overlap
```

Phase 2 frozen-input hashes at handoff:

```text
REV6_FROZEN_SPEC.md
70DAE16C8B12FE26D38A7BFDABF0202066FE7149F790D0D2942279D9C3B8FF50

analysis_constants_v1.yaml
3F5C4BD5258EEB306D76D45AA4AD568A2483F007415E7D11DF89EBBC8C4B182A
```

The spec hash must remain unchanged. Phase 3 is the specifically authorized phase
that adds `min_completion_h15/h30/h60` to the YAML. Therefore the YAML hash is
expected to change **only after** the values are derived, independently audited,
and recorded in the ledger. Record both the old and new hashes.

Historical instruction at Phase 3 entry:

> **Post-freeze note:** The command below predates the authorized YAML threshold
> insertion. At the current Phase 4 state it creates a new provenance identity
> and must not replace canonical `data/`. Restore the preserved sealed artifact
> or follow `docs/SEALED_STORE_REBUILD.md` for a disposable scientific
> reconstruction and its byte-regeneration limits.

```powershell
python -m mnq_lab.spine.build `
  --source-csv "C:\Users\kyawz\Downloads\GLBX-20260331-885WT5W7KA\glbx-mdp3-20100606-20260329.ohlcv-1m.csv" `
  --out data_scientific_rebuild
```

If any fail-closed gate fires during a rebuild, stop and report. Do not work
around it.

Current exploration store:

```text
path              data/exploration/bars_5m
pipeline_version  spine-1.0.0
build_id          0ad7843647f17258
manifest_sha256   1cf6ec5ce7822ce1333984909b52d5c937e4ccc06e280030bcacda22620ffd73
bar_seconds       300
rows              274,847
sessions          1,009
first session     20190506
last session      20230329
```

Never access `data/locked_confirmation/` from the S00 runtime.

## 3. Read in this order

1. This handoff.
2. `REV6_FROZEN_SPEC.md` §14 (STRUCK), then §6, §4.1, §4.2, §10.2,
   §12, §13 tests 5/13/15, §15 row 3, and §16.
3. `analysis_constants_v1.yaml`, especially `session_phases`,
   `horizons_minutes`, `estimands.path`, and `completion`.
4. `docs/PHASE2.md`.
5. `docs/DISCREPANCIES.md`, especially D11 and D12.
6. `docs/PHASE2_HANDOFF.md` §6.5 for the three binding user rulings.
7. `mnq_lab/outcomes/completion.py`.
8. `tests/test_estimand_definition.py`, `tests/test_window_boundaries.py`,
   `tests/test_time_and_timezone.py`, and `tests/test_spec_consistency.py`.
9. `CLAUDE.md`.

Do not treat older revision notes or chat summaries as authoritative over the
frozen spec and the recorded user rulings.

## 4. What is already signed off

### Phase 1

- Deterministic `.npy` `BarStore`.
- Causal active-contract chain.
- One-minute component coverage.
- Exploration/locked sealing.
- Four fail-closed gates.
- Signed off after three external audit passes.

Do not re-audit Phase 1 internals. Report only a Phase 3 regression.

### Phase 2

- Event-time causality: the anchor return ending at τ is conditioner input;
  the anchor bar's high/low path is not its own future outcome.
- `τ = bar-open label + 5 minutes`.
- Anchor eligibility and phase assignment use observation time:
  `08:30 <= τ < 15:00` CT.
- The 08:25 label produces the first 08:30 open anchor.
- The 14:55 label produces τ=15:00 and no anchor.
- Full 78-point τ-grid per session with explicit `anchor_bar_missing`.
- DST-correct localization, including independent CST/CDT coverage at the public
  `ct_minute_of_day` API.
- Data-derived session flags only; calendar early-close truth remains `"unknown"`.
- Per-anchor completion for both estimands.
- Full phase × horizon and year × horizon summaries.
- Checked signed-int64 event-time arithmetic.
- Five audit rounds closed with no surviving mutation.

Current baseline is 294 passed / 5 xfailed and gates 4/4.

## 5. Binding user rulings

These are decisions, not questions for Phase 3.

### D11 Ruling 1 — anchor eligibility

```text
τ = bar_open_label + 5 minutes
anchor eligible iff 08:30 <= τ < 15:00 CT
phase is assigned from τ
outcome begins at the interval starting exactly at τ
```

### D11 Ruling 2 — short sessions

Use only honest data-derived flags:

```text
observed_short_session / observed_rth_ended_early  derived from stored bars
observed_no_rth_bars                               distinct state
calendar_early_close                               "unknown"
official calendar-dependent exclusions             deferred / fail closed
```

No holiday name or official early-close claim may be invented. S00 includes these
sessions because the frozen source population says holidays and early closes are
included and flagged. In Phase 3, “included and flagged” means include every
exploration session and carry the observed flags plus the calendar-unknown state.

### D12 Ruling 3 — conservative path completeness

```text
fully_labeled_1m_grid:
    every required 5-minute bar exists
    AND every required bar contains all five expected 1-minute labels

observed_bar_path:
    every required 5-minute bar exists
    1-minute component coverage is not required
```

A wholly missing required five-minute bar makes a window incomplete under both
estimands. Phase 3 freezes thresholds using `fully_labeled_1m_grid`, exactly as
the YAML and frozen spec require.

## 6. Exact Phase 3 scope

Build S00 over the frozen source population:

```text
tier                 exploration only
date range           2019-05-05 through 2023-03-29, inclusive
actual first session 2019-05-06
market window        RTH only
phases               open, morning, midday, afternoon, close
horizons             15, 30, 60 minutes
path estimand        fully_labeled_1m_grid
thin cells           included, never dropped
short sessions       included and data-flagged
calendar status      unknown, never false
denominator          state anchor AND outcome window fits RTH
completion event     every required path bar is fully labeled
```

The primary S00 threshold-input table is the complete 5 × 3 phase/horizon grid.
Each row must include at least:

```text
phase
horizon_minutes
n_gridpoints
n_state_anchors
n_anchors
n_sessions
weight_ess                 NaN / "not computed until Phase 4"
n_complete_fully_labeled_1m_grid
completion_rate_fully_labeled_1m_grid
status
```

Keep the observed-path completion count/rate as a diagnostic companion, but it
must not enter the threshold calculation.

Canonical row order is YAML phase order, then YAML horizon order. Never sort by a
measured value. Every declared cell is emitted with a status.

Phase 3 must produce:

1. A deterministic S00 result/artifact and CLI replay command.
2. The exact threshold-input counts and rates for all 15 cells.
3. One candidate `s00_p05` per horizon across the five phase rates.
4. One candidate threshold per horizon under the frozen rule.
5. An independent Opus audit of the candidates before any YAML edit.
6. A ledger entry recording the approved values and provenance.
7. The three YAML keys written exactly as ledgered.
8. Tests proving S00, threshold math, ledger/YAML agreement, and fail-closed
   behavior.
9. `docs/PHASE3.md` with measured, inferred, and not-verified sections.

Do not implement Phase 4 kernels, weighting, bootstrap, conditioners, S01A
excursion estimates, or any report that depends on the new thresholds.

## 7. Mathematics Opus must ratify before coding

For phase `p` and horizon `h`, define:

```text
N_eligible(p,h)
    = number of state anchors in phase p whose h-minute window fits RTH

N_complete(p,h)
    = number of those anchors whose required path is complete under
      fully_labeled_1m_grid

c(p,h)
    = N_complete(p,h) / N_eligible(p,h)
```

For each horizon, S00 has five completion rates:

```text
C_h = {c(open,h), c(morning,h), c(midday,h),
       c(afternoon,h), c(close,h)}
```

The spec names the fifth percentile but does not state an interpolation method in
the S00 paragraph. Before implementation, Opus must explicitly ratify the
quantile convention. Recommended:

```text
s00_p05(h) = inf{x : (1/5) Σ_p 1[c(p,h) <= x] >= 0.05}
```

This is the discrete inverse-CDF convention from §7.2. With five equally weighted
phase cells it selects the minimum completion rate. Do not use NumPy's default
linear interpolation silently. If Opus judges the frozen text insufficient to
adopt inverse-CDF semantics here, log a new discrepancy and obtain a user ruling
before computing S00.

Then:

```text
raw_threshold(h)  = floor(100 × s00_p05(h)) / 100
min_completion(h) = max(0.90, raw_threshold(h))
```

Use exact counts/fractions or decimal-safe arithmetic. Do not round a displayed
float and then floor it. Do not pool horizons.

## 8. Provisional oracle — claims to verify, never values to copy

The signed-off Phase 2 table implies the following candidates. Phase 3 must
independently reproduce them from the store:

| horizon | lowest phase | complete / eligible | candidate `s00_p05` under inverse CDF | candidate threshold |
|---:|---|---:|---:|---:|
| 15 | midday | 23,866 / 24,003 | 0.9942923801191518 | 0.99 |
| 30 | midday | 23,763 / 24,003 | 0.9900012498437696 | 0.99 |
| 60 | midday | 23,568 / 24,003 | 0.9818772653418323 | 0.98 |

For transparency, default linear interpolation would produce different p05 values
but the same floored candidates on this dataset. That accidental agreement does
not make the quantile convention optional.

Expected eventual YAML additions, **not authorized to write until candidate
audit and ledger steps complete**:

```yaml
completion:
  min_completion_h15: 0.99
  min_completion_h30: 0.99
  min_completion_h60: 0.98
```

If independently computed values differ, stop and report. Do not copy these
numbers, tune the population, or lower a threshold.

## 9. Required implementation order

### Stage A — branch and baseline

1. Confirm the handoff commit and clean tree.
2. Create `phase-3-s00`.
3. Replay 294/5, gates 4/4, completion CLI, and both Phase 2 hashes.
4. Confirm no threshold key exists in the YAML.

### Stage B — quant preregistration

Before code:

1. Have Opus ratify the exact equations in §7 above.
2. Decide and document the S00 artifact schema and quantile convention.
3. Add a discrepancy rather than guessing if any rule is genuinely ambiguous.

### Stage C — S00 implementation without YAML thresholds

Recommended responsibility split:

- Reuse `mnq_lab.outcomes.completion`; do not duplicate its presence or
  eligibility logic.
- Keep the S00 definition declarative and free of measured values.
- Put orchestration in a thin S00 CLI/module that consumes the exploration store,
  constants, and generic completion functions.
- Do not put market/session concepts into `core/`.
- Do not compute Phase 4 `weight_ess`; retain the honest NaN placeholder.

Run S00 and save a deterministic, hashable threshold-input artifact under the
exploration output area. Generated arrays/data stay uncommitted. The committed
documentation may record counts, rates, artifact hash, build ID, source manifest
hash, code commit, and command.

### Stage D — candidate audit

Stop before changing the YAML. Give Opus:

- code commit;
- exact 15-row table;
- artifact hash and source manifest/build ID;
- p05 calculation with exact inputs;
- three proposed thresholds;
- mutation matrix and baseline replay.

Opus must independently reconstruct the counts and thresholds. Any discrepancy is
a stop-and-report event.

### Stage E — ledger first

After the candidate audit closes:

1. Create the smallest machine-verifiable append-only ledger mechanism needed for
   this freeze; do not pretend the full Phase 11 governance layer exists.
2. Record an entry containing:
   - program/spec version;
   - phase and date;
   - old YAML hash;
   - keys previously absent;
   - exact new key/value triples;
   - frozen rule string;
   - source population and estimand;
   - quantile convention;
   - 15-cell S00 artifact hash;
   - source store build ID and manifest hash;
   - deriving code commit;
   - Opus audit verdict/reference;
   - affected future results: S01A and later;
   - explicit statement that no affected result has run.
3. Commit the ledger entry **before** editing the YAML.

Do not invent a historical timestamp or claim a full ledger system beyond the
mechanism actually implemented.

### Stage F — YAML freeze

In a later commit:

1. Add only the three approved horizon-specific keys.
2. Make the constants loader require them where Phase 3+ consumes thresholds; no
   defaults.
3. Add a test that ledger values, YAML values, and expected keys agree exactly.
4. Record the new YAML SHA-256.
5. Rerun S00 and prove its threshold-input artifact is unchanged by adding its own
   derived thresholds.

No S01A computation is allowed before this step is committed and audited.

### Stage G — Phase 3 closeout

Run the full suite, four gates, S00 CLI, deterministic replay, hash checks, and
mutation tests. Write `docs/PHASE3.md`. Have Opus audit the final freeze. Stop
before Phase 4.

## 10. Required tests and mutations

At minimum:

### Population and grid

- Exact inclusive date bounds.
- RTH-only source.
- Exact five phases and three horizons from YAML.
- Full 15-cell emission in canonical order.
- Thin and empty cells emitted with status, never dropped.
- Short/no-RTH/mid-gap sessions included with honest observed flags.
- Locked tier inaccessible.

### Completion ruling

- Partially labeled bar separates the two estimands.
- Wholly missing required bar fails both.
- Real-store hardening: for every horizon, no row with `n_present < n_required`
  may be complete under either estimand. This addresses the non-blocking D12 audit
  observation that the binding ruling previously rested on one synthetic test.
- Threshold input uses only `fully_labeled_1m_grid`.

### Threshold mathematics

- Horizon-specific, never pooled.
- All five phase rates included.
- Thin cells included.
- Floor, not round.
- A value such as 0.9899 produces 0.98, not 0.99.
- The 0.90 lower bound fires on a synthetic low-support table.
- Exact-boundary 0.9000 remains 0.90.
- Missing, duplicate, non-finite, or extra cells fail closed.
- Wrong estimand fails closed.
- Default linear quantile cannot replace the ratified method unnoticed.
- Candidate derivation is invariant to input row order, while output order remains
  canonical and not value-ranked.

### Ledger and freeze

- Threshold keys absent before freeze.
- Ledger entry committed before YAML edit.
- Exactly three keys present afterward.
- YAML values match the ledger byte-for-byte/numerically exactly.
- Rule, population, estimand, artifact hash, and source build provenance present.
- Constants loader refuses missing keys in Phase 3+ consumption.
- S00 artifact unchanged before versus after YAML additions.

Required adversarial mutations should include:

- use `observed_bar_path` rates;
- pool horizons;
- drop the lowest/thin phase;
- use default linear quantile;
- round instead of floor;
- apply the 0.90 cap as `min` instead of `max`;
- omit one declared cell;
- exclude observed short sessions;
- silently skip an empty/NaN cell;
- read locked confirmation;
- write YAML before a ledger entry;
- mismatch one ledger/YAML value;
- recompute S00 differently after thresholds exist.

Each must be killed by a named test or fail-closed gate.

## 11. Prohibitions and stop conditions

- No access to `data/locked_confirmation/`.
- No ranking, “best” cell, P&L, Sharpe, expectancy, stop/target optimization, or
  trading recommendation.
- No threshold lowering because support looks inconvenient.
- No default for a missing threshold after freeze.
- No executable inline copy of `.99/.99/.98`; the provisional documentation
  oracle may report them, but runtime consumers must read the ledgered YAML.
- No official holiday or early-close assertion.
- No dropping thin/empty cells.
- No tolerance/nearest matching.
- No Phase 4 weight implementation.
- No S01A run before the ledgered YAML freeze is audited.

Stop immediately if:

- a Phase 1 gate fails;
- the 15-cell table or population differs from Phase 2 without explanation;
- candidate values differ from the provisional oracle;
- the quantile convention remains unresolved;
- most cells would be excluded;
- the YAML already contains unledgered threshold values;
- any code path touches the locked tier.

## 12. Definition of done

Phase 3 is complete only when:

- S00 deterministically emits the full 15-cell table.
- Opus independently reproduces its counts, p05 inputs, and candidates.
- The ledger entry predates the YAML edit.
- YAML contains exactly the three audited values.
- The new YAML hash and old hash are recorded.
- S00 is byte-identical before and after its derived values are written.
- Tests and mutations discriminate every rule above.
- Full suite and four Phase 1 gates pass.
- `docs/PHASE3.md` separates measured, inferred, and not verified.
- Final Opus verdict is CLOSED.
- No Phase 4 or S01A result has been computed.

## 13. First new-session message

Paste the prompt supplied with this handoff. The first implementation turn should
only verify the starting state, read the required sources, and ask Opus to ratify
the S00 p05 mathematics. Do not write Phase 3 production code before that quant
preflight is resolved.
