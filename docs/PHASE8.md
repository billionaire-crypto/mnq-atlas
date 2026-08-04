# Phase 8 Closeout - Outcome-Layer Descriptive Measurement

**Program:** `mnq-atlas-001`  
**Specification:** `REV6_FROZEN_SPEC.md`, revision 6  
**Branch:** `phase-7b-outcome-layer`  
**Tests-first base:** `f3797458ab03ff9a46edd820b26c69355ee62c7a`  
**Implemented and production tip:** `7f28af868c7908bff520a50263269e9ff48f9069`  
**Production artifact:** `phase8-first-run-v1`  
**Artifact manifest SHA-256:** `69d552e091c39491cef8b79545780b03240faecf97496cd1a20e6da8222099f5`  
**Status:** production complete; independent Phase 8 closeout audit pending

This document closes the implementation and production work authorized by the
Phase 8 contract and the append-only D21 through D30 rulings. It records the
implementation through `7f28af8` and the independently audited production
artifact computed at that exact clean commit. It does not authorize Phase 9,
does not select or rank a cell, and does not report a tick, quantile, contrast,
interaction, or interval endpoint. This document and its commit are outside the
implemented range and require their own focused independent audit.

## 1. Inputs, ratification, and contract history

The production entry point consumed Unit O only through
`require_ratified_unit_o`. The ratified candidate is
`data/exploration/derived/phase7-unit-o-first-run-v1` at run commit `6dcbff8`.
Its certificate is
`mnq_lab/ledger/ratification_entries/2026-08-03-phase7-unit-o-first-run-v1.json`,
60,679 bytes and SHA-256
`618957cb9d70b949ec78d3e2f89013fda7cfaf3b0b6381170225caf98f2f37bd`.
The referenced closed audit entry is 1,991 bytes and SHA-256
`82588e4fa978e5c8005d5272469e5ace4842c1df64212abeade72b7ae163aa9c`.

The artifact manifest binds the following inputs:

| Input | SHA-256 |
|---|---|
| Frozen specification | `70dae16c8b12fe26d38a7bfdabf0202066fe7149f790d0d2942279d9c3b8ff50` |
| Analysis constants | `1c95aa595c30c48b853303291a7dbaabceaf5b7331bca565a30863e8dcf138d4` |
| Outcome-layer preregistration | `4b5bc97fdfd4b0219c69e6a8adf76f18072091a9389700191d3ddcd10f8207c8` |
| Phase 8 preregistration | `d07174ed0acc9e60ab6b255f4b33fc08141969c64e04f66e1e08c0aca98b4680` |
| Accepted calendar | `b86e112c16112bf11a6a548ca8b3f21d28a08f90442b4dde84098f9d3f6eb069` |
| Unit O input manifest | `c063fe6885d2933cac97c1979185bc3d33d2fe600ff77e826ee9e9f7c1316513` |
| Phase 7 input manifest | `e9d0443cfb5d4b5594b51f8b4c480c312f46ddb0ec4b54797d4b8787d8c5daed` |
| Run input manifest | `39d14712086e074b950316b4ef032299c06a398eea885d49ccfbeb65a272e84e` |
| Corpus seal | `1cf6ec5ce7822ce1333984909b52d5c937e4ccc06e280030bcacda22620ffd73` |

D21 fixed contrast weighting and the exact year-concentration rule. D22 fixed
the two formal nulls. D23 through D26 established the Unit O ratification
conditions and their explicit claim boundaries. D24 made path estimand a
contrast-table key; D25 fixed the four-cell interaction to
`common_session_paired`; D27 and D28 recorded the exact-bootstrap feasibility
stop; D29 authorized rented hardware without changing a frozen parameter; and
D30 authorized byte-identical engineering work after the first production
attempt exposed a serial implementation bottleneck.

## 2. Implemented measurement surface

Phase 8 implements the two frozen outcome directions, three quantile
statistics, five session phases, three volatility states, five contrast
supports, three population estimands, and the two comparative contrast
weightings. Quantiles reuse the audited inverse-CDF helpers. Tick comparisons
are signed integer differences widened to int64 before subtraction.

