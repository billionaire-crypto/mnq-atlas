# Discrepancies between the frozen spec, the repository, and the data

Per spec §16.6: report, do not code around. Entries are appended, never deleted. Each
records what was **measured**, what was **inferred**, and what was **not verified**.

Status values: `OPEN` · `RESOLVED` · `ACCEPTED-DEVIATION` (spec is wrong about the
environment; behaviour documented and tested).

---

## D1 — §16.2 says the workspace is not a git repo. It is. — `ACCEPTED-DEVIATION`

**Spec §16.2:** *"Git — The workspace is NOT a git repo (git log is empty). Record
`"vcs": "none"` in fingerprints; hash source files directly."*

**Measured (2026-07-28):** `C:\mnq-atlas` is a git repository on branch `main` with
remote `https://github.com/billionaire-crypto/mnq-atlas.git`. It had zero commits at
session start, which is presumably what produced the "git log is empty" observation, but
`.git/` exists and the repo is live.

**Resolution:** the environment fingerprint records `vcs: "git"` with the commit SHA and
a dirty-tree flag, **and** continues to hash source files directly as §16.2 requires. The
recorded SHA is strictly additional information; nothing depends on it that previously
depended on file hashes. Recording `"none"` would have been a false statement in an
artifact whose purpose is reproducibility.

**Not verified:** whether the spec author intended a different workspace path.

---

## D2 — Gate 2's date range is ambiguous (UTC span vs trade-date span) — `RESOLVED`

**Spec §5.1 gate 2:** *"Rebuilt 5-min bars 2023-03-29 → 2026-03-29 row-for-row identical
to `data/mnq_active_5m_3y.csv`."*

**Measured:** the reference CSV's UTC `ts_event` span is `2023-03-29T22:00:00Z` →
`2026-03-29T23:55:00Z`, but its CME **trade-date** span per its own manifest is
`2023-03-30` → `2026-03-30`. These describe the same 211,968 rows two different ways,
because the first bar is 2023-03-29 17:00 CT, which belongs to trade date 2023-03-30.

**Resolution (user decision, 2026-07-28):** Gate 2 is defined as row-for-row identity
against **every row of the reference CSV, with no date filter applied**. This removes
implementer discretion over which rows are compared and makes it impossible to narrow the
gate accidentally.

---

## D3 — Finding D's "87 symbols" was unrecorded; now measured — `RESOLVED`

**Spec finding D:** *"Source 2019-05-05 → 2026-03-29; 87 symbols; MNQ outrights 98.4%,
remainder calendar spreads."*

At session start this was unverifiable from any local artifact: the reference manifest
recorded 32 *outright* symbols and a spread **row** count, never a distinct-symbol total.

**Measured (2026-07-28, full pass over the symbol column of all 3,665,228 rows):**

| | symbols | rows | share |
|---|---|---|---|
| outright `MNQ[HMUZ]\d` | 32 | 3,607,321 | 98.4198% |
| calendar spread | 55 | 57,907 | 1.5802% |
| **total** | **87** | **3,665,228** | 100% |

Finding D confirmed exactly. All 55 rejected symbols match `MNQ<M><Y>-MNQ<M><Y>` where
both legs are themselves valid outright symbols; the partition is exhaustive with no
residue. This is the authoritative Gate 3 classifier (§5.1 gate 3 forbids the struck
"≈1.6% spread rows" percentage check — see §14).

**Not verified:** that a future vendor drop uses the same spread naming. Gate 3 fails
closed on any symbol matching neither pattern, and the manifest re-versions the counts on
a new source hash.

---

## D4 — `out_of_session_outright_rows_excluded = 1` — `RESOLVED`

**Retrieved** from `mnq_active_5m_3y.csv.manifest.json`: the original build excluded
exactly **one** outright row as falling outside the CME session mask, out of 3,607,321.

One is a suspicious count — it is either a genuine vendor artifact or an off-by-one at a
session boundary in `_cme_session_mask`. A boundary bug affecting exactly one row would
be invisible in aggregate but could indicate a misplaced `<` vs `<=` at 16:00 or 17:00 CT.

**Measured (2026-07-28):** the build now retains the row rather than counting it. It is:

