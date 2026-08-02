# Phase 7 Calendar Reference Input Closeout

**Status:** calendar input accepted; Phase 7 production not authorized  
**Independent verdict:** `CLOSED`  
**Audit date:** 2026-08-01

## Boundary

This document closes only the bounded Phase 7 CME equity-index calendar
reference-input work authorized by U11 and U12. It does not ratify the Phase 7
executable contract, authorize conditioner or estimator implementation, open
Phase 7b production, or authorize Phase 8 or any later phase.

The independent audit covered the repository range
`4100abadad1d8212b8c98ad7382e1019a1afbe96..4434c632c02c0b046bb0b53fecac90857ad511c9`.
The commit introducing this document is a child of `4434c63` and is itself
unaudited until the focused closeout audit. This document therefore does not
claim to audit itself and does not contain its own SHA-256. Its byte identity is
to be established independently by that closeout audit.

## Audited Commit Chain

The independent auditor verified a clean worktree, the branch
`phase-7-calendar-input`, the unchanged Phase 6 reference, exhaustive U11 path
scope, and this ordered chain:

1. `4100abadad1d8212b8c98ad7382e1019a1afbe96` — Close Phase 6 dependency infrastructure.
2. `b5377a3426cc33ccb833a907242a347f5ec6f8a0` — Authorize versioned Phase 7 calendar input.
3. `f0bde870056c9fce31b799e4c93e25b4efe0aae3` — Add immutable CME equity-index calendar input.
4. `4434c632c02c0b046bb0b53fecac90857ad511c9` — Add Phase 7 calendar input acceptance gate.

The ledger/provenance authorization preceded the artifact, and the artifact
preceded its acceptance tests. The closed `phase-6-dependency` branch remains at
`4100abadad1d8212b8c98ad7382e1019a1afbe96`.

## Audited Protected Hashes

These are the eight hashes independently recomputed during the committed-input
audit. They do not include this closeout document.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `docs/DISCREPANCIES.md` | 49,015 | `68325d575bd5a480fa23c11cc22dc5b1b1ecfbd0f7714cca007721e8f63df1c7` |
| `mnq_lab/ledger/calendar_entries/2026-08-01-phase7-cme-equity-index-calendar-v1.json` | 3,823 | `a32ea05f7b19bdf3e8c6eafc4f8ee124f3b44eb42dfb4f9c4ef3dfe915fba3bb` |
| `mnq_lab/ledger/calendar_entries/validator.py` | 5,512 | `83d0c65b3ca037a04636504ed48f37096ff9fba4bcb3eb1b33e4ea22a2138a45` |
| `mnq_lab/spine/calendar_inputs/cme_equity_index_v1/cme_equity_index_sessions_20190506_20230329_v1.json` | 447,577 | `b86e112c16112bf11a6a548ca8b3f21d28a08f90442b4dde84098f9d3f6eb069` |
| `mnq_lab/spine/calendar_inputs/cme_equity_index_v1/cme_equity_index_sessions_20190506_20230329_v1.manifest.json` | 5,844 | `bdd923a534152ef88bd9db874e60e08c757b85dae729b397ae78351a3e3d7a1d` |
| `mnq_lab/spine/calendar_inputs/cme_equity_index_v1/cme_equity_index_sessions_20190506_20230329_v1.acceptance.json` | 24,039 | `f63e58854e4c5427271140be4452ebb7169a39f665927641f0b63bea3d0df64d` |
| `tools/build_phase7_calendar_v1.py` | 39,158 | `937abff993d3e5a5d43282ae12b895ca0e1a99328082e1438687f6972a306db6` |
| `tests/test_phase7_calendar_input.py` | 17,186 | `d4429aadae3f800d728b87c20addbe1dc9bfea0797a1ff1dde1433c51be7f11a` |

The separate Phase 3 ledger namespace remained unchanged with exactly one entry,
whose SHA-256 is
`55c313c55f791c4744108891d8889f7b17ccd94233408d550d948c45e6696558`.

## Ledger Audit-Status Reconciliation

The calendar ledger entry
`2026-08-01-phase7-cme-equity-index-calendar-v1.json` records
`committed_artifact_audit = "pending"`. That entry was written in commit
`b5377a3`, before the independent audit existed, and is deliberately left
unamended to preserve its protected SHA-256
`a32ea05f7b19bdf3e8c6eafc4f8ee124f3b44eb42dfb4f9c4ef3dfe915fba3bb`
under its own append-only amendment policy. This document is the authoritative
record of the audit outcome and supersedes that field. No ledger byte was
changed.

