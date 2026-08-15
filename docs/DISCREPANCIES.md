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

---

## D22 - Unit O ratification criteria and deterministic tie-break - `RESOLVED`

The frozen corpus does not uniquely determine what the previously undefined
phrase "a ratified Unit O outcome table and manifest" means. The resolution is
therefore fixed before the in-progress corpus result becomes visible. It is
fully specified in `docs/UNIT_O_RATIFICATION_PREREGISTRATION.md` and does not
amend a frozen specification, preregistration, ledger entry, accepted calendar,
closeout, or the byte-pinned historical `docs/UNIT_O.md` snapshot.

**Ratification ruling.** Ratification is an exact-tree, exact-commit claim and
requires all seven conditions C1-C7. C1-C6 are checked mechanically and fail
closed. C7 is a human attestation: code cannot prove that nobody inspected an
outcome before criteria were fixed or that an audit was genuinely independent.
No partial, retroactive, or transferable ratification exists. A producing
script's permanent `NON-ADMISSIBLE` stamp may be overridden only by an explicit
certificate that records the audited basis; this C6 override is a judgment
call, not a mechanical derivation.

**User ruling - 2026-08-02.** The corpus run in progress when this entry was
committed will be Phase 8's input; no further run is required. The pipeline is
deterministic over a sealed corpus, and all analysis choices - quantiles, five
contrasts, three estimands, thresholds, bootstrap entropy, and block lengths -
were frozen and pinned on 2026-08-01 before any outcome existed. Another run
would be byte-identical and add no information, so requiring it would be
ceremony rather than protection. The already audited exclusion of the
preserved first-run baseline is not reopened and is moot because the new run
must reproduce it byte for byte in its scientific columns.

**Tie-break fixed before visibility.** The in-progress run's 109 column hashes
must equal the preserved baseline's corresponding hashes exactly; only the
manifest may differ because `code_commit` changed. If any column hash differs,
the run halts, the first mismatching session is located and classified under
frozen specification section 16.6, and neither tree is usable until the cause
is explained. No tree is selected over the other and nobody picks a winner.

**Status:** `RESOLVED`. This resolution authorizes implementation of the
append-only audit-verdict ledger, ratification certificates, fail-closed
validator, and focused tests. It does not itself ratify a tree or authorize
Phase 8 execution.
---

## D23 - C5 reproduction correction and honest condition labelling - `RESOLVED`

D22 and `docs/UNIT_O_RATIFICATION_PREREGISTRATION.md` contain one objective
self-contradiction and several condition labels stronger than their mechanisms.
Both are corrected here by appended entry. No frozen specification, no
preregistration, no ledger entry, no accepted-calendar byte, no closeout and no
byte-pinned historical document is edited. D22 itself is unchanged and its
pinned section hash is preserved.

**The C5 contradiction.** `UNIT_O_RATIFICATION_PREREGISTRATION.md` requires at
C5 "a separately recorded rerun at the identical complete environment
fingerprint", then designates the preserved first-run baseline as the supplier
of that comparison. The baseline cannot supply it. The two environment
fingerprints differ in exactly one field, `commit`
(`4f185eab998f33f64ae6705fbc494cd6e3e9f327` versus
`6dcbff89e0d7af8e812474537cef41fc6cf7add4`), and are identical in all nine
other fields. `mnq_lab/ledger/ratification.py` enforces exact fingerprint
equality, and the distinctness guard forbids a tree serving as its own
reproduction. C5 was therefore unsatisfiable and no certificate could ever
validate. Refusing to certify was correct behaviour; the defect is the
document's claim, not the validator.

**Resolution, declared POST-HOC.** A reproduction satisfies C5 when the two
environment fingerprints differ ONLY in `commit` and the `git diff` between
those two commits, restricted to the scientific modules, is empty. That diff
must be machine-executed at validation time, never asserted. This relaxation
was decided on 2026-08-02 with the knowledge that the two runs had already
agreed on all 109 scientific column hashes. It is therefore a POST-HOC
relaxation and must never be presented as fixed in advance. Its degrees of
freedom are nevertheless nil: every analysis choice was frozen and pinned on
2026-08-01 before any outcome existed, the pipeline is deterministic over a
sealed corpus, and agreement across two different commits is stronger evidence
than a same-commit rerun because it demonstrates determinism and also that the
intervening commits never touched the scientific path.

**C4 is NOT mechanical.** `ratification.py` builds its expected gate records by
stamping `passed=True` onto the hardcoded gate-classification constant, so C4
verifies only that a certificate contains that constant. No producer-side
record of gate OUTCOMES exists in either artifact tree, and none can be created
after a completed run. C4 is an attestation by the audited party. A certificate
cannot express a gate failure at all. Future production runs must record real
gate outcomes; for the 2026-08-02 trees this evidence does not exist and its
absence may not be described as a passing check.

**Condition labels downgraded.** C1, C2, C3 and C5 are mechanically CHECKED but
several of the values they check are self-recorded by the audited party: the
canonical source-store hash is compared against a recorded string rather than
re-hashed from the store; result visibility rests on a timestamp in a
producer-authored record, with no git query and no clock read anywhere in the
validator; clean-worktree status is three JSON assertions rather than an
inspected worktree; and a byte copy is presently indistinguishable from an
independent rerun. The append-only ledger property is repository policy, not
code. None of this may be described as structural. The honest present
characterisation is a certificate schema validator with strong byte-integrity
checks, not yet a ratification mechanism.

**No certificate may issue under this entry.** This ruling records a decision;
it does not implement it. `ratification.py` still enforces exact fingerprint
equality, so the amended C5 is not yet executable, and
`require_ratified_unit_o` still has no production caller. Phase 8 remains
halted at its final step until the validator implements this entry and an
independent audit returns `CLOSED`.

**Phase 8 steps 1-6 are unaffected.** Frozen Phase 8 section 16 computes no
real contrast until all Unit O gates and synthetic Phase 8 mutations pass, so
the axes, supports, weight constructors, standardization, completion,
positivity, status precedence, bootstrap and interaction layers are built and
tested against synthetic fixtures and require no ratified table.

**Authorship disclosure.** This entry was written by the independent auditor at
explicit user direction on 2026-08-02, after that auditor reported the defects
it corrects. Independence is therefore not available for this entry. It must be
adversarially reviewed by the implementing party before any certificate is
issued, and this disclosure may not be removed.

**Status:** `RESOLVED`. Authorizes the validator correction and the honest
relabelling. It ratifies no tree and authorizes no Phase 8 execution.
---

## D24 - Phase 8 contrast-table path-estimand key - `RESOLVED`

**The ambiguity.** Phase 8 preregistration section 14.1 declares one contrast
row per arm, outcome, support kind, horizon, quantile, contrast, population
estimand, contrast weighting, target phase and target state, and its literal
column list omits the Unit O path estimand. Sections 5.3 and 8 require Phase 8
eligibility and completion to be evaluated for the named path estimand, while
section 14.3 explicitly includes path estimand in the day-type row key. The
frozen corpus therefore does not uniquely determine whether the contrast table
collapses the two path estimands or carries them as distinct rows.

**Evidence.** The independent P8-B audit verified from the Unit O manifest that
its first key column is `estimand`. Unit O therefore supplies distinct outcome
rows for `fully_labeled_1m_grid` and `observed_bar_path`. Without a
path-estimand contrast-table key, those two declared inputs would create pairs
of Phase 8 rows identical on every section 14.1 key column but potentially
different in value. An immutable tidy table could not represent that result
without duplicate keys or silently collapsing one path estimand.

**Ruling.** `path_estimand` is a Phase 8 contrast-table row axis. In the section
14.1 schema it is placed immediately after `outcome_name`. The unique row-key
prefix is therefore:

```text
arm_id, outcome_name, path_estimand, support_kind, horizon_minutes, statistic,
contrast_name, population_estimand, contrast_weighting,
target_phase, target_vol_tercile
```

The full primary inventory is consequently 29,160 rows: two outcomes by two
path estimands by two support kinds by three horizons by three statistics by
three population estimands by fifteen target cells by the nine declared
contrast/weighting combinations. The existing implementation and inventory are
retained; no result was computed and no outcome value was inspected to make
this ruling.

**Timing and correction disclosure.** This ambiguity was resolved during P8-B
implementation, not before it. The tests-first oracle initially asserted
14,580 primary rows at commit `49767d2`, then was revised to 29,160 at commit
`10e718f` before production implementation. The revision was initially
described too strongly as contract-derived. It becomes binding only through
this recorded ruling. The P8-B audit correctly returned `OPEN` until the
omitted schema column and the timing of the decision were made explicit.

