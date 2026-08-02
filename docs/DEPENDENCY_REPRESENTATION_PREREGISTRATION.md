# Phase 7 Dependency Representation Preregistration

**Program:** `mnq-atlas-001`
**Specification:** `REV6_FROZEN_SPEC.md`, revision 6
**Contract date:** 2026-08-02
**Base:** `e6e1c6fdb3eac901e17ccb6a73c801b2f1a797d1`
**Branch:** `phase-7b-outcome-layer`
**Status:** user-ratified representation contract; implementation is prohibited until this document and the legacy identity oracle receive an independent audit

## 1. Governance and boundary

This document preregisters one representation-only correction for the exact
causal dependency evidence retained by Phase 7 seasonal-profile and threshold
rows. It changes no conditioner value, validity flag, status, semantic mask,
calendar rule, arm, history rule, artifact schema, artifact byte, or causal
membership. It authorizes no real-corpus run and no Phase 8 computation.

The ledger trigger does not apply. Frozen section 16 ties a ledger entry to a
change in frozen section 4 or `analysis_constants_v1.yaml`; this contract
changes neither. The Phase 3 ledger is a threshold-freeze instrument, not a
production-run or internal-representation permission namespace. No existing
ledger or accepted-calendar entry may be changed for this work.

The correction is needed because today's row-local tuples retain repeated
historical prefixes. Seasonal rows now share one tuple within each
`(session, phase)`, but successive sessions still retain successively longer
prefixes. Threshold rows retain the same quadratic shape across nine expanding
arms. Bounded measurements project roughly 11.8 GiB for five seasonal sources
and 21.2 GiB for nine expanding threshold arms before other Phase 7 objects.
Another corpus attempt is prohibited until section 10 is satisfied.

This contract covers only:

- seasonal keys `(session_id, observation_bucket_ct)` retained by
  `SeasonalProfileRow`;
- threshold keys `(session_id, tau_ns)` retained by `ThresholdRow`; and
- the exact reconstruction and validation interface named `dependency_keys`.

It does not authorize changes to seasonal estimation, relative volatility,
threshold probabilities, weighted quantiles, assignment categories, artifact
schemas, admissions, the accepted calendar, or the canonical exploration
store. The repeated `sorted(completed_sessions)` call in
`mnq_lab/conditioners/assignments.py` remains a separate time-complexity issue
and is explicitly out of scope.

## 2. Representation contract

There are two separate typed canonical pools:

```text
seasonal pool key:   (session_id: int, observation_bucket_ct: str)
threshold pool key:  (session_id: int, tau_ns: int)
```

Within each pool there is one canonical append-only key sequence per
`(arm_id, session_phase)`. A dependency-bearing row stores exactly:

```text
sequence_ref, start, end
```

`start` and `end` are integer offsets and define the half-open range
`canonical[start:end]`. The referenced sequence has an immutable identity for
the lifetime of every row that refers to it. Appending a later session block
may extend the pool but may not alter, reorder, replace, or remove any earlier
key. No row owns or caches a private fully expanded historical tuple.

The public compatibility interface remains:

```python
row.dependency_keys == tuple(row.sequence_ref[row.start:row.end])
```

`dependency_keys` remains a property returning the exact tuple expected by
today's ratified tests. Callers need no schema or equality-semantics change.
Production construction and validation must not materialize all historical
prefixes simultaneously. A temporary expansion requested by one test or one
caller may exist only for that request and may not be cached on every row.

The range is the dependency evidence. Keys outside `[start, end)` are not
dependencies of the row even when they exist in the same canonical pool.
Sequence identity, key type, arm, phase, start and end are all validated;
substituting a different equal-looking pool is not silently accepted.

## 3. Load-bearing monotonicity premise

The design is valid only because dependency eligibility is monotone in the
current-session clock. For a fixed arm and phase, a prior session qualifies
when all of the following hold:

```text
prior_session < current_session
the accepted calendar marks the prior session seasonal-reference eligible
the prior session has at least one valid source row for the phase
```

The calendar classification and source-row validity of a prior session do not
depend on `current_session`. Advancing the current session therefore cannot
remove or alter a previously qualifying block. It can only admit later whole
session blocks when their session identifiers become strictly prior.

For seasonal profiles, a block contains the valid scale-row keys for one
qualifying `(prior_session, phase)`. The current implementation constructs the
phase dependency list by iterating completed sessions in ascending order and
extending it with the existing scale-row order. Therefore every seasonal row's
dependency sequence is a prefix of one fixed canonical sequence.

