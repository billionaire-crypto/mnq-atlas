---
name: phase-gate
description: Use when starting or finishing a build phase from spec §15. Confirms the phase's own gate tests pass before the next phase begins, and prevents starting the next phase automatically.
---

# Phase gate

The build order in §15 is sequential and each phase has a gate. **Do not start the next
phase automatically.** Finish, report, and wait.

## Build order and gates

| # | Phase | Gate tests (§13) |
|---|---|---|
| 1 | Spine, BarStore, four fail-closed gates, component coverage | 3, 4, 5, 18 |
| 2 | Time model + clock-window engine + completion accounting | 1, 2 |
| 3 | S00 atlas; freeze completion thresholds into the YAML | thresholds written **and ledgered** before S01A |
| 4 | Kernel core, inverse-CDF weighted statistics, `weight_ess` | 7 |
| 5 | Bootstrap: whole-session, block sensitivity, dual estimand | 8 |
| 6 | Dependency-window harness + witness fixtures + registries | 6 |
| 7 | Conditioners, frozen seasonal estimator, state-validity panel | 6, 13 |
| 8 | Named contrasts + positivity gate + interaction estimand | 15, 16 |
| 9 | Prevalence layer on its own support | 14 |
| 10 | Null engine, software controls, surface calibration | 9, 10, 11, 12 |
| 11 | Guards, ledger, vintages, forward budget, fingerprint | 17 |
| 12 | S01A-Descriptive + S01A-Calibration + Field Guide | end-to-end acceptance |

## Starting a phase

1. Confirm the previous phase's gate tests still pass — not just the new ones.
2. Create a branch `phase-N-<name>`. Never work on `main`.
3. Re-read the spec sections the phase implements. Load `analysis_constants_v1.yaml`
   and confirm every constant the phase needs is present. If one is missing, stop.

## Finishing a phase

A phase is done only when all of these hold. Check them; do not assert them.

- [ ] The phase's gate tests from the table above pass
- [ ] **Every new test has a negative case proving it can fail**
- [ ] Previously passing tests still pass (run the whole suite, not the new file)
- [ ] No strategy-selection, ranking, optimization, or P&L functionality was introduced
- [ ] No constant was inlined that belongs in `analysis_constants_v1.yaml`
- [ ] No fallback path was added around a gate
- [ ] `data/locked_confirmation/` was not read by exploration code
- [ ] Any spec/data disagreement is in `docs/DISCREPANCIES.md`, not silently resolved
- [ ] The branch has an implementation summary and reproducible commands

## Report, then stop

Provide: files created or changed · commands run · test results · data-build results ·
manifest summary · **any unresolved discrepancy** · recommended next-phase starting point.

Bad news first and plainly. A gate that fired, a test you could not make fail, or a
number you did not verify goes at the top of the report, not the bottom.
