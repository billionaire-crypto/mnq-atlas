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

## D12 — `observed_bar_path` window completeness was not uniquely determined by §6 — `RESOLVED`

**Spec §6:** the two estimands are `fully_labeled_1m_grid` — "every 5-min bar in the
path contains all five expected 1-min labels" — and `observed_bar_path` — "excursions
across the bars present in the source".

**The ambiguity.** For `fully_labeled_1m_grid` the rule is explicit. For
`observed_bar_path` "the bars present in the source" admits two readings when a
required 5-min bar is entirely absent:

1. **Conservative:** a window is complete only if *all* required
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

**Measured impact under the ruled reading (exploration tier):** the two estimands
differ by at most **0.175 pp** in any phase × horizon cell (largest gap: **midday
Δ30**, 0.99000 vs 0.99175; midday Δ60 is second at 0.162 pp). *Correction
(round-2 audit, 2026-07-28): this entry originally claimed "at most 0.16 pp, worst at
midday Δ60" — wrong because the gap was compared only within Δ60 on the assumption
the worst cell sat at the longest horizon. The gap is not monotone in Δ; all 15 cells
are now compared.* Whole-bar absences are rare, so the two readings would produce
similar thresholds — but "similar" is not "ruled", and the difference is not zero.

**User ruling (2026-07-28):** adopt Reading 1, the conservative definition. Every
required 5-minute bar must exist. A wholly missing required bar makes the window
incomplete under **both** estimands; `observed_bar_path` relaxes 1-minute component
coverage only, never 5-minute path continuity. Measuring an excursion across an
absent interval would treat an unknown path as observed, and the permissive reading
would make `min_completion_*` meaningless for this estimand.

**Status:** RESOLVED — Reading 1 was already the implemented and tested mechanism, so
the ruling changes no measurements. It closes the ambiguity before Phase 3 freezes
`min_completion_h15/h30/h60`.

---

## D13 — weighted-quantile scale invariance is not exact for arbitrary binary64 factors — `RESOLVED`

**Frozen spec §7.2:** weighted inverse-CDF statistics are replication-invariant. The
Phase 4 handoff additionally proposed that positive rescaling of every weight could not
change the returned support value.

**Measured by the independent Phase 4 quant audit (2026-07-29):** at exact CDF
boundaries, multiplying every binary64 weight by an arbitrary positive factor changed
the returned adjacent support value in 23,017 of 100,000 trials. Random-q testing hid
the defect completely: zero changes in 300,000 trials. Power-of-two factors
`{0.25, 0.5, 2, 4, 1024}` produced zero changes in 100,000 boundary trials because
binary scaling is exact.

**Cause:** arbitrary multiplication rounds individual binary64 weights. Near an exact
CDF boundary, those rounded inputs need not preserve the equality between cumulative
mass and `q * total_mass`. This is a property of the supplied finite-precision inputs,
not interpolation or a failure of the inverse-CDF definition.

**Ruling:** Phase 4 guarantees exact scale invariance for exactly representable
power-of-two factors. For a general positive factor it guarantees invariance except
where binary64 rounding moves `q * total_mass` across a cumulative boundary. No
tolerance, epsilon, normalization, or nearest-boundary repair is allowed in quantile
selection. Tests use a power-of-two factor or integer replication counts for the exact
invariance claim.

**Cross-phase impact:** Phase 5 bootstrap fractional weights must use the same canonical
Phase 4 accumulation path. It must not reintroduce a general exact-scale-invariance
claim or a tolerance around CDF boundaries.

**Not verified:** the audit did not establish a closed-form frequency for boundary
changes outside its sampled binary64 populations. The measured 23% is a diagnostic of
the adversarial fixture distribution, not an expected rate for atlas weights.

---

## D14 — “dual estimand” in §15 row 5 was undefined — `RESOLVED`

**Frozen text:** §15 row 5 says:

```text
Bootstrap: whole-session, block sensitivity, dual estimand
```

