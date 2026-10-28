# All-sector Explorer visibility (local profile)

This patch changes **only Explorer packaging and display**. No classifier,
IO crosswalk, economic transaction, spatial clustering, or X network is changed.

- **Filled circles**: establishments with actual scored network-cluster membership.
  Existing score-proportional sizes and hover/click behavior are preserved.
- **Small hollow sector-colored circles**: valid economically assigned
  establishments in `output/pois.parquet` that are absent from
  `output/sigma_points.parquet`. They have no cluster, SIGMA score or X link.
- **Sector panel**: all sectors in the matching generated hierarchical Economy,
  even if the sector contains zero classified establishments. Empty sectors have
  a `0` count and naturally show no points on the map.
- **Downstream score metrics**: never synthesized, interpolated or inferred.
- **Public profile**: establishment-level locations and the local finder remain
  disabled. The augmentation applies to the local Explorer only.

## Safety

`pois.parquet` is used only if included in the current `sigma_manifest.json`
when one exists, and its byte hash is checked against that manifest. The scored
and classified inputs must agree for every scored canonical ID and economic
sector. The local Economy catalog must belong to the exact workspace/output
and its economy ID must match `sigma_run_metadata.json`. The Explorer's source
fingerprint includes classified inputs and Economy catalog hashes, so changes
force regeneration rather than a stale tile reuse.

No unassigned PSIC/IO candidates are promoted to a sector. A location classified
under an economic sector but not clustered is not represented as a cluster.

## Commands (PowerShell)

```powershell
cd "$HOME\Documents\Github\sigma"
conda activate sigma
python "$HOME\Downloads\sigma_explorer_all_sectors_visibility_patch.py" --repo "$PWD" --dry-run --diff "$HOME\Downloads\sigma-all-sectors.diff"
python "$HOME\Downloads\sigma_explorer_all_sectors_visibility_patch.py" --repo "$PWD" --apply
python -m pytest -q tests/test_web_unclustered.py
python -m pytest -q tests/test_web_explorer.py
node --check src/sigma/web/static/app.js
sigma view quezon_city --refresh

```

Run `sigma view quezon_city --help` to check the exact option syntax for your
installed version if needed. Existing Explorer output is replaced only through
its normal safe, staging-and-swap build path.

**Expected QC local counts from the existing audit:** 54 catalog sectors;
43 with classified establishments; 32 with scored network clusters;
approximately 51,297 classified sector-assigned points, of which 18,498
are hollow markers. Exact counts are checked from the current published files.

## Notes

`pois.parquet` is an optional published file. Existing public or synthetic
bundles without the classified handoff preserve their prior behavior.
Workspaces with a hierarchical model but no matching Economy catalog fail
explicitly rather than silently claiming that the scored subset is complete.
The matching hierarchy is not rebuilt or altered.
