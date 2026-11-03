# Reading outputs

The exact file layout is stage-managed, but the following fields are especially important when interpreting the final model.

## Canonical and classified places

Look for stable identifiers, canonical/source names, source IDs, matching diagnostics, PSIC fields, economy code, and provenance/license columns.

<!-- sigma-augment-docs-v1:begin:outputs -->
## Attributes from augmented sources

When `sigma augment` has been used, inspect `aug_<source>__<column>` fields in the loaded GeoParquet for original user attributes (for example, `aug_company_registry__employees`, `aug_company_registry__io240`). Matching retains the existing `canonical_id` and OSM/Overture provenance; unmatched source rows receive deterministic identifiers. `augment_io_code` and `augment_tag_source` identify additional manual classification evidence. `places/augmentations.json` records which source inputs have been applied and their hashes.

These source attributes are retained for future analyses but are not automatically included in clustering or SIGMA scores. See [Augment user-provided places](../methods/augmentation.md).
<!-- sigma-augment-docs-v1:end:outputs -->

<!-- sigma-docs-20261104-v1:begin -->
## Baseline and rolled-up sector provenance

For an iterative hierarchical roll-up, distinguish the **original sector
code** (`original_economy_code`) from the **effective sector code**
(`economy_code`, exported as `type` for X membership). The first records the
original classified industry; the second is the coarse sector actually used
for HDBSCAN, IO aggregation, X connectivity, centrality, and scoring. The
roll-up's Economy ID identifies the derived catalog rather than silently
reusing the baseline catalog. One parent X sector may contain multiple
original industries; there are no child-level X nodes or child SIGMA scores.

In the local Explorer, sector metadata can include `rollup_children`, with
original code, label and classified establishment count. Per-point
`original_type` (or a validated compact `original_type_overrides` metadata
map for existing tiles) controls independent child-point visibility and the
fixed child color. Effective `type` remains unchanged. Public bundles do not
include per-establishment records. UI-only and metadata-only updates to an
existing Explorer do not recompute or rewrite analytical outputs, although
they do not automatically replace all older tile data.
<!-- sigma-docs-20261104-v1:end -->

## Clusters

Key audit fields include:

- `type`, `cluster`;
- HDBSCAN membership;
- network component;
- point-to-network snap distance; and
- adaptive clustering summary/trace metadata.

Noise rows are not passed into cluster-center calculation.

## Centers

`center_method` distinguishes the primary `network_1_median` from the centroid-road-snap fallback. `median_objective` is meaningful for the primary method.

## Partitions

`surface_method` distinguishes `network_voronoi` from `euclidean_voronoi_fallback`. `surface_resolution` records the rendering resolution actually used.

## Economic graph

Each positive directed edge should be interpretable as a technical coefficient from supplier type to user type. If preprocessing is enabled, inspect the effective transaction table and RAS diagnostics before interpreting coefficients.

## X graph

An X edge carries:

- source/target economic type and spatial cluster;
- `technical_coefficient` from the positive directed economic graph;
- `road_distance`, the actual shortest road separation of the two 1-medians;
- `effective_road_distance`, the center distance plus each cluster's **mean** member-to-median road distance;
- shortest `road_path` geometry between the centers; and
- `edge_weight = technical_coefficient * source_cluster_sector_share * target_cluster_sector_share / max(effective_road_distance_metres, 1) ** x_distance_decay_lambda` (default exponent 1).

The sector-share denominator counts only retained **clustered** establishments
of the same exact sector, not all classified establishments. Neither Voronoi
overlap area nor total establishment count is directly multiplied into the
edge weight. Disconnected spatial candidates are logged separately.

For an X weight-only recomputation, `analysis.x` may reuse immutable route
geometry via `x_paths.parquet` plus an overlay. Its **current numerical
attributes** are in `x_edges.csv`, and the supported `load_x()` reader
applies them. Do not treat numerical columns in a reused raw GeoParquet as
authoritative; see [The X graph](../methods/x_graph.md).

## Centrality

For canonical Katz, retain all three quantities when possible:

- `katz_in_raw`;
- `katz_out_raw`; and
- normalized `centrality`.

The two raw components explain *why* a node is balanced or unbalanced as receiver and sender; the final scalar alone cannot show that distinction.

## Point score

Useful columns are:

- `cluster_centrality`;
- road distance to cluster median;
- cluster distance p90;
- normalized cluster distance;
- `distance_tempering`; and
- `sigma_score`.

## Explore published results in a browser

`SIGMA Explorer` visualizes the published `sigma_points.parquet`, the cluster polygons and paths in `sigma_spatial_outputs.gpkg`, and the `sigma_X_nodes.csv`/`sigma_X_edges.csv` network. Launch it with `sigma view AREA` after the corresponding SIGMA run. A derived `explorer/` directory stores browser-ready data without modifying the analytical files. `sigma export-web AREA --public` creates a reduced-data `explorer-public/` bundle for **review**, not automatically safe public release.

A selected establishment is mapped to its `(type, cluster)` X node; edges are cluster-to-cluster modeled spatial-economic relationships, not confirmed individual buyer–supplier transactions. The browser graph and the QGIS project are complementary ways to inspect the same results. See [SIGMA Explorer](../intro/explorer.md).
