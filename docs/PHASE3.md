# Phase 3 — S00 completion atlas and threshold freeze

Phase 3 built the deterministic S00 completion atlas, derived one completion
threshold candidate per horizon, obtained an independent candidate audit,
ledgered the approved values, and only then added the three values to
`analysis_constants_v1.yaml`.

Phase 4 and S01A have not started. No conditioner, excursion estimate, weight,
bootstrap result, P&L, ranking, or trading recommendation was computed.

## Frozen order

The irreversible steps occurred in this order:

| Step | Commit | State |
|---|---|---|
| Quantile/artifact preregistration | `7c3645b` | YAML keys absent |
| S00 candidate implementation | `d9f2bc2` | YAML keys absent |
| Audited freeze authorization added | `f8238ea` | YAML keys absent |
| YAML-only three-key freeze | `8068313` | exactly three lines added |
| No-default loader and ledger agreement enforcement | `203c003` | frozen values required |
| Build-time/current-YAML provenance distinction | `ac662b9` | old and new hashes both live |

`tests/test_threshold_ledger.py::test_ledger_commit_predates_the_yaml_freeze`
reconstructs this ordering from Git history. It reads the YAML blob at the
ledger-addition commit, verifies the old SHA-256, proves all three keys absent,
then proves that commit is an ancestor of the distinct YAML-freeze commit.

The ledger mechanism is intentionally small: one canonical immutable JSON file
per authorization under `mnq_lab/ledger/entries/`. It is not represented as the
full Phase 11 governance layer.

## Measured

### Source and artifact provenance

```text
tier                    exploration
declared population     2019-05-05 through 2023-03-29, inclusive
actual sessions         2019-05-06 through 2023-03-29
sessions                1,009
gridpoints              78,702 = 1,009 × 78
store rows              274,847
pipeline_version        spine-1.0.0
build_id                0ad7843647f17258
manifest_sha256         1cf6ec5ce7822ce1333984909b52d5c937e4ccc06e280030bcacda22620ffd73
artifact bytes          7,636
artifact_sha256         725df33a00e53c6c356c4348df2a02fe9ed309d9d4e4118216894a70ef8a479d
```

The artifact is strict canonical JSON at:

```text
data/exploration/s00/s00_threshold_input_v1.json
```

Two consecutive CLI runs produced identical bytes. Adding the artifact's own
derived threshold keys to the YAML did not change one artifact byte.

`weight_ess` is JSON `null` in every cell, accompanied by
`weight_ess_status = "not_computed_until_phase_4"`.

### Complete threshold-input table

The table is in YAML phase order, then YAML horizon order. `n_anchors` is the
number of state anchors whose outcome window fits RTH. Observed-path values are
diagnostic only.

| phase | h | grid | state | n_anchors | n_sessions | complete fully labeled | rate fully labeled | complete observed path | rate observed path | status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| open | 15 | 6,054 | 6,038 | 6,038 | 1,008 | 6,030 | 0.998675057966214 | 6,033 | 0.9991719112288837 | ok |
| open | 30 | 6,054 | 6,038 | 6,038 | 1,008 | 6,026 | 0.9980125869493209 | 6,031 | 0.9988406757204372 | ok |
| open | 60 | 6,054 | 6,038 | 6,038 | 1,008 | 6,018 | 0.996687644915535 | 6,027 | 0.9981782047035442 | ok |
| morning | 15 | 18,162 | 18,125 | 18,125 | 1,008 | 18,106 | 0.998951724137931 | 18,119 | 0.9996689655172414 | ok |
| morning | 30 | 18,162 | 18,125 | 18,125 | 1,008 | 18,095 | 0.9983448275862069 | 18,115 | 0.999448275862069 | ok |
| morning | 60 | 18,162 | 18,125 | 18,125 | 1,008 | 18,081 | 0.9975724137931035 | 18,109 | 0.9991172413793104 | ok |
| midday | 15 | 24,216 | 24,003 | 24,003 | 1,006 | 23,866 | 0.9942923801191518 | 23,904 | 0.995875515560555 | ok |
| midday | 30 | 24,216 | 24,003 | 24,003 | 1,006 | 23,763 | 0.9900012498437696 | 23,805 | 0.9917510311211098 | ok |
| midday | 60 | 24,216 | 24,003 | 24,003 | 1,006 | 23,568 | 0.9818772653418323 | 23,607 | 0.9835020622422197 | ok |
| afternoon | 15 | 18,162 | 17,532 | 17,532 | 974 | 17,523 | 0.9994866529774127 | 17,532 | 1.0 | ok |
| afternoon | 30 | 18,162 | 17,532 | 17,532 | 974 | 17,519 | 0.9992584987451517 | 17,532 | 1.0 | ok |
| afternoon | 60 | 18,162 | 17,532 | 17,532 | 974 | 17,517 | 0.9991444216290212 | 17,532 | 1.0 | ok |
| close | 15 | 12,108 | 11,688 | 9,740 | 974 | 9,740 | 1.0 | 9,740 | 1.0 | ok |
| close | 30 | 12,108 | 11,688 | 6,818 | 974 | 6,818 | 1.0 | 6,818 | 1.0 | ok |
| close | 60 | 12,108 | 11,688 | 974 | 974 | 974 | 1.0 | 974 | 1.0 | ok |

### Session flags

