---
name: spec-check
description: Use before implementing any rule that cites the frozen spec, or when tempted to state a fact about the data. Forces the claim to be verified against analysis_constants_v1.yaml and the actual dataset rather than recalled.
---

# Spec check

The recurring defect in six adversarial review rounds of this spec was **a fluent claim
stronger than its mechanism**. Every one was caught by running a query, never by
re-reading prose. This skill is the query step.

## Before you implement a rule

1. **Find the constant in `analysis_constants_v1.yaml`.** Not in the spec prose, not in
   your memory of the prompt — the YAML. If it is not there, the study must refuse to
   run. Do not invent a default and do not inline a literal.

2. **Quote the spec section number** in a comment beside the code that implements it.

3. **Check §14 (STRUCK).** If the rule you are about to write appears in the struck
   table, you are implementing a revision 1–5 rule. Stop and use the replacement.

## Before you state a fact about the data

Classify the claim's provenance, out loud, as one of:

| Provenance | Meaning | Allowed to assert? |
|---|---|---|
| given | in the frozen spec or YAML | yes, cite the section |
| computed | you ran a query this session | yes, show the number |
| retrieved | read from a manifest or fixture | yes, name the file |
| **generated from priors** | it sounds right | **no — check it or cut it** |

The last bucket feels identical to the others from the inside. That is where hallucination
lives. "Consistent with" is not "confirmed by": when evidence only fails to rule something
out, say exactly that.

## Claims in this project that are checkable, and how

| Claim | Query |
|---|---|
| `ts_event` is bar open | maintenance window: last label before 16:00 CT is 15:59, none in [16:00,17:00), first is 17:00 |
| RTH is [08:30, 15:00) CT | volume by minute-of-day; look for the 5× jump at 08:30 |
| roll fixture is 28 rolls | `len(manifest["rolls"])` |
| symbol split | full `value_counts()` over the symbol column — never a percentage |
| prices are exact ticks | `(price * 4) % 1 == 0` over every row, not a sample |
| no zero-volume rows | `(volume == 0).sum()` — and note this does **not** establish the vendor's generation rule |

## The test question

After writing a test, ask: **can this fail?** Construct the input that should break it and
confirm it breaks. A check that cannot fail is worse than no check — the LoRA experiment
preceding this project shipped a canary whose pass threshold was negative, so a fully
collapsed representation satisfied it.