The primary arm emits its complete declared inventory. Each of the other nine
arms emits only its one frozen survival surface. Completion, positivity,
support adequacy, degeneracy, and total status precedence are applied without
repair. Every declared cell is retained. Every anchor count is accompanied by
a session count and effective sample size.

The descriptive interaction uses exactly one four-cell common-session support,
`common_session_paired`, with reference phase `midday`, reference volatility
state `mid`, and q50/q90 only. Day types are primary-arm absolute distributions
classified from accepted-calendar fields with scheduled early closes taking
precedence over holiday adjacency. The two frozen truncated regular sessions
remain regular and carry their unresolved data-quality status.

The joint bootstrap generates one global whole-session plan for each block
length and replicate and applies it across all eligible requests. Its contract
is unchanged:

- 4,999 draws per block length;
- mean block lengths 1, 5, 10, and 20 sessions, with 5 primary;
- root entropy `(20260801, 8, 13, 1)` and child spawn keys `(0,)`, `(1,)`,
  `(2,)`, `(3,)` in block-length order;
- `PCG64`, confidence 0.95, inverse-CDF endpoints implied by 0.025 and 0.975;
- whole-session stationary resampling, no partial-session truncation;
- no retry, redraw, or early stopping.

The complete run made exactly 19,996 global resample-plan calls. Target and
baseline statistics, and all four interaction terms, were recomputed within
the same replicate multiplicities. No interval was constructed by subtracting
marginal endpoints.

## 3. Deterministic artifact and checkpoints

The artifact contains four immutable `.npy` column stores and one canonical
JSON manifest:

| Table | Rows | Status-bearing |
|---|---:|---|
| Contrasts | 29,430 | yes |
| Intervals | 26,472 | interval validity |
| Day-type descriptives | 216 | yes |
| Interactions | 720 | yes |

All 85 column files exist and every recorded byte count and SHA-256 matches.
Structural row IDs are unique. The contrast, day-type, and interaction IDs
match their independent declared generators in literal order. The 6,618 `ok`
point rows receive exactly four interval rows each, in block-length order 1,
5, 10, 20; no non-`ok` point row receives an interval.

The checkpoint store is bound to commit `7f28af8`, 32 bootstrap workers, the
`fork` start method, the ratified input-manifest hashes, and the bootstrap
contract. Its 13 contiguous chunks contain 26,472 unique rows. Concatenating
the chunks in order reproduces all 13 final interval columns byte-for-byte.
The four plan matrices and all chunk columns match their recorded hashes.

Protected operational records are:

| Record | Bytes | SHA-256 |
|---|---:|---|
| Artifact manifest | 27,442 | `69d552e091c39491cef8b79545780b03240faecf97496cd1a20e6da8222099f5` |
| Checkpoint identity | 550 | `cfe2f5f7db96164e09a75fdfb2b5645b6fd7c5f8eeb5120a1a3aef5b566e1c69` |
| Plan manifest | 1,635 | `a8f9193eeb576f3c3a698689fa0e4839658a286cd95584da71c8f211ab1df90e` |
| Progress log | 108,782 | `e23c3f5ef0a7bc55994c597ea5b3e20fadee2115fc8daad6f70e74c9ed6e831c` |

The artifact, checkpoints, progress log, and operational logs were copied to
the operator's local machine. The artifact and checkpoint trees were also
copied to persistent QuickPod storage and produced no difference under a
checksum dry run. The local artifact and all 188 local checkpoint files were
revalidated against their manifests after transfer.

## 4. Execution record and resource boundary

The successful production pass ran on Linux x86-64 with 128 logical CPUs and
approximately 252 GiB physical RAM. Stage 1 used eight workers and the
bootstrap used 32. The final pass began at
`2026-08-04T13:02:10.754976+00:00` and completed artifact writing at
`2026-08-04T14:53:13.013492+00:00`, approximately 1 hour 51 minutes. It reused
the exact four plan matrices already checkpointed under the same commit,
inputs, worker identity, and bootstrap contract; generating those plans took
approximately 84.4 seconds in the preceding controlled attempt.