**Governance.** This appended resolution does not edit the byte-pinned Phase 8
preregistration, any frozen specification, YAML value, ledger entry, accepted
calendar, closeout or historical discrepancy text. It fixes the executable
contrast-table key before Step 5 and before any real Phase 8 outcome is
consumed.

**Status:** `RESOLVED`. The `path_estimand` axis and 29,160-row primary
inventory are now explicit; P8-C may build only against this settled key.
---

## D25. Phase 8 interaction population-estimand scope and row key

**Observed during P8-D implementation.** Phase 8 preregistration section 10
lists all three population estimands and the section 12 interaction rows in one
primary-arm inventory. Read as a strict cross-product, that list would attach
`prospective_cell`, `common_session_paired` and
`standardized_shared_population` to every interaction. Section 12 instead
fixes one interaction support, `four_cell_common_sessions`, and forbids the
deferred `four_cell_standardized_population` by name.

Section 10's bullets are not a strict cross-product. The same list includes
q50, q75 and q90, while section 12 independently narrows interaction statistics
to exactly q50 and q90. The section 12 family-specific restriction likewise
governs which population estimand can truthfully describe its fixed support.

**Ruling.** Phase 8 interaction rows carry
`population_estimand = common_session_paired` only. The
`population_estimand` column remains present and constant in the interaction
table. The interaction inventory is 720 rows:

```text
2 outcomes x 2 path estimands x 2 support kinds x 3 horizons
x 1 population estimand x 2 statistics x 15 phase-volatility cells
```

**Basis.** The frozen specification requires "one common population across all
four cells." `prospective_cell` selects each side independently and requires
no later state in the same session; requiring a four-way intersection destroys
that prospective recognizability. Applying
`standardized_shared_population` here would require the expressly deferred
`four_cell_standardized_population`. Section 5.2's
`common_session_paired` definition covers a multi-cell comparison when the
named contrast explicitly requires every constituent cell, which section 12
does.

**Executable evidence.** The initial P8-D implementation enumerated all three
population-estimand labels, but `population_estimand` never entered
`build_four_cell_support`, `evaluate_interaction`, session selection or weight
construction. The 2,160 declared rows were therefore only 720 distinct
measurements repeated three times, twice under labels that did not describe
their support.

**Interaction-table key.** Section 14.4's prose declares both path and
population estimands as row axes, but its literal column list omits
`path_estimand`. D24's ruling is extended to section 14.4:
`path_estimand` is placed immediately after `outcome_name`. This keeps the two
Unit O path estimands uniquely representable rather than producing duplicate
declared keys.

**Timing and correction disclosure.** The tests-first oracle at commit
`3f17a5f` asserted 2,160 interaction rows before this ruling existed. That
count was an interpretation rather than a contract derivation. Revising it to
720 after this ruling corrects an invalid interpretation; it does not weaken
the test. The corrected oracle additionally requires the complete inventory's
population-estimand vocabulary to equal `{"common_session_paired"}`, preventing
the inert axis from returning silently.

**Governance.** This appended resolution does not edit the byte-pinned Phase 8
preregistration, frozen specification, YAML, ledger, accepted calendar,
closeout or historical discrepancy text. It settles the interaction key before
any real Phase 8 outcome is consumed.

**Status:** `RESOLVED`. P8-D may retain the four-cell-common implementation and
remove only the two false population-estimand labels from its inventory.
---

## D26. C5 rests on scientific-byte identity, not a hand-drawn code boundary

**Observed before the D23 amendment was implemented.** D23 proposed requiring
an empty git diff between the reproduction commits over "the scientific
modules." The executed diff between baseline commit
`4f185eab998f33f64ae6705fbc494cd6e3e9f327` and run commit
`6dcbff89e0d7af8e812474537cef41fc6cf7add4` is not empty when the broad
`mnq_lab/conditioners` directory is treated as scientific code:
`mnq_lab/conditioners/artifacts.py` changed in the streaming-under-six-GiB
commit. That file is an artifact-serialization layer, but excluding it would
require a manually judged module boundary that D23 did not declare.

**Ruling - Option B.** C5 does not use a source-module diff. It accepts two
distinct run trees when their complete environment fingerprints are identical,
or when the fingerprints have exactly the same keys and values except for the
`commit` field, and when all 109 scientific columns are raw-byte identical
under the frozen `npy-file-sha256-v1` protocol. A difference in `python`,
`numpy`, `pandas`, `platform`, `machine`, `branch`, `dirty`, `vcs`,
`pipeline_version`, any additional field or any missing field fails C5. Both
commit values remain full lowercase commit hashes and each tree remains bound
to the commit recorded by its own manifests.

**Why Option B.** The 109/109 scientific-column byte match directly answers
whether the two completed runs produced the same scientific values. A module
list is a weaker proxy and introduces a new discretionary boundary requiring
defence on every later run. The artifact serializer changed, so source code was
not identical; C5 therefore provides no structural proof that computation code
was unchanged.

**Claim boundary.** This is empirical reproduction evidence decided post hoc:
two runs at different commits produced byte-identical scientific columns. It
does not prove source-code identity, causal independence, blindness, auditor
competence or future reproducibility. C4 remains an attestation because neither
tree contains producer-side gate outcomes. C2 visibility remains a recorded
timestamp corroborated by filesystem metadata but not anchored to an external
authority. C7 remains a human attestation, and append-only remains repository
policy rather than a code-enforced property.

**Timing and correction disclosure.** The earlier instruction to require an
empty scientific-module diff was issued before that diff was executed. The
executed counterexample made the proposed rule unsatisfiable for the exact run
D23 intended to admit. Replacing that proxy with the already required
scientific-byte comparison corrects the rule openly; it does not claim that the
commit difference was harmless by construction.

**Status:** `RESOLVED`. The validator may now implement commit-only fingerprint
variance backed by exact scientific-byte identity. No certificate exists by
virtue of this ruling alone.
---

## D27. Phase 8 Step 7 exact-bootstrap feasibility stop

**Measured after CP-1 closed and before Step 7 artifact production.** The
ratified Unit O tree was entered through `require_ratified_unit_o`. A 240-row
slice containing 222 eligible anchors from two sessions was used only to time
the frozen Phase 8 joint-bootstrap path. No tick, quantile or interval value
was printed or interpreted. One term required 19,996 weighted-quantile
evaluations, exactly four block lengths by 4,999 draws. An instrumented
two-term run measured 18.927489 seconds inside the audited
`weighted_quantile_ticks` helper, or 9.463745 seconds per distinct term across
all frozen draws. The timing wrapper changed no value, weight, mask, draw,
entropy, block length, request or result and was restored after the call.

**Corrected lower-bound factorisation.** The primary absolute-distribution
family alone requires at least 3,240 distinct statistic/mask/weight
combinations:

```text
2 outcomes x 2 path estimands x 2 support kinds x 3 horizons
x 3 statistics x 3 population estimands x 15 phase-volatility cells
= 3,240
```

An earlier report stated the correct 3,240 total but omitted the three
population estimands from its written product, whose displayed factors
therefore multiplied to 1,080. The three estimands belong in the lower bound:
`prospective_cell`, `common_session_paired` and
`standardized_shared_population` assign distinct masks or weights even when
the outcome and target cell agree. At the measured small-slice cost, 3,240
terms require approximately 30,663 seconds, or 8.52 hours.

**Why this is only a lower bound.** The 8.52-hour figure excludes every
comparative baseline term, the 270 alternative-arm survival rows, the 216
day-type terms, interaction terms, full-frame weight composition and the far
larger real supports. `weighted_quantile` sorts its positive support, so the
222-anchor measurement does not establish the cost of the materially larger
real cell supports. The complete runtime is therefore expected to be higher;
no unexecuted complexity projection is treated as a measurement.

**Ruling and stop.** No frozen statistical parameter may change because the
registered computation is expensive. The draw count remains 4,999 per block
length; block lengths remain 1, 5, 10 and 20; the inverse-CDF definition,
interval endpoints, masks, weights, entropy and no-retry rule remain fixed.
Step 7 stopped before any Phase 8 artifact, result table or closeout was
created.

One implementation-only experiment is permitted before declaring the frozen
design computationally out of reach: prepare each term's replicate-invariant
value ordering once and reuse it across replicates. The experiment must first
prove exact equality to the existing audited weighted-quantile implementation
on named randomized witnesses including tied values, changing zero-weight
rows and single-support cells. Positive-mass filtering and `side="left"`
inverse-CDF selection must remain byte-exact; a plausible argument is not a
proof. The experiment may not change or approximate any registered statistic.
If exact identity cannot be proved, or the measured runtime remains
impractical, Step 7 stops again and returns for a user decision.

