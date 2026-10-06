# Reading outputs

The exact file layout is stage-managed, but the following fields are especially important when interpreting the final model.

## Canonical and classified places

Look for stable identifiers, canonical/source names, source IDs, matching diagnostics, PSIC fields, economy code, and provenance/license columns.

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

- source/target cluster node;
- `technical_coefficient`;
- `road_distance`;
- shortest `road_path`; and
- `weight = technical_coefficient * road_distance`.

Disconnected spatial candidates are logged separately.

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
