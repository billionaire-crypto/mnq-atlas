# Phase 10 Calibration Preregistration

Date: 2026-08-12

Producer: Codex implementation session

This document freezes the design of the future Phase 10 Test 9 calibration. It is
not calibration evidence, an acceptance record, a ledger entry, a receipt, or a
ratification. No randomized control, planted-effect run, corpus p-value, rejection
count, or acceptance decision was produced while writing it.

## 1. Operator authorization and boundary

On 2026-08-12, the Codex implementation session asked the operator the following
question verbatim:

> Question: Do you authorize the Codex implementation session to create and commit `docs/PHASE10_CALIBRATION_PREREGISTRATION.md` containing the B1–B12 calibration design in your instruction dated 2026-08-12, while producing no runner, calibration, evidence, artifact, ledger entry, or data write?

The operator answered verbatim:

> I authorize

This authorization covers this preregistration document only. It does not authorize
implementation of a runner, control generator, effect generator, localization
calculation, parallel driver, or checkpoint system. It does not authorize a
calibration run, Type-I or power evidence, a corpus p-value, a rejection count or
frequency, an acceptance record, an artifact, a ledger entry, a ratification, or a
write under `data/`. Calibration execution requires a later, separate authorization.

The future calibration is conditional on the already frozen formal population:

```text
formal_test              = vol_given_phase
permutation_population   = ordinary_full_rth_nonadjacent_resolved
permutation_sessions     = 900
liquidity_era             = undifferentiated_no_versioned_boundaries
liquidity_era_status      = inactive_missing_versioned_input
effective_null_strata     = calendar_quarter_only
deployment_rng_seed       = 20260728
internal_permutations     = 4999
```

## 2. Randomized-control construction

Each of the 300 null-control replications draws one whole-session mapping over the
real 900-session formal corpus. The mapping is without replacement within calendar
quarter, never crosses a quarter, and assigns no recipient its own donor. It moves
the donor state vector, including donor undefined and warmup entries, while retaining
the recipient outcomes, completeness mask, and structural-fit mask. The mapped data
are treated as that replication's observed control data and are tested with a full
internal ensemble of `B = 4999` mappings.

The former exact-uniformity argument is false. Derangements are not closed under
composition. Exact enumeration at stratum size five found that 71.5% of compositions
leave the derangement space, and some compositions are the identity. For a stratum
of size `n`, the expected number of fixed points in a composition of two independent
uniform derangements is `n / (n - 1)`. Across the 16 frozen calendar-quarter strata,
that is about 16.3 self-paired sessions per control out of 900.

Consequently, the future Type-I behavior is measured, never proved by
exchangeability. The mapping-law fact does not bound the resulting rejection-rate
effect because the coherence statistic is discontinuous at its signed z thresholds.
Ties counted under the frozen `>=` comparison may additionally make the procedure
conservative.

No synthetic comparison of alternative control laws is part of this design. Such a
comparison would require its own frozen fixture family and authorization and could
not replace the real-corpus calibration gate.

## 3. Calibration estimand and fresh internal ensembles

Calibration targets the procedure-level operating behavior averaged over fresh
internal permutation ensembles. It does not target the private rejection probability
conditional on one fixed ensemble.

For replication `r`, the runner will draw:

1. one fresh outer control mapping; and
2. one fresh internal ensemble of exactly 4,999 mappings.

The outer mapping and internal ensemble are independent child streams. The same
outer control and the same 4,999 internal mappings are shared across that
replication's null, weak, medium, and strong quartet. Each of the 300 replications has
its own outer mapping and internal ensemble, independent of the other replication
indices under the declared seed hierarchy.

Reusing one frozen internal ensemble across all 300 null controls would estimate
that ensemble's conditional probability `q_H`, not the procedure-level nominal
parameter for which the acceptance criterion was designed. Conditional on one
ensemble the count can still be binomial; the parameter is the defect. Fresh
ensembles make the 300 null indicators independent at the replication level under
the randomized procedure. Sharing within a quartet creates intentional pairing
between effect levels but does not share randomness across the 300 null indicators.

