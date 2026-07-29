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

## D8 — `null:` in the frozen YAML parses to Python `None` — `ACCEPTED-DEVIATION`

**Measured (2026-07-28):** `analysis_constants_v1.yaml` §12 contains

```yaml
inference:
  null:
    kind: whole_session_trajectory_reassignment
```

YAML resolves an unquoted `null` to the null value, so `yaml.safe_load` returns a mapping
whose key is Python `None`. `constants["inference"]["null"]` raises `KeyError` while the
file plainly reads `null:`.

```python
>>> list(yaml.safe_load(open("analysis_constants_v1.yaml"))["inference"])
['formal_tests', 'descriptive_only', None, 'permutations_final', ...]
```

This is a live landmine for Phase 10, which is the phase that reads the null engine's
configuration. It would surface as a `KeyError` at the moment the permutation engine is
wired up — or worse, as a `.get("null", {})` that silently returns an empty config and
runs the null with default-shaped nothing.

**Resolution:** the frozen file is **not** edited. `mnq_lab/constants.py`
`_normalise_yaml_keys` restores the key to the string it was written as, at load time,
with the reasoning recorded at the call site.
`tests/test_spec_consistency.py::test_the_yaml_null_key_still_needs_normalising` asserts
both that the raw YAML still has the `None` key and that the normalised lookup works, so
if the frozen file is ever re-issued with the key quoted, the accommodation is revisited
deliberately instead of lingering as dead code.

**Recommendation for a future frozen revision:** quote it as `"null":`, or rename it to
`null_engine:`. Either requires a ledger entry under §16.4.2. Not done here — this is a
spec change, not an implementation decision.

---

## D9 — Finding C's "trigger = effective − 1" is one *session*, not one day — `RESOLVED`

**Spec §3 finding C:** *"`trigger_trade_date` = `effective_trade_date` − 1"*.

**Measured:** false when read literally. Of the 28 rolls, several span a weekend:

| from → to | trigger | effective | calendar days |
|---|---|---|---|
| MNQU9 → MNQZ9 | 2019-09-13 (Fri) | 2019-09-16 (Mon) | **3** |

The roll policy recorded in the source manifest says `"effective_time": "next available
CME trade date"`, which is the correct reading: trigger and effective are adjacent
*sessions*, and sessions are business days.

**Resolution:** the executable form of the claim is *no trade date exists strictly
between trigger and effective*. `test_roll_trigger_is_the_previous_session_not_the_previous_day`
asserts exactly that against the union of both tiers' session ids, and additionally
asserts that at least one gap is **not** one calendar day — otherwise the test could not
distinguish the two readings and would prove nothing.

Finding C's first and last rolls do happen to be consecutive calendar days, which is
presumably how the imprecise phrasing survived review. Nothing depends on the literal
reading; no code was written against it.

---

## D10 — Finding F's percentages do not reproduce on any population — `OPEN`

**Spec §3 finding F (marked "Computed"):** *"RTH `[08:30, 15:00)` CT = **71.2%** of
volume. 08:29 → 08:30 volume jumps 0.146% → 0.724%."*

**Measured (2026-07-28)**, volume share of RTH and of the two boundary minutes, over
every population I could construct:

| population | RTH share | 08:29 | 08:30 |
|---|---|---|---|
| spec §3 finding F | **71.2%** | **0.146%** | **0.724%** |
| active chain, full 6.9y | 72.8511% | 0.1134% | 0.6572% |
| active chain, exploration tier 2019–2023 | 71.6971% | 0.0980% | 0.6614% |
| active chain, locked tier 2023–2026 | 73.7909% | 0.1260% | 0.6538% |
| raw source, all 87 symbols | 72.7950% | 0.1136% | 0.6587% |
| raw source, all outrights (not only active) | 72.7999% | — | — |

No population reproduces 71.2%; the closest is the exploration tier at 71.70%, still
0.5 pp away. The boundary-minute figures do not reproduce either.

**What *is* confirmed, on every population without exception:**

- 08:30 CT is the **highest-volume minute of the trading day**;
- the 08:29 → 08:30 transition is a jump of roughly 5× (spec 4.96×, measured 5.80×);
- the RTH share sits in a 71.7–73.8% band depending on era.

