# Phase 2 handoff — time model, clock-window engine, completion accounting

Written at the close of Phase 1 (branch `phase-1-spine`, HEAD `7d19eb5`, signed off by
three external audit passes). Read this whole file, then `CLAUDE.md`, then spec §14
(STRUCK), before writing any code.

## 0. What this project is

A **measurement instrument, not a strategy search** (spec §16.1). `REV6_FROZEN_SPEC.md`
is authoritative and supersedes revs 1–5; `analysis_constants_v1.yaml` holds every
frozen constant — the lab refuses to run without one, and no default is ever supplied.
Nothing you build may rank cells by profitability, select a "best" parameter, or emit a
currency figure. If a task seems to require that, you have misread the task.

## 1. State of the repository

```
branch    phase-1-spine (pushed; main has no refs — merging is the user's call, never yours)
tests     232 passed, 5 xfailed (the xfails are registered placeholders for
          Phase 7/9/11 prefix-invariance targets — do not "fix" them)
gates     4/4 pass via  python -m mnq_lab.spine.gates --store data
frozen    REV6_FROZEN_SPEC.md        sha256 70dae16c…  — never modify
          analysis_constants_v1.yaml sha256 3f5c4bd5…  — never modify without a
          ledger entry BEFORE any affected result (§16.4.2)
```

Phase 1 delivered, all audited:

- `mnq_lab/spine/` — source scan, causal roll map, per-year sharded collection,
  5-min resample **with component coverage**, `.npy` BarStore (mmap, hashed manifest),
  seal, four fail-closed gates.
- `mnq_lab/core/units.py` — exact int32 tick conversion (fails closed on inexact).
- `mnq_lab/constants.py` — fail-closed YAML loader. **Note D8**: the frozen YAML's
  `inference: null:` key parses to Python `None`; the loader normalises it to the
  string `"null"`. Use `constants.get("inference", "null", ...)`.
- Stores (git-ignored; rebuild in ~2m20s):

```
data/exploration/bars_1m           20190506..20230329  1009 sessions  1,369,566 rows
data/exploration/bars_5m                               1009 sessions    274,847 rows
data/locked_confirmation/bars_1m   20230330..20260330   775 sessions  1,059,836 rows
data/locked_confirmation/bars_5m                        775 sessions    211,968 rows
```

```powershell
# rebuild if data/ is absent (real-store tests FAIL, never skip, without it)
python -m mnq_lab.spine.build --source-csv "C:\Users\kyawz\Downloads\GLBX-20260331-885WT5W7KA\glbx-mdp3-20100606-20260329.ohlcv-1m.csv" --out data
python -m mnq_lab.spine.gates --store data
python -m pytest tests -q
```

Read `docs/PHASE1.md` (implementation + three audit rounds) and
`docs/DISCREPANCIES.md` (D1–D10) — several entries directly constrain Phase 2.

## 2. Your assignment — Phase 2 only (spec §15, row 2)

**Time model + clock-window engine + completion accounting.**
Gate to pass before Phase 3: **spec §13 tests 1 and 2** (`test_time_and_timezone`,
`test_event_time_conditioner`). `test_window_boundaries` and
`test_estimand_definition` from the §13 test-18 list also belong naturally here.
**Do not start Phase 3** (S00 atlas / threshold freezing) — stop and report when
Phase 2's gate passes.

### 2.1 The time model (spec §4.1 — implement exactly)

```
anchor bar label        08:30 CT              covers [08:30, 08:35) CT
close observed at       08:35 CT              <- anchor_observation_time (τ)
time-of-day bucket      keyed on 08:35, NEVER on the 08:30 label
outcome window          [08:35, 08:50) CT     (Δ = 15 clock minutes)
required bars           08:35, 08:40, 08:45   all present, all 1-min complete
```

The general rule, in event time — **never** as `shift()`, which is an implementation,
not the specification (§14 struck `shift(1)`-as-spec):

> At observation time τ, a conditioner may use every return whose ending timestamp
> ≤ τ and none ending after τ. An outcome may use only the path strictly after τ.

Two consequences that are different rules and must not be conflated:
- the anchor bar's own **return** enters the conditioner (it ends exactly at τ);
- the anchor bar's own **high/low** is excluded from its future excursion.