For thresholds, a block contains the valid `vol_rel` row keys for one
qualifying `(prior_session, phase)`. Expanding-history arms select all
qualifying prior blocks and therefore use a prefix beginning at zero.
`threshold_rolling60` selects the last at most sixty qualifying session blocks
and therefore uses one contiguous range whose start and end are both block
boundaries.

This premise is load-bearing. If any eligibility input changes as a function
of a later current session, if a qualifying prior block is removed, or if a
block's key order changes after admission, the range design is void and the
builder must halt. A prefix-monotonicity test constructs successive current
sessions and asserts that each expanding expansion equals the preceding
expansion followed by zero or more complete later blocks. A planted input that
removes an earlier qualifying block for only the later current session must
fail that test. A rolling test asserts that each range equals exactly the last
sixty block identities; a planted non-contiguous selection must fail.

## 4. Canonical ordering and typed sequences

Canonical ordering is fixed:

1. qualifying session blocks in ascending `session_id` order;
2. within each block, the source rows' existing canonical order; and
3. no sorting by a value, status, scale, threshold, category or other measured
   field.

The seasonal within-block order is the existing scale-anchor order, which is
equivalent to ascending observation time and therefore ascending
`observation_bucket_ct` on the frozen RTH grid. The threshold within-block
order is the existing `VolRelTable` row order, equivalent to ascending
`tau_ns` within the session and phase.

The canonical sequence contains only qualifying keys. It is not a universe of
all possible anchors plus a rule for deciding which ones count. Seasonal and
threshold sequences cannot be interchanged, and sequences from different
arms or phases cannot be interchanged.

The exact legacy oracle is authoritative for final ordering:

```text
seasonal expansion == tuple(sorted(set(legacy_phase_dependency_keys)))
threshold expansion == today's dependency_keys construction in build_thresholds
```

If existing row order and `tuple(sorted(set(...)))` ever disagree, the
implementation halts and reports the first row; it does not silently sort a
new representation into agreement.

## 5. Holes and exclusions

Invalid source rows are never appended. Calendar-ineligible sessions are never
appended. A session with no valid row in the phase contributes no block.
Consequently the canonical index space remains contiguous even when session
identifiers skip or a session block has fewer than the nominal number of
anchors.

No missing key is inferred from a session identifier, timestamp interval,
bucket name, calendar class, or neighboring key. Every expanded dependency was
explicitly appended from a validated source row. The range representation is
therefore stricter than an inferred timestamp or session range: it can expose
only exact stored qualifying keys, including exact holes, never keys generated
by a rule.

Early-close, holiday, invalid-row and all-invalid-session fixtures must be
present in the implementation tests. Their absence from the canonical sequence
is compared against the legacy tuple, not accepted merely because a count
looks plausible.

## 6. Exact expansion semantics

For every dependency-bearing row:

```text
dependency_keys = canonical_sequence[start:end]
```

The result is a tuple with exactly the same element types, contents and order
as today's implementation. For seasonal rows it must equal the legacy
`tuple(sorted(set(phase_dependency_keys)))`. For threshold rows it must equal
the tuple produced by today's nested iteration over selected sessions and
their valid `VolRelRow` objects. Equality is required for every row, including
warmup, undefined, expanding and rolling60 rows; no sampling and no summary
hash may substitute.

The `dependency_keys` property remains available under that exact name so all
ratified tests that compare tuples continue working without modification.
Tuple equality, row equality and table equality remain unchanged. The property
does not expose pool keys before `start` or at or after `end`.

The legacy identity oracle is written and committed against the tuple-based
implementation before any representation code. It covers both builders, an
expanding threshold arm and `threshold_rolling60`, at all 78 RTH anchors per
session. The later implementation is not admissible unless every expanded row
equals this oracle in full.

## 7. Validation rules

No current predicate is removed.

Both current row types retain:

- exact sorted and unique dependency keys; and
- every dependency session strictly earlier than the row's current session.

Threshold rows additionally retain today's predicate that the number of
distinct dependency sessions equals `qualifying_prior_sessions`. Today's
`SeasonalProfileRow.__post_init__` does not contain the analogous count check;
the new representation validator adds it explicitly so the number of distinct
seasonal dependency-session blocks must equal
`qualifying_prior_sessions`. This is an added guard, not a claim that the
current seasonal constructor already enforces it.

The representation adds all of these predicates:

- `sequence_ref` is the registered sequence for the row's pool type, arm and
  phase;