```text
observed_short_session                         34
observed_rth_ended_early                       34
observed_no_rth_bars                            1
observed_mid_rth_gap                            4
ended-early plus mid-gap overlap                0
calendar_early_close = "unknown"            1,009
```

Every exploration session remains in the S00 population. No holiday name or
official early-close classification is claimed.

### Ratified mathematics and candidates

Opus 5 ratified the equal-phase discrete inverse-CDF convention before code:

```text
s00_p05(h)
    = inf{x : (1/5) Σ_p 1[c(p,h) <= x] >= 0.05}
    = min_p c(p,h)

raw_threshold(h)  = floor(100 × s00_p05(h)) / 100
min_completion(h) = max(0.90, raw_threshold(h))
```

Exact integer arithmetic produced:

| h | attaining phase | exact fraction | p05 | floor | frozen value |
|---:|---|---:|---:|---:|---:|
| 15 | midday | 23,866 / 24,003 | 0.9942923801191518 | 0.99 | 0.99 |
| 30 | midday | 23,763 / 24,003 = 7,921 / 8,001 | 0.9900012498437696 | 0.99 | 0.99 |
| 60 | midday | 23,568 / 24,003 = 7,856 / 8,001 | 0.9818772653418323 | 0.98 | 0.98 |

Opus independently reconstructed the raw `.npy` population without using the
S00, completion, or time-model modules and returned Stage D `VERDICT: CLOSED`.
It reproduced every table field, fraction, candidate, hash, flag count, test
baseline, and gate.

### YAML provenance

```text
old analysis_constants_v1.yaml SHA-256
3f5c4bd5258eeb306d76d45aa4ad568a2483f007415e7d11df89ebbc8c4b182a

new analysis_constants_v1.yaml SHA-256
1c95aa595c30c48b853303291a7dbaabceaf5b7331bca565a30863e8dcf138d4
```

The exploration store manifest correctly retains the old, build-time YAML hash.
It was not rewritten after the freeze. The ledger records that old hash; the
current YAML hash and exact ledger/YAML values are checked independently.

The YAML now contains exactly:

```yaml
min_completion_h15: 0.99
min_completion_h30: 0.99
min_completion_h60: 0.98
```

The completion-threshold loader has no defaults and rejects missing, extra,
non-numeric, non-finite, non-hundredth, or out-of-range values.

### Verification replay

```text
python -m pytest tests -q
332 passed, 5 xfailed

python -m mnq_lab.spine.gates --store data
4/4 pass

python -m mnq_lab.outcomes.completion --store data
1,009 sessions; 78,702 gridpoints

python -m mnq_lab.outcomes.s00 --store data
artifact SHA-256 725df33a00e53c6c356c4348df2a02fe9ed309d9d4e4118216894a70ef8a479d
```

Named tests kill or fail closed on wrong estimand, pooled horizons, dropped
lowest/thin phase, linear interpolation, round instead of floor, `min` instead
of `max`, missing/duplicate/extra cells, empty/NaN/infinite cells, excluded
short sessions, whole-bar gaps, locked-tier paths, YAML-before-ledger ordering,
ledger/YAML mismatch, missing threshold defaults, and post-freeze S00 drift.

Opus additionally applied six mutations independently: observed-rate
substitution, round-not-floor, min-not-max, dropped-lowest-phase, linear
quantile, and pooled horizons. Zero survived.

## Inferred and arithmetic implications

- The h30 value has effectively zero population margin: one additional
  incomplete midday h30 window would move its candidate from 0.99 to 0.98.
  The corresponding floor margins are 103 windows for h15 and 45 for h60.
  This does not change the audited result; it records sensitivity to any future
  data re-vintage, source revision, or pipeline change.
- On this store, substituting the diagnostic `observed_bar_path` rates happens
  to yield the same three candidates. Rounding also happens to yield the same
  candidates. The real values therefore do not discriminate those wrong
  mechanisms; synthetic mutation tests do.
- Midday is the inverse-CDF-attaining phase at all three horizons. This is a
  completion measurement, not a profitability ranking or market recommendation.

## Not verified

- No versioned CME calendar exists locally. The 34 ended-early sessions are not
  classified as scheduled closes, and the no-RTH session is not assigned a
  holiday name.
- Completion versus volatility state remains unmeasured because conditioners
  do not exist yet.
- The frozen values are specific to the recorded store build and pipeline.
  Stability under a future source vintage or pipeline version is not claimed.
- The minimal immutable-entry ledger is not the full Phase 11 governance
  system.
- No Phase 4 weight, bootstrap, conditioner, null, or S01A output has been
  computed.

## Final audit closure

Opus 5 returned final `VERDICT: CLOSED` at commit `65e9901` after independently
verifying the freeze ordering from Git objects, canonical ledger contents,
old/build-time versus new/current YAML provenance, full replay, artifact
identity, mutation behavior, documentation, and Phase 3 scope.

One non-blocking low observation remains: the test name
`test_ledger_artifact_provenance_matches_generated_bytes` overstates its direct
mechanism. The test compares the existing generated artifact's size and hash to
the ledger; it does not itself regenerate S00. Regenerating after an S00-payload
mutation does change the bytes and is caught, so the protection is real. A
future maintenance unit may rename the test or strengthen it to regenerate
before comparing. This does not reopen Phase 3.