The phrase “dual estimand” appears only there and is not defined locally. At
least three pairs elsewhere in the frozen spec could initially appear to fit:

1. §6’s two path estimands, `fully_labeled_1m_grid` and
   `observed_bar_path`;
2. §7.1’s session-equal primary and anchor-equal companion weightings; or
3. §7.3’s horizon-specific and common support.

Those readings imply different deliverables, so Phase 5 did not choose one
silently.

**Independent audit:** Opus 5 tied the phrase to §6. Section 6 is the only
frozen location that explicitly counts exactly two objects and calls them
“estimands.” Section 7.1 defines three population estimands and describes
session-equal and anchor-equal as weightings within an estimand. Section 7.3
calls horizon-specific and common alternatives “support,” not estimands.

**User ruling (2026-07-29):** “dual estimand” in frozen-spec §15 row 5 means
the two §6 path estimands:

```text
fully_labeled_1m_grid
observed_bar_path
```

Phase 5 proves only the market-free abstraction required to support that pair:
one coherent global resample plan can serve two aligned value/eligibility-mask
paths with differing support, with masks applied only after the plan. Phase 5
does not construct either market path estimand, import outcome logic into
`core/`, or begin Phase 6+ work.

Session-equal primary and anchor-equal companion weighting remain independently
required Phase 5 paths under §7.1 and the signed-off Phase 4 contract. They are
not the meaning of “dual estimand.”

**Governance ruling:** this resolved discrepancy plus the committed
`docs/PHASE5_PREREGISTRATION.md` and its SHA-256-pinning test are sufficient.
The frozen YAML is unchanged. No Phase 5 entry is added to the Phase 3-only
threshold ledger, and its schema is not expanded.

**Status:** `RESOLVED` before any Phase 5 production implementation or
stochastic acceptance execution.

---

## D15 — v1 coverage gate assumed nominal 95% equals finite-sample coverage — `RESOLVED`

**Registered failure:** On 2026-07-30, the preregistered Phase 5 v1 coverage
fixture executed exactly once and returned 267 covering intervals out of 300
against the inclusive acceptance region [277, 292]. The exact command,
evidence line, failure, environment, and commits are preserved permanently in
`docs/PHASE5_ACCEPTANCE_RECORD.md`. The v1 fixture will never execute again.
The AR(1) fixture was not executed and its registered entropy remained
unconsumed.

**Forensic verdict:** independent read-only audit classified the result as a
preregistered acceptance-design defect, not an implementation defect. The
fixture correctly executed the registered procedure, and the production path
remained supported by its prior independent randomized reproductions and
mutation audits.

**Exact evidence:** under the gate's assumed model,

```text
P[C <= 267 | C ~ Binomial(300, 0.95)] = 2.272e-05
```

The exact central 95% bounds for the procedure's true coverage from 267/300
were [0.849, 0.923]. The result therefore rejects the gate's `p = 0.95` risk
model rather than representing an ordinary draw from its declared 3–8%
false-failure risk.

**Identified mechanism:** the v1 calibration treated nominal 95% percentile
coverage as finite-sample 95% coverage for the whole-session stationary block
bootstrap. With 80 independent groups and mean block length 5, distinct
positions selected within a stationary block narrow the bootstrap median
distribution relative to iid multinomial resampling. The forensic derivation
gave the variance factor

```text
1 - 8/79 = 0.899
```

and, through an explicitly labelled normal-approximation layer, moved the
idealized discrete endpoints from 31/49 to 32/48, corresponding to
approximately 0.925 coverage. The exact registered procedure's true coverage
was not claimed to be known from that approximation; the exact rejection of
`p = 0.95` does not depend on it.

**Audit responsibility:** the incorrect 3–8% risk band originated in the
independent Mode A audit's iid idealization. It was inferred and unmeasured,
and the effect of within-block distinct sampling was omitted when the gate was
ratified.

