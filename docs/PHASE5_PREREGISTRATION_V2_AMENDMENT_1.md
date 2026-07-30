# Phase 5 Preregistration V2 — Amendment 1

**User ruling date:** 2026-07-30

**Authority:** This amendment is authorized by the user's 2026-07-30 ruling
under the pre-agreed Amendment P5-2 failure clause.

## Scope

This amendment supersedes exactly one line of
`docs/PHASE5_PREREGISTRATION_V2.md`: the calibration command in Section D,
item 7.

The superseded command is:

```text
python tools/phase5_coverage_calibration.py
```

The corrected command is:

```text
python -m tools.phase5_coverage_calibration
```

The corrected command is run from `C:\mnq-atlas`, exactly once.

## Deterministic launch defect

The superseded script-path launch placed `C:\mnq-atlas\tools` on
`sys.path[0]`, not the repository root. `mnq_lab` is not installed and
resolves only from the repository root, so the runner's import of `mnq_lab`
failed before `main()`. No `SeedSequence` or Generator was constructed, no
replication ran, and no registered entropy was consumed.

The runner bytes are unchanged at SHA-256
`f383ae3268772e522ee9e4b0ba1e6df6c900749e27042badcf8d86a154cddef1`.
Consequently, the seed schedule, DGP, replication count, statistic, interval,
and evidence contract are identical. The module-form launch changes only
module resolution and does not affect the resulting `K`.

Every other v2 parameter remains binding and unmodified. Neither
`docs/PHASE5_PREREGISTRATION.md` nor
`docs/PHASE5_PREREGISTRATION_V2.md` is edited.

The two pytest commands at v2 lines 222 and 231 are unaffected because pytest
prepends its root directory to the import path.