- `start` and `end` are built-in integers;
- `0 <= start <= end <= len(sequence_ref)`;
- both offsets lie on valid session-block boundaries;
- every expanding range starts at zero;
- every rolling60 range spans at most sixty whole session blocks;
- the range's block count equals `qualifying_prior_sessions`;
- every expanded key has the row's phase in the source table;
- every expanded session is calendar eligible;
- every expanded key names a valid source row;
- no session whose phase rows are all invalid contributes a block;
- expanding ranges are prefix-monotone across successive current sessions;
- rolling60 ranges equal the latest at most sixty qualifying blocks; and
- exact expansion equals the legacy oracle tuple.

An unknown pool, missing block, repeated block, partial block, reordered key,
wrong arm, wrong phase, mutated prefix, invalid bound or pool mutation after a
row is constructed is corruption and halts. It does not receive a status and
does not trigger a fallback to private tuples.

Construction-time validation may use the canonical sequence and block index
directly. It may not prove correctness by materializing and retaining all row
prefixes, because that would recreate the defect behind a different API.

## 8. Artifact and provenance effect

There is no Phase 7 artifact-schema change. `dependency_keys` is absent from
both `SEASONAL_SCHEMA` and `THRESHOLD_SCHEMA`, and
`mnq_lab/conditioners/artifacts.py` contains no dependency field or dependency
serialization path. Sequence references, offsets and block metadata are
runtime causal evidence only and are not added to `.npy` columns or manifests.

The implementation must prove complete Phase 7 artifact byte identity. Using
the same bounded synthetic input and matching environment fingerprint, write
artifacts once with today's tuple implementation and once with the new
representation. Compare every relative path and every raw byte. The comparison
must include manifests and all columns, not merely scientific values or file
hash summaries. A negative control that perturbs one serialized seasonal or
threshold value must make the byte-tree comparison fail.

The manifest records `code_commit` through its complete environment
fingerprint. The identity fixture supplies the same explicit matching
fingerprint to both writer invocations, as permitted by the existing writer,
so the complete artifact trees must be byte-identical under that controlled
scope. No test may delete or ignore a provenance field to obtain identity.
Normal production manifests continue to bind the actual implementation commit
and therefore distinguish builds made from different commits; that provenance
difference is not a scientific-column or schema change.

## 9. Bounded memory acceptance rule

Before any corpus run, measure these three quantities in fresh bounded
processes:

```text
retained dependency keys
deep dependency bytes
peak process working-set bytes
```

Measure at `N = 100, 200, 400` sessions for:

- one seasonal arm at all 78 RTH anchors per session; and
- one expanding threshold arm at all 78 RTH anchors per session.

For each series, both doubling ratios `100->200` and `200->400` must be no
greater than `2.4`. The retained-key count counts physically retained keys in
canonical sequences and block metadata once; it does not sum repeatedly
expanded compatibility-property tuples. The memory harness must assert that no
row owns or caches a private expanded tuple and must fail a planted legacy
materialization mutant.

Use the bounded curve to extrapolate to `N=1009` across all five seasonal
source arms and all ten threshold arms, including the nine expanding arms and
`threshold_rolling60`. The projected concurrent Phase 7 conditioner process
peak, including canonical pools, rows, tables and fixed process overhead, must
be strictly less than `2 GiB`. Label the extrapolation as inferred and report
the model. If either bounded ratio exceeds `2.4`, the projected peak is at
least `2 GiB`, or the model cannot account for every concurrently live table,
the gate fails closed. Do not run the corpus to resolve uncertainty.

The acceptance rule is fixed before the new distribution is measured. It may
not be raised after observing the implementation curve, and memory may not be
reduced by discarding, hashing, approximating or lazily inferring dependency
membership.

## 10. Mutation floor and named failing inputs

Each mutation is scored by a behavioral test tied to the defect. A source-hash
pin may detect a changed file but does not count as the killing test.

1. **Missing dependency.** Remove the valid `08:30` key from one prior regular
   session block; the exact expansion oracle must fail on the first dependent
   row.
2. **Additional dependency.** Append a valid-looking key outside the legacy
   selection; the expansion oracle must report the extra element.
3. **Reordered dependency.** Swap two keys inside a session block; canonical
   ordering validation must halt.
4. **Duplicated dependency.** Append the same key twice; sorted-unique and
   block validation must halt.
5. **Current-session dependency.** Append a key whose session equals the row's
   current session; strict-prior validation must halt.
6. **Future-session dependency.** Append a later session key; strict-prior
   validation must halt.
7. **Wrong-phase dependency.** Put a midday source key in an open-phase
   sequence; typed phase/source validation must halt.
