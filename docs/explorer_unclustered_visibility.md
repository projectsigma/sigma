# All-sector Explorer visibility (local profile)

Explorer shows every sector of the area and, on request, the establishments that have a sector but no cluster. This is **packaging and display only**: no classifier, IO crosswalk, economic transaction, spatial clustering, or X network is affected.

## What the map shows

- **Scored establishments** are score-sized filled circles with actual HDBSCAN/X-node membership (stages 8–10 and 17). Hover and click behavior is the same for all of them.
- **Unclustered establishments** appear in a *separate opt-in symbol layer*, shown as hollow **circles**. They are establishments of `output/pois.parquet` that are absent from `output/sigma_points.parquet`: they have an effective economic sector but no HDBSCAN cluster ID, no X link and no SIGMA score. Their original tag may differ from the effective roll-up parent (stage 9). Hollow circle radius follows the minimum published scored point of its own effective sector, with a global-minimum fallback for zero-cluster sectors.
- **Sector panel**: all sectors of the matching generated hierarchical economy, including sectors with zero classified establishments (count `0`, no points on the map). The sector list does not imply that every establishment of a sector is clustered.
- With no X node selected, **Show unclustered for scored sectors** independently shows all eligible unclustered places in sectors that have qualifying clusters, as hollow circles. When an X node is selected, that same checkbox shows only unclustered places geographically contained inside the **highlighted focus and linked Voronoi partitions**, respecting sector identity. Changing depth, direction, strongest links or sector visibility updates this display subset. **Show unscored sectors** independently reveals classified places belonging to zero-cluster sectors only while no scored X node is selected. Neither checkbox assigns a score, X membership or a synthetic cluster.
- In expanded rolled-up sectors, original industries have independent point-layer checkboxes and keep their colors from the fixed 336-color palette.
- After a scored selection, hovering a cluster-center triangle outlines its *published* partition boundary in its sector color. Neither geographic containment nor hover creates a cluster score.
- **Downstream score metrics** are never synthesized, interpolated or inferred.
- **PSIC labels**: local point tiles include both PSIC code and title, using an explicit source label first and then the bundled Rev. 5 taxonomy. Unknown codes remain without a title; no classification is inferred.
- **Public profile**: establishment-level locations, these layers and the local finder are disabled.

## Safety

`pois.parquet` is used only if it is listed in the current `sigma_manifest.json` when one exists, and its byte hash is checked against that manifest. The scored and classified inputs must agree for every scored canonical ID and economic sector. The local economy catalog must belong to the exact workspace/output, and its economy ID must match `sigma_run_metadata.json`. The Explorer's source fingerprint includes the classified inputs and economy catalog hashes, so changes force regeneration rather than a stale tile reuse.

No unassigned PSIC/IO candidates are promoted to a sector. A location classified under an economic sector but not clustered is not represented as a cluster.

## Checks

```powershell
python -m pytest -q tests/test_web_unclustered.py
python -m pytest -q tests/test_web_explorer.py
node --check src/sigma/web/static/app.js
sigma view quezon_city --refresh
```

Existing Explorer output is replaced only through its normal safe, staging-and-swap build path. Counts of sectors, scored clusters and unclustered points depend on the area and the run; read them from the current published files.

## Notes

`pois.parquet` is an optional published file. Public or synthetic bundles without the classified handoff show only scored establishments. Workspaces with a hierarchical model but no matching economy catalog fail explicitly rather than claiming that the scored subset is complete. The matching hierarchy is not rebuilt or altered.