**Status:** `OPEN`. CP-1 is closed. Step 7 artifact production remains blocked
on measured feasibility; this entry authorizes only the exact-semantics timing
experiment above.
---

## D28. Prepared ordering is exact but does not resolve Step 7 feasibility

**Authorized D27 experiment completed.** The core inverse-CDF implementation
now exposes a prepared value-ordering path while retaining the original
implementation as its independent executable oracle. Preparation performs the
stable value `mergesort` once per term. Every replicate still sorts weights
within each tied-value group, removes zero-mass support, accumulates group and
support mass in the frozen binary64 order and uses
`searchsorted(..., side="left")`. No draw, seed, block length, mask, weight,
quantile probability, interval endpoint or retry rule changed.

**Exact-identity evidence.** Tests compare the prepared and original paths on
fixed randomized weights, tied tick values, changing zero-weight rows,
single-positive-support cells, binary64 accumulation-order witnesses and all
three Phase 8 statistics. A structural spy confirms value `argsort` runs once
during preparation and not when later replicate weights are evaluated. The
authorized safe suite returned 1,112 passed, one skipped and two expected
xfails before the repeated benchmark.

**Repeated ratified measurement.** The same two-term, 240-row benchmark entered
the Unit O tree through `require_ratified_unit_o`, used 222 eligible anchors
from two sessions and executed 39,992 quantile calls. It printed no tick,
quantile or interval value. Total runtime fell from 37.759852 to 34.413233
seconds. Time inside the quantile helper fell from 18.927489 to 15.945487
seconds, or from 9.463745 to 7.972744 seconds per term across all frozen draws.
That is an approximately 15.8 percent reduction in measured quantile time.

**Feasibility remains unresolved.** Applying the new measured per-term time to
the corrected 3,240-term absolute-distribution lower bound gives approximately
25,832 seconds, or 7.18 hours, on the small 222-anchor slice alone. This still
excludes comparative baselines, 270 survival rows, 216 day-type terms,
interaction terms, full-frame weight composition and materially larger real
supports. The one authorized implementation experiment therefore does not make
the complete frozen computation tractable. No further optimization is inferred
or authorized from this result.

**Status:** `OPEN`. The prepared implementation is an exact measured
improvement, but Step 7 artifact production remains blocked. No Phase 8 result
table, artifact manifest or closeout was created; the feasibility question
returns for user decision.
---

## D29. Step 7 feasibility decision: rented hardware, no frozen parameter changed

**The question D28 returned.** D27 and D28 both closed with Step 7 artifact
production blocked, and D28 ended by returning the feasibility question for a
user decision. This entry records the answer. It is written while the
authorized run is already executing. That ordering is stated plainly here
rather than concealed, and no part of this entry is backdated.

**Measured evidence for the decision.** A Task A preflight executed on the
user's laptop over 4,325 candidate terms was independently reconciled before
the decision. Reported figures: sequential total 464,026.262118 s, or
128.896 h; average 7.715308 s per distinct term; inventory-planning phase
44 min 43 s; measured speedups 4.87144x at eight workers and 6.54920x at
sixteen; cost-model residuals spanning 0.840825778 to 1.139897429; benchmark
cell of 7,284 anchors across 354 sessions, eight evaluations in 138.122147 s.
The sequential total is a cost-model projection across terms of differing
support, not a flat product of the per-term average and the term count; the
residual range above is that model's stated fit quality.

Applying the measured speedups and adding the 0.745 h inventory phase gives
128.896/4.87144 = 26.46 h, so 27.2 h at eight workers with a 23.0 to 30.9 h
range, and 128.896/6.54920 = 19.68 h, so 20.4 h at sixteen workers with a
17.3 to 23.2 h range.

These figures were reported and audited in session and were not carried into
this repository at the time. That was a provenance gap: the numbers that
justified the decision existed only in conversation, where they cannot be
recomputed or challenged by a later reader. This entry closes that gap by
recording them.

**Decision.** The measured runtime materially exceeds the ten-hour target. The
user elected to proceed on rented hardware rather than reduce, approximate or
prefilter any registered quantity.

**Nothing frozen changed.** The draw count remains 4,999 per block length.
Block lengths remain 1, 5, 10 and 20. The registered entropy, confidence
level, interval endpoints, inverse-CDF definition, masks, weights, resampler
and no-retry rule are untouched. The only altered values are operating
parameters that cannot enter a result: worker count, aggregate memory ceiling
and launch minimum available memory. This decision therefore honours the D27
ruling that no frozen statistical parameter may change because the registered
computation is expensive. Speed was obtained from hardware, not from the
design.

**Run identity.** Code commit `9fb8ae0`, clean worktree. Launched 01:40 UTC on
2026-08-04 with 128 workers, a 68,719,476,736-byte aggregate memory ceiling
and a 34,359,738,368-byte launch minimum available memory. Host: 128 threads,
251 GiB RAM, AMD EPYC 7773X, rented. Output root `phase8-first-run-v1`;
checkpoint root `phase8-first-run-v1.checkpoint`.

**Unmeasured on this host.** The 44 min 43 s inventory-planning figure and both
runtime projections were measured at eight and sixteen workers on the user's
laptop. Neither the inventory phase nor the complete run has been timed at 128
workers on the rented host, whose single-core clock is slower. No projection
for this configuration exists and none is inferred here. Elapsed time observed
on this host is therefore an observation, not a departure from an established
expectation.

**Status:** `RESOLVED` as to authorization only. D27 and D28 remain the record
of the feasibility stop, and the question each returned is answered here. The
run is in progress. No Phase 8 result table, artifact manifest, closeout or
ratification exists, none is authorized by this entry, and nothing in this
entry interprets, accepts or ranks a measured value.
---

## D30. Stage 1 root cause, authorized implementation fix and controlled parallelism

**What happened.** The first Phase 8 Step 7 production run (D29) ran 3 h 07 min
on rented hardware without leaving the serial point-estimate stage
(`build_production_computation`) and was terminated with no checkpoint and no
artifact produced. Its own progress log recorded zero checkpoint files and
zero output files on every one-minute poll for the full duration. Nothing was
lost; nothing had been written.

**Root cause, measured.** `py-spy` sampling of the identical stage running
locally showed every hot leaf frame is pure-Python per-element iteration, not
a numpy kernel. The principal cause is `core/weights.py:session_equal_weights`,
which is accidentally quadratic: for each of `g` groups it rescans the entire
`n`-row array (`weights[inverse == index]`) rather than visiting each row
once. On the real ratified Unit O input, one horizon slice has `n = 157,404`
rows over `g = 1,009` sessions: `g * n = 158,820,636` operations against the
`n` an `O(n)` implementation requires. Measured cost: 0.338 s per call. This
function, and the same iterate-and-validate pattern in
`_as_opaque_group_labels`, `_validated_session_labels` and `_session_labels`,
are called repeatedly across the 30,366 declared rows.

**Measured fix.** An order-preserving vectorized replacement
(`np.unique(..., return_inverse=True, return_counts=True)` plus a stable
`argsort` to sum each group's rows in the same ascending order the original
loop visits them) was benchmarked against the real slice above: 0.014 s per
call, a 24.1x speedup, and the output weight vector is bit-identical to the
original — `np.array_equal` true, max absolute delta `0.000e+00`,
`tobytes()` equal. This was measured, not asserted.

**Authorization.** The user authorizes, in this entry:
  1. Replacing the quadratic and repeated-per-element-validation hot spots in
     `core/weights.py`, `mnq_lab/phase8/diagnostics.py` and
     `mnq_lab/phase8/estimands.py` with vectorized equivalents, each gated by
     a test proving byte-identical output against the current implementation
     on the real ratified input, including a negative case that a
     deliberately wrong implementation fails that test.
  2. Parallelizing the stage 1 serial computation across more than one CPU
     core on the operator's own hardware, provided the reassembled output is
     proved identical, row for row and byte for byte, to a single-core run.
  3. A stderr progress indicator emitting only loop index, item count and
     elapsed seconds. It may never emit a tick, quantile, contrast, interval
     endpoint or any other measured or computed value.

**What does not change.** No draw count, block length, entropy, confidence
level, interval endpoint, mask, weight definition, resampler, or no-retry
rule changes. This entry authorizes implementation and engineering changes
only; it authorizes no change to any frozen statistical parameter and ranks,
interprets or emphasizes no measured value.

**Status:** `RESOLVED` as to authorization only. No Phase 8 result table,
artifact manifest or closeout exists and none is authorized here. The
identity proof for each change is the acceptance gate, not a plausible
argument: per D27, a plausible argument is not a proof.
---

## D31. Phase 8 completion denominator omitted structural RTH fit

