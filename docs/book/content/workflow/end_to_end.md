# End-to-end workflow

SIGMA is implemented as a dependency-aware artifact graph. The conceptual order is linear enough to teach, but execution can reuse any valid upstream artifact.

## Stage numbers, commands and artifacts

| Stage | What happens | Command | Managed stage or workspace output | Chapter |
|---:|---|---|---|---|
| 1 | read OSM and Overture places, clip to the area | `sigma load` | `source.*`, `places.osm_area`, `places.overture_area` | [Places](../methods/places.md) |
| 2 | match records one-to-one → canonical places | `sigma load` | `places.canonical` | [Places](../methods/places.md) |
| 3 | classify activity (PSIC); administrative-office rule | `sigma load` | `places.psic` | [Places](../methods/places.md), [Institutional evidence](../methods/shadow_classification.md) |
| 4 | IO candidate sets and tags; ownership evidence | `sigma load` | `places.classified` | [Institutional evidence](../methods/shadow_classification.md), [Hierarchical economy](../methods/hierarchical.md) |
| 5 | area-specific sector partition (IO240/IO80/IO16) | `sigma load`; rebuilt by `sigma run` when older than the handoff | `hierarchical/` (economy, places preview, audit) | [Hierarchical economy](../methods/hierarchical.md) |
| — | optional review or augmentation of the handoff | edit file; `sigma augment` | `places/places.parquet`, `places/augmentations.json` | [Augmentation](../methods/augmentation.md) |
| 6 | managed road graph | `sigma run` | `transport.roads` | [Roads](../methods/roads.md) |
| 7 | normalize points, snap to roads | `sigma run` | `spatial.points`; snap context in `spatial.clusters` | [Roads](../methods/roads.md) |
| 8 | network HDBSCAN* per sector (baseline labels) | `sigma run` | `spatial.clusters` (`hdbscan_cluster`) | [Network HDBSCAN*](../methods/hdbscan.md) |
| 9 | zero-cluster roll-up (generated hierarchy) | `sigma run` | `hierarchical/iterative_rollup/<hash>/` | [Zero-cluster roll-up](../methods/iterative_rollup.md) |
| 10 | one network Gap k-medoid pass | `sigma run` | `spatial.clusters` (`cluster`, `median_gap_audit.json`) | [Gap refinement](../methods/network_gap_medians.md) |
| 11 | network-node 1-median of each final cluster | `sigma run` | `spatial.centers`, `spatial.point_distances` | [Centers](../methods/centers.md) |
| 12 | network Voronoi territories | `sigma run` | `spatial.partitions` | [Voronoi](../methods/voronoi.md) |
| 13 | effective transactions → technical coefficients | `sigma run` | `economy.*` | [Economy](../methods/economy.md) |
| 14 | spatial-economic graph X | `sigma run` | `analysis.x` | [The X graph](../methods/x_graph.md) |
| 15 | PPML tile-area correction; incoming and outgoing Katz | `sigma run` | `analysis.centrality` | [Centrality](../methods/centrality.md) |
| 16 | balanced centrality (geometric mean, L2) | `sigma run` | `analysis.centrality` | [Centrality](../methods/centrality.md) |
| 17 | inverse-road-distance establishment scores | `sigma run` | `analysis.scores` | [Scoring](../methods/scoring.md) |
| — | publication: GIS outputs and routing graph | `sigma run` | `export.bundle` | [Route publication](../methods/routing.md) |
| — | browser view (read only) | `sigma view` | `output/explorer/` | [Explorer](../intro/explorer.md) |

Stages 8–10 all produce the `spatial.clusters` artifact. When stage 9 applies, SIGMA first materializes a baseline `spatial.clusters` without Gap refinement, derives the roll-up package, verifies it with a second unrefined clustering of the effective sectors, and only then computes the final `spatial.clusters` with Gap refinement. When stage 9 does not apply (or finds no `K=0` sector), one `spatial.clusters` artifact holds both the HDBSCAN* labels (`hdbscan_cluster`) and the final labels after Gap refinement (`cluster`). With `--no-median-gap`, `cluster` is the HDBSCAN* label.

## Stage map

### Area, sources, and places (stages 1–5)

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
                  places.canonical                         (stages 1–2)
                         │
classification.taxonomy ├─> places.psic                    (stage 3: PSIC,
        │                │                                   administrative offices)
        └─> classification.tagging_references
                         │
                         ▼
                  places.classified                        (stage 4: IO tags,
                         │                                   ownership evidence)
                         ▼
     places/places.parquet (editable handoff)
                         │
                         ▼
     hierarchical/ (stage 5: area sectors, IO240 → M Z Mᵀ)
