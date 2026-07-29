# Phase 1 — Data spine, BarStore, fail-closed gates

Spec §5 and §15 row 1. Gate to pass before Phase 2: §13 tests 3, 4, 5, 18.

## Result

All four fail-closed gates pass against the real source. 217 tests pass, 5 xfail
(registered placeholders for later-phase prefix-invariance targets). No
strategy-selection, ranking, optimization, or P&L functionality was introduced.

| Gate | Check | Result |
|---|---|---|
| 1 | Rebuilt roll list == verified fixture | 28 rolls, exact match, 2019-06-18 → 2026-03-18 |
| 2 | 5-min bars row-for-row identical to reference CSV | 211,968 rows, all 8 columns |
| 3 | Symbol classification exhaustive and exact | 32 retained + 55 spread = 87 distinct |
| 4 | Roll causality | 1,009 sessions, one contract each; 17:00 CT divergence fixture |

## Historical build and current validation

The original Phase 1 build predates the Phase 3 threshold freeze. At the current
Phase 4 commit, a direct build uses the post-freeze YAML and therefore creates a
new `build_id` even though the scientific arrays reproduce. The sealed manifest
also records a dirty working tree whose uncommitted contents were not preserved,
so certified artifact-byte regeneration is not claimed. Follow
`docs/SEALED_STORE_REBUILD.md`; do not overwrite canonical `data/` with a
current-YAML rebuild. The commands below validate the preserved artifact.

```powershell
# Four fail-closed gates against the preserved sealed build
python -m mnq_lab.spine.gates --store data

# Tests
python -m pytest tests -q
```

## Design decisions worth knowing

**Memory.** Two streaming passes plus per-year shards, as §16.2 directs. Pass 1
validates and aggregates session volume (dict-bounded, not row-bounded). Pass 2 keeps
only the causally selected contract and flushes one `.npz` shard per trade-date year. A
trade date belongs to exactly one year, so no `(trade_date, symbol)` resample group ever
spans a shard. Peak memory is one year of rows regardless of corpus length.

**Prices.** Stored as exact `int32` ticks. `core/units.to_quanta` raises on any price
that is not an exact multiple of the tick size — it never rounds. 0.25 is a dyadic
rational, so the integrality test is a true test rather than a near-check.

**Timestamps.** UTC nanoseconds, explicitly. pandas 3.0's `to_datetime(..., utc=True)`
returns `datetime64[us]`, so a build that let the unit be inferred would silently store
microseconds — values 1000× too small. `test_barstore_roundtrip` asserts every 5-minute
timestamp is divisible by 300e9 ns, which microsecond storage would fail.

**Component coverage.** Written during resample. `expected_1m_components` is *computed*
from CME-session and same-trade-date membership of each of the five one-minute labels,
not assumed to be 5. It measured 5 everywhere, which is the expected result given the
session bounds are five-minute aligned — but it is now a verified fact rather than an
assertion in prose.

**`rollover` is window-relative.** It is derived per store from `symbol`, over exactly
the rows that store contains. See `docs/DISCREPANCIES.md` D7 — this is the one-row trap
that would otherwise fail Gate 2 and invite a tolerance.

**Vendored helpers.** `_sha256_file` and `_cme_session_mask` are copied into
`spine/vendored.py` rather than imported, because `data_pipeline.py` pulls torch at
module scope. `tests/test_vendored_equivalence.py` proves bit-identical behaviour across
an exhaustive minute grid spanning both US DST transitions, and **fails** rather than
skips if the originals are unreachable (D5).

## Verification of spec claims

§16.7 instructs checking anything the spec asserts that is checkable.

| Finding | Claim | Measured | Verdict |
|---|---|---|---|
| B | 0 explicit zero-volume rows in 3,665,228 | 0 | **confirmed** |
| C | 28 rolls, 2019-06-18 → 2026-03-18 | identical | **confirmed** |
| C | `trigger = effective − 1` | false as days, true as *sessions* | **D9** |
| D | 87 symbols, outrights 98.4% | 87 = 32 + 55, 98.4198% | **confirmed** |
| E | `ts_event` is bar OPEN | last label 15:59, first after break 17:00; the *raw source* contains exactly one label inside [16:00,17:00) — the D4 row, excluded from the chain | **confirmed, with the D4 exception** |
| F | RTH = 71.2% of volume | 71.70–73.79% by era; no population gives 71.2% | **D10** |
| F | 08:30 CT jump, day's highest minute | ~5.8× jump, highest minute on every population | **confirmed** |

Determinism: two builds from the same source produced 44/44 byte-identical column files.
Manifest drift was confined to the **environment fingerprint fields** — `commit` and
`dirty` (a commit landed between the builds, and the working tree state differed with
it); an external audit confirmed no field outside `environment` differed. Spec §13 test
17 requires byte-identity only when the environment fingerprint matches, so this is the
specified behaviour *and* it demonstrates the fingerprint is live rather than decorative.

## Not verified

- Whether the vendor's bar-generation rule omits no-trade intervals. Finding B says 0
  explicit zero-volume rows were observed; that does **not** establish the rule, and §6
  depends on not claiming it does.
- Which population produces finding F's 71.2%. I did not search for a slice that matches
  the number — that would be fitting the population to the answer.
