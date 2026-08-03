# MNQ Atlas Memory Ceiling V2 Preregistration

**Program:** `mnq-atlas-001`
**Specification:** `REV6_FROZEN_SPEC.md`, revision 6
**Decision date:** 2026-08-02
**Base:** `4f185eab998f33f64ae6705fbc494cd6e3e9f327`
**Branch:** `phase-7b-outcome-layer`
**Status:** user-ratified prospective memory-safety supersession

## 1. Scope and precedence

This document supersedes only the numeric process-memory ceiling in section 9
of `docs/DEPENDENCY_REPRESENTATION_PREREGISTRATION.md`. The new ceiling is:

```text
6,442,450,944 bytes = 6 GiB
```

It applies to any single production run in this program. Any downstream
restatement of the section 9 numeric threshold, including the section 12 gate
that refers to the bounded concurrent projection, is read with this 6 GiB
number. No other condition is superseded.

Everything else in section 9 remains unchanged. In particular:

- both bounded doubling ratios must remain no greater than `2.4`;
- no row may own or cache a private expanded dependency tuple;
- memory may not be reduced by discarding, hashing, approximating, or lazily
  inferring dependency membership;
- the projection remains inferred and its model must be disclosed;
- uncertainty about every concurrently live table still fails closed; and
- the corpus may not be run merely to resolve a failed or incomplete bounded
  memory model.

The superseded preregistration remains byte-pinned and must not be edited. This
document changes no frozen section 4 value and no value in
`analysis_constants_v1.yaml`. It changes only a prospective runtime resource
guard and therefore requires no threshold-freeze ledger entry.

## 2. Prospective 6 GiB ceiling

The fixed peak-process-working-set ceiling is exactly 6,442,450,944 bytes.
Every existing stage-boundary checkpoint remains fail-closed. A peak reading
equal to the ceiling passes; a reading of 6,442,450,945 bytes raises and names
the stage. There is no warning-only path, placeholder, zero, fallback, or
exception suppression.

This is a prospective raise. The column-at-a-time implementation already
passes the original 2 GiB ceiling: its conservative exploration projection is
1,998,931,999 bytes, or approximately 1.862 GiB. The ceiling is not being
raised to rescue a failing implementation or a failing measurement. It is
being raised before the run it governs and before any confirmation-tier
measurement, to cover the larger programme corpus and avoid a mid-programme
amendment.

## 3. Quantitative basis

The machine has 15.92 GiB of physical memory. A 6 GiB ceiling is approximately
38 percent of that total.

The exploration corpus contains 1,009 sessions. The conservative projection
for the complete Phase 7 plus Unit O run shape is approximately 1.862 GiB.
The full available source span through 2026-03-29 is approximately 1,786
sessions, about 1.77 times the exploration session count. Applying that factor
to the conservative exploration projection gives a programme-scale projection
of roughly 3.3 GiB.

The 6 GiB ceiling therefore provides approximately:

- 3.2 times the exploration projection; and
- 1.8 times the approximate full-span projection.

It still rejects a threefold exploration regression: three times 1.862 GiB is
approximately 5.586 GiB before normal measurement variation, and any observed
peak above the exact 6 GiB boundary fails at the next checkpoint.

These figures justify a fixed resource envelope. They do not authorize a
change to any scientific value, evidence form, artifact field, schema, dtype,
column width, or row order.

## 4. Largest-corpus projection rule

Every future memory acceptance decision must project at the largest corpus the
particular run will process, not merely at the current exploration corpus.
The report must state the largest session count, the bounded observations, the
projection model, and every concurrently live table included in that model.

This rule corrects the specific defect in the original figure. The original
2 GiB proposal was justified using a model that omitted artifact serialization
and considered only the exploration corpus. That incomplete model understated
the production memory lifetime. A projection that omits artifact writing,
validation, Unit O, or a larger authorized corpus is not an acceptance test and
must fail closed as incomplete.

The bounded `N=100,200,400` full-shape probe remains required. Its ratio rule
does not change. The projection target changes only from the superseded 2 GiB
number to the exact 6 GiB ceiling fixed here.

## 5. Free-physical-memory preflight

