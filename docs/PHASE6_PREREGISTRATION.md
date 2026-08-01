# Phase 6 preregistration — dependency locality and conditioner registries

This document records the complete executable Phase 6 contract after its
independent ratification and before any Phase 6 production implementation or
test is written. Phase 6 remains limited to a market-free dependency-locality
harness, deterministic synthetic witness infrastructure, and causal/descriptive
registry mechanics. Actual market conditioners and state assignments remain
Phase 7.

## Authority and audit sequence

The binding frozen inputs are:

```text
REV6_FROZEN_SPEC.md
70dae16c8b12fe26d38a7bfdabf0202066fe7149f790d0d2942279d9c3b8ff50

analysis_constants_v1.yaml
1c95aa595c30c48b853303291a7dbaabceaf5b7331bca565a30863e8dcf138d4
```

Repository and audit continuity:

```text
mandated Phase 6 handoff base
8e68095203ec0fa1b8be0b23a0e2f7655118dfc1

first contract correction
a51c35c0a4bf59ffa4f5bbdc532145fc797d874a

ratified contract tip
77af37eb1ac2fa37542c2df828c889fef468988a
```

The first independent review at `8e68095` returned `OPEN`. The focused review
at `a51c35c` returned `OPEN` / `AMEND`. Both failed audits remain permanently
recorded in `docs/DISCREPANCIES.md` D17. The focused re-audit at `77af37e`
returned:

```text
VERDICT: CLOSED
CONTRACT: RATIFIED
```

The user ruled on 2026-07-31 to follow the prior phases' single-path,
fail-closed admission discipline. This preregistration records that resulting
contract. It does not itself admit a callable or claim proof of causality.

## Ratified executable contract

BOUNDARY
1. Phase 6 provides only a market-free dependency-locality harness, synthetic
   witness fixtures, and causal/descriptive registry mechanics. Actual market
   conditioners and state assignments remain Phase 7. The generic declaration,
   comparison, and harness primitives belong in `core/`; registry mechanics
   belong in `conditioners/`; deterministic witness callables remain test-only.
2. A dependency case supplies immutable baseline inputs, immutable dependency
   coordinates, a declared allowed-dependency mask for the requested output,
   and an explicit callable invocation. Shapes align and inputs are never
   silently coerced, truncated, filtered, or mutated.
3. Dependency coordinates determine membership. Out-of-window mutation changes
   values only and cannot alter coordinates or mask membership.

LOCALITY
4. A fixed ordinary test-only `Generator(PCG64(0))` mutates every declared
   out-of-window region through a non-no-op mutation whose changed indices are
   verified. Seed 0 is an ordinary deterministic software-test seed, not
   scientific entropy, a one-shot seed, or a registered Phase 5 entropy.
5. The baseline and out-of-window-mutated calls must compare bit-identically
   for ticks, integer categories, and boolean masks. Floating estimators use
   only function-specific finite nonnegative absolute and relative tolerances
   fixed in immutable registration metadata. Floating comparison is elementwise
   `abs(actual - expected) <= atol + rtol * abs(expected)` after exact shape and
   dtype agreement. Undeclared, negative, NaN, infinite, or categorical-output
   tolerances fail closed and no tolerance may repair a wrong time boundary.
6. Missing outputs, changed shapes or dtypes, non-finite values not explicitly
   allowed by the contract, input mutation, or a no-op adversarial mutation fail
   closed. The harness makes supplied arrays read-only, preserves exact pre-call
   snapshots, and repeats identical invocations on fresh inputs to detect direct
   caller-array mutation and nondeterministic output. Planted hidden-RNG,
   module-global, corpus-length, and undeclared-companion dependencies must be
   killed where declared adversarial controls expose them; this is empirical
   coverage of those cases, not a general proof that no hidden dependency exists.

WITNESS
7. Every causal admission carries at least one deterministic hand-built witness
   whose selected in-window change and expected output are specified
   independently of the implementation under test.
