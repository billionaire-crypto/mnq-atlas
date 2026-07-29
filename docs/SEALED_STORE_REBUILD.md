# The sealed Phase 1–4 store and scientific reconstruction

The canonical `data/` store is a sealed, one-time artifact built before the
Phase 3 completion thresholds were added to `analysis_constants_v1.yaml`. Its
manifests truthfully retain the exact YAML bytes and environment fingerprint
used at build time.

This creates an intentional distinction:

```text
build-time YAML SHA-256
3f5c4bd5258eeb306d76d45aa4ad568a2483f007415e7d11df89ebbc8c4b182a

current audited YAML SHA-256
1c95aa595c30c48b853303291a7dbaabceaf5b7331bca565a30863e8dcf138d4
```

The current YAML adds only the three Phase 3 thresholds, but `build_id` hashes
the complete constants file. Running `mnq_lab.spine.build` directly at the
current commit therefore creates scientifically identical arrays with a new
`build_id` and manifest hash. Such a build is a new provenance artifact; it is
not a byte-level reconstruction of the sealed store, and the tests that pin
sealed provenance are expected to reject it.

Do not weaken those tests, rewrite the canonical manifests, or replace the old
manifest hash with the current YAML hash.

The observed current-YAML rebuild is rejected by three intentional pins:

- `test_frozen_file_hashes_track_build_input_and_authorized_yaml`, because the
  rebuilt manifest records the current rather than historical YAML hash;
- `test_real_store_population_provenance_and_flags_are_exact`, because the
  rebuilt manifest has a different identity;
- `test_ledger_artifact_provenance_matches_generated_bytes`, because S00 embeds
  that manifest identity and no longer matches the frozen ledger artifact.

## Why exact artifact regeneration is not claimed

The sealed exploration manifest records:

```text
branch  phase-1-spine
commit  8c84570bcb76f2f18b3b18fbd55b464e247ad729
dirty   true
```

The manifest hash covers that environment fingerprint. Git preserves the named
commit but not the uncommitted source state represented by `dirty=true`.
Therefore the repository and source CSV are sufficient to reconstruct the
scientific arrays, completion cells, and thresholds, but they are not sufficient
to certify byte-identical regeneration of the original manifest or S00 artifact.

Preserve and back up the sealed `data/` artifact. If it is lost, a scientifically
equivalent store can be rebuilt, but its new manifest identity must remain
honest. Do not edit the rebuilt manifest to impersonate the lost sealed bytes.

## Normal validation

When the sealed `data/` directory is present, validate it rather than rebuilding
it:

```powershell
python -m pytest tests -q
python -m mnq_lab.spine.gates --store data
python -m mnq_lab.outcomes.completion --store data
python -m mnq_lab.outcomes.s00 --store data
```

## Scientific reconstruction in a disposable clone

Never perform this procedure in the canonical working repository. Use a
disposable clone with sufficient disk space and the original source/reference
files available at the paths recorded in `CLAUDE.md`.

The audited Phase 4 closeout commit is:

```text
edf0a0129d43c03cc94e77ba64abc9ef2c639667
```

The Phase 3 authorization commit immediately before the YAML threshold insertion
is:

```text
f8238ea1d98c3b2c3ddabd0ec3ac2620d128340a
```

In the disposable clone:

```powershell
git switch --detach edf0a0129d43c03cc94e77ba64abc9ef2c639667

# Restore the exact constants bytes used for the original build_id.
git restore --source=f8238ea1d98c3b2c3ddabd0ec3ac2620d128340a -- analysis_constants_v1.yaml

$oldHash = (Get-FileHash -Algorithm SHA256 analysis_constants_v1.yaml).Hash.ToLowerInvariant()
if ($oldHash -ne "3f5c4bd5258eeb306d76d45aa4ad568a2483f007415e7d11df89ebbc8c4b182a") {
    throw "historical build-time YAML hash mismatch: $oldHash"
}

python -m mnq_lab.spine.build `
  --source-csv "C:\Users\kyawz\Downloads\GLBX-20260331-885WT5W7KA\glbx-mdp3-20100606-20260329.ohlcv-1m.csv" `
  --out data

# Restore the audited current YAML before running Phase 3+ validation.
git restore --source=edf0a0129d43c03cc94e77ba64abc9ef2c639667 -- analysis_constants_v1.yaml

$currentHash = (Get-FileHash -Algorithm SHA256 analysis_constants_v1.yaml).Hash.ToLowerInvariant()
if ($currentHash -ne "1c95aa595c30c48b853303291a7dbaabceaf5b7331bca565a30863e8dcf138d4") {
    throw "current audited YAML hash mismatch: $currentHash"
}

python -m mnq_lab.spine.gates --store data
python -m mnq_lab.outcomes.completion --store data
python -m mnq_lab.outcomes.s00 --store data
```

Expected scientific reconstruction:

```text
build_id          0ad7843647f17258
pipeline_version  spine-1.0.0
source rows       3,665,228
exploration rows  274,847
exploration       1,009 sessions
gridpoints        78,702
thresholds        h15 0.99, h30 0.99, h60 0.98
```

The historical YAML must be present only while building. Tests and S00 must run
after restoring the current audited YAML so that ledger/YAML validation remains
active. The reconstructed arrays and threshold inputs should match, but the
manifest and S00 artifact hashes are not expected to equal the sealed hashes
unless the original complete environment fingerprint and dirty source state are
also reproduced. The pinned provenance tests may therefore reject a scientifically
equivalent reconstruction; that is their intended behavior.

## Building a new provenance version

A build made intentionally with the current or a future constants file is not a
repair of the sealed Phase 1–4 store. Treat it as a new versioned input:

- write it outside the canonical `data/` directory;
- retain its new `build_id` and manifest hashes;
- do not compare or concatenate it with the sealed store as if they shared one
  data definition;
- obtain the required ledger/version authorization before any affected result is
  computed.

The red-team audit independently confirmed that a current-YAML rebuild preserves
the scientific arrays and all 15 completion cells while changing provenance.
That is expected behavior, not permission to overwrite the sealed artifact.