**Defect.** Phase 8 gated admissibility on a completion rate whose
denominator omitted the structural fit of the outcome window. S00, which
derived the frozen thresholds, uses
`state anchor AND window_fits_rth_h{horizon}`
(`mnq_lab/outcomes/completion.py:_summarise`). Phase 8 production supplied
only `arm.active` as `structurally_eligible`; `window_fits_rth` is loaded at
`production.py:127`, discarded by `_slice`, and never reaches
`completion_diagnostics`. No comment, test, ledger entry or preregistration
clause authorising the wider denominator was found.

An outcome window that leaves RTH is not missing data. The requested outcome
is structurally undefined, so counting it as an incomplete observation
understates completion.

**Discovered after v1 completed.** The defect was found while investigating
why the closed Phase 8 v1 artifact returned no admissible cell for the close
phase. `phase8-first-run-v1` remains immutable evidence of what the previous
mechanism produced and is not edited, deleted or reused.

**No outcome magnitude was inspected to choose the correction.** The
investigation used support, completion, structural-fit and cell-count
information only.

**Measured.** `outcome_valid` is a strict subset of `window_fits_rth`: zero
violations across 472,212 Unit O rows, so a non-fitting anchor can never be
complete. Primary-arm structural fit fractions are 100.0 percent for open,
morning, midday and afternoon at every horizon, and 83.3, 58.3 and 8.3
percent for close at h15, h30 and h60. The atomic denominator difference is
therefore confined to the close phase, although its status effect is not,
because comparison baselines for other phases can include close cells.

The S00 record `data/exploration/s00/s00_threshold_input_v1.json` was
reproduced independently. Its fifth-percentile cell is midday at every
horizon: 23,866/24,003 at h15, 23,763/24,003 at h30 and 23,568/24,003 at
h60, giving 0.9942923801191518, 0.9900012498437696 and 0.9818772653418323.
Applying the registered rule `max(0.90, floor(s00_p05 * 100) / 100)` returns
0.99, 0.99 and 0.98. The frozen YAML thresholds are correct and are NOT
changed by this entry. The record stores those fractions in reduced form
(7,921/8,001 and 7,856/8,001); the unreduced counts are the midday cell
counts and agree exactly.

In that same S00 record the close phase reports a completion rate of exactly
1.000000 at all three horizons, on denominators of 9,740, 6,818 and 974
against 11,688 state anchors. Under the correct denominator the close phase
is fully complete; under the Phase 8 denominator it produced no admissible
cell at all.

**Correction.** The structural denominator becomes support-aware:

- `horizon_specific`: `arm.active AND window_fits_rth(named horizon)`
- `common_support`:   `arm.active AND window_fits_rth(60 minutes)`

The second rule follows from the Unit O contract recorded in
`docs/OUTCOME_LAYER_PREREGISTRATION.md`: for each estimand `common_support`
is computed independently as validity at the maximum declared horizon, so a
15- or 30-minute common-support row uses that estimand's 60-minute-valid
anchors. Its structurally eligible population must therefore be the
population whose 60-minute window can fit RTH. `common_support` itself
remains the completion event in the numerator and is not used as the
denominator.

**Scope.** The correction changes admissibility and the resulting interval
inventory. It does not change point support, estimand weights, target or
baseline masks, contrast weighting, positivity, status precedence,
quantiles, the resampler, the bootstrap, or interval construction. The draw
count, block lengths, entropy, bit generator, confidence level and interval
probabilities are untouched.

**A new versioned run is required.** The correction cannot be applied to
`phase8-first-run-v1`. A corrected run must use a new versioned output root
after audit authorisation.

**Status:** `OPEN`. This entry records the defect and the authorised
correction. It does not reopen the Phase 8 closeout, which remains the
accurate record of what the previous mechanism produced, and it does not
authorise Phase 9.
---

## D32. The root defect is a fixed RTH close in the outcome layer, not the Phase 8 denominator

**Relationship to D31.** This entry supersedes D31's proposed implementation
and completes D31's threshold claim. D31's bytes are not edited and D31 is
not withdrawn: its central finding is confirmed below. Both entries stand;
where they conflict, this one governs.

**1. D31's finding is correct.** Phase 8 gated admissibility on a completion
rate whose denominator omitted the structural fit of the outcome window,
while S00 derived the frozen thresholds over `state anchor AND
window_fits_rth_h{horizon}` (`mnq_lab/outcomes/completion.py`). An outcome
window that leaves the trading session is not missing data: the requested
outcome is structurally undefined, so counting it as an incomplete
observation understates completion. That omission is real and is not
disputed here.

**2. D31's proposed implementation does not remove the defect.** The
correction drafted under D31 builds its structural denominator from Unit O's
`window_fits_rth` column. That column is itself the defective quantity. A
Phase 8 consumer that reads it inherits the defect rather than removing it,
and Unit O's structural-fit field and outcome-status field remain
semantically wrong for every later consumer, none of which is obliged to
know that the field must be recomputed before use. Correcting the
denominator while leaving its input wrong relocates the defect; it does not
repair it.

**3. Root cause.** `TimeModel.outcome_window_fits_rth`
(`mnq_lab/spine/timemodel.py:279`) evaluates `tau_ct_minute +
horizon_minutes <= self.rth_end_minute`. `rth_end_minute` is parsed once
from the single global constant `time.rth_end_ct: "15:00"` in
`analysis_constants_v1.yaml`; the function takes no session argument and
therefore has no access to a session schedule. It consequently cannot
distinguish an ordinary full session, a scheduled early close, a session
with no scheduled RTH, a registered temporary market interruption, and a
genuinely missing bar during otherwise available trading time. All five
collapse onto one fixed 15:00 CT boundary. A structurally unavailable
required timestamp is then classified as a missing path timestamp and
charged against completion as incomplete data. The absence of per-session
availability in the outcome layer, not the Phase 8 denominator, is the
governing defect.

**4. D31's threshold claim is incomplete.** D31 states that the frozen
completion thresholds are unchanged. That is true of the reproduction D31
performed, which was conditioned on the same fixed-close fit field, and it
is therefore not a statement about the corrected population. Under a
session-aware structural population the thresholds are not all invariant.

**5. Expected corrected thresholds.** A session-aware reproduction reported
to this project returns h15 -> 0.99, h30 -> 0.99 and h60 -> 0.99 under the
unchanged registered rule `max(0.90, floor(s00_p05 * 100) / 100)`, against
the recorded v1 values 0.99, 0.99 and 0.98. Only h60 moves. This entry
records that expectation and withdraws D31's unqualified "thresholds
unchanged" claim; it does not itself establish the new value. The corrected
population does not yet exist, so the figure cannot be reproduced at the
time of this ruling. It must be independently re-derived and ratified as
S00 v2 from the corrected structural population, and it must not be forced
if independent reproduction disagrees. `analysis_constants_v1.yaml` is
untouched by this entry and remains frozen; any corrected value is recorded
in a new versioned constants file, never by editing v1.

**6. A Phase 8-local patch is rejected as the final repair.** Masking the
condition inside Phase 8 would conceal it from Phase 8 completion while
leaving the defective Unit O fields in place and available for reuse. It is
rejected as the terminal remedy. The repair belongs in the canonical session
schedule and the outcome layer.

**7. Authorised remedy.** The user directed a versioned rebuild of Phase 7
and Unit O together, because the governed producer constructs them together,
because Phase 7 labels six regular sessions `unresolved_truncated_session`,
and because registering structural interruptions may legitimately change
calendar and data-quality metadata and possibly eligibility. Reusing Phase 7
unrebuilt would assume those fields are unaffected rather than prove it. The
rebuild is expected to leave Phase 7 scientific conditioning values and
assignments unchanged, and that expectation is to be tested by raw-byte
comparison, not assumed. This authorises no change to Phases 1-6.

**8. The existing artifacts remain immutable evidence.** Neither Phase 7 +
Unit O v1 tree, `phase8-first-run-v1`, any v1 manifest, checkpoint,
progress log, ratification certificate, S00 record, preregistration,
closeout, `docs/UNIT_O.md`, the accepted calendar v1, nor any historical
ledger entry is edited, deleted, renamed or reused. All corrected products
take new versioned paths and identifiers, recorded before production.

**9. No outcome magnitude informed this decision.** The investigation and
this ruling used session-schedule information, structural fit, completion
counts, coverage counts, status counts, row identities, source bytes and
hashes only. No tick, quantile, contrast or interval value was read.

**10. This entry produces no corrected result.** Recording the ruling
creates no rebuild, no v2 artifact, no certificate and no threshold. Every
such product requires its own production run, its own manifest and its own
independent audit before it exists.