The manifest records aggregate peak RSS as 483,577,282,560 bytes. The external
parent-plus-descendant monitor observed a maximum of 483,578,699,776 bytes and
a minimum physical-available memory of 55,772,721,152 bytes (51.94 GiB), above
the 48 GiB emergency floor. Aggregate RSS double-counts shared forked mmap
pages and therefore exceeds physical RAM; it is an accounting ceiling, not a
claim of unique physical allocation. No emergency stop record exists.

After artifact completion, the operator directly read `/proc/135660/stat`
while the runner was a zombie awaiting reaping. It reported raw exit code 0,
exit status 0, and signal 0. That observation was captured in the execution
transcript but was not written to a durable exit-status log. Progress reaching
bootstrap chunks 13/13 and artifacts 1/1, the canonical manifest, and all
matching artifact hashes independently corroborate normal completion. The
absence of a durable exit-status file is retained as an operational limitation,
not rewritten as stronger evidence.

## 5. Status surface and conditioned availability

The full declared inventory remains visible. Status counts are:

- contrasts: 6,570 `ok`, 22,572 `insufficient_completion`, and 288
  `insufficient_anchors`;
- day types: all 216 `insufficient_completion`;
- interactions: 48 `ok`, 336 `degenerate_baseline`, and 336
  `insufficient_interaction_support`.

The independently audited reconciliation found 21,582 contrast targets passing
their completion threshold, 9,036 baselines passing or not applicable, and
exactly 6,570 rows where both required sides passed. Those 6,570 rows are
exactly the `ok` contrast rows, with no residual in either direction. The
baseline side is therefore the binding recorded completion constraint for this
inventory. All 216 day-type rows retain nonempty support but fail the frozen
target completion minimum.

Nothing was repaired, suppressed, pooled, reclassified, or re-thresholded.
The `ok` rows are a conditioned, non-random subset determined by the frozen
completion and support gates; they are not representative of every declared
cell. This sparsity is itself part of the measurement and cannot be used to
select or emphasize a cell.

## 6. Verification result

At production tip `7f28af8`, the only authorized suite invocation was:

```text
python -m pytest tests --ignore=tests/test_bootstrap_acceptance.py -q
```

The final independent production-results audit reran it and obtained:

```text
1236 passed, 1 skipped, 2 xfailed in 217.23s
```

The xfails are exactly `prevalence_results` and
`consumed_vintage_artifacts`. The skip is the Windows-unavailable
`resource.getrusage` probe. The protected acceptance module was not imported,
collected, or executed. The audit independently passed artifact integrity,
checkpoint/reproduction integrity, contract compliance, and descriptive-only
reading, and authorized this closeout document subject to the disclosures in
sections 4, 5, and 8.

## 7. Protected implementation hashes through `7f28af8`

The following raw-byte pins cover every path changed from the parent of the
tests-first base `f379745` through production tip `7f28af8`. This table does
not include this closeout document or its commit.