Every quartet is evaluated in full. There is no early stopping based on a partial
p-value, partial rejection count, power curve, or localization result.

## 4. Rejection convention

The rejection rule is frozen as:

```text
p = (1 + count(T_null >= T_observed)) / 5000
reject if p <= 0.05
```

At `B = 4999`, writing the exceedance count as `k`, this rejects when `k <= 249`.
That includes 250 of the 5,000 possible rank positions and preserves the intended
nominal cutoff. This arithmetic does not prove exact 5% size for the deployed
procedure or for the control construction.

The comparison remains one-sided upper, ties remain in the numerator through `>=`,
and the plus-one correction remains mandatory. No alternative rejection convention
may be selected after results exist.

## 5. Calibration seed hierarchy

The calibration root is domain-separated from the deployment entropy
`inference.rng_seed = 20260728`. Its derivation is frozen exactly as follows:

```text
label       = MNQ ATLAS Phase 10 Test 9 randomized controls rev1
encoding    = UTF-8
SHA-256     = 05b25e58157921b96cd8f84fee78fe2a533f533fce496b4f72136412c55ac537
byte order  = big-endian
uint32 root = (95575640, 360260025, 1826158671, 4000906794,
               1396659007, 3460918095, 1913873426, 3311060279)
```

The future implementation must assert the label, digest, byte order, and complete
eight-word tuple exactly. None may be supplied through a CLI flag, environment
variable, configuration file, or caller override.

The spawn hierarchy is frozen as follows, using zero-based indices:

```text
calibration_root = numpy.random.SeedSequence(uint32_root)
replication_roots = calibration_root.spawn(300)

for replication r in 0..299:
    control_child, ensemble_root = replication_roots[r].spawn(2)
    control_rng = numpy.random.Generator(numpy.random.PCG64(control_child))
    internal_children = ensemble_root.spawn(4999)
    internal_rng[b] = numpy.random.Generator(
        numpy.random.PCG64(internal_children[b])
    ) for b in 0..4998
```

`control_rng` generates the quartet's one outer control mapping. Internal child `b`
generates the quartet's joint internal mapping `b`, used identically for the null,
weak, medium, and strong members. No separate RNG child serves an effect level:
effect magnitudes and application masks are deterministic. Resumption reconstructs
children from the frozen root and the `(replication, role, internal_index)` stream
coordinates; it never advances a shared mutable root according to completion order.

The exact root tuple must be pinned by a deterministic unit test before any evidence
run. `default_rng`, bare-integer construction, or a non-PCG64 generator is forbidden.
Separate roots make the streams domain-separated and reproducible; they do not make
a collision between an outer control mapping and an internal mapping impossible.
Such a collision is allowed and is not redrawn.

## 6. Planted effects

The planted cells are:

```text
(morning, high)
(midday, high)
(afternoon, high)
```

They form one rook-connected vertical chain in the high-volatility column of the
frozen five-by-three phase-by-volatility lattice. The same intervention is evaluated
separately in each frozen weighting plane. The expected planted region sign is
positive.

The three magnitudes are fixed in raw integer ticks:

| Effect level | Added downward-excursion ticks |
|---|---:|
| weak | 10 |
| medium | 30 |
| strong | 60 |

For `vol_effect_given_phase`, the target volatility cell is excluded from its
same-phase baseline by `mnq_lab/phase8/contrasts.py`. Therefore, when all eligible
observations in a target cell receive a uniform shift `delta`, its raw target-minus-
baseline contrast moves by exactly `delta`. No stronger claim is made.

The ladder is not justified by the previously disclosed 34-tick holiday-adjacent
diagnostic; that comparison concerns a different estimand and using it would be
outcome-informed tuning. Whether 10, 30, and 60 ticks span a useful detectable range
is itself a preregistered finding and an accepted design risk. The magnitudes may not
be changed after the calibration begins merely because the resulting curve is
uninteresting.

## 7. Intervention semantics and invariants

For each replication, completion, structural-fit, and control-assigned state-validity
masks are frozen before any effect is planted. The intervention is then applied to a
copy of the already-floored `downward_excursion_ticks` anchor-outcome array, before
weighted-outcome preparation or surface evaluation.