**11. Timing.** The ruling was made during instrument construction, before
any hypothesis test and before any Phase 9 work. Phase 9 remains blocked.

**Forward reference to reconcile.** The uncommitted Phase 8 working-tree
change carries a source comment labelled "D32" for a different proposition,
namely which horizon's threshold grades a `common_support` row. This ruling
does not decide that question. It must be settled and recorded under the v2
contract freeze, and the stale comment corrected, when that code is revised.

**Status:** `OPEN`. It authorises the repair sequence and the versioned
rebuild. It does not reopen the Phase 8 closeout, which remains the accurate
record of what the previous mechanism produced, and it does not authorise
Phase 9.
---

## D33. Whole-session exclusion of four unresolved official-interruption sessions

**Relationship to D32.** D32 is independently audited and CLOSED. It is not
edited, amended, withdrawn or concealed, and its bytes are unchanged. This entry
supersedes exactly one narrow part of the repair plan D32 authorised, namely the
treatment of four specific sessions. Every other part of D32 stands.

**1. The four dates.** Authoritative official records confirm market-wide
circuit-breaker (Level 1) events on the US trading dates 2020-03-09, 2020-03-12,
2020-03-16 and 2020-03-18. The occurrence of an official interruption on each of
those dates is established.

**2. Exact CME/MNQ boundaries remain unresolved.** What is established is the
mechanism: CME halts US equity index futures, the Nasdaq-100 complex among them,
when the cash equity market declares a Level 1 market-wide circuit breaker. What
is NOT established is the pair of transition timestamps that a five-minute
structural classification requires. Two specific gaps prevent it:

- the NYSE Market-Wide Circuit Breaker Working Group report states that CME
  halted affected symbols "approximately one minute after each breach was
  triggered", so the futures halt instant is neither the cash trigger instant
  nor a stated time;
- resumption is stated inconsistently across sources, a fifteen-minute
  cash-market halt against CME material describing US-hours equity index
  products reopening ten minutes after the halt is instituted.

A primary-source sweep was commissioned across CME rulebook, Special Executive
Reports, advisories and rule filings, and across SEC, CFTC, Federal Register,
NYSE, Nasdaq and Cboe CFE material. It returned no document fixing exact CME or
MNQ transition timestamps for the four dates. The sweep terminated on resource
limits rather than on exhaustion of the source space, so its negative result is
recorded as "not established", never as "proven absent".

**3. A conservative structural decision.** The user selected whole-session
exclusion of all four sessions in preference to uncertain intraday
classification. Excluding a session whose availability cannot be established
removes anchors that might have been valid. It cannot manufacture a valid
outcome from a structurally undefined one, and it cannot import an unsourced
timestamp into the instrument. The cost is coverage; the alternative cost would
be an unattributable boundary inside the measurement. This entry records the
choice as conservative, not as optimal.

**Explicitly prohibited, and not done.** No CME boundary was guessed. No
cash-market trigger time was used as an MNQ halt time. No boundary was inferred
from missing bars. No halt start was estimated as a trigger plus approximately
one minute. No pre-halt or post-resumption anchor from these four sessions is
retained.

**4. No measured market value informed this decision.** No outcome magnitude,
tick, quantile, contrast, interval, ranking, threshold improvement or market
interpretation was read or used. The decision rests on official interruption
records, session identity and the absence of authoritative boundary timestamps.

**5. Calendar v1 is unchanged and immutable.** The accepted calendar
`mnq-cme-equity-index-calendar-v1` and its pinned artifacts are not edited,
reissued or superseded. The four sessions remain in calendar v1 exactly as
recorded, classified as regular full-RTH sessions. Exclusion is not a calendar
correction and must not be written into the calendar.

**6. A separate versioned session-exclusion registry.** The exclusion is carried
by a new, separately versioned, byte-pinned session-exclusion registry that
references calendar v1 session identities. It is an additional input, never a
mutation of an existing one.

**7. Reason code.** The registered exclusion reason is exactly
`excluded_unresolved_official_interruption`. The vocabulary is closed and the
loader fails closed on any unknown reason.

**8. Scope of the exclusion.** No anchor from an excluded session may enter
Phase 7 eligibility or the Unit O v2 population. The exclusion is evaluated
before window availability, so an excluded session never reaches the
scheduled-close or interruption tests.

**9. Narrow supersession.** The earlier requirement to preserve pre-interruption
and post-resumption windows is superseded for these four unresolved sessions
only. It remains in force everywhere else.

**10. The architecture keeps precise-interruption support.** The canonical
availability layer retains support for temporary structural interruptions
carried by authoritative start and end timestamps. Whole-session exclusion is
the treatment for the unresolved case, not a replacement for the interruption
model. Should authoritative CME boundaries later be established, they enter as a
new versioned interruption record and a new versioned population, never by
editing this ruling or any artifact built under it.

**11. Production remains blocked.** No Phase 7, Unit O, S00 or Phase 8 v2
production run is authorised by this entry.

**12. Phase 9 remains blocked.**

**13. No corrected artifact exists.** Recording this ruling creates no registry,
no rebuild, no v2 artifact, no certificate and no threshold. Each requires its
own production, manifest and independent audit before it exists.

**Consequence to reconcile, recorded rather than silently fixed.** The Stage 2
tests committed at `c3de65d3c5f15cf44039734bb8bee503dff6b8bc` include a witness
asserting that the four March sessions carry no registered interruption and that
their windows remain structurally available. Under this ruling that witness
states the wrong expectation and must be revised to assert exclusion instead.
The test is left unchanged by this documentary entry and is corrected only after
this ruling receives an independent CLOSED verdict.

**Status:** `OPEN`. It records a user decision and its scope. It does not reopen
D31 or D32, does not modify calendar v1, does not authorise production, and does
not authorise Phase 9.
---

## D34. A ratification certificate must be verified against its own commit, not the live tree

**Defect.** Ratification condition C4 re-hashes the *working-tree* copy of the
producing code (`mnq_lab/ledger/ratification.py:506`,
`_sha256_file(repo / "mnq_lab" / "production" / "first_exploration_run.py")`)
and compares it against the frozen constant `PRODUCING_CODE_SHA256`. The
certificate it validates attests that a specific artifact was produced by code
at a specific commit, which the certificate itself records as
`run_commit = 6dcbff89e0d7af8e812474537cef41fc6cf7add4`. Verifying that claim
requires consulting the code *at that commit*. Consulting the present working
tree instead answers a different question: whether the repository still happens
to sit at that code today.

**Consequence, and why it surfaced now.** The two requirements cannot both
hold. The governing rebuild plan directs that Phase 7 and Unit O be rebuilt by
the existing governed producer rather than by a new one, because a second
producer would introduce a new provenance path needing its own justification.
Reusing that producer means editing it. Editing it makes C4 fail, so the v1
certificate becomes unverifiable in any tree where the repair exists. The
defect is latent until the first time the producer legitimately changes, which
is exactly now.

**Measured.** The producer at the certificate's recorded `run_commit` hashes to
`5c6b3b2d6e5b06533c07489018b7c74932ad32aa823304f535103d6cef31613a`, identical
to the pinned `PRODUCING_CODE_SHA256`. The same file in a working tree carrying
the Stage 4 classification wiring hashes differently. C4 therefore fails on a
tree that has changed nothing about the v1 artifact.

**Ruling.** C4 verifies the producing code against the git blob at the
certificate's own recorded `run_commit`, not against the working tree. The
check fails closed when git is unavailable, when the recorded commit is
unreachable, or when the blob is absent: an unverifiable certificate is never
treated as a verified one.

**The anti-tampering purpose is preserved, not weakened.** Git object identity
is content-addressed, so the historical blob cannot be forged to match a
different constant. The independent check one line earlier, that the run
manifest's own recorded `producing_code_sha256` equals the pinned constant
(`ratification.py:504`), is unchanged and still binds the artifact to the code.
What is removed is only the incidental requirement that the present checkout
still contain those bytes, which the certificate never claimed.

**Explicitly not done.** `PRODUCING_CODE_SHA256` is not edited. No threshold is
relaxed, no tolerance is added, no fallback is introduced, and no gate is
weakened. No historical certificate, audit entry or completion record is
modified. C4 remains a producer-authored attestation for the purposes of the
attested-not-proven disclosure.

**Scope.** This changes a verification path only. It produces no artifact, no
certificate and no scientific value, and it changes no measured result. No
outcome magnitude, tick, quantile, contrast or interval informed it. Production
remains blocked and Phase 9 remains blocked.

**Status:** `OPEN`. It authorises the C4 verification correction and nothing
else.
---

## D35. Protected-hash checks read the commit they describe (extends D34)