Before opening the source store or beginning any expensive work, the production
entry point must read current free physical memory. It must refuse to start
unless at least:

```text
4,294,967,296 bytes = 4 GiB
```

is free. Equality passes. A reading of 4,294,967,295 bytes raises `SpineError`
and identifies the free-physical-memory preflight. The failure happens before
source-store opening, staging, Phase 7, Unit O, or finalization. The check is
fail-closed: there is no try/except continuation, warning-only path, fallback,
or substituted estimate.

The floor and ceiling serve different purposes. The 4 GiB free-memory floor
prevents a production run from beginning on a loaded machine. The 6 GiB peak
ceiling detects runaway growth after a run begins. The floor is deliberately
lower than the ceiling because it measures the machine's available headroom at
launch rather than the process's permitted peak over its lifetime.

At the time of this decision, the machine snapshot recorded 12.55 GiB in use
and 3.37 GiB free. That snapshot would be rejected by the new preflight. An
earlier run ended with roughly 230 MiB free because no free-memory launch gate
existed. These observations motivate the gate; they do not change its fixed
4 GiB value.

## 6. Disclosure and decision timing

The independent auditor proposed the original 2 GiB ceiling from an incomplete
model. Subsequent full-shape measurement exposed the omitted artifact lifetime,
and column-at-a-time streaming then reduced the conservative exploration
projection to 1.862 GiB, which passes the original ceiling.

The user raises the ceiling prospectively on 2026-08-02, before the production
run governed by it and before any confirmation-tier measurement. Six GiB was
selected from total physical memory, the exploration projection, and the
approximate full-span session count. It was not selected by observing a future
peak and is not set equal to a measured value.

The decision therefore does not legitimize the prohibited pattern of moving a
gate after a future result fails. A later observed curve does not authorize a
second raise.

## 7. What this document does not authorize

This document does not authorize:

- raising the ceiling again after observing a future curve;
- weakening, removing, hashing, approximating, or lazily inferring dependency
  evidence;
- allowing a row to retain a private expanded dependency tuple;
- weakening the `2.4` doubling-ratio rule;
- changing an artifact schema, dtype, fixed-width column, filename, row order,
  column order, manifest field, or serialized value;
- removing any stage-boundary peak checkpoint;
- continuing after peak-memory or free-memory telemetry fails;
- treating a completed shakedown run as admissible evidence;
- inspecting, summarizing, ranking, or contrasting outcome values; or
- executing Phase 8.

The mechanical shakedown remains non-admissible diagnostic work. Separate
authorization and the existing scientific governance continue to control every
later measurement and contrast.

## 8. Implementation and behavioural witnesses

The implementation must retain the complete column-at-a-time lifetime fix and
must change only the resource guards required here:

1. set `PEAK_MEMORY_CEILING_BYTES` to exactly 6,442,450,944;
2. retain all eight existing peak-memory checkpoints;
3. add the 4,294,967,296-byte free-memory preflight beside the peak preflight
   and before expensive work;
4. preserve exact boundary behavior for both numbers;
5. preserve full artifact raw-byte identity against the legacy all-at-once
   writer; and
6. preserve the explicit equal-column-length validation in the streaming
   writer.

Named failing inputs are load-bearing:

- peak ceiling: inject 6,442,450,945 bytes; the named stage must raise;
- free-memory floor: inject 4,294,967,295 bytes; the free-memory preflight must
  raise before the source store opens;
- telemetry failure: inject an operating-system API failure; the run must halt;
- column alignment: shorten one non-first column by one row; streaming must
  halt; and
- byte identity: perturb one serialized seasonal value; the complete raw-byte
  tree comparison must fail.

A source hash does not count as any behavioural witness. The unmutated controls
must pass, and every mutated region must be nonempty.

## 9. Authorization boundary

This document authorizes only the prospective memory-ceiling and launch-
preflight implementation described above, together with the already validated
column-at-a-time lifetime correction. It authorizes no corpus run in the
implementation step. After implementation, the authorized safe suite and an
independent focused audit must verify the change before a production run is
considered.

No outcome value may be inspected and no Phase 8 code may run under this
document.