The modification mask is exactly the conjunction of:

- control-assigned volatility state equals canonical `high`;
- phase is `morning`, `midday`, or `afternoon`;
- recipient `outcome_valid` is true; and
- control-assigned `state_valid` is true.

The canonical state-name mapping must be reused; a new numeric encoding for `high`
must not be invented. The structural-fit mask remains unchanged and continues to
enter the existing completion diagnostic exactly as it does for the null member.

The following must be asserted before and after each intervention:

- `outcome_valid`, `window_fits_rth`, control-assigned `state_valid`, session ids,
  phases, calendar years, and calendar quarters are byte-identical;
- no invalid anchor becomes valid and no incomplete anchor is repaired;
- the original control outcome array and the frozen corpus remain unchanged;
- only the copied outcome values selected by the modification mask change;
- every selected value changes by exactly the declared magnitude; and
- every one of the three target cells has at least one eligible selected observation
  in every represented calendar year. Failure of the last condition halts rather
  than silently changing the stability multiplier for reasons unrelated to effect
  magnitude.

The addition is performed in `int64`. The runner asserts that every changed result is
nonnegative and no larger than the `int32` maximum, then casts the complete copied
array back to `int32`. Direct `int32` addition is forbidden. A positive 10-tick shift
does not reapply or interact with the zero floor because this is an intervention on
the already-floored anchor outcome, not a synthetic market-price path.

Every eligible target observation is shifted. Selecting observations at or near the
empirical q90 would be prohibited tailoring. Weak, medium, and strong are each rebuilt
from the unchanged null-control outcome copy; effects are never accumulated as weak
to medium to strong.

## 8. Localization

Localization is evaluated for each weak, medium, and strong replication only after
the full formal rejection event has been determined. The planted target set is the
three phase-state cells above; weighting-plane identity is not part of that target
set.

For a rejected result, co-maximal regions are exactly those members of
`SurfaceStatistic.regions` whose own statistic equals `SurfaceStatistic.value` by
exact floating equality. No tolerance is used. A co-maximal negative region has
overlap zero because the expected planted sign is positive. A positive co-maximal
region has Jaccard overlap

```text
|region cells intersect planted cells| / |region cells union planted cells|.
```

The replication's localization value is the arithmetic mean over all co-maximal
regions, including zero contributions from wrong-sign co-maximal regions. It never
takes the best overlap among ties. A non-rejection scores zero. A rejection with no
regions scores zero. Mean localization for each effect level is calculated over all
300 replications, including every zero.

The runner must fail closed if a reported positive statistic has no exactly matching
co-maximal region, because that would indicate inconsistent retained-region state.
No winner selection, favorable tie resolution, or post-result tolerance is allowed.

## 9. Calibration gate and interpretation

The null gate uses 300 replications at nominal alpha 0.05. Its acceptance band is
frozen at 8 through 23 rejection events, inclusive. The exact probability that a
`Binomial(300, 0.05)` variable lies in this band is `0.96719`, not 0.95. The band is
never widened or shifted after a run.

Ties and the non-exact control construction mean the actual null count is not
guaranteed to follow `Binomial(300, 0.05)`. The band is a chosen acceptance criterion,
not a theorem about this instrument. Any breach, high or low, fails the gate and
requires diagnosis. Power behavior may help describe a failure pattern but never
rescues acceptance. The gate is conjunctive.

For completeness, all existing Test 9 criteria are frozen here. For rejection
fractions in weak, medium, strong order and their two-sided 95% Wilson intervals, the
future summary gate requires:

1. the null count to be within 8 through 23, inclusive;
2. a positive least-squares slope across the three rejection fractions;
3. intervals consistent with increasing power: the medium upper endpoint is at
   least the weak lower endpoint, and the strong upper endpoint is at least the
   medium lower endpoint;
4. the strong lower endpoint to exceed the weak upper endpoint;
5. a positive least-squares slope across the three mean localization overlaps; and
6. strong mean localization overlap to exceed weak mean localization overlap.

Strict adjacent monotonicity of the rejection fractions, Wilson intervals, or
localization values is not required. All six checks must pass.