**User ruling (2026-07-30):** the original 267/300 result is permanent and is
never erased, reinterpreted, or overwritten. Under the pre-agreed Amendment
P5-2 failure clause, the user authorized a calibration-first recovery with a
new versioned coverage-only preregistration, new seed schedules, independent
static audits before execution, and mechanically derived exact-binomial
bounds. The v1 preregistration remains byte-pinned and unmodified. No
production change is authorized. The AR(1) one-shot is re-authorized unchanged
only after a v2 coverage pass.

**Status:** `RESOLVED` as an acceptance-design discrepancy. Phase 5 remains
open and Stage E2b remains blocked until the separately preregistered v2
calibration and coverage gate complete under the ruled sequence.

---

## D16 — v2 calibration script-path launch could not resolve `mnq_lab` — `RESOLVED`

**Registered failure:** On 2026-07-30, the v2 calibration launch used:

```text
python tools/phase5_coverage_calibration.py
```

It failed in 0.1359 seconds with this exact traceback:

```text
Traceback (most recent call last):
  File "C:\mnq-atlas\tools\phase5_coverage_calibration.py", line 14, in <module>
    from mnq_lab.constants import load_bootstrap_constants
ModuleNotFoundError: No module named 'mnq_lab'
```

The complete command, traceback, runtime, environment fingerprint, commits,
and runner hash are permanently preserved in
`docs/PHASE5_ACCEPTANCE_RECORD.md` at commit `af5f1c3`.

**Root cause:** the script-path launch placed `C:\mnq-atlas\tools`, rather
than the repository root, on `sys.path[0]`. The local `mnq_lab` package is not
installed in site-packages and resolves only from `C:\mnq-atlas`, so the
top-level import failed before `main()`.

**Entropy status:** the v2 calibration entropy remains unspent. Because the
import failed before `main()`, the entropy was never passed to
`SeedSequence`, no Generator was constructed, no replication ran, no evidence
line was emitted, and no `K`, partial result, or stochastic information was
observed.

**User ruling (2026-07-30):** the event is permanently classified as a
deterministic launch defect, not a statistical result, implementation defect,
or acceptance outcome. The failed launch and its record may never be erased,
reinterpreted, or overwritten. Under Amendment P5-2, the user corrected the
one authorized launch command to:

```text
python -m tools.phase5_coverage_calibration
```

run from `C:\mnq-atlas`, exactly once and only after the amendment commit
receives a fresh independent static audit returning CLOSED. The runner and
every statistical parameter remain unchanged.

**Resolution:** `docs/PHASE5_PREREGISTRATION_V2_AMENDMENT_1.md` records the
single-line command amendment, and
`test_phase5_preregistration_v2_amendment_1_bytes_are_pinned` in
`tests/test_spec_consistency.py` pins its bytes. The deterministic preflight
guard separately proves the corrected module resolution and the recorded
script-path failure mode without importing or executing the runner.

**Status:** `RESOLVED` as a deterministic launch discrepancy. The calibration
remains blocked until the amendment commit passes independent static audit;
the v2 coverage and AR(1) one-shots remain blocked.

---

## D17 — Phase 6 dependency and registry design latitude — `RESOLVED`

**Frozen text:** frozen spec §13 test 6 requires out-of-window mutation,
deterministic per-function witnesses, exact comparison for tick/integer/mask
output, and declared floating tolerance. Section 11 requires separate causal
and descriptive registries and says causal admission must pass the declared
adversarial suite, while explicitly describing that result as empirical evidence
rather than proof. The frozen text does not uniquely specify the executable
window representation, mutation seed, purity coverage, registry lifecycle,
module placement, or non-forgeable admission mechanism.

