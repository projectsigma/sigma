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
spatial clusters + centers + partitions + economy.graph
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

## Why this order matters

The workflow separates four different kinds of inference:

1. **identity inference** — deciding which source records refer to one place and which economic activity a place represents;
2. **spatial structure inference** — deciding which establishments form local road-network clusters and how territory is assigned;
3. **economic structure** — translating transactions into directed technical requirements; and
4. **spatial-economic influence** — instantiating economic relations only where spatial cluster territories overlap, then measuring directed centrality.

A downstream score therefore cannot be interpreted independently of the upstream choices. A centrality value summarizes a graph whose nodes already encode classification, clustering, center, and partition decisions.

## Human review boundary

SIGMA supports a deliberate human review step after deterministic place classification. The safest review artifact removes out-of-scope establishments while preserving at least `canonical_id`, geometry/CRS, and the selected economy code. Downstream clustering acts on the rows it receives; an unused flag is not equivalent to filtering the input.