The gate has limited power to detect modest miscalibration. For a true false-alarm
rate shown below, the probability that the 8-through-23 band detects it is:

| True false-alarm rate | Detection probability |
|---:|---:|
| 2% | 74.5% |
| 3% | 32.0% |
| 6% | 9.7% |
| 7% | 27.9% |
| 8% | 53.1% |
| 10% | 89.8% |
| 15% | approximately 100% |

At the nominal 5% rate, the same band has a 3.3% false-failure probability. Detecting
a true 6% rate with 90% power would require about 5,400 replications, not 300. A pass
therefore certifies **not grossly miscalibrated**, not **correct**.

## 10. Failure accounting and deterministic resumption

A failure is classified using external evidence, never convenience.

### 10.1 Transient infrastructure failure

Confirmed host loss, spot reclaim, or externally recorded infrastructure termination
is transient. The exact unfinished replication is retried from its recorded stream
coordinates. Its RNG inputs are identical by construction; no replacement child is
drawn and the denominator remains 300.

The same stream does not by itself guarantee byte-identical scientific output across
different CPUs, NumPy builds, or execution environments. A retry must use the frozen
and recorded environment identity. If duplicate completed attempts exist, their
canonical scientific payloads, excluding timing and host telemetry, are compared by
cryptographic hash. Different bytes for the same stream coordinates halt the run as
nondeterminism; neither attempt is selected.

### 10.2 Structural failure

An engine exception, non-finite or otherwise invalid value, failed invariant,
structural status, corpus or code hash mismatch, payload-hash disagreement, or
checkpoint inconsistency is structural and halts all work for diagnosis.

An OOM or timeout is retried on the same child at most once on a verified healthy and
environment-compatible host. A repeated OOM or timeout is structural. An unknown
cause is structural until an external infrastructure record proves it transient. A
vanished process is never declared transient merely because it stopped reporting.

No replication is silently dropped, replaced, or assigned a new stream. Partial
results never reduce the declared denominator.

## 11. One-repair budget for an uninformative effect ladder

If and only if the sole failure is an uninformative power curve, the original 300
Type-I controls remain valid because the effect ladder does not touch them. A ladder
redesign reruns only the 900 power replications. It uses fresh outer base controls,
fresh internal ensembles, and a new entropy namespace declared and frozen under a
separate authorization before those runs. The original null controls are not rerun
and no fresh null-control entropy is spent.

The redesigned weak, medium, and strong members remain paired within each of 300 new
power trios, but they are not retroactively paired with the retained original null
controls. The new magnitudes may be chosen only under the separately preregistered
rule; the original failed curve remains permanently disclosed.

At most one ladder redesign is permitted. A second uninformative ladder halts Phase
10 power acceptance. This limited repair applies only when the engine, null
construction, 900-session population, `B = 4999`, rejection rule, intervention
method, and all shared code remain unchanged. A defect or semantic change in shared
machinery invalidates the retained Type-I evidence and requires all 1,200
replications to be repeated under a new authorization and entropy namespace.

## 12. Residual limitations

- Calibration is conditional on these 900 sessions and this one observed market
  history. It does not establish calibration across possible markets or every
  plausible market process.
- Calibration validates the procedure averaged over fresh internal ensembles.
  Deployment uses one preregistered ensemble derived from
  `inference.rng_seed = 20260728` and retains ordinary Monte Carlo variability
  specific to that ensemble, approximately 0.0031 in p-value units near 0.05. The
  deployment seed may never be changed because its result looks inconvenient.
- Calibration cannot detect a right-statistics-wrong-question defect such as a
  time-of-day assignment error. Exact-grid, timestamp, join, anchor-time, and mask
  invariants guard those questions structurally rather than statistically.
- A passing 300-control band has weak sensitivity to modest size distortions, as
  quantified in Section 9. Passing means not grossly miscalibrated, not correct.

## 13. Required evidence plumbing before execution

The following are prerequisites for a separately authorized calibration run. They
are declarations here, not implementations.

### 13.1 Evidence protection