**Initial independent audit:** the first review of the Phase 6 handoff at
`8e68095203ec0fa1b8be0b23a0e2f7655118dfc1` returned `OPEN`. It verified the
Phase 5 correction, protected hashes, safe `614 passed, 5 xfailed` baseline, and
Phase 6 scope, but found three contract defects: an unspecified alternate
causal-admission mechanism, a floating witness that could be insensitive within
its own tolerance, and unrecorded design-latitude resolutions. This `OPEN`
history is permanent and is not replaced by a later correction or re-audit.
The focused correction re-audit at
`a51c35c0a4bf59ffa4f5bbdc532145fc797d874a` returned `OPEN` / `AMEND`:
the single admission path and recorded design decisions closed F1 and F3, but
the floating-witness rule cleared only one tolerance band and did not require a
baseline assertion, allowing a constant output to satisfy both comparisons.
That second `OPEN` result is also permanent.

**User ruling (2026-07-31):** follow the prior phases' single-path, fail-closed
admission discipline. `register_causal_conditioner` must execute the complete
declared locality cases, deterministic witnesses, and required negative controls
inside the registration call; validate them before insertion; and atomically
insert only after every check succeeds. Phase 6 has no alternate causal-admission
path. Caller-supplied booleans, tokens, evidence objects, cached or serialized
results, prior-run results, and duck-typed certificates cannot cause admission.

**Recorded executable resolutions:** prior to production implementation, the
Phase 6 preregistration must preserve all of the following:

1. Window membership uses immutable event-time dependency coordinates plus an
   explicit immutable boolean allowed-dependency mask. Positional offsets alone
   are insufficient on gapped or irregular coordinates.
2. Coordinates and the mask determine membership and are never adversarially
   mutated. Locality mutations change aligned values only, exercise every
   forbidden region, and verify at least one actual changed value in each region.
3. Deterministic test mutation uses `Generator(PCG64(0))`. Seed 0 is an ordinary
   software-test seed, not scientific entropy, a one-shot seed, or registered
   Phase 5 entropy.
4. The harness makes supplied arrays read-only, retains exact snapshots, and
   repeats calls on fresh identical inputs to detect direct mutation and
   nondeterministic output. Hidden RNG, module globals, corpus-length dependence,
   and undeclared companion inputs are tested through planted controls where the
   contract claims coverage. Passing those controls is empirical evidence only;
   it cannot prove the absence of every possible hidden dependency.
5. Integer, tick, category, and boolean outputs compare exactly. Floating output
   first requires exact shape and dtype, then compares elementwise by
   `abs(actual - expected) <= atol + rtol * abs(expected)` using function-specific
   finite nonnegative tolerances fixed in immutable metadata. A floating witness
   independently specifies baseline and expected changed responses, and the
   harness asserts the callable against both. At a required affected element the
   expected responses must satisfy `abs(expected_changed - expected_baseline) >
   (atol + rtol * abs(expected_changed)) + (atol + rtol *
   abs(expected_baseline))`, making their comparison bands disjoint. Otherwise
   the witness is vacuous and fails before admission, so no constant or
   insensitive output can satisfy both comparisons.
6. Identifiers are unique across causal and descriptive registries. Every
   duplicate identifier fails; overwrite, unregister, downgrade, and
   reclassification do not exist. The same callable object cannot enter through
   an alias or the other registry. A distinct wrapper is independently admitted.
   Metadata and retrieval are immutable, and iteration is insertion-ordered,
   never sorted by a measured output.
7. Generic market-free declarations, comparisons, and harness mechanics belong
   in `core/`; registry mechanics belong in `conditioners/`; synthetic witness
   callables remain in tests. No actual conditioner or market-data access enters
   Phase 6.
8. Phase 6 verifies locality relative to a declared window. It cannot generically
   prove that a future real conditioner's declared window is semantically correct
   or minimally sufficient. Review and mutations for an over-wide real-conditioner
   declaration remain a Phase 7 obligation and must not be claimed closed by the
   Phase 6 gate.

**Governance:** these resolutions amend only the proposed Phase 6 executable
contract. They do not modify the frozen specification, YAML, any Phase 5 record,
or any scientific result. `docs/PHASE6_PREREGISTRATION.md` remains absent until
this correction receives a focused independent `CLOSED` audit and the complete
amended contract is `RATIFIED`.

**Status:** `RESOLVED` by explicit user ruling and recorded design decisions,
pending independent re-audit of the documentation correction. No Phase 6
production implementation is authorized by this entry alone.

