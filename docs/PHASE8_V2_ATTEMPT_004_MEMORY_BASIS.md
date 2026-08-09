# Phase 8 v2 attempt-004 memory basis

**Program:** `mnq-atlas-001`
**Decision date:** 2026-08-09
**Branch:** `phase-7b-outcome-layer`
**Status:** user-authorized prospective operational correction

## Scope

This record corrects `AGGREGATE_MEMORY_CEILING_BASIS` before a fresh Phase 8
v2 attempt. It changes no scientific formula, threshold, tolerance, bootstrap
contract, output schema, certificate, or ratification gate. It does not change
the fixed 192 GiB process-tree PSS ceiling, the 224 GiB launch minimum, the
30-second sampling cadence, the `/proc/<pid>/smaps_rollup` source, or the
fail-closed emergency stop.

It supersedes the stale v2 basis, which cited attempt-002's first 16 GiB
crossing as a Stage 1 peak even though attempt-003 subsequently crossed the
192 GiB boundary. Neither crossing establishes a plateau: the monitor stops on
the first sample above its boundary.

## Durable failed-attempt evidence

Attempt-003's external execution receipt is bound by SHA-256:

```text
5216eba31f78c15fc46978dbc15ecef984344c5130e5e52d5b3bbdfd9879d97f
```

The canonical receipt records:

- run commit `c733890c86a49130c0acf06b36200adc394ffbe5`;
- Stage 1 workers `8` and bootstrap workers `64`;
- child and wrapper exit `-15`;
- output incomplete;
- memory ceiling `206,158,430,208` bytes;
- first recorded crossing `207,103,779,840` bytes; and
- memory-stop sample count `3`.

The crossing is labelled `pss_at_stop`, not `peak`. Bootstrap was never
reached, so attempt-003 provides no evidence that 64 bootstrap workers are
safe.

## Prospective operating correction

The next attempt is fresh, never a resume, and binds:

```text
Stage 1 workers      6
bootstrap workers   32
start method         fork
```

The worker reduction is paired with the independently audited Stage 1 changes
through commits `abb55fb`, `6359458`, `557a121`, `44feb00`, and `7651891`.
Those changes hoist repeated full-array invariants, serialize PSS sampling,
deduplicate identical session-derived arrays, and bound monitor shutdown. They
change computation frequency and storage lifetime, not scientific results.

The governed Unit O manifest declares `470,340` structural rows across two
estimands and three horizons: six slices of `78,390` rows. At six workers, the
audited 75-byte-per-row retained invariant-cache payload is approximately
`35,275,500` bytes in aggregate. This is far below the cache audit's
attempt-003 breach-margin break-even and establishes that the deduplicated
cache is not itself a material memory risk for this corpus.

## Linux PSS timing witness

A read-only pod validation at commit `7651891` used six synthetic forked
workers, each holding 4 GiB of touched private memory. It created no repository
or production path and all workers exited normally.

```text
synthetic private bytes       25,769,803,776
measured process-tree PSS     25,867,137,024
PSS sample minimum seconds             0.015241635031998158
PSS sample mean seconds                0.015403398778289557
PSS sample maximum seconds             0.015742299146950245
```

This witness supports retaining the 30-second cadence and the measured,
two-window stop timeout. It is not evidence that a 192 GiB scan has the same
duration, and it is not a claim that Stage 1 will remain below the ceiling.

## Decision and limitations

The 192 GiB ceiling remains an emergency backstop rather than a calibrated
plateau multiple. It is deliberately not raised. The 224 GiB launch minimum
continues to reserve at least 32 GiB between launch capacity and the process
ceiling. Preflight must independently remeasure effective CPU capacity,
available memory, disk, process conflicts, fixed-path absence, and external
checkpoint storage immediately before launch.

Exactly one fresh invocation is authorized only after that preflight passes.
Any memory stop, evidence failure, identity mismatch, path conflict, or child
failure ends the invocation without automatic retry. A later attempt requires
new operator authorization and new evidence roots.
