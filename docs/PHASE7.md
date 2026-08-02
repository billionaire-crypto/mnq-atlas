# Phase 7 Closeout — Causal Volatility Conditioners and State Validity

**Program:** `mnq-atlas-001`  
**Specification:** `REV6_FROZEN_SPEC.md`, revision 6  
**Branch:** `phase-7-conditioners`  
**Accepted calendar base:** `ded8ba0733f525b31b3cb948ece9a6ada493c9ec`  
**Implemented tip:** `85da2417e80d325ca5243680a35db4d6bd35f9c3`  
**Status:** implementation complete; independent Phase 7 closeout audit pending

This document closes the implementation work authorized by U13, U14, and U15.
It records the implementation through `85da241`; it does not authorize Phase 8
and it does not report a market result. The commit introducing this document is
a child of `85da241` and is itself unaudited until the independent closeout
audit. This document therefore does not contain or claim its own SHA-256.

## 1. Audited inputs and contract history

The accepted CME equity-index reference calendar is inherited unchanged from
the independently closed `phase-7-calendar-input` tip `ded8ba0`. The scientific
contract is the append-only `docs/PHASE7_PREREGISTRATION.md` at 51,877 bytes and
SHA-256 `eeb97cb7e6ccd17a0ccd676de3cf7424f511fc773bacd62ff9e9f88aa404a930`.
Its amendments close P7C-1, P7C-3, and P7C-4 without rewriting earlier bytes.
P7C-2 was classified as not a defect. U15 expanded the audit cadence to four
checkpoints; contract ratification and checkpoints 2 and 3 are closed, and this
document initiates checkpoint 4.

The implementation chain after the accepted calendar base is:

1. `e0853ca` — preregister the Phase 7 contract;
2. `f7be278` — pre-authorize pinned-base maintenance (P7C-1);
3. `f0b6816` — add return construction, status, median, masks, and adapter;
4. `90e66c8` — correct historical ledger binding governance (P7C-3);
5. `39685e7` — execute D20/A5/pin maintenance atomically;
6. `cdfea2e` — implement bias-adjusted EWMA and rolling MAD;
7. `5220215` — pre-authorize the conditioner guard correction (P7C-4);
8. `02c3d4b` — narrow the Phase 6 registry guard and add the Phase 7 guard;
9. `98b7521` — implement accepted-calendar consumption and seasonal profiles;
10. `226955e` — implement `vol_rel`, thresholds, assignments, and migration;
11. `383cc9d` — execute the integrated real-conditioner registry gate;
12. `c2ada39` — implement the descriptive state-validity panel; and
13. `85da241` — implement deterministic artifacts and frozen test 13.

No accepted-calendar byte, calendar-ledger byte, frozen specification byte,
YAML byte, Phase 5 artifact, or scale implementation changed after its relevant
checkpoint.

## 2. Implemented definitions

Phase 7 implements close-to-close natural-log five-minute returns on full
Globex support. Returns never span a roll, non-five-minute interval, daily
maintenance halt, weekend closure, or—under the strict arm—an incompletely
covered bar. Both strict and permissive component-coverage definitions are
retained as a one-factor-at-a-time pair.

The bar-scale layer provides bias-adjusted numerator/denominator EWMA RMS at
halflives 39, 78, and 156, all with a fixed 78-return warmup, and an independent
78-return rolling lower-median MAD multiplied by 1.4826. The scheduled daily
halt and weekend break reset both estimators, so no volatility state crosses a
Globex session boundary. Contract-roll and gap tests compare every post-reset
value bit-for-bit with a from-scratch run on the isolated post-reset segment.

The seasonal layer consumes only the accepted static calendar. Observation
buckets are the 78 five-minute wall-clock endpoints from 08:30 through 14:55
America/Chicago. Calendar-excluded sessions do not enter the 60-session warmup
or reference. Bucket medians shrink toward the median of per-session phase
medians with `w=n/(n+30)` until `n=30`. The implementation never infers a
holiday or early close from observed shortening.

The ten immutable OFAT arms are emitted in the preregistered order: reference,
strict coverage, EWMA 39, EWMA 156, MAD 78, rolling-60 thresholds, and the four
paired probability shifts. Thresholds use equal total mass per qualifying
session and strictly prior sessions only. Assignment encoding is int8
`undefined=-1`, `low=0`, `mid=1`, `high=2`; exact lower-boundary values are low
and exact upper-boundary values are mid. Migration emits the complete 4-by-4
grid, including zero cells and both directional undefined counts.

## 3. Executed causal-admission gate