---

## D18 — Phase 6 Stage D admission-gate audit — `OPEN; CORRECTED PENDING RE-AUDIT`

**Audited implementation:** the independent Stage D review of
`ed59c541d7212c036d3867ff82dfff4bd3bb101d..4a3db01d475a737952dab474588c3b8cf7e17a14`
returned `VERDICT: OPEN` and `NEXT: STAGE E NOT AUTHORIZED`. That `OPEN`
history is permanent and is not replaced by this correction or a later
re-audit.

**Verified finding D-1:** the negative-control recognizer inferred the failure
family from exception-message substrings. Caller-controlled case or input names
containing `comparison failed` could therefore make an out-of-window shape
mismatch count as the required locality-comparison failure. The auditor
executed both vectors and admitted a causal entry whose recorded negative
control had failed through the wrong mechanism.

**D-1 correction:** Stage C comparison failures now carry a structured
`DependencyCheck` and `DependencyFailure` on `DependencyCheckError`. Shape,
dtype, exact-comparison, and floating-comparison failures are distinct;
locality, witness-baseline, and witness-changed checks are distinct. Registry
negative controls inspect only those enum identities. They do not parse case
names, input names, exception prose, or another caller-supplied string. A
structured exception raised directly by the conditioner is still wrapped as a
callable failure and cannot satisfy a negative control.

**Verified finding D-2:** `ConditionerRegistry._register_causal` was reachable
by ordinary attribute access and inserted directly without repeating the
validators used by the module-level wrapper. Passing empty locality, witness,
and negative-control tuples produced a stored causal descriptor with zero
executed evidence and confirmation eligibility equal to true.

**D-2 correction:** both insertion methods are name-mangled, and the causal
insertion method itself validates the identifier, callable, immutable metadata,
complete nonempty suite, exact callable linkage, witness linkage, and both
required negative-control families before executing or inserting. Calling the
name-mangled method directly cannot bypass these checks. The descriptive
insertion method likewise performs its own identifier, callable, and metadata
validation so the shared lifecycle has one validation choke point per
classification.

**Scope and governance:** this correction changes only the two verified
admission-gate mechanisms, their negative tests, and this permanent audit
record. It does not amend the ratified preregistration, implement a real
conditioner, or authorize Stage E. Stage E remains blocked until this correction
receives a focused independent `CLOSED` re-audit.

---

## D19 — Phase 7 versioned CME equity-index calendar acquisition — `OPEN; COMMITTED ARTIFACT AUDIT PENDING`

**Frozen-input basis.** Frozen spec §4.3 requires full exchange holidays and
scheduled early closes to be excluded from the seasonal reference using a
versioned CME calendar table. D11b deferred that input only until the seasonal
profile in Phase 7. Phase 7 is now that phase. Observed shortening is never a
calendar oracle: it may corroborate, falsify, or create a §16.6 data-quality
discrepancy, but it may not generate or amend a holiday classification.

**Authorization and licence record.** On 2026-08-01 the user stated that they
hold a CME data licence and authorized local-only use of CME data obtained
through a licensed channel. The licence document was not inspected by the
independent auditor, and no legal determination is claimed. Automated retrieval
from cmegroup.com remained unauthorized and did not occur. The user subsequently
authorized permissively licensed third-party calendars, with accuracy of the
dates rather than source identity as the binding scientific criterion. No
calendar branch may be pushed.

**Failed acquisition routes, preserved.** The licensed Databento material
available locally contained OHLCV-1m data but no session-calendar or status
extract for this period. The initial two-library Route B compared
`pandas-market-calendars` 5.4.0 with `exchange-calendars` 4.13.2 and stopped as
required when their extracts disagreed. The latter self-describes CMES as a
generic conservative CME calendar and is ineligible for the product-specific
CME equity-index requirement. Its nine falsified dates remain permanent
evidence rather than being discarded:

| trade date | pandas-market-calendars | exchange-calendars |
|---|---:|---:|
| 2019-07-03 | 12:15 CT | regular |
| 2019-11-29 | 12:15 CT | 12:00 CT |
| 2019-12-24 | 12:15 CT | 12:00 CT |
| 2020-11-27 | 12:15 CT | 12:00 CT |
| 2020-12-24 | 12:15 CT | 12:00 CT |
| 2021-04-02 | 08:15 CT | full holiday |
| 2021-11-26 | 12:15 CT | 12:00 CT |
| 2022-06-20 | 12:00 CT | regular |
| 2022-11-25 | 12:15 CT | 12:00 CT |

The exploration store independently falsifies all nine generic-calendar claims:
the observed final bar ends at the product-specific time on every date, including
183 five-minute bars through 08:15 CT on 2021-04-02. This evidence rejected an
ineligible candidate; it did not author the accepted classifications.

**U10 source and acceptance ruling.** The user ratified
`pandas-market-calendars` calendar `CME Globex Equity`, release 5.4.0, upstream
commit `275890784073a3a3a347e4f05f4dc986456e6a75`, as the single source candidate.
Its source defines a 17:00 CT prior-calendar-day raw open, a 16:00 CT regular raw
close, and product-specific early closes. The study RTH projection remains the
separate frozen interval `[08:30, min(raw exchange close, 15:00))` CT. A total
mapping has no default branch: full closures have no RTH, an early close at or
before 08:30 has no scheduled RTH, one strictly between 08:30 and 15:00 shortens
RTH, one at or after 15:00 but before 16:00 leaves RTH full, and an alleged early
close at or after 16:00 fails closed. `unscheduled_closure` may be populated only
by an external authority and is never inferred from bars.

**A4 ordering violation.** The first candidate extract existed before known-date
expectations were preregistered. A4 is therefore permanently
`ORDERING-VIOLATED`; no later document may backfill those expectations or claim
they were preregistered. Acceptance substitutes an exhaustive observational
battery that the external library did not derive from this Databento extract.
That battery is corroboration, not proof, and its comparisons are strongly
correlated within approximately eight to ten holiday-rule families.

**Measured acceptance support.** Across the 1,018 Monday-through-Friday dates
from the first in-range weekday, 2019-05-06, through 2023-03-29, the candidate
contains 976 regular sessions, 33 scheduled early closes, and nine full
closures. The exploration spine contains 1,009 sessions. The complete disjoint
reconciliation is:

- 974 candidate-regular sessions with observed final bar end exactly 16:00 CT;
- 32 timed early closes matching to the minute: 25 at 12:00 and seven at 12:15;
- one no-scheduled-RTH structural match, 2021-04-02 at 08:15;
- nine candidate full closures matching the nine absent weekdays; and
- two explicitly retained §16.6 data-quality discrepancies.

The two discrepancies remain calendar class `regular` and carry
`unresolved_truncated_session`: 2020-02-28 ended at 10:00 CT and 2020-06-30
ended at 09:15 CT. They are not holidays and are not silently reconciled. Under
the frozen seasonal rule they remain regular reference candidates while their
truncation is counted and disclosed.

**Audit corrections without asymmetry.** The permanent history records errors
by both roles. The initial acceptance design incorrectly required a full closure
to correspond to a session anomaly flag even though a full closure has no
session row. The auditor also conflated the study's 15:00 RTH boundary with the
source's 16:00 Globex close, initially counted 41 rather than 42 anomalous
comparisons, and called correlated checks independent. Codex's initial extractor
retained only a five-file source subset while describing it too strongly for
regeneration and used an extraction environment different from the laboratory
environment. Each error is retained rather than overwritten by its correction.