## Accepted Input and Provenance

The accepted static input contains 1,018 ordered weekday rows from 2019-05-06
through 2023-03-29 and no confirmation-period date. Its single source is the
`CME Globex Equity` calendar in `pandas-market-calendars` 5.4.0 at upstream
commit `275890784073a3a3a347e4f05f4dc986456e6a75`, retained under the MIT
licence.

All 47 Python source files from the pinned package are retained as inert
`.py.txt` provenance. There are no retained `.py` modules, importable source
modules, or pytest-collectable tests. The auditor independently recomputed the
documented source-tree hash:

`253ca03bc5ba4956a930d47d167843469c4440a0514961599cc3ee0d376890ee`

The source-index SHA-256 is
`bc6934832e2a9934bf485504ad844ed64948d83292c88a012cef9cef493a92a6`,
and the extraction dependency-lock SHA-256 is
`68707c623e0a89df75474eba00de587ac5462dd666c9ce138e327166875d3676`.

The extraction environment used pandas 3.0.5 and NumPy 2.5.1. The laboratory
uses pandas 3.0.1 and NumPy 2.2.3, and deliberately does not install
`pandas-market-calendars`. Raw-byte reproduction is claimed only in the matching
extraction environment; cross-environment determinism means semantic identity
of the canonical table.

## Complete Observational Reconciliation

After validation of the exploration store manifest and the consumed
`session_id.npy` and `ts_event_ns.npy` hashes, the auditor independently
reproduced this complete, disjoint 1,018-cell partition from the committed JSON:

- 974 candidate-regular sessions whose observed final bar ended at 16:00 CT;
- 32 timed early closes matching exactly, comprising 25 at 12:00 and seven at 12:15;
- one no-scheduled-RTH structural match, 2021-04-02 at 08:15;
- nine full closures matching the nine absent weekdays bidirectionally; and
- two registered regular-session data-quality discrepancies.

The two discrepancies remain classified as regular calendar sessions with
`unresolved_truncated_session`: 2020-02-28 ended at 10:00 CT and 2020-06-30
ended at 09:15 CT. Observed data corroborated or falsified source claims; it did
not generate or amend a calendar classification.

## Deterministic Gate

The focused calendar gate reproduced `20 passed, 1 xfailed`. The only xfail was
the explicitly pending, strict A5 gate `a5_calendar_import_isolation`.

The authorized repository suite reproduced:

`770 passed, 6 xfailed`

The six xfails were exactly:

1. `seasonal_profiles`
2. `tercile_thresholds`
3. `conditioner_assignments`
4. `prevalence_results`
5. `consumed_vintage_artifacts`
6. `a5_calendar_import_isolation`

The first five remained unchanged. The sixth records the mandatory dependent-code
gate authorized by U11. It must become a discriminating passing test before any
EWMA, MAD, seasonal-profile, `vol_rel`, threshold, or assignment computation is
committed; it may not be removed without that conversion.

## Deviations and Known Limits

A4 remains permanently `ORDERING-VIOLATED`: the first candidate extract existed
before known-date expectations were preregistered, and no later document may
backfill or claim such evidence. Acceptance instead rests on the independently
reproduced observational battery.

The input is single-source. Its 1,016 corroborating cells span only a small
number of close mechanics and approximately eight to ten holiday-rule families;
comparisons are strongly correlated within a mechanic. This is corroboration,
not proof that every exchange classification is correct. Holiday-adjacent flags
have no independent time signature, and a claimed full closure can coincide with
vendor absence. A future Databento GLBX.MDP3 status stream remains preferred
independent corroboration but is not an input-acceptance blocker.

No seasonal profile, conditioner assignment, state-validity result, market
effect, confirmation result, profitability result, or trading result has been
computed or established by this input.

## Independent Outcome

The independent committed-artifact audit concluded:

- `CALENDAR INPUT: ACCEPTED`
- `PHASE 7 PRODUCTION: NOT AUTHORIZED`
- `VERDICT: CLOSED`

The closeout audit must verify this new document and its single-file commit.
Until a separately ratified complete Phase 7 executable contract exists, no
Phase 7 production implementation may begin.