**Same defect as D34, second instance, wider.** The Unit O closeout records the
byte length and SHA-256 of fifteen protected files as they were when Unit O v1
closed. `tests/test_unit_o_closeout.py` re-read those files from the *working
tree*. That asks whether the repository still sits at those bytes today, not
whether the closeout's record is accurate. Stage 5 legitimately edits seven of
the fifteen, so the check failed on a tree that changed nothing about v1.

**Ruling.** The check reads each protected file at the commit the closeout
describes, `da68aee974dab1f039d3eeabfbc5eabfbf04a6ea`, where all fifteen recorded
hashes reproduce exactly. Git objects are content-addressed, so reading history
cannot be forged; a negative control asserts the check still rejects a wrong pin
and an absent file. No recorded hash, byte count or closeout document is edited.

**Unit O schema version.** The outcome table gained
`structural_unavailability_reason` and renamed `window_outside_rth` to
`structurally_unavailable`. That is a different schema, so it carries a
different identifier: `unit-o-outcomes-v2`. The v1 identifier remains attached to
the v1 artifact and is not reused.

**Outcome-layer contract (Stage 5).** `build_outcome_table` now requires an
explicit `schedule_table`. Unit O loads no calendar, holds none in a global, and
has no fallback close. Anchors from D33-excluded sessions are dropped before
resolution. The isolation guard was TIGHTENED rather than relaxed: an exact
two-name allowlist, the forbidden-name set unchanged, the new parameter required
to be the neutral-layer `SessionScheduleTable`, and the runtime loader sentinel
re-armed on `spine.accepted_calendar` and `spine.availability`, where the real
loader now lives.

**Scope.** Verification paths, a schema identifier and the outcome-layer
signature. No artifact, no certificate, no measured value and no threshold
changes. No outcome magnitude informed any of it. Production and Phase 9 remain
blocked.

**Status:** `OPEN`.

---

## D36. Phase 7 + Unit O session-aware v2 production authorization and post-run record

**Relationship to D31-D35.** This entry records narrow production
authorizations that the user gave directly in the operator conversation. It
supersedes only the production-blocked language in D33 section 11, D34 and D35
for the failed preflight attempt and the separately authorized successful retry
described below. It does not close, amend or withdraw any scientific ruling in
D31-D35, and it does not authorize Phase 8 or Phase 9.

**Authorization chronology.** The initial operator instruction explicitly
authorized one production invocation. That attempt stopped at the child-side
free-memory preflight and is preserved at external receipt root
`C:\Users\kyawz\mnq_atlas_runs\phase7-unit-o-v2-final-6f1c506`. The user then
separately authorized memory cleanup and one retry. The successful artifact was
produced by that retry. Both authorizations existed outside the repository
before their respective attempts while D33-D35 still stated that production
was blocked. This entry is intentionally post-run and is not retro-dated. It
records the user's scope now under the user's explicit instruction to close
that governance gap; it does not claim that a repository-visible authorization
preceded either attempt.

**Authorized retry scope.** The second authorization covered exactly one Phase
7 + Unit O session-aware v2 retry from commit
`6f1c506b462b8c4e6df93a4ffcc1be04cbbba76f`, through
`mnq_lab.production.phase7_unit_o_run_receipt`, with live output root
`data/exploration/derived/phase7-unit-o-session-aware-v2` and external receipt
root
`C:\Users\kyawz\mnq_atlas_runs\phase7-unit-o-v2-final-6f1c506-attempt-2`.
The authorization did not include Phase 8, publication, push, self-ratification
or certificate issuance.

**Execution record.** The wrapper and child both exited zero. The run began at
`2026-08-09T01:24:51.253458Z`, finished at
`2026-08-09T02:36:43.938894Z`, and recorded
`outcome_values_inspected = false` and `phase8_executed = false`. The completed
tree is bound by the append-only record
`mnq_lab/ledger/run_completion_entries/2026-08-09-phase7-unit-o-session-aware-v2.json`:

- run commit: `6f1c506b462b8c4e6df93a4ffcc1be04cbbba76f`;
- run-manifest SHA-256:
  `456e3ea04532606042af9b505a6918f659c2ccffbbf1ceb66b8fde9dd809851d`;
- tree SHA-256 under the ratification ledger's canonical tree algorithm:
  `dc7b3f607d28d2f2a1ccad1cc04340f48b03623a7448c8516734aa3c95e40a87`.

**Independent audit.** A separate auditor independently reproduced the commit,
archive, receipt, protected snapshots, structural populations, label counts and
raw-byte artifact comparison. Its verdict was scientific content SOUND,
mechanical execution SOUND and population correctness SOUND. It declined
ratification because the authorization and run completion had not yet been
recorded and because the historical failed-v2 quarantine tree was outside the
receipt's protected roots. This entry and the run-completion record address the
first gap. The receipt root list is separately hardened to include
`data/exploration/derived/.quarantine-failed-v2-e8542c1`; that code change is
post-run and does not claim retroactive receipt coverage.

**No certificate.** Recording authorization and completion does not ratify or
certify the artifact. A genuinely separate auditor must verify these new bytes
and decide whether the remaining receipt-scope limitation is closed before any
C1-C7 certificate may issue.

**Status:** `OPEN; POST-RUN GOVERNANCE AND RECEIPT-SCOPE CLOSEOUT AUDIT PENDING`.

---

## D37. Phase 8 bootstrap runtime projection superseded by target-host measurements — `RESOLVED`

**Superseded projection.** Commit
`3d17937a1184f7477b3fa07ed7194bedad3bcd29` recorded about 5.0 hours for
the Phase 8 bootstrap and about 37 minutes per chunk. Those figures used
165 ns per eligible-row/bootstrap-draw, measured with synthetic data on a
Windows review machine. They are superseded as target-host planning figures by
the measurements and uncertainty assessment below. This entry does not amend
or rewrite that commit.

**M-1 target-host kernel measurement.** On the Linux pod, a synthetic
single-core benchmark of
`mnq_lab.core.weights.weighted_quantiles_prepared_batch_fast` produced a
cross-cell median of **244.279 ns per eligible-row/bootstrap-draw**. The process
was pinned to CPU 0; each of twelve cells used five repeats and the production
batch sizes selected by the Phase 8 evaluation path. The complete measurement
table is:

| Eligible rows | Requested distinct | Realized distinct | Batch | Median ns/row-draw | Minimum | Maximum |
|---:|---:|---:|---:|---:|---:|---:|
| 1,000 | 300 | 300 | 512 | 266.233 | 263.421 | 267.386 |
| 1,000 | 1,000 | 1,000 | 512 | 255.235 | 248.142 | 310.723 |
| 1,000 | 3,000 | 1,000 | 512 | 313.214 | 300.052 | 317.808 |
| 5,000 | 300 | 300 | 512 | 229.916 | 194.675 | 324.380 |
| 5,000 | 1,000 | 1,000 | 512 | 261.772 | 254.889 | 313.232 |
| 5,000 | 3,000 | 3,000 | 512 | 191.597 | 188.660 | 192.456 |
| 20,000 | 300 | 300 | 209 | 213.732 | 189.020 | 259.908 |
| 20,000 | 1,000 | 1,000 | 209 | 188.461 | 183.080 | 269.931 |
| 20,000 | 3,000 | 3,000 | 209 | 284.310 | 231.047 | 313.790 |
| 78,390 | 300 | 300 | 53 | 233.324 | 198.611 | 333.315 |
| 78,390 | 1,000 | 1,000 | 53 | 305.457 | 191.949 | 323.274 |
| 78,390 | 3,000 | 3,000 | 53 | 232.824 | 185.988 | 239.594 |

Using 244.279 ns gives a 126.31 core-hour balanced floor. With the unchanged
eligible-row-weighted recomputation factor of 1.868 and 32 workers, the
arithmetic projection is 7.37 hours, or 55.3 minutes per chunk across eight
chunks.

**Withdrawal of the claimed attempt-007 contradiction.** An earlier audit
response claimed that M-1 conflicted with the attempt-007 observation. That
claim is withdrawn as an auditor error. The straggler batch contained 670,574
eligible rows across 19,996 draws, or approximately `1.3410e10` row-draws.
Thus, 2,260 seconds implies 168.5 ns only if chunk 0 was complete, while it is
consistent with 244.279 ns if chunk 0 was 69.0 percent complete. The completion
fraction is unknown. `chunk_progress.advance` fires only after a complete chunk
(`mnq_lab/phase8/runner.py:1024-1034`), so the progress record contains no finer
completion evidence. The earlier estimate that chunk 0 was about 97 percent
complete was circular: it assumed the 165 ns constant that it was then used to
support.