**F-1 source-retention ruling.** Accuracy takes priority over implementation
effort. The committed provenance retains all 47 Python source files in the
pinned `pandas_market_calendars` package, plus licence, project metadata, tag and
commit evidence, and an exact extraction dependency lock. Every Python source
file is stored with inert `.py.txt` suffix; the provenance tree has no
`__init__.py`, importable module, or pytest-collectable test. A canonical sorted
per-file index records original path, stored path, byte count, and SHA-256. The
tree hash is SHA-256 over, in original-path order, UTF-8
`original_path + NUL + decimal_bytes + NUL + lowercase_sha256 + LF`. External
interpreter dependencies are version-locked but not vendored, so the retained
tree is not described as a hermetic regeneration environment.

**F-2 determinism ruling.** The one-time extraction used pandas 3.0.5 and numpy
2.5.1, while the MNQ Atlas laboratory records pandas 3.0.1 and numpy 2.2.3.
`pandas_market_calendars` is deliberately absent from the runtime. Raw-byte
re-extraction is claimed only for the recorded matching extraction environment.
Across environments the requirement is semantic identity of the canonical
table. The repository acceptance path validates the committed static table
against the exploration spine without importing either calendar library.

**Canonical representation and placement.** The versioned reference input is
canonical sorted-key UTF-8 JSON under
`mnq_lab/spine/calendar_inputs/cme_equity_index_v1/`, not a generated market
store. The externally derived CSV is not committed. The global `data/` and CSV
ignore rules remain unchanged. Calendar material remains market-aware and may
not enter `core/`. Retained source is inert provenance only and cannot be a
runtime dependency.

**Ledger and branch governance.** U11 authorizes only local branch
`phase-7-calendar-input` from
`4100abadad1d8212b8c98ad7382e1019a1afbe96`. The Phase 3 threshold ledger remains
unchanged and keeps its exact one-entry invariant. Calendar authorization uses a
separate immutable `mnq_lab/ledger/calendar_entries/` namespace. Commit order is
ledger/provenance authorization first, artifact second, acceptance tests third.
The post-D19 hash of this file is recorded in the calendar ledger entry rather
than circularly inside this file.

**A5 dependent-code boundary.** Calendar-import isolation cannot be tested
against nonexistent EWMA and MAD modules without a vacuous pass. U11 therefore
registers `a5_calendar_import_isolation` as an explicit pending xfail. It becomes
a real passing test, with a matched negative import mutation, before any EWMA,
MAD, seasonal-profile, `vol_rel`, threshold, or assignment computation is
committed. A5 does not block acceptance of the calendar reference input itself.

**Known limits.** Single-source acceptance is corroboration, not proof that
every exchange classification is correct. Holiday-adjacent flags lack an
independent time signature, and an alleged full closure can coincide with vendor
absence. A future Databento GLBX.MDP3 status stream is preferred independent
corroboration but is not a blocker. No seasonal profile, conditioner assignment,
state-validity result, market effect, confirmation result, or trading result has
been computed.

**Status.** `OPEN; COMMITTED ARTIFACT AUDIT PENDING`. This entry authorizes only
the bounded calendar reference-input commits. Phase 7 production, Phase 7b,
Phase 8, and every later phase remain unauthorized.

---

## D20 — Phase 7 frozen test-name convention and real dependency windows — `CONTRACT CLOSED; IMPLEMENTATION EVIDENCE PENDING`

**Frozen test-name convention (F-0).** Frozen spec §13 item 18 names nine
required tests, while the repository convention through Phase 6 implements
those names at file level rather than as literal function definitions. Seven
names already existed as files. `test_vintage_consumption.py` remains correctly
deferred to Phase 11. `test_roll_reset.py` is assigned to Phase 7 because the
named behavior is the Phase 7 EWMA/MAD reset at a contract roll with a new
78-return warmup; it is not the distinct Phase 1 causal roll-mapping property
covered by `test_roll_causality.py`. Phase 7 must therefore add
`tests/test_roll_reset.py` and satisfy the from-scratch, zero-memory, warmup,
gap, maintenance-halt, and deliberately bridging negative controls frozen in
`docs/PHASE7_PREREGISTRATION.md` §15. This records and closes F-0's ownership
ambiguity; passing evidence remains due at Phase 7 closeout.