The integrated registry contains 35 distinct causal callables: five scale,
five seasonal, five `vol_rel`, ten threshold, and ten assignment entries. Every
entry executes the Phase 6 dependency-locality harness, a deterministic witness,
both required negative-control families, and exact equality with a semantic
mask built independently of implementation metadata. Float comparisons use
`atol=0` and `rtol=1e-12`; discrete outputs are exact.

Semantic masks are bar-indexed. EWMA uses the entire current contiguous segment;
MAD uses exactly 79 bars for 78 returns. The planted anchor-minus-79 mutation
changes EWMA while leaving MAD bit-identical. Composite seasonal and threshold
masks exclude the current session and reject both narrowed and widened masks
even when a numerical output happens not to change.

The Phase 6 registry guard remains unconditional over `registry.py` and
`conditioners/__init__.py`. The Phase 7 layer guard allows immutable-identity
ordering in real conditioner modules while rejecting measured-value ordering,
forbidden layer imports, locked-tier/store literals, and helper-based evasion.
Its static-analysis limit—an allowlisted identifier rebound to measured content
cannot be tracked—is disclosed in the test and backstopped by canonical-order
and prefix-invariance assertions.

## 4. State-validity panel

The descriptive panel emits the nine fixed metric families in canonical order:

1. category and assignment-status frequencies;
2. average defined-category run length;
3. complete 3-by-3 transition matrices and conditional entropy in bits;
4. primary-versus-OFAT migration;
5. complete threshold series and median absolute consecutive drift;
6. average-rank Spearman raw-scale correlation;
7. component-coverage and horizon-specific completion correlations as
   right-hand-side diagnostics only;
8. explicit deferred liquidity-era rows; and
9. all non-ok status fractions by arm, phase, and year.

Reset and non-ok status diagnostics are arm-specific. Outcome completion never
enters a return, dependency mask, seasonal profile, threshold, or assignment.
The panel emits no score, preference, selection, prevalence estimand, or
pass/fail decision.

## 5. Deterministic artifact contract

The artifact writer serializes five immutable `.npy` column stores—anchor
scales, seasonal profiles, thresholds, assignments, and state validity—plus one
canonical sorted-key UTF-8 JSON manifest. It enforces the frozen column order,
dtype, aligned nonempty support, finite float64 storage, and positive-zero
canonicalization. The manifest records source build identity, hashes of the
specification/YAML/preregistration/calendar, accepted calendar and schema
versions, code commit and dirty flag, complete environment fingerprint, arm and
table order, row counts, and every column's dtype, byte count, and SHA-256. It
also records all 35 registry comparison policies.

Seasonal-dependent output halts before writing if the calendar version or hash
is null or differs from the accepted input. A planted Phase 8–12 artifact key
fails. Same-fingerprint synthetic rebuilds are byte-identical. Cross-environment
claims are semantic only. No artifact bundle and no market-derived Phase 7
result was written to the repository during implementation.

## 6. Prefix invariance and deferred targets

Bar scales, seasonal profiles, tercile thresholds, and conditioner assignments
have real passing prefix-invariance tests with nonempty prefix/extension guards
and named negative controls. The three Phase 7 targets that entered this phase
as xfails are now passing tests. The only remaining xfails are:

- `prevalence_results`, deferred to Phase 9; and
- `consumed_vintage_artifacts`, deferred to Phase 11.

Neither may be deleted or converted in Phase 7.

## 7. Protected hashes through `85da241`

The following raw-byte pins cover every path changed from accepted base
`ded8ba0` through implemented tip `85da241`. The closeout audit must recompute
them; this table does not include this document.