8. **Calendar-ineligible session.** Append a scheduled-early-close or full-
   holiday session block; calendar validation and the legacy oracle must fail.
9. **All-invalid session.** Append a block for a session whose phase source
   rows are all invalid; valid-source and block-count validation must halt.
10. **Legacy expansion mismatch.** Change one otherwise valid key while
    preserving length and bounds; the full row oracle must fail on contents.
11. **End before start.** Use `start=4, end=3`; bound validation must halt.
12. **End beyond sequence.** Use `end=len(sequence)+1`; bound validation must
    halt.
13. **Rolling60 exceeds sixty blocks.** Set its start to include sixty-one
    qualifying blocks; the history-window validator must halt even when bounds
    are otherwise valid.
14. **Expanding range not starting at zero.** Use `start=1`; expanding-prefix
    validation must halt.
15. **Simultaneous historical-prefix materialization.** Cache a private
    expanded tuple on every row; the object-ownership assertion and retained-
    key curve must fail, with a doubling ratio above `2.4` on the named bounded
    fixture.
16. **Quadratic memory curve.** Restore row-local historical tuples while
    keeping value outputs equal; the `N=100,200,400` memory gate must fail.
17. **Non-monotone expanding support.** Remove one old qualifying block only
    for a later current session; prefix-monotonicity validation must halt.
18. **Non-contiguous rolling selection.** Select blocks 1-59 and 61 while
    omitting block 60; latest-sixty validation must halt.

Every fixture asserts that the mutated region is nonempty and that the
unmutated control passes. A constructor rejection counts only when it is the
specific predicate named above, not an incidental malformed-object failure.

## 11. Legacy identity oracle

The legacy oracle is a test-tree reference implementation of today's builders,
authored and committed before representation implementation. It imports no
future dependency-pool module and obtains no expected dependency tuple from a
production result.

It covers:

- `build_seasonal_profiles` at 78 RTH buckets per session;
- `build_thresholds` for an expanding arm;
- `build_thresholds` for `threshold_rolling60`;
- warmup and post-warmup rows;
- invalid source rows and calendar-ineligible sessions; and
- complete dependency contents and ordering for every emitted row.

The comparison walks every row in canonical order and every dataclass field.
It compares float fields by exact IEEE-754 bytes and non-floats by exact type
and value. It is not a sample and not a summary hash. A negative control
perturbs one structurally valid dependency key and proves the comparator can
fail for seasonal and threshold tables.

The oracle must pass against the unchanged tuple implementation at this
contract's base. If it does not, the oracle is wrong. Production code may not
be changed to satisfy it.

## 12. Conditions authorizing another corpus run

Another Phase 7 plus Unit O corpus run is authorized only after all four gates
are independently established:

1. this byte-pinned preregistration is ratified;
2. the representation implementation receives an independent `CLOSED` audit;
3. the legacy identity oracle passes for seasonal and threshold builders and
   for expanding and rolling60 history; and
4. the bounded memory acceptance rule passes through `N=400`, including the
   less-than-2-GiB concurrent projection.

All four are required. A faster runtime, extra physical RAM, a green source-
hash pin, or success at `N<400` substitutes for none of them. If a gate fails,
stop and report the first mismatch. Do not relax the ratio, raise the memory
ceiling, weaken dependency evidence, stream around an unvalidated table, or
attempt the corpus to see what happens.

## 13. Implementation order and explicit exclusions

After this contract and the pre-implementation oracle receive an independent
ratification audit, implementation may proceed in this order:

1. typed canonical sequences and immutable session-block metadata;
2. seasonal ranges and exact compatibility expansion;
3. threshold expanding and rolling60 ranges;
4. all validation and mutation witnesses;
5. artifact byte-identity proof;
6. bounded `N=100,200,400` memory gate; and
7. independent implementation audit.

The following remain out of scope:

- changing `sorted(completed_sessions)` inside the threshold double loop;
- changing any seasonal or threshold value formula;
- changing arm inventory, probabilities, history length or warmup;
- changing the accepted calendar or eligibility rules;
- changing Phase 7 artifact schemas or provenance fields;
- changing any existing preregistration, frozen specification, YAML, ledger or
  closeout;
- running the canonical corpus or inspecting outcomes; and
- any Phase 8 computation.

The only authorized repository suite invocation remains:

```text
python -m pytest tests --ignore=tests/test_bootstrap_acceptance.py -q
```

The acceptance module may be hashed as raw bytes when explicitly required but
must never be imported, collected or executed. The bare full suite is
forbidden.