**Real-conditioner dependency windows (D17 #8).** Phase 6 established locality
only relative to a caller-declared mask and explicitly deferred proof that each
real declaration is semantically correct and minimally sufficient. The
byte-pinned Phase 7 contract closes that design obligation in §10 before any
estimator exists: masks index bars; 78 returns span 79 bars; expected masks are
constructed independently from the preregistered pseudocode; admission requires
`numpy.array_equal(declared_mask, semantic_mask)`, never containment; and the
required widened, narrowed, future, and EWMA-versus-MAD long-run mutations make
an over-wide declaration fail even where output values happen not to change.
No expected mask may be obtained from an estimator or its metadata. This closes
D17 #8 at the executable-contract level. Real-conditioner admission evidence
and all required mutations remain mandatory implementation and closeout gates;
this entry does not claim that not-yet-written estimators have passed them.

**Governance.** This append accompanies the single pinned-base maintenance
commit pre-authorized by Phase 7 preregistration §21. In the same atomic commit,
the calendar A5 strict xfail is converted into its dynamic sentinel-and-mutant
test and only the internal pin for this file is updated. The maintenance commit
records both files' old and new byte counts and SHA-256 values. Historical
calendar closeout and ledger bytes are not amended. Phase 8 remains
unauthorized.

---

## D21 - Outcome-layer and Phase 8 contract rulings - `RESOLVED`

The two ratified, byte-pinned preregistrations surfaced four points that the
frozen specification does not determine uniquely. Each resolution below was
fixed before any Unit O outcome value existed. They do not amend Phase 7 or
authorize Phase 8 production.

**Natural-prevalence reading.** Frozen section 8's "pooled at natural ANCHOR
frequency" is ambiguous. Phase 8 section 4 reads it as pooling constituent
cells at natural prevalence while preserving session-equal weighting within
each cell. Anchor-equal pooling is rejected: it would duplicate section 7.1's
separate `anchor_weighted` companion and contradict the rule that, within an
estimand, `session_equal_weighted` is primary. This is a resolved ambiguity in
the D11a/D12 pattern, not an outcome-dependent choice.

**Equal-mass extension.** Frozen section 8 defines equal weighting across
comparison phases and, by explicit analogy, across volatility states. It does
not define equal weighting for `cell_vs_complement` or
`cell_vs_population`. Phase 8 section 4 extends the rule to give equal mass to
each constituent phase-volatility cell, with the named estimand's
session-equal construction applied inside each cell. This is declared
preregistered latitude fixed before outcomes: an extension, not a
transcription.

**Year-concentration ruling - user ratified 2026-08-01.** Frozen section 6
fires `insufficient_completion` when accepted sessions "concentrate in one
year or era" without defining how much concentration is enough. The gate fires
only when accepted support is confined completely to one calendar year while
the source population spans more than one. Every other concentration is
emitted as a per-year completion diagnostic and does not fire the gate. The
basis is frozen section 10.1: thresholds chosen before their distributions are
known would be the same tuning this lab exists to avoid, while later work may
preregister validity requirements against known diagnostic ranges. Choosing a
numeric cutoff now would be that forbidden blind threshold, so a numeric rule
is deliberately deferred to a later preregistration. Nothing is hidden because
per-year completion is emitted regardless. Era concentration is not evaluated
while `liquidity_era` is inactive.

**Liquidity-era wording.** Phase 7's shipped `state_validity.py` emits
`deferred_missing_versioned_input`; the ratified term from Phase 8 onward is
`inactive_missing_versioned_input`. The substance is identical: no partition,
correlation invalid rather than zero, and no conservativeness claim. Phase 7
is historical and is not amended.

**Status:** `RESOLVED`. The calendar-input test now protects the first 51,539
bytes of this append-only document against the historical SHA-256
`7ec200bb1de83769b8ce07551fec4e0b81f5e90e20a4792c22ae47f285bed615`
and permits only growth after that exact prefix. No frozen or accepted-calendar
pin changes.