| SHA-256 | Bytes | Path |
|---|---:|---|
| `7ec200bb1de83769b8ce07551fec4e0b81f5e90e20a4792c22ae47f285bed615` | 51,539 | `docs/DISCREPANCIES.md` |
| `eeb97cb7e6ccd17a0ccd676de3cf7424f511fc773bacd62ff9e9f88aa404a930` | 51,877 | `docs/PHASE7_PREREGISTRATION.md` |
| `ceeb30224d2e880386e12720d066e8909b7145e7cca64d822b9bffc5cc894860` | 19,330 | `mnq_lab/conditioners/admission.py` |
| `f25fd25d8d681eacd673b3af901a60d384aff7ffba9b6f4c8cd963702841a6c8` | 2,430 | `mnq_lab/conditioners/arms.py` |
| `9520b27fd8aa28af319eaa83ce1436c7ac34e70993f550d07d677adfe937d8ec` | 13,535 | `mnq_lab/conditioners/artifacts.py` |
| `c10a4ef369d41508517d5c599dd4b754fe4b52c866bdee6270fa15e347db4b56` | 29,138 | `mnq_lab/conditioners/assignments.py` |
| `b8b5d6888b91a96c8df2809653b240535e171fda05850acfa99740a39f0ac2f7` | 9,168 | `mnq_lab/conditioners/calendar.py` |
| `638f44ecd85b8bd8b889c35a0592b3a3786b17de0f02a4acd42a7f1b5cb59e5a` | 6,440 | `mnq_lab/conditioners/pipeline.py` |
| `ee364ca747bb400ef0663fe2858d218011361405bd974bae12867724de5187dd` | 247 | `mnq_lab/conditioners/scales/__init__.py` |
| `a1e4ed59d0af8d7a3be9f0d30940511f112659113422130599948d81f03c20eb` | 7,571 | `mnq_lab/conditioners/scales/ewma.py` |
| `a1c328d35f79e66e04178d9cba6e9cf5f5aa590c39337bdf4457925b77ff1094` | 6,846 | `mnq_lab/conditioners/scales/mad.py` |
| `8b8fa3c42f83757a176745ee4808c525e4c73f855c0908d0dc4e3be7b039db85` | 1,335 | `mnq_lab/conditioners/scales/median.py` |
| `381dd5f05c2925abd800b22712914e10fc50f32462a69f69a762a77313894b62` | 10,457 | `mnq_lab/conditioners/scales/returns.py` |
| `ac7c7c0e591ef7e261802cfc2d27c215b9eaf199cc72c58df14c3135b0403645` | 17,520 | `mnq_lab/conditioners/seasonal.py` |
| `2e04657f2e58ea7b4a682d09af1ce88d8a7791a04db06b825e0fdbe0857e2445` | 1,240 | `mnq_lab/conditioners/semantic_masks.py` |
| `a5c736ef31390a313389e068b2ccfd680b2ad351e6bf68cf72740620c8aec0fa` | 23,506 | `mnq_lab/conditioners/state_validity.py` |
| `2208a12da296b71915a75a3a92434d69c283d9e180fccddc93a1ca06f8a3f3fb` | 6,271 | `mnq_lab/conditioners/status.py` |
| `549a34293b96d4cb2d200403be69961b2fe847c2c99b6feb1bfce9672e9b7590` | 6,792 | `mnq_lab/spine/exploration.py` |
| `7ff4484b88eed981e0006fe7382ec7c30ffef7b2e33695d41c711f49bb62bfc2` | 1,258 | `tests/phase7_contract_oracles.py` |
| `f9b4c6d77985c69670f1e02ea6f312453e783b64c05142bebec2cf85004f7d31` | 2,973 | `tests/phase7_pipeline_fixtures.py` |
| `d0814c6851ff763c6b6b588a17346b250165f42ed2981f8da5dca40ee6ef5750` | 31,941 | `tests/test_conditioner_registry.py` |
| `a953bdeb5df37f43f3fb839394d1d9c1a3d15ddffcb4fe3acc878b85f0c4a99f` | 5,915 | `tests/test_phase7_artifacts.py` |
| `f802bb3f0286b957ad9109ec6db96ed82c251ac627d3ff11cac126e5cb9bb44d` | 12,579 | `tests/test_phase7_assignments.py` |
| `b6cd9ca93c397c80e34eff47fc6259331070a4d23989edb1df0ad21e30cefb50` | 11,889 | `tests/test_phase7_calendar_and_seasonal.py` |
| `1687f2a792e81cd397b22e1e1a81524fd88df1511adb4a5bb2e61928f9b52fba` | 24,490 | `tests/test_phase7_calendar_input.py` |
| `635bed037184b703d3ed7a28975d45da2ccb1c66d674878cab89386eb1ef2e83` | 5,859 | `tests/test_phase7_conditioner_layer_scope.py` |
| `f45d87d8e3b598a7d85c9137b49e8f9e064a680fb6bd4f17b894e6029f3aad88` | 4,658 | `tests/test_phase7_conditioner_pipeline.py` |
| `fd39dd2d0dbd0845b70009ae6bff9fa01c60041c5078726cea111421429eeb36` | 6,512 | `tests/test_phase7_exploration_adapter.py` |
| `fd203cff00467c0d249548029ddb02fc6bcbd464be6c751a104ae57819727f32` | 4,790 | `tests/test_phase7_real_semantic_masks.py` |
| `d009c286b7ee497c9fe68206fdc7a0003bc00499da49af9938da083ecd57ccf8` | 5,266 | `tests/test_phase7_registry_gate.py` |
| `18b75f58db56dd4daecc1f7c5239ff8d062c5cc7dbf54099b13cf2ed0ed3e734` | 8,060 | `tests/test_phase7_returns.py` |
| `f8bbe339f2b81003fc7841290680813348371d2c9cada0d56f5026fda7102958` | 3,769 | `tests/test_phase7_scale_prefix_invariance.py` |
| `95d7c4e842af928b1d6073e961f218ec3c9f21179cbc77a0c42ec7e4bfeb8d8f` | 6,494 | `tests/test_phase7_scales.py` |
| `617b9258b4d2ed6a3e974ef4274022979098c81d6a6cd4b4163002ad091bcd92` | 3,191 | `tests/test_phase7_semantic_masks.py` |
| `470112821cf913fe4f0406d762e4ebed9e50ac0ef206be0c1086d1c0bba46c01` | 6,071 | `tests/test_phase7_state_validity.py` |
| `b08a308ccf95b8dcdf831d2904ee39a200a67c328f20a523b45ad3fc67796f93` | 5,062 | `tests/test_phase7_status_and_median.py` |
| `1dec8a3f02056a9f1a312f8c5cff80136ab53860a6c5381742e1f48761d23b2f` | 10,043 | `tests/test_prefix_invariance.py` |
| `8729752bb9e25245cc6e472031fad0e47a07bd3f4ce8469cbd09f18cf97333c3` | 6,773 | `tests/test_roll_reset.py` |
| `8c65f85d0d7e92cd0a90903ddd08df9673682faca5c9351b42e033fe9883ed5e` | 19,593 | `tests/test_spec_consistency.py` |