**Assessment.** Finding F is load-bearing only for *where the RTH boundary is*, and that
conclusion is robust — the jump is unambiguous and lands on 08:30 CT in every slice. The
specific percentages are decorative and are not reproducible from this source. They were
presumably computed on an earlier vintage, a different denominator, or a subset that is
no longer identifiable.

**Not verified:** which population produces 71.2%. I could not find one, and I am not
going to search for a slice that matches the number — that would be fitting the
population to the answer.

**Impact:** none on Phase 1. Phase 2 uses the RTH *boundary*, which is confirmed. No
report should quote 71.2%; quote the measured band and the population it came from.
Nothing in `analysis_constants_v1.yaml` encodes these percentages, so no ledger entry is
required — but §3 of the frozen spec should be corrected in a future revision.

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

---

## D11 — Two spec ambiguities ruled by the user (2026-07-28), implemented in Phase 2 — `RESOLVED`

Both questions were surfaced per §16.6 before coding, put to the user, and ruled. The
rulings are recorded in `docs/PHASE2_HANDOFF.md` §6.5; this entry logs their
implementation. They are binding; neither is an implementer choice.

### D11a — Anchor eligibility is by observation time τ, never the bar label

**The ambiguity.** Spec §4.1's worked example starts the day at the 08:30-labeled bar
(τ = 08:35), which *suggests* the anchor bar itself must lie inside RTH — but the spec
never states that rule, and §4.2 keys phases on "observation-time CT" with buckets keyed
on observation time "NEVER" the label.

**Ruling.** `τ = bar_open_label + 5 min`; an anchor is eligible when
`08:30 ≤ τ < 15:00` CT (half-open); phase is assigned from τ; the outcome begins
strictly after τ. Consequences, implemented in `mnq_lab/spine/timemodel.py`:

- the 08:25-labeled bar (overnight data, τ = 08:30) **is** the session's first
  open-phase anchor;
- the 14:55-labeled bar (τ = 15:00, contained in no phase) yields **no** anchor;
- 78 anchors per full session (the rejected label-in-RTH reading gives 77);
- the §4.1 worked example remains a verbatim test oracle but is an *illustrative*
  anchor, not the first of the day;
- the full declared τ-grid {08:30, 08:35, …, 14:55} is emitted per session; a missing
  anchor bar produces the gridpoint with `status = "anchor_bar_missing"`, never a
  silent absence (§16.4.5);
- τ = 14:50/14:55 anchors are outcome-ineligible at every horizon but remain
  `state_anchors` for prevalence (§10.2);
- the anchor bar's **own** completeness is not required (the worked example lists only
  outcome-path bars as required); its return entering the conditioner at τ is causal.

