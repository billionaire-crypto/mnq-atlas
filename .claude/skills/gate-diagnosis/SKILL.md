---
name: gate-diagnosis
description: Use when a fail-closed gate fires, a regression test fails, or rebuilt data disagrees with a reference. Enforces the spec §16.6 stop-and-diagnose procedure instead of coding around the failure.
---

# Gate diagnosis

A gate fired. **You are not permitted to make it pass.** You are permitted to find out
why it fired and report.

## Forbidden responses

Do not do any of these, even if they look like a fix:

- lower a threshold, widen a tolerance, or add `atol`/`rtol` where the spec grants none
- pin one era to an old file while rebuilding another ("bridging two data definitions")
- add a fallback path, a try/except that proceeds, or a warning-instead-of-raise
- restrict the comparison range so the mismatching rows fall outside it
- regenerate the reference from the new code
- mark the test `xfail` or `skip`

Two data definitions in one atlas make every difference unattributable between the market
and the pipeline. That is the whole reason the gate exists.

## Procedure

1. **Locate the first mismatch.** Not a count of mismatches — the *first* one, by
   timestamp. Print the reference row and the rebuilt row side by side, plus the three
   rows before and after each.

2. **Classify the cause** into exactly one of:

   | Cause | Signature |
   |---|---|
   | roll mapping | mismatch begins at a contract boundary; `symbol` differs |
   | missing bars | rebuilt has fewer/more rows in a window; OHLCV present in one only |
   | timestamps | values match but are offset by a fixed interval, or a DST week differs |
   | aggregation | same inputs, different OHLCV — check `label`/`closed`/`origin` |
   | duplicates | a timestamp appears twice on one side |
   | source revision | the vendor file's sha256 differs from the manifest's record |

   Check the source sha256 **first** — a vendor re-issue explains everything else and
   costs one command.

3. **Establish whether it is market or pipeline.** Take the first mismatching session and
   recompute that one session by hand from the raw 1-minute rows. If the hand computation
   matches the reference, the new pipeline is wrong. If it matches the rebuild, the
   reference is stale — which is a finding, not a licence to overwrite it.

4. **Report** with: first mismatching timestamp, classification, the hand computation,
   and what you did *not* check. Then stop.

## The only two legitimate resolutions

- Reproduce the original pipeline exactly, or
- Rebuild **both** corpus tiers under a new pipeline version, with a ledger entry.

Never one tier under one definition and one under another.