### 2.2 Session phases (spec §4.2 — observation-time CT)

open [08:30,09:00) · morning [09:00,10:30) · midday [10:30,12:30) ·
afternoon [12:30,14:00) · close [14:00,15:00). Horizons: 15/30/60 min (YAML
`horizons_minutes`). These tile RTH exactly (a Phase 1 test already asserts this).

**Checkable claims in the spec — check them, don't trust them** (§16.7): the
registered prediction says close-phase eligible anchors per full session are Δ60→1,
Δ30→7, Δ15→10 (τ ≤ 15:00−Δ). Your engine's counts on a full ordinary session must
reproduce these numbers, and the test must assert them.

### 2.3 Completion accounting (spec §6)

Two estimands, exactly these names (§14 struck `complete_1m_path`/`observed_trade_path`):
- `fully_labeled_1m_grid` — every 5-min bar in the outcome path has all five 1-min
  labels (the spine already carries `observed_1m_components == expected_1m_components`);
- `observed_bar_path` — bars present in the source, retained with a flag.

Phase 2 builds the **machinery**: per anchor × horizon, is the outcome window complete
under each estimand; per-cell completion rates over the frozen S00 population. Phase 3
computes `s00_p05` and freezes `min_completion_h15/h30/h60` into the YAML **with a
ledger entry** — that freezing is not yours. Also keep prevalence's distinction in
mind for the API (§10.2): `state_anchors` (condition at τ, regardless of outcome
availability) vs `outcome_eligible_anchors_h*` — prevalence must be horizon-invariant.

### 2.4 Required tests (spec §13, verbatim targets)

1. `test_time_and_timezone` — the §4.1 worked example asserted exactly; **a bar-end
   interpretation must fail**; RTH asserts 08:30/15:00 CT; coverage across both US DST
   transitions, early closes, and US/EU DST divergence weeks.
2. `test_event_time_conditioner` — hand-built timestamps proving exactly which returns
   enter the state at τ; the anchor bar's own return **is** included, its path **is not**.

Every test needs a negative case proving it can fail. A check that cannot fail is
worse than no check — this is the project's core discipline and all three audits
mutation-tested it.

## 3. Binding obligations carried from Phase 1 audits

1. **RTH bounds must be consumed from the YAML, not re-hardcoded.** The re-audit
   proved a YAML with `rth_start_ct: "09:00"` builds byte-identical Phase 1 data
   because nothing consumes it yet. The moment your code makes any RTH-dependent
   selection, `rth_start_ct`/`rth_end_ct` must come from `constants.get("time", ...)`,
   with a consistency test tying any runtime literal to the YAML (pattern: audit-M2
   fix in `mnq_lab/constants.py`, which fail-closes `session_tz` and
   `maintenance_break_ct` against the vendored mask).
2. **Session phases likewise** — read `constants.get("session_phases")`, never inline.
3. **Claims must not exceed mechanisms.** Both audits' recurring theme. When you
   document what a check certifies, state its scope honestly (see Gate 4's docstring
   for the required style).
4. Never call `lora_statistics.cme_session_ids` at study time — DST test oracle only
   (spec §5). Session ids are already in the spine (`session_id`, int32 YYYYMMDD).

## 4. Traps discovered in Phase 1 that will bite Phase 2

- **pandas 3.0 returns `datetime64[us]`, not ns.** Always force
  `.to_numpy(dtype="datetime64[ns]")`; never `.astype("int64")` on a datetime series.
  A Phase 1 test asserts store timestamps are ns; keep that invariant.
- **τ boundary cases** — decide and test explicitly, don't let them fall out:
  - bar labeled 14:55 has τ = 15:00, which is **outside** every phase (phases are
    half-open, RTH ends 15:00) — is it an anchor at all?
  - bar labeled 08:25 (pre-RTH data) has τ = 08:30, which is **inside** the open
    phase. The §4.1 worked example starts the day at the 08:30-labeled bar (τ 08:35),
    which implies the anchor bar itself must lie in RTH — but the spec never states
    it. **This is a genuine ambiguity: surface it to the user before coding it**, per
    §16.6. Expensive-if-wrong; one sharp question with your best-guess reading.
