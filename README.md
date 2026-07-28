# MNQ Empirical Market Atlas

A versioned empirical map of when MNQ market states occur, whether those states are
stable enough to mean anything, what path distributions follow them, and how often
equally convincing structure appears after the proposed relationship is deliberately
destroyed.

**This is a measurement instrument, not a strategy search.** It produces facts that
hypotheses are later built *from*, in a separate lab. It does not rank cells by
profitability, select a "best" parameter, optimize stops or targets, compute expectancy
or Sharpe, or emit any currency figure.

`REV6_FROZEN_SPEC.md` is authoritative and supersedes revisions 1–5 entirely.
`analysis_constants_v1.yaml` holds every frozen constant; the lab refuses to run without
it and never supplies a default. See `CLAUDE.md` for implementation rules and
`docs/DISCREPANCIES.md` for every place the spec, the repository and the data disagree.

## Status

| Phase | Description | State |
|---|---|---|
| 1 | Data spine, BarStore, four fail-closed gates | **complete** — see `docs/PHASE1.md` |
| 2 | Time model, clock-window engine, completion accounting | not started |
| 3–12 | see spec §15 | not started |

## Setup

```powershell
python -m pip install numpy pandas pyyaml pytest
```

Python 3.13.2 · numpy 2.2.3 · pandas 3.0.1 · pyyaml 6.0.3 · pytest 9.1.1.
`pyarrow` and `fastparquet` are both absent, so `to_parquet()` raises `ImportError` and
the stores are `.npy` column stores loaded with `mmap_mode="r"`.

## Build the spine

```powershell
python -m mnq_lab.spine.build `
  --source-csv "C:\Users\kyawz\Downloads\GLBX-20260331-885WT5W7KA\glbx-mdp3-20100606-20260329.ohlcv-1m.csv" `
  --out data
```

Takes about 2m20s and produces four stores:

```
                                   trade dates              sessions      rows
data/exploration/bars_1m           2019-05-06 .. 2023-03-29     1009  1,369,566
data/exploration/bars_5m                                        1009    274,847
data/locked_confirmation/bars_1m   2023-03-30 .. 2026-03-30      775  1,059,836
data/locked_confirmation/bars_5m                                 775    211,968
```

The locked-tier counts reproduce the prior pipeline's manifest exactly
(`selected_active_1m_rows: 1059836`, `five_minute_rows: 211968`), which is Gate 2.

`data/` is git-ignored. Source data is read-only and is never copied into the repository.

## Run the gates

```powershell
python -m mnq_lab.spine.gates --store data
```

All four halt the build on failure. None accepts a tolerance, and none may be given one —
see `.claude/skills/gate-diagnosis`.

## Tests

```powershell
python -m pytest tests -q
```

217 pass, 5 xfail (registered placeholders for prefix-invariance targets that do not
exist until later phases). Every test has a negative case proving it can fail; a check
that cannot fail is worse than no check.

## Corpus tiers

| Tier | Trade dates | Status |
|---|---|---|
| Exploration | 2019-05-06 → 2023-03-29 | free use |
| Locked confirmation | 2023-03-30 → 2026-03-30 | post-preregistration only; **already contaminated** by prior Kronos/LoRA work |
| Forward vintages | after freeze | the only untouched evidence |

The tiers are physically separate directories. `mnq_lab/spine/seal.py` guards the
boundary and `tests/test_seal_guard.py` scans the package by AST so no exploratory
module can even name the locked store. This is **friction, not structure** — the real
protections are preregistration, the ledger, access control, and human discipline.
