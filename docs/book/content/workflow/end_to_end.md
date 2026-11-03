# End-to-end workflow

SIGMA is implemented as a dependency-aware artifact graph. The conceptual order is linear enough to teach, but execution can reuse any valid upstream artifact.

## Stage map

### Area, sources, and places

```text
area.definition ──> area.boundary

source.geofabrik_pbf ──> source.osm_national_pois
                         └─> source.osm_area_index ──┐
area.definition ────────────────────────────────────┘

source.overture_snapshot ────────────────────────────┐
area.boundary ───────────────────────────────────────┤
                                                    ▼
places.osm_area + places.overture_area + area.boundary
                         │
                         ▼
                  places.canonical
                         │
classification.taxonomy ├─> places.psic
        │                │
        └─> classification.tagging_references
                         │
                         ▼
                  places.classified
```

### Roads and spatial structure

```text
source.geofabrik_pbf + area.boundary ──> transport.roads
transport.roads + places.classified ───> spatial.points
spatial.points + transport.roads ──────> spatial.clusters
spatial.clusters ──────────────────────> spatial.centers
spatial.clusters + spatial.centers ────> spatial.point_distances
spatial.clusters + spatial.centers + area.boundary ──> spatial.partitions
```

### Economy

```text
economy.definition
      │
      ▼
economy.transactions.raw
      │
      ▼
economy.transactions.effective
      │
      ▼
economy.coefficients
      │
      └──────────────┐
                     ▼
economy.transactions.effective + economy.coefficients
                     │
                     ▼
                economy.graph
```

### Spatial-economic analysis

```text
spatial clusters + centers + partitions + point_distances + economy.graph
                         │
                         ▼
                     analysis.x
                         │
                         ▼
                 analysis.centrality
                         │
spatial.point_distances ─┘
                         │
                         ▼
                  analysis.scores
```

<!-- sigma-docs-20261104-v1:begin -->
## Hierarchical economy derivation between tagging and X construction

`places.classified` first obtains the baseline IO240/IO80/IO16 sparse
sector assignments chosen at `sigma load`. In a generated hierarchical
`SIGMA run`, HDBSCAN cluster counts reveal which sectors retain `K=0`.
The optional (default-on) iterative residual-first roll-up changes the
effective sector partition only when a valid candidate meets the positive
net-retention criterion, then regenerates the affected downstream spatial
and economic stages. The original tags persist as
`original_economy_code`; the effective IDs are used for all `(type,cluster)`
X nodes and for national IO sector aggregation. Turning off the roll-up
preserves the loaded baseline classification.

This is a **conditional dependency branch** of the analysis pipeline, not
an added establishment-to-establishment edge or an automatic nearest-center
assignment. Explorer's 336 colors, original-child toggles, contextual
unclustered overlay, and hover outlines are strictly downstream
presentation, never inputs to `analysis.x` or `analysis.scores`.
<!-- sigma-docs-20261104-v1:end -->

## Why this order matters

The workflow separates four different kinds of inference:

1. **identity inference** — deciding which source records refer to one place and which economic activity a place represents;
2. **spatial structure inference** — deciding which establishments form local road-network clusters and how territory is assigned;
3. **economic structure** — translating transactions into directed technical requirements; and
4. **spatial-economic influence** — instantiating positive directed sector relationships only where spatial cluster territories overlap and the 1-medians are road-connected; weighting each X edge by direct technical coefficients, clustered-sector shares, and mean hub-mediated road distance; then measuring directed centrality. These modeled edges are not verified local trades.

A downstream score therefore cannot be interpreted independently of the upstream choices. A centrality value summarizes a graph whose nodes already encode classification, clustering, center, and partition decisions.

<!-- sigma-augment-docs-v1:begin:workflow -->
## Optional post-load augmentation

The editable `places/places.parquet` handoff can also be augmented *after* `sigma load` using `sigma augment AREA INPUT --source SOURCE`. The augmentation is not a new upstream OSM/Overture acquisition stage: it reconciles additional observations against loaded canonical places, enriches provenance, and validates any manual IO tags. Running `sigma augment ... --check` performs a read-only preview; the subsequent `sigma run AREA` consumes the augmented handoff and refreshes stale derived hierarchy/analysis outputs. See [Augment user-provided places](../methods/augmentation.md).
<!-- sigma-augment-docs-v1:end:workflow -->

## Human review boundary

SIGMA supports a deliberate human review step after deterministic place classification. The safest review artifact removes out-of-scope establishments while preserving at least `canonical_id`, geometry/CRS, and the selected economy code. Downstream clustering acts on the rows it receives; an unused flag is not equivalent to filtering the input.

## Post-analysis visualization

After `sigma run AREA`, use `sigma view AREA` to browse the published points, partitions, cluster-level X links, and shortest-road-path geometries through [SIGMA Explorer](../intro/explorer.md). This is a **read-only presentation step after export**, not an additional model stage. The generated QGIS project remains available for conventional GIS inspection.