```

### Roads and spatial structure (stages 6–12)

```text
source.geofabrik_pbf + area.boundary ──> transport.roads             (6)
transport.roads + places handoff ──────> spatial.points              (7)
spatial.points + transport.roads ──> baseline HDBSCAN* labels, K     (8)
                            │
                            ├─ generated hierarchy: K=0 roll-up      (9)
                            │       -> effective sector partition
                            │       -> recluster, verify count
                            ▼
                     retained HDBSCAN* clusters + noise
                            │
                            └─ Gap k-medoids, one pass, up to 4 workers   (10)
                                 └─ unsplit clusters and noise kept
                                          │
                                          ▼
                                  spatial.clusters
                                          │
                                          ▼
                                    spatial.centers                  (11)
spatial.clusters + spatial.centers ────> spatial.point_distances
spatial.clusters + spatial.centers + area.boundary ──> spatial.partitions (12)
```

### Economy (stage 13)

```text
economy.definition            (stage 5 or stage 9 sectors; or fixed/custom)
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

### Spatial-economic analysis and publication (stages 14–17)

```text
spatial clusters + centers + partitions + point_distances + economy.graph
                         │
                         ▼
                     analysis.x                     (14)
                         │
                         ▼
                 analysis.centrality                (15–16)
                         │
spatial.point_distances ─┘
                         │
                         ▼
                  analysis.scores                   (17)
                         │
                         ▼
                   export.bundle                    (publication)
```

## Why this order matters

The economic sector of every establishment must be final before clusters are final, because clustering runs separately per sector. Stage 9 therefore runs before stage 10, and stage 10 never revisits the sector decision. Stage 11 computes a new 1-median for each final child cluster, and every later stage uses the final clusters.

The numerical `analysis.x` stage uses exact center-to-center shortest-road **distances** but calculates no route geometry. With the default `--route-geometry browser`, the export publishes a compact road graph and center IDs, and Explorer draws routes on request. The optional precomputed mode materializes all routes **after** X weights are computed. Route display is never an input to Katz scoring.

The workflow separates four different kinds of inference:

1. **identity inference** — deciding which source records refer to one place, which activity a place carries, and which IO industry and ownership side it supports;
2. **spatial structure inference** — deciding which establishments form local road-network clusters and how territory is assigned;
3. **economic structure** — translating transactions into directed technical requirements; and
4. **spatial-economic influence** — instantiating positive directed sector relationships only where spatial cluster territories overlap and the 1-medians are road-connected; weighting each X edge by direct technical coefficients, clustered-sector shares, and mean hub-mediated road distance; then estimating degree–area scaling on the original X topology (per-geography pooled PPML) and measuring **focal-tile-area-adjusted** incoming and outgoing Katz centrality. Establishment scores apply a separate full inverse-road-distance rule. Neither the degree–area correction nor point scoring validates economic influence against observed local trade. These modeled edges are not verified local trades.

A downstream score therefore cannot be interpreted independently of the upstream choices. A centrality value summarizes a graph whose nodes already encode classification, sector, clustering, center, and partition decisions.

## Between load and run: review and augmentation

`sigma load` ends with the editable handoff `places/places.parquet`. Two optional steps can change it before analysis:

- **Human review.** Remove out-of-scope establishments (for example non-MSME rows) and save the file in place, preserving at least `canonical_id`, geometry/CRS, and `economy_code`. Downstream clustering acts on the rows it receives; an unused flag is not equivalent to filtering the input.
- **Augmentation.** `sigma augment AREA INPUT --source SOURCE` reconciles additional observations against the loaded canonical places with the stage 2 matching rule, enriches provenance, and validates any explicit IO tags. `sigma augment ... --check` is a read-only preview. See [Augment user-provided places](../methods/augmentation.md).

SIGMA hashes the handoff bytes. The next `sigma run AREA` rebuilds stage 5 when it is older than the handoff and recomputes the stages that depend on the changed rows; source data and roads are reused.

## Post-analysis visualization

After `sigma run AREA`, use `sigma view AREA` to browse the published points, partitions and cluster-level X links in [SIGMA Explorer](../intro/explorer.md); routes are drawn on request from the published routing graph. This is a **read-only presentation step after export**, not an additional model stage. The generated QGIS project remains available for conventional GIS inspection.