```json
{"ts_event_utc": "2020-03-31T21:59:00+00:00",
 "ts_event_ct":  "2020-03-31T16:59:00-05:00",
 "weekday_ct": 1, "symbol": "MNQM0", "volume": 17}
```

16:59 CT on a Tuesday is **inside the daily maintenance break** `[16:00, 17:00)` CT, one
minute before the Globex session reopens. The mask is therefore correct and the exclusion
is right: the vendor emitted a single bar inside the halt window across 6.75 years. Not a
boundary bug.

This is also independent corroboration of finding E (`ts_event` is the bar open): a
close-labelled bar at 16:59 would denote the interval `[16:58, 16:59)`, equally inside
the halt, so the row is anomalous either way — but its isolation is consistent with a
stray print rather than a systematic labelling error.

The row is recorded verbatim in every store manifest under `out_of_session_source_rows`.

**Not verified:** why the vendor emitted it. Not needed — it is excluded either way, and
the exclusion is now evidence-backed rather than assumed benign.

---

## D7 — `rollover` is window-relative, not a property of the bar — `RESOLVED`

The original pipeline computed `rollover = symbol.ne(symbol.shift())` **after** slicing to
its three-year window, so the first row of the reference CSV is `True` even though MNQM3
was already the active contract on the preceding trade date 2023-03-29. `rollover` is
therefore a property of the *emitted window*, not of the bar.

A naive full-history build that sliced afterwards would produce `False` on that row and
fail Gate 2 on exactly one cell — a one-row discrepancy that is easy to "fix" with a
tolerance and would then hide real roll-mapping errors.

**Resolution:** `symbol` is authoritative and `rollover` is derived per store, via
`resample.compute_rollover`, over exactly the rows that store contains. Because the locked
tier begins at trade date 2023-03-30 — precisely the reference CSV's first trade date —
the locked store's `rollover` column reproduces the reference exactly, and Gate 2 compares
it rather than excusing it. **Measured: all 211,968 rows match on all 8 columns**,
`rollover` included.

`rollover` must never be used to reconstruct contract identity; read `symbol`.

---

## D5 — `data_pipeline.py` imports torch at module scope — `ACCEPTED-DEVIATION`

Spec §16.2 says to reuse `_sha256_file` and `_cme_session_mask` from `data_pipeline.py`.
Importing that module executes `import torch` (it defines `nn.Module` subclasses at module
scope), pulling a training stack into a measurement lab and inflating the environment
fingerprint.

**Resolution:** both helpers plus `CME_TIMEZONE` are vendored verbatim into
`mnq_lab/spine/vendored.py` with provenance headers naming the source file and line
numbers. `tests/test_vendored_equivalence.py` imports the originals and asserts
bit-identical output across an exhaustive minute grid spanning both US DST transitions.

Vendoring **without** that equivalence proof would be an unjustified reimplementation and
is forbidden. If the test cannot import the originals, it fails — it does not skip.

---

## D6 — The Gate 2 reference CSV *is* the locked-confirmation tier — `RESOLVED`

**Spec §11:** exploration = 2019-05-05 → 2023-03-29; locked confirmation = 2023-03-30 →
2026-03-29. **Spec §16.4.1:** never touch `data/locked_confirmation/` from the
exploration runtime.

**Observed:** the Gate 2 oracle `mnq_active_5m_3y.csv` spans trade dates 2023-03-30 →
2026-03-30 — precisely the locked tier. So the gate that validates the build necessarily
reads locked-tier data.

**Resolution:** this is not a conflict, because §16.4.1 constrains the *exploration
runtime*, not the build. The boundary is made explicit in code: only `spine/build.py`,
`spine/gates.py` and `spine/seal.py` may reference the locked path, and
`tests/test_seal_guard.py` asserts by AST scan that no module under `conditioners/`,
`outcomes/`, `studies/`, `report/` or `core/` names it. `Corpus.EXPLORATION` is truncated
at `seal_boundary − max_horizon_bars` so locked rows are *absent from the object*, not
merely flagged.

The tier split is on **CME trade date**, not UTC date: exploration `trade_date <=
2023-03-29`, locked `trade_date >= 2023-03-30`. Chosen because the spec's two tier bounds
are contiguous calendar days and 2023-03-30 is the reference CSV's first trade date, so
only the trade-date reading makes the tiers adjacent and non-overlapping.
