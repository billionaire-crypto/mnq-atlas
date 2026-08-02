# Unit O Closeout - Causal Excursion Outcome Layer

**Program:** `mnq-atlas-001`  
**Specification:** `REV6_FROZEN_SPEC.md`, revision 6  
**Branch:** `phase-7b-outcome-layer`  
**Starting tip:** `e9e8a10b03a3b102cffb9692eef14cfeba563232`  
**Implemented tip:** `212ca4dc231b769fd3eea7130d41d66681798866`  
**Status:** implementation corrections complete; focused independent re-audit pending

This document closes the implementation work authorized by the ratified
`docs/OUTCOME_LAYER_PREREGISTRATION.md`. It records implementation through
`212ca4d`; this closeout document and its byte-pin test are outside that
implementation range and do not claim their own hashes here. Phase 8 production
remains unauthorized unless the independent Unit O audit returns `CLOSED`.

## 1. Commit scope and governance

The local-only chain after the ratified contracts is:

1. `fe1476c` - append D21 and replace the recurring full-file discrepancy pin
   with exact append-only historical-prefix protection;
2. `67ce72e` - commit the Unit O executable tests before production code; and
3. `212ca4d` - implement the exact resolver, excursion table, semantic masks,
   validation, and deterministic artifact writer.

No frozen specification, YAML constant, accepted-calendar byte, Phase 7
historical closeout, calendar ledger, calendar validator, preregistration, or
canonical market-data byte changed. Nothing was pushed, tagged, published, or
made remotely visible.

## 2. Implemented outcome definition

For observation time `tau`, the reference is the close of the bar labelled
`tau-5m`. The future window contains exact UTC labels `tau, tau+5m, ...,
tau+delta-5m`; the label `tau+delta` is excluded. Resolution is by exact label
equality. Positional adjacency, shifting, interpolation, tolerance matching,
and inferred bars do not exist in the implementation.

The resolver widens every int32 price to int64 before extrema and subtraction,
then range-checks all four results before int32 storage. It emits the floored
downward and upward excursions plus both unfloored signed companions. Invalid
OHLC, noninteger prices, duplicate labels, overflow, empty valid paths, and
negative floored values halt as corruption.

Every declared estimand x session x observation-time x horizon row is emitted in
fixed structural order. The seven outcome statuses use the preregistered total
precedence. Invalid rows retain counts and mechanically true diagnostic flags,
carry false numeric validity, and use canonical zero storage that has no
meaning without its validity boolean.

## 3. Estimands and support

Both `fully_labeled_1m_grid` and `observed_bar_path` require every expected
five-minute label in the same session and decoded symbol. The fully-labelled
estimand additionally requires `observed_1m_components ==
expected_1m_components == 5` for every future bar. The anchor bar's own
component count is not an outcome requirement. This is the binding D12 reading.

Common support is each estimand's own 60-minute validity. It is copied to that
estimand's 15-, 30-, and 60-minute rows and is never intersected across the two
estimands.

## 4. Dependency, isolation, and prefix evidence

Production-declared bar and component masks are checked against independent
contract-derived masks with `numpy.array_equal`. The tests reject one-bar
widening before the anchor, widening to `tau+delta`, and narrowing away the
anchor or any future label. Deterministic in-window witnesses move the intended
excursion; an out-of-window price mutation is bit-identical. Component mutation
changes fully-labelled validity while leaving observed-path outcome values and
validity unchanged.

The public builder calls the existing exploration-safety and five-minute store
duration guards. Static imports and strings contain no conditioner or accepted-
calendar loader. Dynamic sentinels monkeypatch both real loader families while
executing every Unit O public entry point; neither is reached. An in-memory
mutant of the real excursion module adds conditioner access and reaches the
sentinel, proving the guard is non-vacuous.

A nonempty one-session prefix and nonempty extension preserve every prefix
value, status, validity, common-support flag, and dependency mask. The planted
backward-carry mutant fails the same fixture.

## 5. Deterministic artifact contract

The writer emits the 25 columns in the immutable preregistered order as
pickle-free `.npy` files and one sorted-key, indent-2, ASCII-safe UTF-8 JSON
manifest with one terminal newline. The manifest binds the source exploration
manifest, frozen inputs, both preregistrations, code, base and build commits,
dirty flag, environment fingerprint, exact axes, status counts, schema, per-
column dtype/bytes/hash, and semantic comparison policy. Same-fingerprint
synthetic rebuilds are byte-identical. Metadata containing a forbidden corpus
tier name halts.

No market-derived Unit O table or artifact was created or committed. The tests
used only synthetic in-memory or temporary exploration stores.

## 6. Protected raw-byte hashes through `212ca4d`

The closeout audit must recompute every entry as raw bytes.

