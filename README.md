# Spatial Intelligence and Graph Modeling for MSME Acquisition (SIGMA)

[![Documentation](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://projectsigma.github.io/sigma/)

Methodological documentation: **[SIGMA Jupyter Book](https://projectsigma.github.io/sigma/)** · publishing instructions: [`GITHUB_PAGES.md`](GITHUB_PAGES.md).


## Project Summary

**Spatial Intelligence and Graph Modeling for MSME Acquisition (SIGMA)** is an end-to-end geocomputation framework for identifying, modeling, and prioritizing localized MSME ecosystems.

The project applies geospatial analytics, network analysis, input-output economics, and graph-based modeling to shift MSME acquisition from an individual, location-based approach toward an **ecosystem-driven, network-aware strategy**. Rather than treating each establishment as an isolated prospect, SIGMA identifies geographically concentrated business ecosystems, classifies establishments by economic activity, models spatial and economic relationships among clusters, identifies influential ecosystem nodes, and produces cluster-to-cluster links that indicate where one ecosystem is structurally connected to another.

The intended business use is to support more precise MSME targeting, lower acquisition effort, improve lead quality, identify influential businesses that can serve as acquisition entry points, and inform ecosystem-specific product and engagement strategies.

SIGMA is designed so that the computational pipeline and the business decision layer remain distinct. The software produces reproducible geospatial, network, economic, and scoring outputs; bank-specific judgments such as whether a location is underserved, whether a business qualifies as an MSME, and which product bundle should be offered may be incorporated as human-reviewed or downstream decision inputs.

---

## How SIGMA works: 17 stages

SIGMA runs in two commands. `sigma load` (stages 1–5) builds the classified list of places for one area. `sigma run` (stages 6–17) builds the road network, the clusters, the network X and the scores, and then publishes the results. Every stage below is explained with a worked, interactive example in **Under the Hood** (open it from the SIGMA Explorer header) and in the [SIGMA Jupyter Book](https://projectsigma.github.io/sigma/).

| # | Stage | Command | What it does |
|---:|---|---|---|
| 1 | Sources | `load` | OpenStreetMap places from the shared Geofabrik PBF and Overture Places, clipped to the area boundary |
| 2 | Matching | `load` | one-to-one OSM–Overture reconciliation within 120 m, by name similarity and distance |
| 3 | Activity | `load` | deterministic PSIC classification; one narrow rule reassigns clear government administrative offices to PSIC 84120 |
| 4 | IO tags and ownership evidence | `load` | PSIC → IO240/IO80/IO16 candidates; the public or private side of education and health is chosen only from strong evidence (verified registry link, official ID, explicit source attribute) |
| 5 | Area sectors | `load` | per-area hierarchical PSA 2018 economy: an IO240 industry where at least 5 places support it, otherwise IO80 or IO16 groups and residual `o` sectors |
| — | Review and augmentation (optional) | edit file / `sigma augment` | remove places from the editable handoff, or add places from a CSV or Parquet file |
| 6 | Road graph | `run` | managed undirected road network from the same PBF, with a 5 km buffer around the area |
| 7 | Snapping | `run` | each place is attached to its nearest road position; network distance is measured along roads from there |
| 8 | Network HDBSCAN* | `run` | density clusters of each sector, with distance measured along roads; places outside clusters are noise |
| 9 | Zero-cluster roll-up | `run` | generated hierarchies only: a sector with no retained cluster (K=0) is merged into a broader sector when the merge retains more establishments in clusters |
| 10 | Network Gap k-medoids | `run` | one pass, on by default with up to four worker processes: an eligible cluster is split into road-medoid children when the Gap statistic supports it |
| 11 | 1-median centers | `run` | the road position with the smallest total road distance to the members of each final cluster |
| 12 | Network Voronoi | `run` | each cluster's territory: the roads nearer to its members than to members of the same sector's other clusters, drawn as polygons |
| 13 | IO coefficients | `run` | the directed technical-coefficient graph of the area's sectors; cycles and reciprocal links are kept |
| 14 | Network X | `run` | a directed link between two clusters when their sectors have an IO coefficient, their territories overlap and a road connects their centers |
| 15 | Tile-adjusted Katz | `run` | estimate degree–area scaling by per-geography PPML; compute outgoing and incoming Katz using the focal tile's own area factor |
| 16 | Balanced centrality | `run` | geometric mean of the two Katz values, then one L2 normalization |
| 17 | Establishment scores | `run` | cluster centrality divided by establishment-to-1-median road distance, with a 1 m floor (canonical Katz) |
| — | Publication | `run`, `view` | GeoParquet, CSV, GeoPackage and QGIS outputs, and a compact routing graph from which Explorer draws routes on request |

Stage 9 is decided on the HDBSCAN* clusters before any Gap split, and stage 10 then refines the clusters of the final sectors. HDBSCAN* noise stays noise in both stages. The original sector (`original_economy_code`) and the original HDBSCAN* label (`hdbscan_cluster`) of every place remain in the outputs, together with `rollup_audit.json` and `median_gap_audit.json`. A network X node is a `(sector, cluster)` pair, not one firm, and an X edge is a modeled spatial-economic relationship, not evidence that two establishments trade.

```powershell
sigma run quezon_city                                # canonical: roll-up + Gap, up to four workers
sigma run quezon_city --no-median-gap                # keep the HDBSCAN* clusters (skip stage 10)
sigma run quezon_city --median-gap-workers 1         # same Gap method, one process
sigma run quezon_city --no-iterative-rollup          # keep the original sectors (skip stage 9)
sigma run quezon_city --route-geometry precomputed   # also store route lines in the GeoPackage
```

Stage 9 applies only to generated hierarchical economies; fixed IO16/IO80/IO240 and custom economies keep their sectors, and stage 10 applies to every economy. The legacy `--equivalent` profile keeps unrefined HDBSCAN* clusters unless `--median-gap` is given. Splitting a cluster does not guarantee that the sector's combined Voronoi territory becomes smaller or that its Katz scores become less concentrated. See [Zero-cluster roll-up](docs/book/content/methods/iterative_rollup.md), [Network Gap refinement](docs/book/content/methods/network_gap_medians.md), [Hierarchical economy](docs/book/content/methods/hierarchical.md) and [End-to-end workflow](docs/book/content/workflow/end_to_end.md).

---

## SIGMA Explorer — interactive results in your browser

**[SIGMA Explorer](SIGMA_EXPLORER.md)** shows existing SIGMA results on an interactive map and a synchronized **directed cluster-network diagram**, without QGIS and without running the analysis again. Select an establishment to see its assigned `(sector, cluster)` network neighborhood, inspect incoming and outgoing connections, expand to two steps, and draw the shortest road route between two linked cluster centers. By default the route is computed in the browser, on request, from a compact routing graph published with the results.

After running SIGMA for an area, open the Explorer locally:

```powershell
sigma run pasig
sigma view pasig
```

The browser opens at `http://127.0.0.1:8765/` by default. Use `sigma view pasig --refresh` after the published outputs change, or `sigma view pasig --no-browser` to print the address without opening a browser. To prepare a portable static site from published results, use `sigma export-web pasig`; see the [Explorer guide](SIGMA_EXPLORER.md) and the [Explorer chapter of the documentation](docs/book/content/intro/explorer.md).

**Under the Hood** (in the Explorer header) explains the 17 stages above with interactive figures. A panel and a note under every step show what the opened bundle publishes for that stage, for example its sector codes, rolled-up sectors, final cluster counts and route mode.

**Fixed sector colors.** Sector colors come from one fixed 336-color specification (16 IO16, 80 IO80 and 240 IO240 colors). Sparse hierarchy codes resolve to the color of their industry, and residual `o` sectors use the color of their parent. In Explorer, a rolled-up sector can be expanded to show its original sub-sectors with their own colors and point-only visibility controls; the parent remains the effective sector for clustering, Voronoi territories, X nodes, centrality and scores. Colors are presentation only and never change an X weight or a score.

**Context displays.** In the local Explorer, two independent checkboxes are off by default.
**Show unscored sectors** reveals classified, unclustered establishments in zero-cluster sectors
only when no network is selected. **Show unclustered for scored sectors** reveals all such
establishments of scored sectors without a selection; with a selected scored establishment
or cluster, it shows only those inside highlighted focus or linked Voronoi polygons of their
own effective sector. The circles are hollow and sector-colored; their radius is based on
the smallest scored point of that sector (or the smallest scored point overall when the sector
has no scored members). Visibility is presentation-only: it never supplies a cluster, X link,
or SIGMA score. Hovering a cluster-center triangle during a selection outlines its published
Voronoi polygon in the sector color.

**Fast UI changes:** after an Explorer bundle exists, `sigma view pasig --fast` copies the current HTML, CSS, JavaScript, logo and favicon into it and opens the browser **without rebuilding** its graph, tiles or routing data. It does **not** check whether SIGMA's published results changed; use ordinary `sigma view pasig` to check freshness or `--refresh` for a full rebuild. `--fast` and `--refresh` cannot be combined, and `--ui-only` is an alias for `--fast`.

**Interpretation and privacy:** each X node represents a **sector cluster**, not one firm, and an edge is a **modeled spatial-economic relationship**, not evidence that two establishments trade. The default Explorer bundle contains individual establishment locations and should remain private unless data rights, attribution and publication risks have been reviewed. A reduced `--public` export omits establishment-level records but is **not a guarantee of anonymity**. The [SIGMA documentation website](https://projectsigma.github.io/sigma/) explains the methods; it does not host your local Explorer data.

## Objectives

The main objective of SIGMA is to enable the design of **ecosystem-specific MSME acquisition strategies** by identifying spatially concentrated business systems, estimating how those systems are connected, and ranking influential businesses within them.

The project objectives map to the implemented SIGMA pipeline as follows:

| Project objective | SIGMA implementation |
|---|---|
| 1. Identify emerging MSME ecosystem clusters with strong economic potential but underserved by BPI | Place acquisition and reconciliation; PSIC classification; PSIC-to-IO mapping; road-network preparation; network-constrained clustering; cluster centers; Voronoi/partition construction. Bank coverage/underservice is a downstream overlay or reviewed attribute rather than a hard-coded SIGMA rule. |
| 2. Develop a Network Influence Score to identify key connectors or anchors within local business ecosystems | The spatial-economic **X graph**, tile-area-adjusted balanced directed Katz, and inverse-road-distance point scoring identify influential cluster nodes and establishments. |
| 3. Estimate which MSME ecosystems are structurally linked to other ecosystems | SIGMA's **cluster-to-cluster link generation** instantiates directed X-graph edges only where economic relationships, spatial overlap, and road-network reachability jointly support a connection. This is SIGMA's operational form of graph link prediction / structural link inference. |
| 4. Enable ecosystem-specific acquisition strategies and product bundles | SIGMA exports ecosystem polygons, centers, linked-cluster edges and paths, centrality, point-level scores, economic relationships, and audit/provenance artifacts that can be translated into target zones, priority MSMEs, and product strategies. |

---

## Significance of the Project

Current MSME acquisition approaches can depend heavily on broad geographic indicators and individual prospecting, producing high acquisition effort and uneven lead quality. MSMEs, however, often operate as parts of localized economic systems such as markets, malls, transport hubs, commercial corridors, and economic zones. Their commercial relevance may therefore depend not only on their individual characteristics, but also on their position within a spatial and economic network.

SIGMA reframes the acquisition problem around **ecosystems rather than isolated establishments**. The resulting analysis can support:

- identification of high-density and economically meaningful MSME clusters;
- prioritization of businesses that occupy influential positions within those clusters;
- identification of cluster-to-cluster relationships that may support indirect acquisition pathways;
- comparison of target zones using spatial, network, and economic structure rather than location alone; and
- design of ecosystem-level engagement and product strategies.

The analytical premise is that acquiring a strategically positioned business may have value beyond that individual account when the business is embedded in a connected local ecosystem of suppliers, buyers, service providers, and adjacent economic activities.

---

## Scope and Limitations

### Scope

SIGMA supports:

- development of MSME ecosystem maps using external geospatial/business-place data and, where available, aggregated, synthetic, reviewed, or otherwise permitted internal attributes;
- place reconciliation and PSIC-based economic classification;
- mapping from PSIC activity classes to configurable input-output sectors;
- extraction of a routable road network from the shared Geofabrik Philippines PBF;
- network-constrained geospatial clustering;
- cluster-center and spatial partition construction;
- directed input-output economic network construction;
- cluster-to-cluster spatial-economic link generation;
- network centrality and influence scoring;
- point-level scoring with canonical inverse-road-distance attenuation;
- restartable, content-addressed workflow execution; and
- export of tabular, GeoParquet, CSV, and GeoPackage analytical products.

### Limitations

- Bank-specific customer-level transactional data are not required by the current codebase. Where the research design uses aggregated or synthetic internal data, those data must be introduced through permitted inputs or downstream joins.
- External place data may contain incomplete, stale, duplicated, or incorrectly classified establishments. SIGMA therefore treats **human review as a legitimate analytical stage**, especially for determining which classified establishments should be treated as MSMEs.
- The current cluster-link mechanism is **deterministic structural link inference**, not a supervised probabilistic link-prediction model trained on observed adoption outcomes.
- Product-bundle selection is a strategic interpretation of SIGMA outputs; the current codebase does not contain a bank-product recommendation engine.
- The routing graph is currently undirected. OSM `oneway` is retained as audit metadata but is not used to create a directed road graph.
- Managed-road extraction uses a 5 km buffer around the selected administrative boundary so routes near the edge may leave and re-enter the area.

---


# Getting Started: Practical Walkthrough

This section is the recommended entry point for day-to-day use. The methodology and implementation details later in this README explain why the pipeline works the way it does; this walkthrough focuses on **what to type, what each command does, where outputs go, and how to inspect or rerun work safely**.

## Install from the repository

SIGMA requires Python 3.11 or newer. From the repository root, install it into the active Python/conda environment:

```powershell
python -m pip install -e .
```

For development/testing tools:

```powershell
python -m pip install -e ".[dev]"
```

For the optional OpenAI-assisted classification path:

```powershell
python -m pip install -e ".[llm]"
```

The normal deterministic workflow does **not** require the LLM extra.

Confirm that the CLI is available:

```powershell
sigma --version
sigma --help
```

Every command and command group has its own help page. For example:

```powershell
sigma init --help
sigma areas --help
sigma areas list --help
sigma load --help
sigma run --help
sigma view --help
sigma export-web --help
sigma status --help
sigma storage --help
sigma storage report --help
sigma storage prune --help
sigma analysis run --help
```

See the [complete `run` and `view` option reference](docs/SIGMA_RUN_VIEW_CLI.md), including cache/refresh semantics.

> **PowerShell note.** `--quiet` is a global option, so place it before the subcommand: `sigma --quiet run pasig`, not `sigma run pasig --quiet`.

---

## Step 1 — Initialize SIGMA once

Before any workflow command, initialize the shared national source:

```powershell
sigma init
```

SIGMA shows the visible shared data location and asks before downloading. By default:

```text
%USERPROFILE%\Documents\SIGMA
```

The initialized Philippines Geofabrik `.osm.pbf` is shared across every area and is used for both OSM place extraction and road-network preparation. Overture Places remains area-specific and is acquired by `sigma load`.

Useful initialization variants:

```powershell
# Non-interactive confirmation
sigma init --yes

# Re-check/download a fresh Geofabrik Philippines PBF
sigma init --refresh

# Machine-readable initialization result
sigma init --json
```

Advanced deployments can move all shared state by setting `SIGMA_HOME` **before** initialization:

```powershell
$env:SIGMA_HOME = "D:\SIGMA"
sigma init
```

Do not normally override the source store per command; the initialized shared source store is intentional.

Check the installation after initialization:

```powershell
sigma doctor
sigma classification-check
```

For structured output:

```powershell
sigma doctor --json
sigma classification-check --json
```

---

## Step 2 — Find the area you want to analyze

SIGMA exposes **1,727 selectable Philippine areas** from its canonical catalog:

```text
1,493 municipalities
149 cities
82 provinces (derived from locality boundaries)
3 composites: Metro Manila, Metro Cebu, Metro Davao
```

### Print every available area

```powershell
sigma areas list
```

The default tab-separated output is:

```text
slug    kind    name    psgc_code
```

Examples include canonical slugs such as `pasig`, `quezon_city`, and `metro_manila`.

### Search for possible area names

Use a partial, case-insensitive search across slug, display name, PSGC code, and aliases:

```powershell
sigma areas list --search "Pasig"
sigma areas list --search "Quezon"
sigma areas list --search "Cebu"
sigma areas list --search "National Capital"
```

This is the recommended command whenever you are unsure of the exact slug:

```powershell
sigma areas list --search "<part of the place name>"
```

### Filter by area kind

```powershell
sigma areas list --kind city
sigma areas list --kind municipality
sigma areas list --kind province
sigma areas list --kind composite
```

You can combine filters:

```powershell
sigma areas list --kind city --search "Davao"
```

### Inspect one exact area

```powershell
sigma areas show pasig
sigma areas show quezon_city
sigma areas show metro_manila
sigma areas show palawan
sigma areas show cebu_province
```

`areas show` prints the full area definition as JSON, including the bounding box, PSGC code where applicable, aliases, members for composites, and the packaged boundary specification.

Area resolution accepts an exact canonical slug, exact area name, exact alias, or a listed PSGC-code alias. Examples:

```powershell
sigma areas show "Metro Manila"
sigma areas show "National Capital Region"
sigma areas show NCR
sigma areas show 1381200000
```

If a value is unknown, SIGMA tells you to use `sigma areas list --search ...` rather than guessing.

### Save the complete area catalog to a file

Plain text/TSV-style output:

```powershell
sigma areas list | Set-Content ".\sigma_areas.txt"
```

Or display it while saving it:

```powershell
sigma areas list | Tee-Object -FilePath ".\sigma_areas.txt"
```

JSON is more convenient for scripts:

```powershell
sigma areas list --json | Set-Content ".\sigma_areas.json"
```

Search results can be saved the same way:

```powershell
sigma areas list --search "Cebu" --json | Set-Content ".\cebu_areas.json"
```

### Use a custom area catalog

Commands that accept `--areas-file` can use another YAML catalog instead of the packaged one:

```powershell
sigma areas list --areas-file ".\custom_areas.yml"
sigma areas show my_area --areas-file ".\custom_areas.yml"
sigma load my_area --areas-file ".\custom_areas.yml"
sigma run my_area --areas-file ".\custom_areas.yml"
```

---

## Step 3 — Load, reconcile, classify, and label places

Once you have selected an area:

```powershell
sigma load pasig
```

For an ordinary run, this performs the **place branch only**:

```text
area boundary
    ↓
1  OSM places from the initialized national PBF + Overture Places for the area
    ↓
2  source reconciliation → canonical places
    ↓
3  deterministic PSIC classification + administrative-office rule
    ↓
4  PSIC → IO240/IO80/IO16 candidates + public/private ownership evidence
    ↓
5  area sectors (per-area hierarchical economy, or the fixed level you chose)
    ↓
editable places handoff
```

The default handoff is:

```text
%USERPROFILE%\Documents\SIGMA\workspaces\pasig\places\places.parquet
```

By default, `sigma load` also builds this area's hierarchical IO240/IO80/IO16 economy from the packaged PSA 2018 IO240 reference (see *Choosing the IO resolution at load time* below); the places handoff itself carries PSA 2018 IO80 codes. Deterministic classification is the default; the optional LLM path is off.

Useful variants:

```powershell
# Explicit built-in IO16 instead of the default per-area hierarchy
sigma load pasig --economy builtin:io16

# Refresh only Overture for this area
sigma load pasig --refresh-overture

# Refresh/check the initialized Geofabrik source too
sigma load pasig --refresh-geofabrik

# Explicit optional LLM-assisted classification
sigma load pasig --llm

# Machine-readable output
sigma load pasig --json

# Force regeneration even if an equivalent managed artifact is valid
sigma load pasig --force
```

You may also provide a custom economy directory through `--economy PATH`; otherwise use `builtin:io80` or `builtin:io16`.

### Choosing the IO resolution at load time

`sigma load AREA` builds an area-specific hierarchical economy: exact IO240 industries where enough places support them, and IO80 or IO16 groups elsewhere. It uses the national PSA 2018 IO240 reference that is versioned in this repository under `src/sigma/resources/economy/psa_2018_io240/`. The first such load creates `hierarchical-defaults.json` in the SIGMA data folder (`coarse_policy=residual`, `min_places=5`); that file points to the packaged reference. For candidate-conservative attribution, set `coarse_policy=contain` explicitly. Edit the profile, or use `sigma economy hierarchical-configure`, to change the settings.

```powershell
# Default: hierarchical IO240/IO80/IO16 economy for this area
sigma load pasig

# Fixed national resolutions
sigma load pasig --io-level 16
sigma load pasig --io-level 80
sigma load pasig --io-level 240
```

The choice is recorded in `<workspace>\economy-selection.json`, and `sigma run AREA` follows it. Legacy areas with no recorded selection or prior hierarchy remain IO80 until explicitly reloaded. In fixed IO240 mode only places with an exact IO240 code are used, and `sigma load` reports how many. `--io-level` cannot be combined with `--economy`. If the hierarchical settings change after an area was loaded, `sigma run` stops and asks you to refresh or reload the area instead of rebuilding it with different settings. Details: [`docs/SIGMA_LOAD_PORTABILITY.md`](docs/SIGMA_LOAD_PORTABILITY.md).

---

<!-- sigma-augment-docs-v1:begin:readme -->
### Optional: augment loaded places from CSV or Parquet

After `sigma load`, `sigma augment` can reconcile additional observations from a user-supplied CSV or Parquet against the existing canonical places. It uses SIGMA's existing name-and-distance matching policy; matching records retain their canonical identity and unmatched records are added. No additional OSM/Overture acquisition occurs.

```powershell
sigma augment quezon_city "C:\data\registry.csv" --source company_registry --check
sigma augment quezon_city "C:\data\registry.csv" --source company_registry
sigma run quezon_city
```

Four input fields are required: `source_id`, `name`, `lon`, and `lat` (WGS84 longitude/latitude). Optional `category`, `psic_code`, `io16`, `io80`, and `io240` columns supply classification evidence. **The finest provided IO code determines missing ancestors, not descendants.** Contradictory supplied IO relationships are reported per row and block application; conflicts with existing *inferred* classifications are reported as warnings. Unspecified IO fields may be blank. Do **not** use the superseded single `io_code` input column.

Arbitrary further attributes are retained under source-qualified names (for example, `aug_company_registry__employees`) for future analysis; they do not alter the present SIGMA score. `--check` does not write. Augmentation records provenance, preserves OSM/Overture identities and the existing acquisition policy, and leaves network/scoring recomputation to the subsequent `sigma run`. This applies to an **already loaded** workspace: it is an optional step, not a replacement for `sigma load`.

See the [Augment specification](docs/SIGMA_AUGMENT.md) and the [GitHub Pages augmentation chapter](docs/book/content/methods/augmentation.md) for the full schema, matching thresholds, explicit-tag precedence, safety checks, and refresh behavior.
<!-- sigma-augment-docs-v1:end:readme -->

## Step 4 — Optionally review the place handoff

The loaded GeoParquet is deliberately editable. Open:

```text
%USERPROFILE%\Documents\SIGMA\workspaces\pasig\places\places.parquet
```

in QGIS, ArcGIS Pro, Python, or another GeoParquet-capable tool. You can remove establishments that should not participate in the analysis and save the file **in place**.

At minimum preserve:

```text
canonical_id
geometry
CRS
economy_code
```

Retaining PSIC, names, source fields, and provenance columns is strongly recommended.

SIGMA hashes the actual handoff bytes used by the analysis. If you edit the file, the affected downstream artifacts are invalidated while unrelated reusable prerequisites remain cached.

---

## Step 5 — Run the complete spatial-economic analysis

After `sigma load`:

```powershell
sigma run pasig
```

The ordinary default is intentionally opinionated:

```text
managed Geofabrik road network (undirected, metre-based)
area-specific hierarchical PSA 2018 IO240/80/16 economy for newly loaded areas
network HDBSCAN EOM; network leaf recovery on error; Euclidean recovery if needed
K=0 residual-first roll-up for generated hierarchical economies, before Gap
single-pass network Gap k-medoids on retained HDBSCAN clusters (default limit: 4 workers)
final network-node 1-median for every retained/refined cluster
network Voronoi partitions: 50 m start, refine until convergence or a limit; planar fallback if needed
full positive directed IO technical-coefficient graph (no transaction preprocessing)
mean hub-mediated X distance, exact-type clustered shares, inverse-power attenuation
per-geography PPML tile-area-adjusted balanced directed Katz; inverse-road-distance establishment scores
QGIS/GeoParquet and browser-native route publication (precomputed optional)
```

The economic graph is **not forced into a DAG** by default. Positive directed IO relationships, reciprocal edges, and cycles are retained. Optional fast MWAS+RAS preprocessing is available only when explicitly requested.

Canonical Katz uses both directions of the directed X graph:

```text
raw incoming Katz
        +
raw outgoing Katz
        ↓
nodewise geometric mean
sqrt(K_in × K_out)
        ↓
one final L2 normalization
        ↓
balanced centrality
```

Before either Katz pass, SIGMA fits a **per-geography pooled PPML degree–area exponent** from final Voronoi tile areas and total directed degree (including zero-degree X nodes). For each tile, $f_i=A_i^{-\hat\gamma}$; the two **focal-tile** operators are $W'^{out}=FW$ and $W'^{in}=FW^{\mathsf T}$, where $F=\mathrm{diag}(f_i)$. Neither X topology nor its stored original weights change. The two Katz components share the same spectrally safe attenuation, derived from `alpha_factor = 0.85`; `beta = 1`. The geometric mean is L2-normalized **once**, after combining the raw components. A weighted eigenvector method is available only as an explicit legacy alternative.

The new area-adjusted canonical rule is on by default. `--no-area-adjustment` gives ordinary balanced Katz; `--area-adjustment` requests the default explicitly. A separate canonical **establishment scoring** choice applies $S_p=C_{c(p)}/\max(d_R(p,m_{c(p)})/(1\,\mathrm m),1)$ instead of the old bounded 15% p90 distance tempering (retained only for explicit legacy eigenvector scoring). See [Centrality](docs/book/content/methods/centrality.md), [Scoring](docs/book/content/methods/scoring.md), and [Area-adjustment diagnostics](docs/book/content/methods/area_adjustment_diagnostics.md). The Metro Manila cluster diagnostics are **not** an external economic validation or a validation of establishment-level rankings.

Each line corresponds to one or more of the stages 6–17 in [How SIGMA works](#how-sigma-works-17-stages).

Common run variants:

```powershell
# Skip zero-cluster roll-up (stage 9) or Gap refinement (stage 10)
sigma run pasig --no-iterative-rollup
sigma run pasig --no-median-gap

# Run Gap refinement serially (same results as the four-worker limit)
sigma run pasig --median-gap-workers 1

# Start the stage 12 Voronoi grid at 100 m instead of 50 m (refinement still runs)
sigma run pasig --voronoi-resolution 100

# Change the X distance-decay exponent (default 1.0)
sigma run pasig --x-distance-decay-lambda 0.5

# Also store route geometries in the GeoPackage (browser routing is the default)
sigma run pasig --route-geometry precomputed

# Explicit canonical Katz (already the default)
sigma run pasig --centrality-method katz

# Legacy eigenvector option on the positive-weight undirected projection of X
sigma run pasig --centrality-method eigenvector

# Disable tile-area correction while retaining canonical inverse-distance point scoring
sigma run pasig --no-area-adjustment

# Inspect reuse without touching expensive clustering or other stages
sigma run pasig --plan

# Legacy eigenvector ONLY: change its bounded p90 distance tempering
sigma run pasig --centrality-method eigenvector --distance-tempering 0.10

# Change clustering thresholds
sigma run pasig --min-cluster-size 8 --min-samples 4

# Allow a type to form one cluster when appropriate
sigma run pasig --allow-single-cluster

# Optional fast MWAS+RAS transaction preprocessing
sigma run pasig --transaction-preprocessing mwas_ras_fast

# Legacy Engine-equivalent profile
sigma run pasig --equivalent --mwas-method fast

# Explicit full refresh (potentially expensive; review --plan first)
sigma run pasig --refresh --allow-expensive

# Legacy: force terminal scoring; other valid stages may be reused
sigma run pasig --force

# Structured result
sigma run pasig --json
```

`--centrality-direction` remains a compatibility option. Canonical balanced Katz necessarily computes **both** incoming and outgoing Katz and therefore ignores that switch; the legacy eigenvector option also ignores it.

---

## Step 6 — Check progress and cached stage status

At any time after initialization:

```powershell
sigma status pasig
```

Before `sigma load`, status reports that the loaded place handoff is missing and tells you the next command. After loading/running, it reports each managed stage and whether its current artifact is valid, reusable, missing, or stale.

Machine-readable status:

```powershell
sigma status pasig --json
```

SIGMA is content-addressed and restartable. Repeating:

```powershell
sigma run pasig
```

should reuse valid upstream artifacts. A configuration/input change invalidates only the affected stage and descendants.

### Inspect and reclaim disk space

Shared OSM extraction creates large temporary libosmium node-location indexes. SIGMA removes
those indexes when extraction finishes, including when extraction raises an exception. If
Windows holds an index open, deletion produces a warning rather than failing the stage.
A cache left by an *older* SIGMA version is not automatically purged merely by upgrading.

Workspace results are different: versioned artifacts under `artifacts/` support selective
recomputation and provenance; `output/` contains GIS deliverables, and `output/explorer/`
contains the derived browser bundle. Do **not** delete these directories indiscriminately.

```powershell
# Size inventory, largest files/stages, and eligible cleanup candidates (read-only)
sigma storage report

# Preview old interrupted staging and temporary files; no deletion
sigma storage prune

# Apply the conservative cleanup to SIGMA-owned debris idle for >= 30 days
# Close SIGMA processes and GIS viewers before running this.
sigma storage prune --apply

# Limit maintenance to one workspace
sigma storage report --workspace "$HOME\Documents\SIGMA\workspaces\pasig"
```

Deletion of superseded immutable artifacts is **separate and opt-in**:

```powershell
sigma storage report --obsolete            # preview
sigma storage prune --obsolete --apply     # deletes eligible old versions
sigma storage prune --quarantine --apply   # deletes eligible old corrupt quarantines
```

`--obsolete` preserves the active dependency graph, but can remove history needed to
reproduce older parameter sets. If the graph is unsafe/incomplete or run archives exist,
obsolete-artifact pruning is disabled. All pruning requires `--apply`; the default age
threshold is 30 days, adjustable with `--older-than-days N`. Current exports, Explorer,
reviewed places, and run archives are not pruned. The command does **not** clean the
shared `sources/` directory. See [Storage maintenance](STORAGE.md) and the
[storage and retention guide](docs/book/content/reproducibility/storage.md) for details.

---

## Step 7 — Find and open the final outputs

Unless `--output-dir` was set when the workspace was created, area-mode outputs are written under:

```text
%USERPROFILE%\Documents\SIGMA\workspaces\<area>\output
```

For Pasig:

```text
%USERPROFILE%\Documents\SIGMA\workspaces\pasig\output
```

The most convenient GIS entry point is:

```text
pasig.qgz
```

The generated QGIS project uses relative GeoParquet paths, so keep the `.qgz` beside its exported files. The project uses EPSG:4326 / WGS 84 for publication. Metric road/network calculations still occur internally in an appropriate projected CRS.

The QGIS layer tree is intentionally compact:

```text
sigma_points
Partitions
    01 - Palay
    02 - Corn
    ...
    80 - Other services
sigma_network_centers
sigma_roads
sigma_boundary
```

Only partitions are split into per-sector QGIS layers. Establishments are a **single mutually exclusive categorized point layer**. `sigma_roads.parquet` is clipped to the exact area boundary for publication even though SIGMA retains the buffered road network internally for analysis.

The canonical point layer is:

```text
sigma_points.parquet
```

It combines the useful establishment attributes from clustering, center-distance, balanced Katz, and scoring stages, including `katz_in_raw`, `katz_out_raw`, `centrality`, and `sigma_score` when applicable.

### Explore the same results in a browser

Run `sigma view pasig` to open **SIGMA Explorer**, an interactive counterpart to the `.qgz` output. It reuses the published point layer, cluster polygons, network nodes and edges, and the compact routing graph from which it draws shortest road routes on request. Click a mapped establishment or cluster center to see its **directed cluster-network neighborhood** on the map and in a linked network diagram. You can switch between incoming, outgoing and combined exploration, change network depth, and enlarge the diagram to theater view.

```powershell
sigma view pasig                # local browser view; uses existing exports
sigma view pasig --refresh      # refresh the derived visualization bundle
sigma view pasig --fast         # copy current UI files only; reuse existing graph and routing data
sigma export-web pasig          # write <output>\explorer for portable hosting
sigma export-web pasig --public # reduced-data bundle in <output>\explorer-public
```

The local view uses a loopback-only HTTP server. `Ctrl+C` stops it. The full browser bundle includes establishment locations: **do not publish it by default**. The reduced public profile removes individual establishment records but still requires licensing and disclosure review. See [SIGMA Explorer](SIGMA_EXPLORER.md).

---

## Step 8 — A complete Pasig example

```powershell
# 1. One-time setup
sigma init

# 2. Verify available area and exact definition
sigma areas list --search "Pasig"
sigma areas show pasig

# 3. Build the reviewable establishment handoff
sigma load pasig

# 4. Optional: review/filter
# %USERPROFILE%\Documents\SIGMA\workspaces\pasig\places\places.parquet

# 5. Run the analysis
sigma run pasig

# 6. Inspect managed stage status
sigma status pasig

# 7. Open final GIS project
# %USERPROFILE%\Documents\SIGMA\workspaces\pasig\output\pasig.qgz

# 8. Or inspect the same results interactively in a browser
sigma view pasig
```

For a metropolitan composite, the workflow is the same:

```powershell
sigma areas show metro_manila
sigma load metro_manila
sigma run metro_manila
```

---

## Quick command map

| Goal | Command |
|---|---|
| Show all top-level commands | `sigma --help` |
| Initialize shared national source | `sigma init` |
| Check installation/runtime | `sigma doctor` |
| Validate packaged classification assets | `sigma classification-check` |
| Print every packaged area | `sigma areas list` |
| Search for an area | `sigma areas list --search "Pasig"` |
| Filter cities/municipalities/composites | `sigma areas list --kind city` |
| Inspect one area | `sigma areas show pasig` |
| Build editable place handoff | `sigma load pasig` |
| Augment loaded places (optional) | `sigma augment pasig path/to/places.csv --source user_registry` |
| Run full analysis/export | `sigma run pasig` |
| Explore results in a local browser | `sigma view pasig` |
| Rebuild Explorer from latest exports | `sigma view pasig --refresh` |
| Refresh only Explorer UI files | `sigma view pasig --fast` |
| Export browser-ready results | `sigma export-web pasig` |
| Export reduced-data public review bundle | `sigma export-web pasig --public` |
| Inspect cache/stage state | `sigma status pasig` |
| Report workspace disk use and largest files | `sigma storage report` |
| Preview workspace cleanup (no deletion) | `sigma storage prune` |
| Remove aged abandoned temporary files | `sigma storage prune --apply` |
| Preview superseded immutable artifacts | `sigma storage report --obsolete` |
| Run only road preparation | `sigma network prepare ...` |
| Run only spatial branch | `sigma spatial run ...` |
| Build only economic graph | `sigma economy graph ...` |
| Run X/centrality/scoring branch | `sigma analysis run ...` |
| Ensure one exact managed stage | `sigma stage ...` |
| Force one stage to recompute | `sigma recompute ...` |
| Export ensured analysis | `sigma export ...` |
| Restart from supplied spatial products | `sigma from-partitions ...` |

---

# Methodology and Implementation Mapping

## 1. Geospatial Ecosystem Discovery

The first milestone constructs MSME ecosystem maps from observed establishments and the physical road network.

### 1.1 Area selection and boundary resolution

A user selects an area from SIGMA's canonical Philippine area catalog. SIGMA resolves the corresponding exact boundary and uses that boundary as the spatial scope for place acquisition and analysis.

Relevant stages:

```text
area.definition
area.boundary
```

### 1.2 Place acquisition

SIGMA acquires place observations from two implemented source families:

1. **OpenStreetMap**, using the shared Geofabrik Philippines PBF; and
2. **Overture Maps Places**.

SIGMA requires an explicit one-time `sigma init` before any workflow command. Initialization creates a visible shared data directory (by default `Documents\SIGMA`) and downloads the national Geofabrik Philippines PBF there. That one content-addressed PBF is reused across areas and supplies both OSM places and managed roads.

Relevant stages:

```text
source.geofabrik_pbf
source.osm_national_pois
source.osm_area_index
source.overture_snapshot
places.osm_area
places.overture_area
```

> **Source-policy note.** The current implementation does **not** directly ingest Foursquare. It uses OSM + Overture Places, and the current Overture source policy excludes Foursquare-attributed records. If the research proposal refers to Foursquare as an example of an external business directory, that should be understood as conceptual source context rather than a statement that the present SIGMA code directly consumes Foursquare.

### 1.3 Canonical place reconciliation

OSM and Overture observations are reconciled into canonical places, reducing duplicate observations while preserving source provenance and audit information.

Relevant stage:

```text
places.canonical
```

### 1.4 PSIC classification and economic tagging

Canonical places are classified against the Philippine Standard Industrial Classification (PSIC) (stage 3). A narrow administrative-function rule reassigns unmistakable government health and education offices to PSIC 84120 and sends ambiguous names to review. PSIC is then mapped to IO240/IO80/IO16 candidates, and the public or private side of education and health industries is chosen only from strong ownership evidence (stage 4). Finally the places are grouped into the sectors of the area (stage 5). The ordinary `sigma load AREA` default is an area-specific hierarchical PSA 2018 IO240/IO80/IO16 economy. Fixed IO16, IO80, and IO240 resolutions can instead be selected with `--io-level`; custom economies use `--economy`. `Economy.default()` and areas without a recorded selection use IO80.

Relevant stages:

```text
classification.taxonomy
classification.tagging_references
places.psic
places.classified
```

The default classification path is deterministic. Optional OpenAI-assisted classification is available but not required.

The deterministic layer is data-driven and reviewed. Exact OSM/Overture category mappings and high-precision name patterns live in `src/sigma/resources/classification/crosswalks/psic_rev5_reviewed.csv`; compatible multi-tag OSM combinations live in `osm_compound_compatibility.csv`. Strong source categories take precedence, compatible auxiliary tags do not suppress a trusted mapping, and genuinely conflicting compound activities remain review candidates rather than being forced. Name rules can deterministically rescue otherwise weak or name-only records, but overlapping incompatible name rules fail closed as ambiguous.

### 1.5 Human MSME validation

After the place list has been generated and PSIC-tagged, **human review is expected and supported conceptually as a provenance boundary**.

A reviewer may open the resulting GeoParquet in QGIS, ArcGIS Pro, Python, or another GIS/data-review platform and:

- remove establishments that are irrelevant to the study;
- remove or flag establishments that are not MSMEs;
- correct obvious place-name or category errors where appropriate;
- retain only establishments that should participate in ecosystem analysis; and
- preserve the canonical identifiers, geometry, and economic classification fields needed by downstream SIGMA stages.

For downstream analysis, filtering non-MSMEs **out of the reviewed file** is currently safer than merely adding an `is_msme` flag, because the spatial pipeline clusters the rows it receives and does not presently apply a special MSME flag filter.

At minimum, a reviewed point file should preserve:

```text
canonical_id
geometry
CRS
economy_code
```

It is strongly preferable to retain the PSIC and source/provenance columns as well.

### 1.6 Road-network preparation

For ordinary area-mode analysis, no user road file is required. SIGMA uses a managed road source derived from the same shared Geofabrik Philippines PBF.

The managed-road procedure is:

1. resolve the selected area boundary;
2. select an appropriate local metre-based UTM CRS;
3. buffer the boundary by 5 km;
4. scan the PBF for the pinned motor-road classes in the vicinity;
5. project the selected road geometry;
6. clip the roads to the exact buffered polygon; and
7. build the routable road network used by spatial algorithms.

Relevant stage:

```text
transport.roads
```

A user-supplied projected road file remains available as an expert override, but it is not the expected workflow.

The 5 km buffered road network is an **internal analytical object**. Final GIS publication clips `sigma_roads.parquet` to the exact selected area boundary so the QGIS deliverable does not display out-of-bound analysis roads.

### 1.7 Network-constrained clustering

Classified establishments are snapped to the road network (stage 7) and clustered separately for each sector by network HDBSCAN* (stage 8): each sector may form one or more geographically distinct clusters. For generated hierarchies, a sector with no retained cluster can be merged into a broader sector (zero-cluster roll-up, stage 9). Each retained cluster is then tested once by network Gap k-medoids and split into road-medoid children where the Gap statistic supports it (stage 10). Every final cluster receives a network 1-median center (stage 11) and a network Voronoi territory (stage 12). The territory polygons are rendered on a grid that starts at 50 m and is halved until at most 0.5 % of the area changes owner between successive grids, within a 1,000,000-cell budget and five refinements.

Relevant stages:

```text
spatial.points
spatial.clusters
spatial.centers
spatial.point_distances
spatial.partitions
```

The outputs define localized business ecosystems as combinations of:

- economic type;
- cluster identity;
- network center;
- road-network accessibility; and
- spatial partition.

These clusters and partitions form the base MSME ecosystem map.

---

## 2. Network Influence Scoring

SIGMA then evaluates the structural importance of ecosystem nodes.

Each spatial-economic node is identified by the pair:

```text
(economic type, spatial cluster)
```

SIGMA constructs the X graph, computes tile-area-adjusted balanced Katz centrality (default), and transfers cluster centrality to establishments with full inverse-road-distance attenuation.

Relevant stages:

```text
analysis.x
analysis.centrality
analysis.scores
```

Each X edge carries a **gravity-inspired** weight: the directed technical coefficient times both clusters' shares of their exact sector's clustered establishments, divided by the mean hub-mediated road distance (exponent 1, not Newton's inverse square; the two notional masses are set to one). Tile area is not a term of this weight.

Canonical SIGMA centrality is **tile-area-adjusted balanced weighted directed Katz** on the full directed X graph. Total directed degree is regressed on final Voronoi area (km²) using pooled PPML, estimating $\hat\gamma$ for each geography. The two tile-perspective operators $FW$ and $FW^{\mathsf T}$ discount every tile's own incoming and outgoing connections by the same $A_i^{-\hat\gamma}$ factor. The original X weights and eligibility remain unchanged. Each run records the specification's diagnostics with the centrality stage and in `sigma_run_metadata.json` (`tile_area_adjustment`): the fitted exponent and its uncertainty, an unadjusted balanced-Katz comparison, score concentration, an area-decile table of degree and $f_ik_i$, and the in/out degree balance.

 Incoming and outgoing Katz components are computed unnormalized with the same attenuation parameters, combined nodewise by geometric mean, and normalized once at the end:

$$
C_i = \frac{\sqrt{K_i^{\mathrm{in}} K_i^{\mathrm{out}}}}{\sqrt{\sum_j K_j^{\mathrm{in}} K_j^{\mathrm{out}}}}.
$$

This retains direction and cycles while reducing pure-source and pure-sink dominance. The default attenuation uses `alpha_factor = 0.85` with `beta = 1`; the effective `alpha` is scaled safely from the graph's spectral radius (or a conservative safe scale for zero-radius/fallback cases). A weighted eigenvector rule is available as an explicit alternative and uses the positive-weight **undirected projection** of X.

Canonical point scores use **full inverse-road-distance decay**, $S_p=C_{c(p)}/\max(d_R(p,m_{c(p)})/(1\,\mathrm m),1)$; the earlier p90-scaled 15% tempering belongs only to legacy eigenvector scoring. This score is a modeling choice, not measured firm-level economic impact.

Conceptually:

```text
cluster influence
    ×
proximity to cluster center
    =
point-level acquisition influence score
```

This directly supports the project's **Network Influence Score** objective: identify businesses and ecosystem nodes that are structurally positioned to act as anchors, connectors, or high-leverage acquisition entry points.

---

## 3. Graph Link Prediction as Cluster-to-Cluster Structural Link Inference

Within SIGMA, the project milestone called **Graph Link Prediction** is implemented as **cluster-to-cluster structural link generation** in the X graph.

This is not a black-box probability model. Instead, SIGMA infers a directed connection from one ecosystem node to another when three conditions jointly support the link:

1. the source and target economic sectors have a positive directed relationship in the input-output economic graph;
2. their spatial partitions have positive-area overlap; and
3. their cluster centers are connected through the road network.

For each qualifying pair, SIGMA computes the exact shortest road distance between the cluster centers and instantiates a directed X-graph edge. The X graph stores this distance, not the route line; route lines are drawn later for display (see the end of this section).

The edge retains:

```text
source economic type
source cluster
target economic type
target cluster
technical coefficient
road distance
effective road distance (center route plus both mean member-to-median road radii)
combined edge weight
```

The canonical combined edge weight is:

```text
technical coefficient * (source_cluster_count / source_sector_clustered_count) * (target_cluster_count / target_sector_clustered_count) / max(mean_source_radius + center_road_distance + mean_target_radius, 1) ** x_distance_decay_lambda
```

The default `x_distance_decay_lambda = 1.0` gives inverse-road-distance attenuation, with a one-metre floor so the spatial factor stays in `(0, 1]`. The X weight is at most the economic coefficient; longer effective hub-mediated distances weaken rather than strengthen the modeled link. The exponent does not change `road_distance`. The X exponent is distinct from the geography-specific PPML degree–area exponent used only inside canonical Katz, and from the `alpha_factor = 0.85` Katz parameter. `distance_tempering = 0.15` is a legacy eigenvector-scoring compatibility setting, **not** canonical point scoring. Same-cluster self-edges remain omitted by the X topology policy. Changing the exponent invalidates `analysis.x` and its downstream centrality/score artifacts, not the upstream clusters, centers, roads, or economic graph.


This produces a **multi-relational or multiplex-like ecosystem graph**: economic dependence, spatial co-location, and transport connectivity are represented together. The implementation uses a directed graph (`DiGraph`) rather than a literal `MultiDiGraph`, but the analytical interpretation is multigraph-like because each connection is supported by multiple relationship dimensions.

Relevant economic stages:

```text
economy.definition
economy.transactions.raw
economy.transactions.effective
economy.coefficients
economy.graph
```

Relevant combined stage:

```text
analysis.x
```

This operationalizes the project's link-prediction objective by estimating **which localized economic ecosystems are structurally capable of linking to which other ecosystems, in which economic direction, and at what road distance**. For display, SIGMA publishes a compact routing graph (`sigma_routing_graph.bin`), and Explorer reconstructs the shortest road route of an edge on request and checks it against the stored distance. `--route-geometry precomputed` instead writes all route lines into the GeoPackage `paths` layer at export. Neither display mode changes the X graph or the scores.

---

## 4. Strategic Insights

The final milestone translates the analytical products into decision-support outputs.

SIGMA produces the components needed to identify:

- priority acquisition zones;
- high-density MSME ecosystems;
- influential ecosystem nodes;
- high-priority establishments;
- directed cluster-to-cluster relationships;
- economically related neighboring ecosystems;
- shortest road routes connecting linked ecosystems (drawn on request in Explorer);
- disconnected or unsupported candidate relationships; and
- spatial contexts for ecosystem-level product and acquisition strategy design.

The software does not prescribe a specific bank product. Instead, it provides the analytical structure on which Business Banking, Data Science, and strategy teams can design and validate ecosystem-specific acquisition and product bundles.

---

# End-to-End SIGMA Workflow

The complete **canonical area-mode** workflow separates source preparation,
economic-sector decisions, numerical analysis, and presentation. Conditional
steps are annotated; the same immutable artifacts may be reused across runs.

```text
sigma init: shared Geofabrik OSM and area boundary
    │
sigma load: OSM + Overture → reconcile → PSIC → IO candidates
    │
    ├─ optional post-load augmentation / human review of places handoff
    └─ baseline sparse IO240/80/16 sector partition (new area default)
    │
managed undirected roads → snap → network HDBSCAN per sector
    │                             └─ EOM → leaf on exception → Euclidean fallback
    │
    ├─ generated hierarchy only: original sectors with K=0 retained clusters
    │    → try residual-first iterative roll-up → rebuild effective economy
    │    → verify unrefined HDBSCAN counts for effective sectors
    └─ otherwise keep original economy / clusters
    │
network Gap k-medoids (one pass, default ON, up to 4 workers)
    │   └─ split eligible retained HDBSCAN clusters; noise remains noise
    ↓
final clusters → independent full-network 1-medians → point distances
    │                                              └─ network Voronoi partitions
    │
effective technical coefficients + positive-area overlap + center routing
    ↓
numerical X: coefficients × both clustered-sector shares / mean hub distance^λ
    ↓
tile-area-adjusted balanced incoming/outgoing Katz → inverse-road-distance establishment scores
    ↓
GIS/CSV/GeoParquet export → browser-native on-demand routes (default)
                        └─ precomputed path geometry by explicit option only
    ↓
sigma view: Explorer map / Under the Hood (read-only presentation)
```

The managed `analysis.x` artifact computes and stores **numerical** center
separations and X weights without generating shortest-path geometries. With
the default `--route-geometry browser`, a compact routing graph is published
and Explorer reconstructs routes when requested. Explicit
`--route-geometry precomputed` generates geographical route paths at export.
Neither visualization mode changes the numerical X graph or its scores.

---

# Human-in-the-Loop Review Workflow

SIGMA has an explicit three-part user lifecycle:

```text
install SIGMA
    ↓
sigma init
    ↓
prepare and review places
    ↓
run analysis
```

## 1. Required initialization

Before any workflow command, run:

```powershell
sigma init
```

SIGMA shows the shared data location before downloading anything and asks for confirmation. The default is intentionally visible:

```text
%USERPROFILE%\Documents\SIGMA
```

Initialization downloads the Philippines Geofabrik OSM PBF once. The same national source contains the OSM objects used for **places and roads**. Area-specific Overture Places are acquired later by place preparation.

All workflow commands are verbose by default and prefix progress with elapsed wall-clock time. Use the global quiet mode only when desired:

```powershell
sigma --quiet load quezon_city
sigma --quiet run quezon_city --workspace ".\workspaces\quezon_city"
```

## 2. Prepare, triangulate/reconcile, and label places

```powershell
sigma load quezon_city
```

This command owns the place branch only (stages 1–5): OSM + Overture acquisition, reconciliation into canonical places, PSIC classification with the administrative-office rule, IO tags with ownership evidence, and the sectors of the area. It then publishes the explicit handoff:

```text
<workspace>\places\places.parquet
```

The GeoParquet is deliberately user-visible and editable. A reviewer may open it in QGIS, ArcGIS Pro, Python, or another data tool, filter rows, remove irrelevant/non-MSME establishments, and save it **in place**. Preserve at least:

```text
canonical_id
geometry
CRS
economy_code
```

SIGMA preserves the original immutable managed place artifacts separately, so editing the handoff does not destroy provenance.

## 3. Run the analysis from that handoff

Only after the prepared GeoParquet exists:

```powershell
sigma run quezon_city
```

`run` does not acquire Overture or classify places. It consumes the exact current bytes of `<workspace>\places\places.parquet`, prepares or reuses roads, runs clustering, roll-up, Gap refinement, centers and partitions, builds the economic and X graphs, computes centrality and scores, and exports results (stages 6–17). If the GeoParquet has been filtered, the filtered file is the analysis input and its content hash invalidates the necessary descendants.

If `sigma run` is invoked before `sigma load`, it stops immediately and tells the user which GeoParquet is missing.

For ordinary area mode, managed roads are extracted on demand from the already initialized Philippines PBF. No second road download is required.

---

# Normal User Workflow

```powershell
# Once per installation / shared-data location
sigma init

# Discover/verify the area slug
sigma areas list --search "Quezon City"
sigma areas show quezon_city

# Once per area or whenever place sources/classification should be refreshed
sigma load quezon_city

# Optional human review/filtering of:
# %USERPROFILE%\Documents\SIGMA\workspaces\quezon_city\places\places.parquet

# Analysis and export
sigma run quezon_city

# Inspect cache/reuse state
sigma status quezon_city
```

For a **newly loaded area**, the default economic selection is hierarchical PSA 2018 IO240/IO80/IO16 (areas without a recorded selection use IO80). The other defaults are `transaction_preprocessing=none`, the full positive directed technical-coefficient graph, managed Geofabrik roads, network-first spatial methods with documented fallbacks, deterministic PSIC classification during `load`, balanced directed Katz centrality, and no LLM requirement. Generated hierarchies use zero-cluster roll-up after HDBSCAN*, every economy uses single-pass network Gap refinement with up to four worker processes, Voronoi territories start on a 50 m grid that is refined until ownership converges, and network X uses both clustered-sector shares and mean hub-mediated road separation before Katz centrality.

---

# Full CLI Command Surface

The current CLI is organized into coarse workflow commands plus exact-stage controls. When in doubt, `sigma --help` and `<command> --help` are authoritative for the installed version. Progress output is on by default; `sigma --quiet <command> ...` suppresses normal progress while preserving warnings/errors.

## General inspection and validation

### Version

```powershell
sigma --version
```

### Environment and dependency check

```powershell
sigma doctor
sigma doctor --json
```

### Classification-resource integrity check

```powershell
sigma classification-check
sigma classification-check --json
```

---

## Area catalog

The default catalog exposes **1,727 areas**: 1,493 municipalities, 149 cities, 82 provinces, and the three composites `metro_manila`, `metro_cebu`, and `metro_davao`. The packaged `areas.yml` defines 1,645 municipal, city and composite areas; provincial areas are derived from their `province` metadata. Each province is clipped to the exact union of its member PSGC locality polygons, rather than a bounding box. Localities without a province assignment, including independent highly urbanized cities, are excluded from administrative provinces.

### List every area

```powershell
sigma areas list
sigma areas list --kind province
sigma areas show palawan
sigma areas show cebu_province
sigma load palawan
sigma run palawan
```

For provinces sharing a name with a locality, use the `_province` suffix (for example, `cebu_province` or `leyte_province`).

### Search for possible matches

```powershell
sigma areas list --search "Quezon City"
sigma areas list --search "Pasig"
sigma areas list --search "Cebu"
```

### Filter by kind

```powershell
sigma areas list --kind city
sigma areas list --kind municipality
sigma areas list --kind province
sigma areas list --kind composite
```

### Print/save the complete catalog

```powershell
sigma areas list | Set-Content ".\sigma_areas.txt"
sigma areas list --json | Set-Content ".\sigma_areas.json"
```

### Use another catalog

```powershell
sigma areas list --areas-file ".\custom_areas.yml"
sigma areas list --areas-file ".\custom_areas.yml" --json
```

Options:

```text
--kind
--search
--areas-file
--json
```

### Show one exact area

```powershell
sigma areas show quezon_city
sigma areas show pasig
sigma areas show metro_manila
sigma areas show "National Capital Region"
sigma areas show quezon_city --areas-file ".\custom_areas.yml"
```

Resolution accepts exact slugs, names, aliases, and listed PSGC-code aliases. If you do not know the exact value, search first with `sigma areas list --search ...`.

---

## Load, reconcile, and label places

```powershell
sigma load AREA
```

Available options:

```text
--workspace PATH                 optional; defaults to <SIGMA home>/workspaces/<area>
--output-dir PATH                 optional; set durable export location at workspace creation
--areas-file FILE
--economy SPEC
--io-level 16|80|240             fixed national level instead of the per-area hierarchy
--refresh-geofabrik
--refresh-overture
--clip / --no-clip
--llm / --no-llm
--top-n INTEGER
--min-score FLOAT
--min-margin FLOAT
--force
--json
```

This stops after `places.classified` and publishes the editable handoff at `<workspace>/places/places.parquet`. It does not run the spatial/economic analysis.

---

## Road/network preparation

```powershell
sigma network prepare AREA --workspace PATH
```

This specialist stage command requires an explicit workspace.

Available options:

```text
--workspace PATH                 required
--roads FILE                     optional specialist override
--managed-roads                  explicit spelling of managed default
--roads-layer NAME
--economy SPEC
--force
--json
```

For ordinary area-mode use, omitting `--roads` selects the managed Geofabrik road source.

---

## Spatial analysis

```powershell
sigma spatial run AREA --workspace PATH
```

This specialist stage command requires an explicit workspace.

Available options:

```text
--workspace PATH                 required
--roads FILE
--managed-roads
--roads-layer NAME
--economy SPEC
--min-cluster-size INTEGER
--min-samples INTEGER
--classification VALUE
--classification-column NAME
--io80-column NAME
--io16-column NAME
--allow-single-cluster
--voronoi-resolution FLOAT       start grid spacing for stage 12, metres (default 50)
--force
--json
```

This command uses the default network Gap settings of stage 10; zero-cluster roll-up (stage 9) is part of `sigma run`. It prepares the spatial branch through:

```text
spatial.centers
spatial.point_distances
spatial.partitions
```

with `spatial.points` and `spatial.clusters` as prerequisites.

The default spatial policy is **network-first with graceful Euclidean fallback**:

```text
clustering:  network HDBSCAN EOM -> network HDBSCAN leaf (EOM exception only) -> Euclidean HDBSCAN EOM by road component
refinement:  network Gap k-medoids on each eligible retained cluster (one pass)
1-median:    network 1-median -> Euclidean centroid -> road/network snap fallback
Voronoi:     network Voronoi on a 50 m grid (coarser only to fit 1,000,000 cells)
             -> halve the grid and compare until <= 0.5% of the area changes owner,
                the cell budget is reached, or 5 refinements are made; keep the finest valid surface
             -> planar Euclidean Voronoi fallback only if the sector has no valid network surface
```

Fallback is automatic, not an opt-in CLI mode.  Verbose progress and managed diagnostics
record recoveries.  If both the network method and its fallback fail for one independent
type/cluster, SIGMA skips that unit where downstream invariants permit and continues with
the remaining viable units.

The Voronoi grid is refined even when the first grid succeeds, because a valid grid is not evidence that the polygons no longer depend on the spacing. `--voronoi-resolution` sets the start spacing only. `spatial.partitions/partition_diagnostics.json` records the spacing kept for each sector (`surface_resolution`) and one terminal event per sector with a network surface (`converged_resolution`, `retain_last_valid_network_resolution` or `max_refinements_reached`), so a non-empty event list is normal. In large study areas the cell budget allows fewer refinements: with the default budget, a bounding box larger than about 625 km² cannot be refined below 50 m, and its surface is kept without a convergence check. See [Network Voronoi](docs/book/content/methods/voronoi.md).

---

## Economy graph

```powershell
sigma economy graph AREA --workspace PATH
```

This specialist stage command requires an explicit workspace.

Available options:

```text
--workspace PATH                 required
--economy SPEC
--transaction-preprocessing VALUE
--equivalent
--mwas-method VALUE
--force
--json
```

Canonical default:

```text
--transaction-preprocessing none
```

Optional sparse balancing:

```text
--transaction-preprocessing mwas_ras_fast
```

With the canonical default `none`, SIGMA constructs the **full directed economic graph** from positive IO relationships. It does not remove cycles or reciprocal relationships and does not require a DAG. The `mwas_ras_fast` path is explicitly optional; `--equivalent` activates the preserved legacy-equivalent profile.

---

## Combined analysis

```powershell
sigma analysis run AREA --workspace PATH
```

This specialist stage command requires an explicit workspace.

Available options:

```text
--workspace PATH                 required
--roads FILE
--managed-roads
--roads-layer NAME
--economy SPEC
--transaction-preprocessing VALUE
--equivalent
--mwas-method VALUE
--centrality-method VALUE        katz (default) or eigenvector
--centrality-direction VALUE     compatibility option; balanced Katz uses both directions
--area-adjustment / --no-area-adjustment  Katz area correction on by default
--x-distance-decay-lambda FLOAT  X distance-decay exponent (default 1.0)
--distance-tempering FLOAT     legacy eigenvector scoring only (not canonical Katz)
--min-cluster-size INTEGER
--min-samples INTEGER
--allow-single-cluster
--voronoi-resolution FLOAT       start grid spacing for stage 12, metres (default 50)
--force
--json
```

This runs through:

```text
analysis.x
analysis.centrality
analysis.scores
```

Canonical `--centrality-method katz` computes raw incoming and outgoing directed Katz, combines them with the geometric mean, and performs one final L2 normalization. Use `--centrality-method eigenvector` only when the undirected-projection eigenvector centrality is wanted.

---

## Analysis/export run

```powershell
sigma run AREA --workspace PATH
```

`sigma load <area>` is the required predecessor. `run` consumes the editable loaded-place GeoParquet and never performs place acquisition or classification implicitly.

Available options:

```text
--workspace PATH                 optional; defaults to <SIGMA home>/workspaces/<area>
--roads FILE
--managed-roads
--roads-layer NAME
--output-dir PATH                must match the durable workspace setting
--areas-file FILE
--economy SPEC
--transaction-preprocessing VALUE
--equivalent
--mwas-method VALUE
--min-cluster-size INTEGER
--min-samples INTEGER
--median-gap / --no-median-gap   stage 10 Gap refinement (on; off with --equivalent)
--median-gap-max-k INTEGER       largest tested k (6)
--median-gap-replicates INTEGER  reference draws B (10)
--median-gap-max-sites INTEGER   members used for fitting per cluster (64)
--median-gap-seed INTEGER        base seed (20261105)
--median-gap-workers 1-4         maximum worker processes (default: 4)
--allow-single-cluster
--voronoi-resolution FLOAT       start grid spacing for stage 12, metres (default 50)
--centrality-method VALUE        katz (default) or eigenvector
--centrality-direction VALUE     compatibility option; balanced Katz uses both directions
--area-adjustment / --no-area-adjustment  Katz area correction on by default
--x-distance-decay-lambda FLOAT  X distance-decay exponent (default 1.0)
--distance-tempering FLOAT     legacy eigenvector scoring only (not canonical Katz)
--iterative-rollup / --no-iterative-rollup
                                 stage 9 zero-cluster roll-up (on for generated hierarchies)
--plan                           read-only stage plan (no analysis)
--through STAGE                  execute stage and dependencies only
--recompute STAGE                force one stage and affected descendants
--allow-expensive                opt in to rebuilding expensive cached stages
--refresh                        recompute analytical stages from the loaded places (guarded)
--force                          legacy: force only final scoring
--route-geometry VALUE           browser (default) or precomputed
--json
```

---

## Export an existing/ensured analysis

```powershell
sigma export AREA --workspace PATH
```

This specialist export command requires an explicit workspace.

Available options:

```text
--workspace PATH                 required
--roads FILE
--managed-roads
--roads-layer NAME
--output-dir PATH
--economy SPEC
--transaction-preprocessing VALUE
--equivalent
--mwas-method VALUE
--force
--route-geometry VALUE           browser (default) or precomputed
--json
```

---

## Browser visualization (`view` and `export-web`)

These commands **read already-published SIGMA output files**. They do not run clustering, IO modeling, X-graph construction, or point scoring. Run `sigma run AREA` first, or supply another valid published output directory.

```powershell
sigma view pasig                     # serve <output>\explorer locally
sigma view pasig --refresh           # force refresh before serving
sigma view pasig --no-browser        # serve without opening a browser
sigma view pasig --port 8766         # choose preferred local port
sigma export-web pasig               # generate a static local-profile bundle
sigma export-web pasig --public      # omit individual establishment records
```

Both commands accept `--workspace PATH`, `--source-dir PATH` (published SIGMA outputs), `--output-dir PATH` (web bundle), and `--roads/--no-roads`. `view` supports `--refresh`, `--fast`, `--port`, `--no-browser`, and `--public`; `export-web` supports `--force` and `--public`. Use `--help` for the complete options. `view` binds to localhost (`127.0.0.1`) rather than exposing data on the local network. The site must be served over HTTP, not opened using `file://`.

The full local profile contains individual establishment positions and attributes. The `--public` profile is a **reduction of exposed data**, not a certification that a dataset is safe to publish. Publishing externally requires separate attribution, source-license, confidentiality, and inference-risk checks. [Full Explorer documentation](SIGMA_EXPLORER.md).

---

## Inspect workflow status

```powershell
sigma status AREA --workspace PATH
sigma status AREA --workspace PATH --json
```

Available options:

```text
--workspace PATH                 optional; defaults to <SIGMA home>/workspaces/<area>
--roads FILE
--managed-roads
--roads-layer NAME
--economy SPEC
--transaction-preprocessing VALUE
--json
```

`status` is inspection-only and does not intentionally acquire or refresh sources merely to report status.

---

## Ensure one exact stage

```powershell
sigma stage AREA STAGE --workspace PATH
```

`--workspace` is required for exact-stage control.

Available options:

```text
--workspace PATH                 required
--roads FILE
--managed-roads
--roads-layer NAME
--economy SPEC
--transaction-preprocessing VALUE
--equivalent
--mwas-method VALUE
--force
--json
```

Example:

```powershell
sigma stage quezon_city places.classified `
  --workspace ".\workspaces\quezon_city"
```

or:

```powershell
sigma stage quezon_city analysis.x `
  --workspace ".\workspaces\quezon_city"
```

---

## Force recomputation of one stage

```powershell
sigma recompute AREA STAGE --workspace PATH
```

`--workspace` is required for exact-stage control.

Available options:

```text
--workspace PATH                 required
--roads FILE
--managed-roads
--roads-layer NAME
--economy SPEC
--transaction-preprocessing VALUE
--json
```

SIGMA recomputes the requested stage while preserving reusable prerequisites whose identities have not changed.

---

## Restart from previously computed spatial products

```powershell
sigma from-partitions `
  --workspace PATH `
  --partitions FILE `
  --centers FILE `
  --points-with-center-distance FILE `
  --roads FILE
```

Available options:

```text
--workspace PATH                         required
--partitions FILE                        required
--centers FILE                           required
--points-with-center-distance FILE       required; final sigma_points.parquet is accepted
--roads FILE                             required
--roads-layer NAME
--output-dir PATH
--economy SPEC
--mwas-method VALUE
--json
```

This command is primarily a compatibility/restart boundary and intentionally requires explicit road input.

---

# Managed Stage Catalog

The principal managed stages that may be inspected, ensured, or recomputed are:

```text
area.definition
area.boundary

source.geofabrik_pbf
source.osm_national_pois
source.osm_area_index
source.overture_snapshot

places.osm_area
places.overture_area
places.canonical
classification.taxonomy
classification.tagging_references
places.psic
places.classified

transport.roads

spatial.points
spatial.clusters
spatial.centers
spatial.point_distances
spatial.partitions

economy.definition
economy.transactions.raw
economy.transactions.effective
economy.coefficients
economy.graph
economy.graph.legacy_mwas

analysis.x
analysis.centrality
analysis.scores

export.bundle
```

Not every stage is available in every execution mode. For example, restart/custom-input modes expose only the stages supported by their supplied inputs.

---

# Principal Exported Outputs

A complete area-mode export may include:

```text
pois.parquet
ATTRIBUTION.txt
DATABASE_LICENSE.txt
run.json

sigma_points.parquet
sigma_network_centers.parquet
sigma_partitions.parquet
sigma_roads.parquet
sigma_boundary.parquet
<area>.qgz

sigma_economic_graph.csv
# or sigma_io_dag.csv under the legacy-equivalent profile

sigma_X_nodes.csv
sigma_X_edges.csv
sigma_disconnected_overlap_pairs.csv
sigma_spatial_outputs.gpkg
sigma_routing_graph.bin

sigma_run_metadata.json
sigma_manifest.json
OUTPUTS.txt
```

`sigma view AREA` and `sigma export-web AREA` additionally create a derived `explorer/` or `explorer-public/` browser bundle under the output directory. These are **visualization products**, not new analytical stages, and do not replace the GeoPackage or QGIS project. See the [Explorer guide](SIGMA_EXPLORER.md).

All published GIS layers are normalized to **EPSG:4326 / WGS 84**. Internal routing, snapping, clustering distance, center, and network calculations continue to use an appropriate metric projected CRS where required.

The published road layer is clipped to the exact area boundary; the wider buffered road network remains an internal analytical artifact.

### Interpretation

- `pois.parquet` — exact classified/reviewed place handoff consumed by the analysis, published with type annotations.
- `sigma_points.parquet` — the **single canonical analyzed establishment layer**, combining type/cluster assignment, scalar clustering diagnostics, center distance, incoming/outgoing raw Katz components, balanced centrality, and final `sigma_score`.
- `sigma_network_centers.parquet` — one network center for each viable `(type, cluster)` ecosystem node.
- `sigma_partitions.parquet` — spatial ecosystem partitions; QGIS exposes these as one filtered layer per economic type.
- `sigma_roads.parquet` — publication road layer clipped to the exact administrative/composite boundary.
- `sigma_boundary.parquet` — selected analysis boundary.
- `<area>.qgz` — ready-to-open QGIS project using relative GeoParquet paths, one categorized `sigma_points` layer, per-type partition layers, centers, clipped roads, and boundary.
- `sigma_economic_graph.csv` — full directed sector-level economic relationships under the canonical profile.
- `sigma_io_dag.csv` — legacy-equivalent MWAS/DAG economic output when that profile is explicitly selected.
- `sigma_X_nodes.csv` — cluster-level spatial-economic nodes and graph measures, including final tile area (`voronoi_area_km2`), tile-area factor (`area_factor`) and raw incoming/outgoing Katz.
- `sigma_X_edges.csv` — inferred directed cluster-to-cluster links with economic and road-distance attributes.
- `sigma_disconnected_overlap_pairs.csv` — candidate links that fail road-network connectivity.
- `sigma_spatial_outputs.gpkg` — GIS-ready partitions, X nodes, and a `paths` layer that is empty in the default browser route mode and filled with `--route-geometry precomputed`.
- `sigma_routing_graph.bin` — compact routing graph (road vertices and cluster centers only, no establishment positions) from which Explorer draws shortest routes on request.
- `sigma_run_metadata.json` — workflow/profile counts, CRS metadata, artifact IDs, run summary, and the stage 15 `tile_area_adjustment` diagnostics.
- `sigma_manifest.json` — reproducible lineage and file manifest for the exported bundle.

### QGIS presentation

The QGIS project uses SIGMA's fixed 336-sector color specification (IO16, IO80 and IO240 colors; residual `o` sectors use their parent's color). `sigma_points` is categorized by mutually exclusive economic `type` and marker size follows `sigma_score`. Canonical inverse-distance scores can be very small, so canonical runs use a display-only 5th–95th percentile size range and the label expression:

```text
concat("canonical_name", ' - ', format_number("sigma_score", 10))
```

Explicit legacy eigenvector runs keep the former label, `concat("canonical_name", '-', round(100 * "sigma_score", 2))`. Neither setting changes `sigma_score`.

Partition layers are present per type but start unchecked. Centers remain one layer. Roads and boundary are visible by default.

---

# Methodology-to-Output Traceability

| Methodology milestone | Core SIGMA stages | Main outputs | Business interpretation |
|---|---|---|---|
| Geospatial Ecosystem Discovery | `places.*`, `transport.roads`, `spatial.points`, `spatial.clusters`, `spatial.centers`, `spatial.partitions` | classified POIs, clusters, centers, partitions | Where are the localized MSME ecosystems? |
| Network Influence Scoring | `analysis.x`, `analysis.centrality`, `analysis.scores` | X nodes, point centrality/scores | Which ecosystem nodes and establishments are influential acquisition entry points? |
| Graph Link Prediction / Structural Link Inference | `economy.graph`, `analysis.x` | X edges, road distances, routing graph, disconnected-pair audit | Which ecosystems are structurally linked, in what direction, and by what spatial-economic pathway? |
| Strategic Insights | `export.bundle` | GeoPackage, GeoParquet, CSVs, manifests | Which zones and MSMEs should be prioritized, and what ecosystem relationships should strategy teams investigate? |

---

# Recommended Project Interpretation

SIGMA should be described as an **end-to-end geocomputation toolkit for MSME ecosystem discovery, network influence analysis, and spatial-economic graph modeling**.

The system's distinctive contribution is not any single clustering or centrality algorithm. It is the integration of:

```text
place evidence
+ economic classification
+ road-network geography
+ spatial clustering
+ input-output structure
+ cluster-to-cluster link inference
+ influence scoring
+ reproducible artifact lineage
```

into one coherent, restartable analytical workflow.

The human analyst remains part of that workflow. In particular, the point between **PSIC/economy classification** and **ecosystem analysis** is an appropriate review gate for deciding which establishments are actually relevant MSMEs before they influence clustering, graph construction, and acquisition scores.
