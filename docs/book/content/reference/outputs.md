# Reading outputs

The exact file layout is stage-managed, but the following fields are especially important when interpreting the final model. Stage numbers refer to the [17-stage pipeline](../workflow/end_to_end.md).

## Canonical and classified places (stages 1–5)

The published `pois.parquet` holds the classified handoff used by the run. Look for stable identifiers, canonical/source names, source IDs, matching diagnostics (`match_distance_m`, `match_name_score`), PSIC fields, economy code, and provenance/license columns. Further fields record the evidence of stages 3–5:

- `admin_activity_status`, `admin_activity_reason`, `admin_original_psic` — the administrative-office rule (stage 3);
- `io240_code`, `io80_code`, `io16_code`, their `*_status` and `*_source`, and `io_mapping_provisional` — IO tags (stage 4);
- `institution_promotion_status`, `institution_evidence_basis`, `institution_evidence_reference`, `institution_evidence_source_urls`, `institution_baseline_conflict`, `ownership_side`, `ownership_reason` — ownership evidence (stage 4);
- `economy_status`, `economy_evidence`, `economy_evidence_flags`, `economy_review_required`, `economy_candidate_io240`, `economy_candidate_local_sectors` — sector assignment (stage 5).

## Attributes from augmented sources

When `sigma augment` has been used, inspect `aug_<source>__<column>` fields in the loaded GeoParquet for original user attributes (for example, `aug_company_registry__employees`, `aug_company_registry__io240`). Matching retains the existing `canonical_id` and OSM/Overture provenance; unmatched source rows receive deterministic identifiers. `augment_io_code` and `augment_tag_source` identify additional manual classification evidence. `places/augmentations.json` records which source inputs have been applied and their hashes.

These source attributes are retained for future analyses but are not automatically included in clustering or SIGMA scores. See [Augment user-provided places](../methods/augmentation.md).

## Baseline and rolled-up sector provenance (stage 9)

For an iterative hierarchical roll-up, distinguish the **original sector code** (`original_economy_code`) from the **effective sector code** (`economy_code`, exported as `type` for X membership). The first records the original classified industry; the second is the coarser sector actually used for HDBSCAN*, IO aggregation, X connectivity, centrality, and scoring. `rollup_iteration` records the round in which a place moved, and `rollup_audit.json` in the derived package records every tested and accepted merge. The roll-up's economy ID identifies the derived catalog rather than reusing the baseline catalog. One parent X sector may contain multiple original industries; there are no child-level X nodes or child SIGMA scores.

In the local Explorer, sector metadata can include `rollup_children`, with original code, label and classified establishment count. Per-point `original_type` (or a validated compact `original_type_overrides` metadata map for existing tiles) controls independent child-point visibility and the fixed child color. Effective `type` remains unchanged. Public bundles do not include per-establishment records. UI-only and metadata-only updates to an existing Explorer do not recompute or rewrite analytical outputs, and they do not replace existing tile data.

## Clusters (stages 8–10)

Key audit fields include:

- `type`, `cluster`;
- HDBSCAN membership;
- network component;
- point-to-network snap distance; and
- adaptive clustering summary/trace metadata.

Noise rows are not passed into cluster-center calculation.

For the canonical Gap-refined run, `spatial.clusters` retains the original
`hdbscan_cluster` and the effective final `cluster` used for X nodes, alongside
`median_gap_audit.json` in the **immutable clustering artifact**. The audit
records original sector/cluster, observations and sampled observations,
chosen `selected_k`, one-SE or `upper_bound_reached` outcome, selected
observed-node medoids, and final child cluster IDs. A selected `k=1`
means no refinement; `upper_bound_reached` means the search bound was hit,
**not** that unlimited subdivision is justified. The full list of outcomes is
in {ref}`Gap refinement <outcomes-and-audit>`. The method runs **once**
per original retained cluster, by default with **up to four workers**; HDBSCAN
noise remains noise. This audit is an analytical artifact, not necessarily
included in the browser Explorer bundle. Do not treat the browser's
worked examples as a substitute for the run-specific audit.

## Centers (stage 11)