8. The witness must produce the exact expected response. “Different from
   baseline” alone is not enough, and random in-window mutation is not a
   substitute for a witness. For floating output the witness must independently
   specify both the baseline response and expected changed response, and the
   harness must assert the callable against each. For at least one required
   affected output element, the two independently specified responses must be
   separated by strictly more than the sum of their comparison bands:
   `abs(expected_changed - expected_baseline) > (atol + rtol *
   abs(expected_changed)) + (atol + rtol * abs(expected_baseline))`. A floating
   witness that does not clear that separation is vacuous and fails before
   admission, so no constant or insensitive output can satisfy both comparisons.
9. Every test includes a negative mutation proving the locality comparison or
   witness assertion can fail.

REGISTRIES
10. Causal and descriptive entries share one identifier namespace and expose
    immutable metadata. Every duplicate identifier fails closed, including an
    otherwise identical repeat; no overwrite, unregister, downgrade, or
    reclassification exists. The same callable object cannot be registered under
    an alias or in the other registry; a distinct wrapper is a distinct callable
    requiring its own identity and, for causal admission, its own executed suite.
    Retrieval cannot mutate stored state, and iteration preserves insertion order
    rather than sorting by any measured output.
11. `register_causal_conditioner` has exactly one admission path: it executes
    the complete declared locality cases, deterministic witnesses, and required
    negative controls inside the registration call, validates all evidence, and
    only then atomically inserts the immutable entry. No caller-supplied boolean,
    string, token, dataclass, protocol or duck-typed object, serialized or cached
    result, prior-run result, alternate constructor, or other certificate can
    cause admission. Failure leaves the registry unchanged. No alternate causal
    admission mechanism exists in Phase 6.
12. register_descriptive_conditioner does not require causal-locality evidence,
    but every returned descriptor is permanently labelled
    NONCAUSAL — NOT ELIGIBLE FOR CONFIRMATION.
13. A single eligibility query used by future confirmation/forward code returns
    true only for causal entries. Descriptive entries cannot opt in through an
    argument, alias, metadata edit, or re-registration under the same identity.
14. Passing the causal suite is described as empirical admission evidence, not
    proof of causality.

SCOPE
15. No registry or harness reads a store, names the locked tier, imports study
    or report modules, creates a market result, or consumes scientific entropy.
16. No Phase 7 conditioner, Phase 8 contrast, Phase 9 prevalence result, Phase
    10 null, Phase 11 vintage, Phase 12 S01A output, or trading strategy is
    implemented.

The design-latitude resolutions in items 1–6 and 10–11 are recorded in
`docs/DISCREPANCIES.md` D17 and must be incorporated unchanged into the audited
`docs/PHASE6_PREREGISTRATION.md` before production implementation. Phase 6 can
test a declared window but cannot prove that a future real conditioner declared
the semantically correct, minimally sufficient window; over-wide declaration
review remains an explicit Phase 7 obligation.

## Recorded executable resolutions

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

## Binding verification and mutation floor

The complete test and mutation floor in `docs/PHASE6_HANDOFF.md` §11 is
incorporated in full. Every test must have a negative case or named mutation
showing it can fail. In particular, causal admission must kill forged evidence,
no-op out-of-window mutation, insensitive witnesses, wrong event-time
boundaries, overly broad floating tolerances, input mutation, registry identity
collisions, descriptive eligibility overrides, and market-aware imports or data
access from Phase 6 code.

Passing the declared suite is empirical admission evidence against the cases
executed. It is not proof of causality or proof that a future real conditioner
declares the correct minimally sufficient window.

## Governance and implementation boundary

- This preregistration must be committed and independently audited before any
  Phase 6 production code or test is written.
- A later correction preserves every prior `OPEN` audit and uses a new small
  commit; this record is never silently rewritten after implementation evidence.
- If permanent byte-pinning is required by the independent preregistration
  audit, the pin is added in a following documentation/test-only commit before
  production implementation.
- Phase 6 implementation follows handoff Stages C through F one bounded unit and
  one independently audited commit at a time.
- No Phase 7 conditioner, S01A result, confirmation result, or forward vintage
  is created or consumed under this contract.
- No protected Phase 5 artifact, frozen specification, YAML, S00 artifact, or
  canonical data store is modified.