| SHA-256 | Bytes | Path |
|---|---:|---|
| `75f438150c929fcc03d986dd92837df1b8510d2273f58e2a207097bee86d1908` | 84,222 | `docs/DISCREPANCIES.md` |
| `7ab5d64d28a441df97fc5f005713f17ba6135f8c4b4f82f90412eaab131a70e1` | 9,538 | `docs/MEMORY_CEILING_V2_PREREGISTRATION.md` |
| `9977996cc19a6593822968abfe770265610bc10762f65df843371c6fe65e71fd` | 29,925 | `mnq_lab/core/weights.py` |
| `82588e4fa978e5c8005d5272469e5ace4842c1df64212abeade72b7ae163aa9c` | 1,991 | `mnq_lab/ledger/audit_entries/2026-08-02-unit-o-first-run-v1.json` |
| `ff7164fdb83ed7faecd40790950c9787d82b54fe64bb8eeaa1eb99d0c2317394` | 31,914 | `mnq_lab/ledger/ratification.py` |
| `618957cb9d70b949ec78d3e2f89013fda7cfaf3b0b6381170225caf98f2f37bd` | 60,679 | `mnq_lab/ledger/ratification_entries/2026-08-03-phase7-unit-o-first-run-v1.json` |
| `64a5d95f0d72bd717d1c1a6d74f03d36c0e9ac4172e3f57905812ccf0826337b` | 2,600 | `mnq_lab/phase8/__init__.py` |
| `00083891077a5464bc2902f08e3d9ace71767d8a7fe1d9543b8132871081a7ec` | 16,658 | `mnq_lab/phase8/artifacts.py` |
| `37d6e0983deb938d605b04f0308bb1f8682cd978c7a94d75815942976217602d` | 15,573 | `mnq_lab/phase8/contrasts.py` |
| `00f8bbd8556cc6ccff4e8cf6ee9a62d248fe87096597feea0308e67647a5e5a1` | 14,685 | `mnq_lab/phase8/day_types.py` |
| `1f9d7de803e3699041975c2812e6b6e7248586d27e52135c991931e8669cf5ff` | 25,532 | `mnq_lab/phase8/diagnostics.py` |
| `8f051d0ad878e36fef2edba89c09d63632a03e6d3e49659b8656e0fa4d3d69d3` | 16,987 | `mnq_lab/phase8/estimands.py` |
| `1d0d32f0d1c98c6b22b1aea890541af41b2fa5db665c96b8b6aba40cef294bb4` | 21,510 | `mnq_lab/phase8/interactions.py` |
| `83e62cc613ab6f1d7ae3521cc6e185bbe2c693af294a98b2170a5f76ac9c9c51` | 9,418 | `mnq_lab/phase8/inventory.py` |
| `93dc8e5b763ab8a3cf8298b80ab7bac1019a0238e93bc751b8e00f98fe76e059` | 5,367 | `mnq_lab/phase8/preflight.py` |
| `d9216e0d0ebda503a610b6368e77767889fb17efd7d3bfebea3c3fadd7f5a679` | 50,000 | `mnq_lab/phase8/production.py` |
| `81b7a72882d9b3ecfc41cc3d7f4c44c763aff101c95fbb01645f3ebb0b57ff00` | 13,758 | `mnq_lab/phase8/progress.py` |
| `e60e2e23746ffd1941bcf06f1bb3b595cc6127488cb469303d8a7551b6fb9f66` | 24,605 | `mnq_lab/phase8/runner.py` |
| `7a7379f9dad3ba48a0bf918e366d4da88b7ff37ce9f42617171990ce2e00fb5c` | 45,465 | `mnq_lab/phase8/uncertainty.py` |
| `4b2eafae47f1f88fc360178f3c0e324f940e7a75464792f40557cccd16268795` | 10,815 | `tests/test_peak_memory_probe.py` |
| `f55e06b83dbe85ec19be8f2887ebbdc3b72bc288ab682fc83b5dd55d2fee03f0` | 6,676 | `tests/test_phase8_axes_and_contrasts.py` |
| `f4d3fc9f5aa5b77d79a1b3203319215b0658e3bc3eeedfe40daafa1c806c1faf` | 6,715 | `tests/test_phase8_bootstrap_performance.py` |
| `dbb6479b957b78fedf128e7722c5ce457ecbc26b04e44daa035053d0525a78de` | 8,305 | `tests/test_phase8_day_types.py` |
| `2c76d960c6e2ba481f5de3afc791ab44df38ea38ac31c46453a9f01b120d9646` | 16,511 | `tests/test_phase8_diagnostics_and_status.py` |
| `517328cab87a47078dd08d1a3903fa049aa96197c433d5eb970d36c82fb6b230` | 10,892 | `tests/test_phase8_estimand_weights.py` |
| `f5aa05b68a0ec0f0dd543baf774f98f42287ee9f862a324ab6e357ef9b86f59c` | 4,583 | `tests/test_phase8_interaction_bootstrap.py` |
| `d8b537f2a331c94aeacc8b80afc2cdd3f8cf1a26b2905435be6b61af96eb4ecd` | 14,830 | `tests/test_phase8_interactions.py` |
| `3cf9dde5e1c21edc3a866a6633fffbd08297623f66b2eff94d8e6334c274257c` | 8,415 | `tests/test_phase8_inventory.py` |
| `920efc12877f81b0fd3933228a08d58d61ceadb7bfdca70c4304deeca1ad8b1f` | 10,191 | `tests/test_phase8_joint_bootstrap.py` |
| `c42cfece500216759a97827669d3c84e38a2eaaf5943d4239089c9b2143f0238` | 6,304 | `tests/test_phase8_partition_merge.py` |
| `1934719403feb98b1b9d3d1549adef40e7bbc578d5b5a388a39051a4f6650ffe` | 5,871 | `tests/test_phase8_prepared_quantiles.py` |
| `2c37e5f7b030155d625d1bba3815f019ccbadcc1b0cd3484ef10ce353345a29e` | 13,375 | `tests/test_phase8_progress.py` |
| `8653cc0f8b645f8227f33bd1af12df8a90a6d6788d9eaf392221cfabd069d736` | 9,643 | `tests/test_phase8_runner_artifacts.py` |
| `4d4bcfa628f47750a4437aef04ff926dcca367e9e814303697f18a69f7b8aee5` | 5,105 | `tests/test_phase8_runner_entry.py` |
| `7d279f5f9bc84f58f19d2de193a462bd5fa5d7e42bb58d2a4ddd624b5f864960` | 2,763 | `tests/test_phase8_runner_preflight.py` |
| `9f1a706859fefe1634b17658d59271e2b9f989352f2717a6e8964bb4b0eb10ab` | 20,371 | `tests/test_unit_o_ratification.py` |
| `c7910ba6cbabcf369824720ec35d207852ff4c8e410f5ca6b3b3bd47ab47f685` | 10,901 | `tests/test_validator_vectorization_identity.py` |
| `d4028a775c386948b8a6e9938f23d27d60711a5781f6997cfd2611f7469bd9c4` | 11,010 | `tests/test_weights_vectorization_identity.py` |
| `c36dd4f5dbe1c7a3be3db92cb0fb77b2b3d8e974c9dcaf8747619651a38f4f85` | 4,679 | `tools/phase8_bootstrap_benchmark.py` |
| `c447bcb08f0d8c39aa2ec12e0c0fb4f6f7ae87f8ad6838763cdcdeacd8056325` | 10,688 | `tools/phase8_bootstrap_term_count.py` |