The randomized evidence runner must be excluded from ordinary pytest collection in
the same fail-closed manner as other one-shot evidence. Fixed deterministic tests may
exercise validation and schema logic, but must not generate control mappings, run
corpus permutations, compute corpus p-values, or count corpus rejection events.

### 13.2 Deterministic parallelism and resume

For fixed inputs and stream coordinates, canonical scientific outputs must be
bit-identical across worker counts and completion orders. Work assignment is by
replication index, never by whichever worker requests randomness next. Resume
reconstructs stream children from their indices. A fixed-seed before/after witness
must compare serial, parallel, interrupted, and resumed execution.

The future implementation must distinguish reproducible RNG input from cross-host
floating-point reproducibility. Environment compatibility and duplicate-payload hash
checks remain mandatory when work is split across machines.

### 13.3 Atomic checkpoints

A completed replication is first written to a temporary, validated, canonical
payload. The payload is durably committed by atomic rename before one atomic
checkpoint transition marks that exact child complete and records its payload hash.
A crash must not leave a child recorded complete without its validated payload, nor
silently leave a committed result classified as unfinished. Recovery reconciles
payload hashes and checkpoint state and halts on ambiguity; it never chooses between
conflicting outputs.

### 13.4 Per-replication result schema

Each replication record must include at least:

- replication index and the complete root label/digest plus SeedSequence spawn keys;
- member identity (`null`, `weak`, `medium`, or `strong`) and effect magnitude;
- completion state and attempt lineage;
- `B`, rejection rule, formal population identity, and weighting-plane inventory;
- p-value and rejection event for each quartet member;
- observed statistic, retained regions, exact co-maximal regions, and localization
  overlap for each effect member;
- structural statuses and classified failures;
- canonical scientific-payload hash; and
- code, package, corpus, environment, and worker-configuration identities.

Operational timing and host telemetry are recorded separately from the canonical
scientific payload so they cannot make an otherwise identical retry hash differently.
No minimum p-value across members, surfaces, or replications is computed or reported.

### 13.5 Environment identity

Every worker must verify and record the repository commit, dirty-state status, Python
and NumPy versions, installed-package lock hash, operating system and architecture,
CPU identity, Phase 10 source hashes, constants hash, canonical corpus manifest and
column hashes, 900-session reconciliation, worker count, process/thread settings,
and the calibration seed label/digest. A mismatch fails closed before scientific
work begins.

### 13.6 Cost-only parallel benchmark

Before evidence is authorized, the completed runner must undergo a cost-only
parallel scaling benchmark at representative worker counts and on each intended host
class. Core count is not assumed to equal speedup. The benchmark may report only
wall seconds, CPU seconds, memory bytes, rows, worker utilization, and temporary
output bytes. It must discard scientific outputs, p-values, rejection events, and
regions in a `finally` cleanup outside the repository. Its revised projection, not
the current single-process core-hour estimate, governs rental planning.

## 14. Implementation preconditions and frozen clarifications

The design above is implementable, but the current Phase 10 public API does not yet
support it. `spawn_session_mappings()` and `evaluate_null_surfaces()` consume the
deployment root internally, so calling the existing path unchanged would reuse the
deployment ensemble and violate Sections 3 and 5. A future, separately authorized
calibration implementation must add a Phase 10 calibration-specific path that accepts
only internally derived SeedSequence children while leaving the deployment seed and
formal path unchanged. Calibration entropy must not become a public override of the
formal test.

Three clarifications are load-bearing:

1. Same-child retry fixes stochastic inputs but is not automatically bit-identical
   across heterogeneous execution environments. Section 10 therefore freezes
   environment compatibility and payload-hash comparison rather than making an
   unsupported portability claim.
2. The null band alone is not the whole Test 9 gate. Section 9 freezes all six
   already-declared null, power, and localization checks and preserves their loose,
   non-strict-monotonic interpretation.
3. Planting in every represented year is enforced per target cell. Missing eligible
   support in any target-cell/year combination is structural failure, not a silently
   weakened intervention.

No item in Sections 2 through 13 is known to be statistically contradictory or
unimplementable subject to these preconditions. Implementation, benchmarking, and
evidence execution remain separately authorized future work.