Three protected transitions are intentional and pre-authorized:

- `docs/DISCREPANCIES.md`: 49,015 bytes / `68325d57…63df1c7` to
  51,539 bytes / `7ec200bb…bed615`;
- `tests/test_phase7_calendar_input.py`: 17,186 bytes /
  `d4429aad…7f11` to 24,490 bytes / `1687f2a7…b52fba`; and
- `tests/test_conditioner_registry.py`: 31,452 bytes /
  `cc7ea4a5…b884ae` to 31,941 bytes / `d0814c68…f5750`.

The first two occurred together in the §21/§22 maintenance commit. The third
occurred only after §23 was independently ratified. The accepted calendar
ledger entry, its validator, and `docs/PHASE7_CALENDAR_INPUT.md` remain unchanged
at their previously audited hashes.

## 8. Verification result

The only authorized suite invocation is:

```text
python -m pytest tests --ignore=tests/test_bootstrap_acceptance.py -q
```

At implemented tip `85da241` it produced:

```text
893 passed, 2 xfailed
```

The two xfails are exactly `prevalence_results` and
`consumed_vintage_artifacts`. The protected acceptance module was not imported,
collected, or executed. The bare full suite was not run.

Checkpoint 2 independently ratified the bar-scale foundation. Checkpoint 3
independently ratified the calendar-to-assignment pipeline and P7C-4 guard
correction. Checkpoint 4 must re-run the safe suite, recompute every hash above,
attack registry admission, state validity, artifact determinism, phase
boundaries, and the protected transitions, and determine whether Phase 7 may
close.

## 9. Known limits and safety boundary

The finite locality, witness, semantic-mask, prefix, and mutation tests are
empirical evidence, not proof of universal causality or purity. The calendar is
single-source corroboration, not proof of every exchange classification. The
two regular-session truncations on 2020-02-28 and 2020-06-30 remain documented
data-quality discrepancies. Lower-median MAD with factor 1.4826 has a small
finite-window downward bias. Daily resets cap effective history; the h=156 arm
reaches at most 70.5% of its steady-state effective sample within one session.
State-validity statistics are descriptive and do not validate or select an arm.

No locked-confirmation path was accessed or named by Phase 7 production code.
No confirmation data, Phase 5 entropy, stochastic calibration, contrast,
prevalence result, null result, vintage, guard, p-value, P&L, expectancy,
Sharpe ratio, strategy, or S01A artifact was created. Canonical market data was
not rebuilt. Nothing was pushed, tagged, published, or made remotely visible.

**PHASE 7 IMPLEMENTATION:** COMPLETE, PENDING INDEPENDENT CLOSEOUT AUDIT  
**PHASE 8:** NOT AUTHORIZED  
**VERDICT:** OPEN