`center_method` distinguishes the primary `network_1_median` from the centroid-road-snap fallback. `median_objective` is meaningful for the primary method.

## Partitions (stage 12)

The fields below are not in the published partition files; they are in `partition_diagnostics.json` of the `spatial.partitions` artifact. There, `surface_method` distinguishes `network_voronoi` from `euclidean_voronoi_fallback`, and `surface_resolution` records the grid spacing of the surface that was kept: the finest valid network grid, so a sector that converged at its first comparison reports 25 m rather than the 50 m start. Its `events` list records, for each sector, whether the spacing converged, was limited by the cell budget or by the refinement limit, or fell back; a non-empty list is normal. See {ref}`Voronoi diagnostics <voronoi-spacing-audit>`.

## Economic graph (stage 13)

Each positive directed edge should be interpretable as a technical coefficient from supplier type to user type. If preprocessing is enabled, inspect the effective transaction table and RAS diagnostics before interpreting coefficients.

## X graph (stage 14)

An X edge carries:

- source/target economic type and spatial cluster;
- `technical_coefficient` from the positive directed economic graph;
- `road_distance`, the actual shortest road separation of the two 1-medians;
- `effective_road_distance`, the center distance plus each cluster's **mean** member-to-median road distance;
- optional center-to-center geographical route **only in explicit precomputed export mode**; the numerical X artifact and default browser export have no stored per-edge route geometry; and
- `edge_weight = technical_coefficient * source_cluster_sector_share * target_cluster_sector_share / max(effective_road_distance_metres, 1) ** x_distance_decay_lambda` (default exponent 1).

The sector-share denominator counts only retained **clustered** establishments
of the same exact sector, not all classified establishments. Neither Voronoi
overlap area nor total establishment count is directly multiplied into the
edge weight. Disconnected spatial candidates are logged separately.

Canonical `analysis.x` is numerical-only: `x_nodes.csv` and `x_edges.csv`
contain the authoritative node and edge attributes. The
`x_paths.parquet` in the analytical artifact is an **empty** GeoParquet
placeholder; route geometry is not part of the numerical pipeline. The published `sigma_X_edges.csv` holds the current weights.

At `export.bundle`, `--route-geometry browser` (default) writes
`sigma_routing_graph.bin` and `routing_node` in `sigma_X_nodes.csv`.
Explorer's Web Worker reconstructs route geometries on demand and verifies
route lengths against `road_distance`; the published GeoPackage `paths`
layer is empty. With explicit `--route-geometry precomputed`, export builds
center-to-center shortest-path geometries and fills `paths`. Both modes use
the same numerical X values and SIGMA scores. See [Route publication](../methods/routing.md).

## Centrality (stages 15–16)

For canonical Katz, retain all three quantities when possible:

- `katz_in_raw`;
- `katz_out_raw`; and
- normalized `centrality`.

The two raw components explain *why* a node is balanced or unbalanced as receiver and sender; the final scalar alone cannot show that distinction.

## Point score (stage 17)

Useful columns are:

- `cluster_centrality`;
- road distance to cluster median;
- cluster distance p90;
- normalized cluster distance;
- `distance_tempering`; and
- `sigma_score`.

## Explore published results in a browser

`SIGMA Explorer` visualizes the published `sigma_points.parquet`, the cluster polygons in `sigma_spatial_outputs.gpkg`, the `sigma_X_nodes.csv`/`sigma_X_edges.csv` network, and either `sigma_routing_graph.bin` (default) or the GeoPackage `paths` layer (precomputed mode) for routes. Launch it with `sigma view AREA` after the corresponding SIGMA run. A derived `explorer/` directory stores browser-ready data without modifying the analytical files. `sigma export-web AREA --public` creates a reduced-data `explorer-public/` bundle for **review**, not automatically safe public release.

A selected establishment is mapped to its `(type, cluster)` X node; edges are cluster-to-cluster modeled spatial-economic relationships, not confirmed individual buyer–supplier transactions. The browser graph and the QGIS project are complementary ways to inspect the same results. See [SIGMA Explorer](../intro/explorer.md).