| Constant | Straggler needs | Implies chunk 0 was | Blocks elapsed |
|---:|---:|:---|---:|
| 165.0 ns | 2,212 s | complete | 4.09 |
| 168.5 ns | 2,259 s | complete | 4.00 |
| 200.0 ns | 2,682 s | 84.3 percent | 3.37 |
| 244.3 ns | 3,275 s | 69.0 percent | 2.76 |
| 281.0 ns | 3,768 s | 60.0 percent | 2.40 |

**M-1 uncertainty.** The measurement carries wide error bars. It measured one
pinned core rather than 32 workers under concurrent load, and CPU 0 absorbs
device-interrupt and timer work on most Linux hosts. Across five repeats, two
within-cell spreads reached 1.67x and 1.68x, while the same code's total spread
on the review machine was 1.08x. The cross-cell median is therefore a planning
centre for a wide band, not a precise target-host constant.

**Reasoning, not measurement.** Both synthetic benchmarks used uniform random
nonnegative weights. That input produces few singleton value groups and
therefore suppresses the kernel's bulk singleton path at
`mnq_lab/core/weights.py:481-484`. Real excursion ticks may exercise that path
more often, so both synthetic benchmarks may overstate real cost. This cannot
be checked without inspecting outcome magnitudes, which remains out of bounds.

**Replacement planning basis.** Plan for about 7 hours, with a range of 5 to 8
hours and a floor of about 5 hours. The kernel constant is the least certain
input in the projection, so no point estimate is warranted. The first completed
bootstrap chunk in the next authorized run will yield the true constant under
true concurrent load at roughly the 40-to-65-minute mark, and that chunk's work
will be retained regardless of the result. No further synthetic benchmark is
warranted.

**M-2 fork memory measurement.** Fork copy-on-write is **confirmed by
measurement**. Across 32 workers, private memory ranged from 1.938 to 2.160 MiB
per worker, compared with the 38.33 MiB per-worker prediction for spawn. Mean
worker PSS was 3.803 MiB, and process-tree PSS was 136.650 MiB across 33
processes. Parent PSS changed from 70.744 to 14.939 MiB because the shared pages
were proportionally re-accounted across the process tree; the change does not
represent freed memory. The 1.198 GiB plan-matrix budget remains correct for
**spawn only** and is unmeasured. Under the measured fork behavior, the
conservative peak projection improves from about 18.4 GiB to about 17.2 GiB
against the unchanged 192 GiB ceiling.

**Unaffected structural facts.** The eligible-row-weighted recomputation-factor
change from 4.466 to 1.868 and the eight-chunk inventory are structural. They do
not depend on either timing measurement and remain unchanged.

**Scope and status.** This is a documentation-only supersession of runtime and
memory planning statements. It changes no code, checkpoint identity, scientific
rule or production artifact. It does not authorize production or declare
readiness. **Status:** `RESOLVED`.

---

## D38. D18 admission-gate remediation and calendar/provenance audit record

**Audit scope and unchanged scientific result.** An independent re-audit
executed 47 admission-gate attacks. The D18 D-1 exception-prose correction and
D-2 unvalidated-causal-insertion correction were independently confirmed
sound; neither was broken. The data spine, contract roll, session calendar,
anchor grid and baseline half of every contrast also passed. No bar, calendar
classification, anchor, contrast baseline, published number or scientific
finding changes as a result of this entry. Phase 7, Phase 8 and the Phase 10
calibration were not rerun.

**F-1 (CRITICAL) — mutable dependency declaration and read-after-invoke.** At
the audited base commit `28d6bcc`, all six frozen dataclasses in
`mnq_lab/core/dependency.py:109,207,215,245,257,299` lacked slots. In
particular, `DependencyCase` at `dependency.py:215` and
`DeterministicWitness` at `dependency.py:257` retained writable instance
`__dict__` mappings despite `frozen=True`. In addition,
`run_dependency_locality` invoked caller code before reading the allowed mask
at `dependency.py:589-590`. A callable reading `x[0] + x[2]` therefore widened
its own declaration so index 2 appeared in-window during the suite, collapsed
the probes from two forbidden regions of sizes `(2, 1)` to one of size `(1,)`,
and was admitted as confirmation-eligible with one locality case, one witness
and two negative controls. The untampered control was correctly rejected, and
direct numpy-array mutation was already refused; the writable `__dict__` swap
was the open route.

**F-1 correction.** All six dependency dataclasses now use
`@dataclass(frozen=True, slots=True)` (`dependency.py:109,207,215,245,257,299`).
`run_dependency_locality` snapshots `allowed_dependency_mask`, `inputs` and
`invoke` before the first invocation (`dependency.py:633-655`), probes only the
snapshotted mask and inputs, calls only the snapshotted callable, and reasserts
all three identities after every callable invocation
(`dependency.py:399-442`). Any identity change raises `SpineError`; it cannot
produce admission evidence. Separate negative tests cover persistent
mask-widening, trace-erasing mask restoration, and the absence of writable
instance dictionaries on both mandatory declaration types.

**F-2 (MEDIUM) — validation/execution callable TOCTOU.** At `28d6bcc`,
`mnq_lab/conditioners/registry.py:402` established that each declared locality
case invoked the registered conditioner, but the execution loops at
`registry.py:308-313` later reread mutable case fields. During case 1, a caller
could replace case 2's `invoke`, causing evidence to be recorded for a callable
that never ran. Execution now reasserts exact registered-conditioner identity
immediately before every locality case and witness, and reasserts each negative
control's pre-suite callable snapshot immediately before that control runs
(`registry.py:315-343`). Cross-case swaps targeting all three loops are refused
atomically.

**F-3/F-4 threat-model decision — reachable deliberate same-process abuse.**
F-3 remains mechanically reachable: the plain storage dictionary declared at
`registry.py:220-225,231` in `28d6bcc` can be reached as
`registry._ConditionerRegistry__entries`, and direct insertion can forge an
eligible descriptor with zero cases, witnesses and controls, including from
inside a running suite. F-4 also remains mechanically reachable at the audited
`registry.py:175-214`: `object.__setattr__` can rewrite a stored descriptor,
and `gc.get_referents` can expose and mutate the backing dictionary of nested
`MappingProxyType` metadata. Ordinary `setattr`, `dataclasses.replace`, pickle,
deepcopy and direct mapping-proxy writes remain blocked.

The decision is explicit: deliberate same-process private-attribute access,
`object.__setattr__` and garbage-collector referent extraction are outside the
admission registry's enforceable threat model. Python name mangling and frozen
dataclasses are ordinary API controls, not security boundaries. The supported
API and in-suite execution paths are the enforcement boundary, now stated in
`registry.py:176-230`. This narrows D18 D-2's rationale: its operative result
under the eleven ordinary insertion attacks remains sound, but the statement
that name mangling itself prevents private-storage access is not a stronger
security claim.

**C-1 (LOW) — stale protected provenance pins.** Two of the eight protected
hashes at `docs/PHASE7_CALENDAR_INPUT.md:43-50` no longer resolve.
`docs/DISCREPANCIES.md` grew from 49,015 to 115,515 bytes before this append,
and the calendar-input test changed at commits `39685e7` and `fe1476c`. The live
pin `governance.discrepancies_sha256_after_d19` at
`cme_equity_index_sessions_20190506_20230329_v1.manifest.json:74` is therefore
dead inside an immutable artifact. The artifact is recorded as-is and is not
edited. This is a provenance defect only and affects no computed result.

**C-2 (LOW) — Independence Day extension boundary.** The pinned rule
`USIndependenceDayBefore2022PreviousDay` means this calendar version models no
July 3 12:15 CT early close from 2022 onward. CME equity index products did
close at 12:15 CT on 2023-07-03. That date lies outside the governed
2019-05-06 through 2023-03-29 range, so present impact is zero. Extending this
calendar version beyond 2023-03-29 without reviewing the rule would introduce
a real calendar error.

**C-3 (LOW) — undisclosed session-start anomaly.** D19's battery tested session
ends only. Testing starts finds exactly one formal-population session that does
not open at 17:00 CT: session 20200701 opens at 19:00 CT on 2020-06-30 and has
249 bars, with 24 missing at the head. It is the tail of the same outage that
truncated session 20200630, is included in the 900-session formal population,
and has no anomaly flag. Its complete 78-of-78 RTH anchor grid is unaffected
because the gap lies wholly outside `[08:30,15:00)`.

**C-5 (LOW) — undocumented structural pause change.** The 15:15-15:30 CT daily
pause exists through 2021-06-25: 536 sessions have 273 bars. It is absent from
2021-06-28 onward: 440 sessions have 276 bars. The change is outside RTH and
has no anchor effect.

