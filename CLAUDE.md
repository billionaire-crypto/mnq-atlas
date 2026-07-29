# MNQ Empirical Market Atlas — implementation instructions

## What this is

A **measurement instrument, not a strategy search.** It measures state validity, state
prevalence, and conditional future-path distributions. It produces empirical facts from
which hypotheses are later built in a *separate* research process.

`REV6_FROZEN_SPEC.md` is authoritative and supersedes revisions 1–5 completely.
`analysis_constants_v1.yaml` holds every frozen constant. Read **§14 (STRUCK)** of the
spec before writing any code — earlier revisions contained rules that are now wrong, and
if you find one quoted in an old note, a chat summary, or your own reasoning, §14 wins.

## Hard prohibitions

This code must never:

- search for profitable strategies, or rank cells by profitability
- select a "best" parameter, or optimize stops or targets
- calculate expectancy or Sharpe ratio
- emit P&L or any currency figure
- modify a live trading strategy
- access `data/locked_confirmation/` from the exploration runtime

If a task appears to require any of these, you have misread the task.

## Non-negotiables (spec §16.4)

1. **Never touch `data/locked_confirmation/`** from exploration code. Only
   `spine/build.py`, `spine/gates.py` and `spine/seal.py` may reference it, and only to
   write and validate it.
2. **Never change a value in `analysis_constants_v1.yaml` after the affected result is
   computed.** Changing one *before* is fine — with a ledger entry first.
3. **Fail closed.** Every gate in §5.1 halts the build. Do not add a fallback path, do
   not "handle" the discrepancy, do not proceed with a warning, do not lower a threshold
   to make a test pass.
4. **No selection verbs in `core/`**: no `sort_values`, `nlargest`, `idxmax`, `argmax`,
   `rank`, `best`, `top` applied to measurement output.
5. **Emit every declared cell**, including empty and unsupported ones, with a `status`.
   Never drop a thin cell, never hide a failed result.
6. `n_anchors` is never rendered without `n_sessions` and `weight_ess` beside it.

## Scientific rules

- Report what was **measured** separately from what was **inferred**.
- Use only information available by the declared observation time.
- `ts_event` is the bar **OPEN**; the interval is `[t, t + bar_seconds)`.
- Assign time-of-day using `anchor_observation_time` (= `t + bar_seconds`), never the
  bar label. An off-by-one here shifts every result by five minutes and **no statistical
  test will catch it.**
- The completed anchor bar's **return** may enter a conditioner. Its **high and low** may
  not enter its own future excursion.
- Store timestamps as UTC nanoseconds; use `America/Chicago` for session logic.
- Prices are `int32` ticks, tick size 0.25 index points.
- Never bridge two incompatible data-pipeline versions.

## Responsibility boundaries

```
core/          knows nothing about markets
conditioners/  know market mechanics, nothing about studies
outcomes/      "
studies/       configuration only
report/        reads frozen tidy result frames only
```

Production or execution code must not import this research package. The profit concept
then has no place to live.

## Environment

```
Platform   Windows 10, PowerShell primary (Bash also available)
Python     3.13.2 | pandas 3.0.1 | numpy 2.2.3 | pyyaml 6.0.3 | pytest 9.1.1
Parquet    pyarrow AND fastparquet are both ABSENT — to_parquet() raises ImportError.
           Use .npy column stores loaded with mmap_mode="r".
VCS        This IS a git repo (spec §16.2 says otherwise; it is wrong — see
           docs/DISCREPANCIES.md). Fingerprints record git commit SHA.
Source     C:\Users\kyawz\Downloads\GLBX-20260331-885WT5W7KA\
             glbx-mdp3-20100606-20260329.ohlcv-1m.csv  (402 MB, 3,665,228 rows)
           Read-only. A full streaming pass takes ~5 s; this is not a scale problem.
           The memory constraint is frame concat over 7 years — fixed with per-year
           shards, not clever chunking of the read.
Reference  C:\Users\kyawz\Documents\Codex\2026-07-27\role-context-you-are-an-elite\
             data/mnq_active_5m_3y.csv            (Gate 2 oracle)
             data/mnq_active_5m_3y.csv.manifest.json (Gate 1: 28-roll fixture)
```

## Reuse, do not reimplement

Under `C:\Users\kyawz\Documents\Codex\2026-07-27\role-context-you-are-an-elite\`:

| File | Reuse |
|---|---|
| `prepare_databento_mnq.py` | `scan_daily_outright_volume`, `build_causal_active_contract_map`, `collect_active_rows`, `resample_active_chain_to_five_minutes`, `_trade_date_strings` |
| `lora_statistics.py` | `session_row_groups`; `cme_session_ids` as a **DST test oracle only**; `stationary_session_resample` as a reference to generalize — **do not call it**, it truncates the final session by rows |
| `data_pipeline.py` | `_sha256_file` (:113), `_cme_session_mask` (:255), `CME_TIMEZONE` (:42) |
| `scale_only_targets.py` | `lagged_ewma_rms` |

`data_pipeline.py` imports torch at module scope, so importing it pulls a training stack
into the measurement lab. The two small pure-pandas helpers are therefore **vendored**
into `mnq_lab/spine/vendored.py` with provenance headers, and
`tests/test_vendored_equivalence.py` proves bit-identical behaviour against the
originals. Vendoring without that proof is forbidden.

## When something disagrees with the spec

**Report it. Do not code around it.** If a fail-closed gate fires: stop, locate the first
mismatching session, classify the cause (roll mapping / missing bars / timestamps /
aggregation / duplicates / source revision), and report. Do not pin one era to an old
file, do not relax a threshold, do not add a tolerance. Two data definitions in one atlas
make every difference unattributable between the market and the pipeline.

Known discrepancies between the spec and the observed environment are logged in
`docs/DISCREPANCIES.md`. Add to it rather than silently resolving.

## Development discipline

- Small commits. Never push directly to `main`; work on a phase branch.
- Do not modify frozen files (`REV6_FROZEN_SPEC.md`, `analysis_constants_v1.yaml`)
  unless resolving an objective contradiction — and then only with a ledger entry.
- Preserve source data unchanged. Never commit datasets, secrets, caches, or generated
  arrays.
- **Every test must have a negative case proving it can fail.** A check that cannot fail
  is worse than no check, because it produces confidence. The preceding LoRA experiment
  shipped a canary whose pass threshold was negative, so a fully collapsed representation
  satisfied it.

## The failure mode to guard against

Across six adversarial review rounds of the spec, every defect took the same form: **a
fluent claim stronger than its mechanism.** Guards described as "structural" that were
only friction. A test oracle that was invalid. A worked example missing a timezone. Each
survived because it read well. Each was caught by *running a query* — not by re-reading.

So: when the spec asserts something checkable, check it. When you write a test, ask
whether it *can* fail. Report what you measured, label what you inferred, and state
plainly what you did not verify.

## Commands

```powershell
# Full test suite
python -m pytest tests -q

# Gates only, against an existing build
python -m mnq_lab.spine.gates --store data
```

The canonical store is sealed against the pre-Phase-3 YAML. Do **not** run
`spine.build` with the current YAML into canonical `data/` and expect the pinned
provenance tests to pass: the scientific arrays reproduce, but the full-file YAML
hash intentionally gives the new build a different `build_id`. Follow
`docs/SEALED_STORE_REBUILD.md` for sealed-artifact handling, the limits of
byte-level regeneration, a disposable scientific-reconstruction procedure, and
guidance on creating a genuinely new provenance version.