- **DST**: bars sit on a fixed UTC 5-min grid; 08:30 CT is a different UTC time
  across transitions. Compute all bucketing in CT via tz-convert, never via a fixed
  UTC offset. `tests/test_session_id_equivalence.py` shows the oracle pattern.
- **Early closes: there is NO versioned CME holiday calendar in the repo**, and §9.2
  says inventing one is worse than declaring the gap (§14 struck event-day strata
  for exactly this reason). §4.3 requires holidays "from a VERSIONED CME calendar
  table" for the seasonal profile (Phase 7), but §13 test 1 wants early-close
  coverage now. You can *detect* short sessions from the data (sessions whose last
  RTH bar ends early); you may NOT label them with holiday names from memory.
  **Stop and ask the user** whether a versioned calendar file will be supplied or
  whether Phase 2 should use data-derived session-length flags only.
- **D4**: the raw source contains exactly one bar inside the maintenance break
  (2020-03-31 16:59 CT); it is excluded from the chain. Any "no bars in the break"
  assertion is about the *chain*, not the raw source.
- **D9**: roll trigger/effective are adjacent *sessions*, not calendar days.
- **D10**: never quote finding F's "71.2%" RTH volume share; it doesn't reproduce.
  The RTH *boundary* (08:30 CT, ~5.8× volume jump) is confirmed on every population.

## 5. Where the code goes (spec §16.3 responsibility boundaries)

```
core/      knows NOTHING about markets — no contract, session, or exchange concepts.
           Event-time window logic (returns ending ≤ τ, paths strictly after τ) is
           market-free and belongs in core/causality.py; generic bar-frame handling
           in core/barframe.py. Tick size, phase tables etc. arrive as PARAMETERS.
conditioners/ + outcomes/  know market mechanics, nothing about studies.
spine/     already owns calendar/session logic; anchor-time derivation from bar
           labels fits alongside spine/calendar.py.
studies/   pure config. report/ reads tidy frames only.
```

No selection verbs in `core/` (`sort_values`, `nlargest`, `idxmax`, `argmax`, `rank`)
— `tests/test_no_selection.py` scans by AST and will fail your build. Emit every
declared cell with a `status`; `n_anchors` never without `n_sessions` and
`weight_ess` beside it (weight_ess arrives Phase 4; design the result schema for it).

## 6. Working discipline

- Branch `phase-2-time-model` off `phase-1-spine`. Small commits. Never push to main.
- When spec and data disagree: **report, do not code around** (§16.6). Append to
  `docs/DISCREPANCIES.md` (D11 is next) with measured/inferred/not-verified sections.
- The user runs external Codex audits between phases. Write code and claims expecting
  an adversarial reviewer who will replay your negative tests, mutate your code to
  check the tests can fail, and diff your docs against your mechanisms.
- Project skills exist and match this workflow: `.claude/skills/phase-gate` (use at
  start and end of the phase), `spec-check` (before implementing any spec rule),
  `gate-diagnosis` (if any Phase 1 gate ever fires — stop, diagnose, report).
- Before coding, run the full existing suite and the gates to confirm you inherit a
  green state; report your starting state to the user first, as Phase 1 did.

## 7. Definition of done for Phase 2

- §4.1 worked example asserted exactly; bar-end interpretation demonstrably fails.
- Event-time conditioner/outcome windows proven on hand-built timestamps: anchor
  return in, anchor high/low out, nothing after τ in any conditioner.
- Phase assignment keyed on observation time; close-phase eligibility counts
  reproduce 1/7/10 for Δ60/30/15 on a full ordinary session.
- Completion accounting produces per-anchor, per-horizon eligibility under both
  estimands, on the real exploration store, with completion-vs-year and
  completion-vs-condition summaries surfaced (the §6 selection-effect confound made
  visible — §16.5 item 6 says measure it FIRST and say so loudly if it varies).
- DST transition weeks, early-close handling (as agreed with the user), and US/EU
  divergence weeks covered by tests.
- RTH bounds and phases consumed from the YAML with a consistency test.
- All Phase 1 tests still pass; gates still pass; no frozen file touched.
- Implementation summary + reproducible commands (docs/PHASE2.md), discrepancies
  logged, and a report to the user. Then STOP — do not begin Phase 3.