- Why the vendor emitted one bar inside the maintenance break (D4). It is excluded either
  way, and the exclusion is now evidence-backed rather than assumed benign.
- Spec §11 says the exploration tier is "~985 sessions"; it is **1,009**. The tilde makes
  this approximate rather than a contradiction, but nothing should quote 985.

## External audit (2026-07-28) and resolutions

An independent adversarial audit returned **FAIL** on the original gate claims while
confirming the data artifacts reproduce byte-identically (44/44 `.npy` files). Its
findings were correct; the fixes below each make a gate stricter, never looser. All are
in commit `67aebdc` and its follow-up.

| Finding | What the audit showed | Resolution |
|---|---|---|
| H1 (high) | The CLI Gate 4 checked only store observables; a same-day selector producing one contract per session passed | `gate_roll_causality` now executes the two-version causality fixture against the real selector, with an inert-fixture guard and a leaky-selector power guard. The audit's exact attack, replayed, now raises `GATE 4 FAILED` |
| H2 (high) | With `data/` absent (it is git-ignored), pytest skipped all 63 real-store tests and exited green | Real-store fixtures `pytest.fail` instead of skip. A clean clone now exits 1 with **every** real-store test failing loudly with the build command (the exact count grows as real-store tests are added — do not pin it) |
| M1 (medium) | Gate 3 accepted `distinct_symbol_count = 999` and per-symbol counts altered under a preserved total | All aggregates are recomputed from the listed partition, and the CLI runner re-scans the source's symbol column to verify per-symbol counts value-for-value (a missing source fails the gate). Both attacks, replayed, now raise. The manifest-only layer still cannot see a total-preserving shuffle — that limitation is documented in the docstring and asserted by a test |
| M2 (medium) | A YAML declaring `Europe/London` / a shifted break would build under the vendored Chicago rules while the manifest documented the YAML's | `SpineConstants` fails closed if `session_tz` or `maintenance_break_ct` diverges from what the vendored mask implements. Changing them requires a new pipeline version with a ledger entry |
| L1 (low) | "Only `environment.commit` differed" was incomplete — `environment.dirty` differed too | Determinism paragraph above corrected to "environment fingerprint fields" |
| NOTE | "None in [16:00,17:00)" needs the D4 exception; the seal is friction, not structure (indirect string construction defeats the AST scan) | Verification table above corrected. The seal's honest scope was already stated in `test_seal_guard.py` and spec §11; no change — the audit confirmed the disclaimer is accurate |

Post-fix state: 229 tests pass, 5 xfail. Every audit attack was replayed against the
hardened gates and raised; positive controls still pass.

### Re-audit (2026-07-28, second pass) — PARTIALLY RESOLVED → closed

The re-audit confirmed R2/R4 resolved and the diff loosened nothing, with three LOW
residuals. Resolutions:

| Finding | What the re-audit showed | Resolution |
|---|---|---|
| L1 (low) | Gate 4's docstring said it "certifies the selector in `mnq_lab.spine.rolls`", but fixture-aware selectors (size-aware or date-special-cased) evade a finite fixture | **Claim shrunk to the mechanism**: the gate *detects the registered same-day-volume defect class*; docstring and report note now say exactly that and name the flank guards (Gate 1 historical equality, the CSV-path test, review of `rolls.py`'s written-out causality argument). No finite fixture can certify arbitrary adversarial selectors — strengthening the wording was not an option, so the wording was corrected |
| L2 (low) | A hash-different source forged to reproduce every recorded symbol count passed with `source_verified=True` | Gate 3 now **authenticates the source against the manifest's recorded sha256 before rescanning**; mismatch fails as source-revision. Report carries `source_sha256_verified`. Negative test reproduces the forgery attack with a count-equivalent scratch CSV; a further test asserts the hash check precedes count comparison |
| L3 (low) | Docs pinned "68 loud failures" on a clean clone; the suite had grown to 71 | Count unpinned (see H2 row above) |
| NOTE | `rth_start_ct`/`rth_end_ct` are recorded in manifests but consumed by nothing in Phase 1 — a YAML with `rth_start_ct: "09:00"` builds byte-identical data | Accurate, and acceptable *for Phase 1*: no Phase 1 column depends on RTH. Recorded as a **binding Phase 2 obligation** below |

## Phase 2 obligations carried forward

- **RTH bounds must be consumed from the YAML, not re-hardcoded.** The re-audit proved
  a divergent `rth_start_ct` currently builds identical Phase 1 data (nothing consumes
  it yet). The moment Phase 2 introduces anchors, phases, or any RTH-dependent
  selection, those values must come from `analysis_constants_v1.yaml` — with a
  spec-consistency test tying any runtime literal to the YAML, as was done for
  `session_tz` and `maintenance_break_ct` after audit M2.
- The `+7h` trade-date rule remains hardcoded with no corresponding YAML key; its
  17:00 CT boundary and DST behaviour are covered by `test_session_id_equivalence`.
  If a future spec revision adds a YAML key for it, tie them the same way.

## Next phase

Phase 2 — time model, clock-window engine, completion accounting. Gate: §13 tests 1 and
2. Starting point: `mnq_lab/core/causality.py` (the event-time rule, `shift()` is never
the specification) and `mnq_lab/spine/calendar.py` (anchor observation time = bar label +
`bar_seconds`; time-of-day buckets key on observation time, never the label).