**Measured (encoded as tests, since the spec's own numbers cannot discriminate):** the
registered close-phase counts (Δ60→1, Δ30→7, Δ15→10) reproduce **identically** under
both readings — `test_window_boundaries.py::test_the_registered_counts_cannot_discriminate_the_eligibility_ruling`
proves it and locates the single differing gridpoint per session ({τ=08:30} vs
{τ=15:00}). The open edge is therefore pinned explicitly:
`test_time_and_timezone.py::test_tau_0830_anchor_exists_in_the_open_phase` and
`::test_the_1455_labeled_bar_yields_no_anchor`. On the real exploration store the grid
is 1009 × 78 = 78,702 gridpoints.

**Why ruled now:** the decision moves exactly one anchor per session into the open
phase (6 gridpoints vs 5, ~20% of open-phase anchor mass) and therefore changes the S00
population Phase 3 freezes completion thresholds from.

### D11b — No CME calendar exists; short sessions carry data-derived flags only

**The gap.** §4.3 requires holidays "from a VERSIONED CME calendar table"; §13 test 1
wants early-close coverage now; no versioned calendar exists in this repository, and
§9.2/§14 hold that inventing one from memory is worse than declaring the gap.

**Ruling.** The user will not supply a calendar now. Phase 2 implements data-derived
flags with honest names in `TimeModel.session_flags`:

```
observed_short_session / observed_rth_ended_early   derived from data
calendar_early_close                                "unknown" — unknown, not false
formal calendar-dependent exclusion                 fail closed / deferred (Phase 10)
```

A scheduled early close, a feed outage, and a vendor gap all produce the same flag;
that uncertainty is intentional. Truncated-end sessions and mid-session-gap sessions
are distinguished (`n_rth_bars_missing_trailing` vs `_interior`; a session can be
both). The YAML's `completion.source_population.include_holidays_flagged: true` is
**satisfied by the data-derived flag** until a versioned CME calendar table arrives as
a new versioned input with a ledger entry — required no later than the seasonal
profile (Phase 7) and formal inference exclusions (Phase 10).

**Measured (exploration tier, 1009 sessions, 2026-07-28; re-measured after the
external audit):** 34 sessions have `observed_rth_ended_early` — last RTH bar ends
12:00 CT in 25 sessions, 12:15 in 7, 10:00 in 1, 09:15 in 1. One further session
(20210402) has **zero RTH bars** while its overnight bars exist. 4 sessions have
`observed_mid_rth_gap`; no session has both. §13 test 1's early-close coverage uses a
synthetic shortened-session fixture plus one real session **selected by data** (the
earliest observed RTH end), with no holiday name attached anywhere.

**Audit correction (2026-07-28).** 20210402 was initially counted among 35
"ended early" sessions with the sentinel `last_rth_bar_end_ct_minute = -1`. The
external audit judged that semantically weak, and it was: *a session that never
started did not end early*, and the flag asserted more than the data shows. It is now
a distinct state, `observed_no_rth_bars`, mutually exclusive with
`observed_rth_ended_early`; the `-1` sentinel is documented as "no RTH bars", and any
consumer ranking sessions by last-end minute must exclude it — the real-session test
now asserts that exclusion.

**Not verified (by design):** which of the 34 shortenings were scheduled, and whether
20210402's absence was a holiday, an outage, or a vendor gap. That classification is
impossible without the calendar table and is not claimed.

---

## D12 — `observed_bar_path` window completeness is not uniquely determined by §6 — `OPEN`

**Spec §6:** the two estimands are `fully_labeled_1m_grid` — "every 5-min bar in the
path contains all five expected 1-min labels" — and `observed_bar_path` — "excursions
across the bars present in the source".

**The ambiguity.** For `fully_labeled_1m_grid` the rule is explicit. For
`observed_bar_path` "the bars present in the source" admits two readings when a
required 5-min bar is entirely absent:

1. **Implemented here (conservative):** a window is complete only if *all* required
   5-min bars are present; 1-minute coverage is not required. A window missing a whole
   bar is incomplete under **both** estimands, because an excursion measured across an
   absent interval would invent the price path over that interval. The two estimands
   then differ *exactly* on 1-minute coverage — which is what §13 test 5's
   discriminating case tests.
2. **Permissive:** measure the excursion across whatever bars exist, so a window with a
   missing bar is still "observed", just sparser. Under this reading the estimand
   places no completeness requirement at all, and `min_completion_*` would be
   meaningless for it.

**Raised by:** the external Phase 2 audit (2026-07-28), which confirmed the
implementation is internally consistent and documented, but noted the spec text does
not compel reading 1 and that no ruling exists.

**Why it matters now:** Phase 3 freezes `min_completion_h15/h30/h60` into the YAML from
the S00 population **under a chosen estimand**, with a ledger entry, and §16.4.2
forbids changing a constant after the affected result is computed. Choosing the reading
after the thresholds are frozen would be exactly that.

**Measured impact under the current reading (exploration tier):** the two estimands
differ by at most 0.16 pp in any phase × horizon cell (largest gap: midday Δ60,
0.98188 vs 0.98350). Whole-bar absences are rare, so the two readings would produce
similar thresholds — but "similar" is not "ruled", and the difference is not zero.

**Status:** OPEN — requires a user ruling before Phase 3 freezes thresholds. Reading 1
is implemented and documented; nothing is coded around the ambiguity, and no threshold
has been frozen.