The protected 51,539-byte prefix of `docs/DISCREPANCIES.md` remains
`7ec200bb1de83769b8ce07551fec4e0b81f5e90e20a4792c22ae47f285bed615`,
and the pinned D22 section remains
`cf27329a329df856290a945eec47ad19e52b0298110b1bfe9c1a75581d0386cf`.
The current full-document hash is separately recorded above because later
append-only rulings intentionally follow those protected bytes.

## 8. Mandatory limitations and claim boundary

The artifact limitations are carried verbatim:

- Gate passage and the audit verdict are attestations, not mechanical proof.
- Result visibility rests on a corroborated but externally unanchored timestamp.
- Append-only is repository policy rather than code.
- The reproduction evidence is empirical byte identity, not structural proof
  that computation code was unchanged.

Phase 8 is descriptive measurement. A weighted quantile difference is not a
causal effect. Common-session pairing is post-session selection.
Calendar-quarter standardization controls only the declared quarter mixture and
must never be labelled market-regime control. Inactive liquidity era leaves the
formal null without longer-term regime adjustment; no direction of
conservativeness is known.

Day type has thin special classes and is descriptive only. The two truncated
regular sessions remain unresolved data-quality discrepancies. The accepted
calendar is a single-source input whose close-time evidence is corroborating,
not proof of every classification.

Confidence intervals describe resampling uncertainty within the historical
mixture. They do not include future regime change, conditioner-estimation
uncertainty, price-feed completeness, calendar-classification uncertainty or
model-selection uncertainty. Overlapping horizons and serial dependence are
not repaired by `weight_ess`; the whole-session block sensitivity makes some,
not all, dependence visible.

No Phase 8 output establishes profitability, a stop recommendation, a trade
entry, a preferred conditioner arm, statistical significance, confirmation,
or future performance. No p-value is emitted. No result may be used to rank,
select, optimize, or recommend an arm or cell.

## 9. Next gate

The production-results audit authorized this closeout document, not Phase 9.
One focused independent audit must verify this document, recompute every hash
in section 7, recheck the artifact and checkpoint bindings, confirm the status
and exit-evidence disclosures, and determine whether Phase 8 may close. Until
that audit returns `CLOSED`, Phase 9 and all market-result interpretation remain
unauthorized.