| SHA-256 | Bytes | Path |
|---|---:|---|
| `70dae16c8b12fe26d38a7bfdabf0202066fe7149f790d0d2942279d9c3b8ff50` | 48,177 | `REV6_FROZEN_SPEC.md` |
| `1c95aa595c30c48b853303291a7dbaabceaf5b7331bca565a30863e8dcf138d4` | 3,311 | `analysis_constants_v1.yaml` |
| `4b5bc97fdfd4b0219c69e6a8adf76f18072091a9389700191d3ddcd10f8207c8` | 17,614 | `docs/OUTCOME_LAYER_PREREGISTRATION.md` |
| `d07174ed0acc9e60ab6b255f4b33fc08141969c64e04f66e1e08c0aca98b4680` | 31,862 | `docs/PHASE8_PREREGISTRATION.md` |
| `d987eddb15fd3f3581c60dbc590704f84d783f8ffe140fcd57259392c0f513a7` | 15,856 | `docs/PHASE7.md` |
| `e7d6a2704d7159e5f5f522705f4d989a0120756594c8026c9e559a144042655e` | 54,495 | `docs/DISCREPANCIES.md` |
| `7ca7e36a94eb59c38f0e8530ece891dc51c32cf1d736dc3901f468b04eceab76` | 6,242 | `mnq_lab/outcomes/artifacts.py` |
| `c521c17e272a391e39902e4016e913e449f7e567755b18455496cb7f9b7db31e` | 27,972 | `mnq_lab/outcomes/excursions.py` |
| `11d086e6dd1522bb635b52a9e283fc8432b4c07bccca7729454995b8ba8c8b70` | 19,561 | `tests/test_estimand_definition.py` |
| `cd175a9df82d4cd2499a2ffd7b6d7db8105e637b1e68f4232ad0726d1a980930` | 7,550 | `tests/test_outcome_artifacts.py` |
| `c79ca27e6230bc192b6599534f53c513e054bc32d60bdf49124f23c1e1779285` | 11,469 | `tests/test_outcome_excursions.py` |
| `ba38d2bfb978a20357048f58a5ce4f17088b918322ac3c67bf6921d5676e811f` | 5,239 | `tests/test_outcome_isolation.py` |
| `f34cb9170103af5ea58bfd067994763c1a66e6e578c4b2c218c7d73389f081f0` | 7,622 | `tests/test_outcome_locality.py` |
| `d9b8dee45bf5dd533074623e9f0fae435123b1fe9a03c714d16aab71245d52f5` | 25,061 | `tests/test_phase7_calendar_input.py` |
| `b37d377674c09fcf5716063cafd9dbb1d64b3da0f5047f50d741a5ccffabf266` | 9,963 | `tests/test_window_boundaries.py` |
| `04a6383c9fda1eebcd7811edfde5ed8f3153d0c9f9bb1720e11908a670953bd0` | 5,542 | `tests/unit_o_fixtures.py` |

## 7. D21 and recurring-pin transition

The D21 maintenance commit changed `docs/DISCREPANCIES.md` from 51,539 bytes /
`7ec200bb1de83769b8ce07551fec4e0b81f5e90e20a4792c22ae47f285bed615`
to 54,495 bytes /
`e7d6a2704d7159e5f5f522705f4d989a0120756594c8026c9e559a144042655e`.
The first 51,539 bytes remain byte-identical to the old hash.

The same commit changed `tests/test_phase7_calendar_input.py` from 24,490 bytes /
`1687f2a792e81cd397b22e1e1a81524fd88df1511adb4a5bb2e61928f9b52fba`
to 25,061 bytes /
`d9b8dee45bf5dd533074623e9f0fae435123b1fe9a03c714d16aab71245d52f5`.
The test now rejects truncation or mutation of the historical prefix and permits
only suffix growth. The immutable `fe1476c` commit message contains a malformed
62-character version of the old test hash; this closeout corrects the provenance
record without rewriting commit history. No other pinned value changed in that
maintenance commit.

## 8. Verification result

The only authorized suite invocation was:

```text
python -m pytest tests --ignore=tests/test_bootstrap_acceptance.py -q
```

At implemented tip `212ca4d`, with the committed implementation bytes, it
produced:

```text
937 passed, 2 xfailed
```

After adding the initial closeout document and its raw-byte/ancestry pin tests,
the clean invocation at audited tip `9620f14` produced:

```text
941 passed, 2 xfailed
```

After the four focused audit corrections recorded below, the final clean-tip
invocation produced:

```text
942 passed, 2 xfailed
```

The two xfails remain exactly `prevalence_results` and
`consumed_vintage_artifacts`. The protected acceptance module was not imported,
collected, or executed. The bare full suite was not run.

## 9. Independent audit correction record

The independent audit of `9620f14` returned `OPEN` with four finite defects in
test coverage and provenance, while independently confirming every excursion
value, window boundary, estimand rule, support flag, semantic mask, isolation
boundary and deterministic artifact check it recomputed.

The focused correction changes no production module:

- UO-1 adds the missing positive-direction production-builder witness for a
  genuine decoded-symbol change;
- UO-2 removes the reintroduced full-file discrepancy pin and retains only the
  exact 51,539-byte historical-prefix invariant plus D21 suffix presence;
- UO-3 corrects the malformed old calendar-input-test hash above and records the
  immutable commit-message error; and
- UO-4 renames the commit-chain test to claim ancestry only, matching its body.

Phase 8 remains unauthorized until these corrections receive a focused
independent `CLOSED` re-audit.

## 10. Limits and authorization boundary

The outcomes are extrema among recorded OHLC bars on complete expected clock-
time paths. Five one-minute labels do not prove trade-feed completeness, and a
five-minute OHLC bar does not reveal intrabar ordering. Floored excursions are
distances, not stops, fills, returns, profit, or an execution rule. Rejecting
incomplete paths retains the frozen section 6 selection surface.

Passing Unit O proves conformance to finite fixtures, exact masks, and declared
mutations. It does not prove market completeness, causality, profitability,
future regime stability, or calendar correctness. The two unresolved truncated
regular sessions remain unchanged downstream diagnostics.

**UNIT O IMPLEMENTATION:** COMPLETE, PENDING INDEPENDENT CLOSEOUT AUDIT  
**PHASE 8 PRODUCTION:** NOT AUTHORIZED  
**VERDICT:** OPEN