**C-6 (LOW) — two correct granularities stated without reconciliation.**
`docs/PHASE7_CALENDAR_CORROBORATION.md:56,58` reports 09:59 and 09:11 for the
two truncated sessions, while D19 reports 10:00 and 09:15. The first pair is at
one-minute granularity and the second at five-minute granularity; both are
correct, but the two project records had not explained the difference. No
computed result is affected.

**Ruling and status.** D18 remains open. The F-1 and F-2 corrections are
implemented, but they return for a focused independent admission-gate re-audit
and are not self-ratified here. F-3/F-4 are recorded limitations under the
explicit same-process threat boundary. C-1, C-2, C-3, C-5 and C-6 are LOW
calendar/provenance disclosures with zero effect on a computed result. Stage E
remains blocked, and this entry does not authorize any new phase checkpoint or
production work. **Status:** `OPEN; CORRECTED PENDING FOCUSED INDEPENDENT
RE-AUDIT`.

---

## D39. D18 focused re-audit remains OPEN: comparison-policy admission bypass

**Independent verdict.** The focused independent re-audit of candidate
`7319f8929b29cab85e08535f88213973114d35e7` returned `OPEN`. Every defence
implemented in D38 held under attack, all seven D38 negative tests were genuine,
the D38 append and evidence-pin chain were correct, and both authorized
regressions passed. The auditor nevertheless admitted one genuinely
out-of-window callable through the ordinary public causal-registration API by
mutating an unsnapshotted sibling field. D18 and Stage E therefore remain open
and blocked respectively.

**F-5 (CRITICAL) — comparison policy was reread after caller execution.** The
D38 remediation snapshotted `allowed_dependency_mask`, `inputs` and `invoke`,
but not `comparison`. On the audited candidate,
`mnq_lab/core/dependency.py:676` executed the caller and
`dependency.py:686` later reread `case.comparison`. A conditioner computing
`x[0] + x[1] + x[4] + tanh(x[2])`, where index 2 was declared out of window,
replaced its exact floating comparison with `atol=2.2` during its first call.
Because the planted leak is bounded, all probe deviations were absorbed by the
widened policy. Registration stored a CAUSAL, confirmation-eligible descriptor
with one locality case, one witness and two negative controls. The identical
conditioner without the swap was correctly refused. Restoring the exact policy
after registration erased the declaration mutation from the case.

The candidate descriptor did preserve a partial forensic trace by recording
the widened `atol=2.2`, but no gate cross-checked that record against the
pre-suite declaration. This trace did not prevent admission and is not a
defence. The defect affects the guard for future registrations. All 35 existing
Phase 7 conditioners are first-party, none performs the swap, and no published
number or scientific artifact is contaminated.

**Exhaustive correction.** A `DependencyCase` execution snapshot now enumerates
all six fields: `name`, `coordinates_ns`, `allowed_dependency_mask`, `inputs`,
`invoke` and `comparison` (`dependency.py:245-264`). Locality and deterministic
witness execution use only that snapshot for invocation inputs, validation,
comparison, diagnostics and reports, and reassert every field identity after
each callable invocation (`dependency.py:418-450,633-712,826-884`). No
post-caller `case.*` reread remains outside the initial snapshot operation.

The registry also snapshots every dataclass field of each locality case,
witness declaration and negative control before the first suite callable runs
(`mnq_lab/conditioners/registry.py:51-70,341-369`). It reasserts those complete
declarations at each execution phase, preventing one case or control from
rewriting a later declaration. Stored comparison-policy evidence is constructed
from the pre-suite snapshots rather than live cases. Negative tests reproduce
both the bounded self-widening admission and a cross-case comparison replacement;
each failed on `7319f89` and passes only after the correction.

**Threat boundary corrected, superseding D38's overbroad wording.**
Caller-controlled declarations submitted through the public causal-admission
API are in scope for the entire admission transaction, including mutations
attempted with `object.__setattr__` while caller suite code runs. This is the
boundary enforced by the F-1, F-2 and F-5 snapshots and rechecks. Direct
same-process mutation of name-mangled registry storage or an already-stored
descriptor remains outside the enforceable boundary: F-3 and F-4 remain
reachable and recorded limitations because Python object encapsulation is not
process isolation. The distinction is now stated at
`registry.py:200-208,246-256`. D38 remains byte-immutable; this entry corrects
its broader statement rather than rewriting history.

**Scope and status.** No store was rebuilt, no production or calibration phase
was rerun, and no artifact, threshold, tolerance or published result changed.
This correction changes admission enforcement, its negative tests and the
append-only record only. It is not self-ratification and does not authorize a
new phase checkpoint. **Status:** `OPEN; CORRECTED PENDING FOCUSED INDEPENDENT
RE-AUDIT`. Stage E remains blocked.

---

## D40. D18 focused re-audit remains OPEN: mutable declaration content and vacuous locality coverage

**Independent follow-up.** The focused review of `16efe2c` confirmed that the
D39 six-field comparison-policy correction is structurally sound. Roughly
twenty failure-seeking variations were all refused and left the registry empty.
The follow-up nevertheless found two separate declaration-content and coverage
gaps. D18 and Stage E therefore remain open and blocked respectively.

**F-6 (HIGH) — mapping content could change without changing mapping
identity.** At `16efe2c`, `DependencyCase.inputs` and
`DeterministicWitness.changed_inputs` were read-only `MappingProxyType` views
over copied ordinary dictionaries (`mnq_lab/core/dependency.py:204,311`), but
the backing dictionaries remained reachable in-process. Dependency execution
and registry admission reasserted only object identity
(`dependency.py:418-426`; `mnq_lab/conditioners/registry.py:51-70`). Replacing a
mapping value therefore left every identity check unchanged. A deterministic
witness with a deliberately wrong expected result of `9999.0` instead of the
true `1010.0` was repaired during an earlier suite call by substituting its
declared input array, and the resulting suite was stored as CAUSAL and
confirmation-eligible. The identical declaration without that substitution
was correctly refused. The arrays themselves remained immutable; the gap was
the mapping content.

The correction retains constructor-owned mappings and immutable, non-aliased
array copies (`dependency.py:216-246,258-284,338-377`) and adds structural
content snapshots covering mapping keys plus array dtype, shape and bytes
(`dependency.py:47-87,287-321`; `registry.py:48-89`). Identity and content are
now reasserted at the existing dependency-call and registry-phase boundaries
(`dependency.py:476-500`; `registry.py:75-89`). Negative tests demonstrate
both a case-input content rewrite during dependency execution and a
wrong-witness repair during causal admission; both failed before the correction
and pass only when the rewrite is refused.

**F-7 (MEDIUM) — zero probes could produce a successful locality report.** At
`16efe2c`, `run_dependency_locality` iterated input names from the live mapping
and returned a report without requiring any probe to have run
(`dependency.py:633-694`). Emptying the backing mapping after baseline
evaluation yielded `mutation_trial_count == 0`,
`forbidden_region_count == 2`, and `changed_value_counts == (0, 0)` while the
runner reported success. The runner now raises whenever declared forbidden
regions would produce zero mutation trials (`dependency.py:701-770`), with a
negative test that failed before and passes after the correction. A report can
no longer claim locality coverage that was not executed.

**Existing checks prevented stored admission of a genuinely out-of-window
callable.** Three independent requirements held: a witness must reference the
same object as a declared locality case (`registry.py:547-555`), witness input
names must exactly match case input names (`dependency.py:777-788`), and a
witness must change at least one in-window value (`dependency.py:822-824`).
Together they refused the reproduced genuinely out-of-window callable despite
the zero-probe locality report. This defence-in-depth result does not excuse
F-6 or F-7; it limits their observed effect.

**Integrity-boundary wording corrected.** D39 and the former registry
docstring described caller declarations as protected for the complete
transaction. Identity checks could not support that statement for mutable
mapping content. The implementation now checks identity and structural content,
and `registry.py:267-276` states the exact enforcement points: before a
declaration's execution and after each dependency callable returns. Direct
same-process modification of name-mangled registry storage or an already-stored
descriptor remains outside the supported retrieval-integrity guarantee. This
is an offline scientific self-check boundary concerned with correctness and
reproducibility.

**Scope and status.** No currently registered first-party measurement function
performs either rewrite, and no published number, scientific artifact,
threshold or tolerance is affected. No data store was rebuilt and no
production or calibration phase was rerun. This correction changes future
admission enforcement, its negative tests and the append-only record only. It
is not self-ratification and does not authorize Stage E. **Status:** `OPEN;
CORRECTED PENDING FOCUSED INDEPENDENT RE-AUDIT`. Stage E remains blocked.
