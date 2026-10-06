# Spatial Intelligence and Graph Modeling for MSME Acquisition (SIGMA)

[![Documentation](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://miraflor.github.io/sigma/)

Methodological documentation: **[SIGMA Jupyter Book](https://miraflor.github.io/sigma/)** · publishing instructions: [`GITHUB_PAGES.md`](GITHUB_PAGES.md).


## Project Summary

**Spatial Intelligence and Graph Modeling for MSME Acquisition (SIGMA)** is an end-to-end geocomputation framework for identifying, modeling, and prioritizing localized MSME ecosystems.

The project applies geospatial analytics, network analysis, input-output economics, and graph-based modeling to shift MSME acquisition from an individual, location-based approach toward an **ecosystem-driven, network-aware strategy**. Rather than treating each establishment as an isolated prospect, SIGMA identifies geographically concentrated business ecosystems, classifies establishments by economic activity, models spatial and economic relationships among clusters, identifies influential ecosystem nodes, and produces cluster-to-cluster links that indicate where one ecosystem is structurally connected to another.

The intended business use is to support more precise MSME targeting, lower acquisition effort, improve lead quality, identify influential businesses that can serve as acquisition entry points, and inform ecosystem-specific product and engagement strategies.

SIGMA is designed so that the computational pipeline and the business decision layer remain distinct. The software produces reproducible geospatial, network, economic, and scoring outputs; bank-specific judgments such as whether a location is underserved, whether a business qualifies as an MSME, and which product bundle should be offered may be incorporated as human-reviewed or downstream decision inputs.

---

## Objectives

The main objective of SIGMA is to enable the design of **ecosystem-specific MSME acquisition strategies** by identifying spatially concentrated business systems, estimating how those systems are connected, and ranking influential businesses within them.

The project objectives map to the implemented SIGMA pipeline as follows:

| Project objective | SIGMA implementation |
|---|---|
| 1. Identify emerging MSME ecosystem clusters with strong economic potential but underserved by BPI | Place acquisition and reconciliation; PSIC classification; PSIC-to-IO mapping; road-network preparation; network-constrained clustering; cluster centers; Voronoi/partition construction. Bank coverage/underservice is a downstream overlay or reviewed attribute rather than a hard-coded SIGMA rule. |
| 2. Develop a Network Influence Score to identify key connectors or anchors within local business ecosystems | The spatial-economic **X graph**, weighted centrality, and distance-tempered point scoring identify influential cluster nodes and establishments. |
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
- point-level scoring with distance tempering;
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
sigma status --help
sigma analysis run --help
```

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

SIGMA ships with a canonical Philippine area catalog containing **1,645 areas**:

```text
1,493 municipalities
149 cities
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
OSM places from the initialized national PBF
+
Overture Places for the area
    ↓
source reconciliation / canonical places
    ↓
deterministic PSIC classification
    ↓
PSIC → selected economy mapping
    ↓
editable places handoff
```

The default handoff is:

```text
%USERPROFILE%\Documents\SIGMA\workspaces\pasig\places\places.parquet
```

The default economy is PSA 2018 IO80. Deterministic classification is the default; the optional LLM path is off.

Useful variants:

```powershell
# Built-in IO16 economy instead of the default IO80
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

---

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
managed Geofabrik road network
network-first clustering with graceful Euclidean fallback
network 1-median with fallback
network Voronoi with refinement + planar fallback
PSA 2018 IO80
full directed IO graph
transaction preprocessing = none
balanced directed Katz centrality
QGIS/GeoParquet publication in EPSG:4326
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

The default attenuation is derived from `alpha_factor = 0.85`; `beta = 1`. The older weighted eigenvector method remains available explicitly.

Common run variants:

```powershell
# Explicit canonical Katz (already the default)
sigma run pasig --centrality-method katz

# Legacy eigenvector option on the positive-weight undirected projection of X
sigma run pasig --centrality-method eigenvector

# Change point-score distance tempering
sigma run pasig --distance-tempering 0.10

# Change clustering thresholds
sigma run pasig --min-cluster-size 8 --min-samples 4

# Allow a type to form one cluster when appropriate
sigma run pasig --allow-single-cluster

# Optional fast MWAS+RAS transaction preprocessing
sigma run pasig --transaction-preprocessing mwas_ras_fast

# Legacy Engine-equivalent profile
sigma run pasig --equivalent --mwas-method fast

# Force recomputation under the requested configuration
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
| Run full analysis/export | `sigma run pasig` |
| Inspect cache/stage state | `sigma status pasig` |
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

Canonical places are classified against the Philippine Standard Industrial Classification (PSIC), then mapped into the selected economic sector system. The default economy is PSA 2018 IO80; built-in IO16 and custom economies are also supported.

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

Classified establishments are normalized to the selected economic sector identity and clustered over the road-network context. Clustering is type-wise: each economic type may form one or more geographically distinct clusters.

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

SIGMA constructs the X graph, computes network centrality, and propagates cluster influence to individual establishments through a distance-tempered point score.

Relevant stages:

```text
analysis.x
analysis.centrality
analysis.scores
```

Canonical SIGMA centrality is **balanced weighted directed Katz** on the full directed X graph. Incoming and outgoing Katz components are computed unnormalized with the same attenuation parameters, combined nodewise by geometric mean, and normalized once at the end:

\[
C_i = \operatorname{L2Normalize}\left(\sqrt{K_i^{in}K_i^{out}}\right).
\]

This retains direction and cycles while reducing pure-source and pure-sink dominance. The default attenuation uses `alpha_factor = 0.85` with `beta = 1`; the effective `alpha` is scaled safely from the graph's spectral radius (or a conservative safe scale for zero-radius/fallback cases). The previous weighted eigenvector rule remains available explicitly and uses the positive-weight **undirected projection** of X.

Point scores are then tempered by a business's road-network distance from its cluster center.

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

For each qualifying pair, SIGMA computes the exact shortest road path between cluster centers and instantiates a directed X-graph edge.

The edge retains:

```text
source economic type
source cluster
target economic type
target cluster
technical coefficient
road distance
road path
combined edge weight
```

The canonical combined edge weight is:

```text
technical coefficient × road distance
```

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

This operationalizes the project's link-prediction objective by estimating **which localized economic ecosystems are structurally capable of linking to which other ecosystems, in which economic direction, and through what road path**.

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
- shortest-road paths connecting linked ecosystems;
- disconnected or unsupported candidate relationships; and
- spatial contexts for ecosystem-level product and acquisition strategy design.

The software does not prescribe a specific bank product. Instead, it provides the analytical structure on which Business Banking, Data Science, and strategy teams can design and validate ecosystem-specific acquisition and product bundles.

---

# End-to-End SIGMA Workflow

The complete conceptual workflow is:

```text
Select Philippine area
        ↓
Resolve exact boundary
        ↓
Ensure shared Geofabrik Philippines PBF
        ↓
Acquire OSM places + Overture Places
        ↓
Reconcile duplicate observations
        ↓
Canonical place list
        ↓
PSIC classification
        ↓
PSIC → IO/economy mapping
        ↓
────────────────────────────────────────────
HUMAN MSME REVIEW BOUNDARY
Review GeoParquet externally
Remove irrelevant/non-MSME establishments
Preserve IDs, geometry, CRS, PSIC/economy fields
────────────────────────────────────────────
        ↓
Extract managed Geofabrik roads
        ↓
Network-constrained clustering by economic type
        ↓
Cluster centers + point distances + partitions
        ↓
Directed input-output economic graph
        ↓
Cluster-to-cluster structural link inference (X graph)
        ↓
Centrality / Network Influence Score
        ↓
Point-level distance-tempered influence score
        ↓
GIS + tables + paths + manifests
        ↓
Strategic interpretation:
priority zones, anchor MSMEs, ecosystem links,
acquisition sequencing, product-bundle design
```

---

# Human-in-the-Loop Review Workflow

SIGMA now has an explicit three-part user lifecycle:

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

This command owns the place branch only: OSM + Overture acquisition, reconciliation into canonical places, PSIC classification, and mapping to the selected economy. It then publishes the explicit handoff:

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

`run` no longer acquires Overture or classifies places. It consumes the exact current bytes of `<workspace>\places\places.parquet`, prepares/reuses roads, runs spatial clustering/centers/partitions, builds the economic and X graphs, computes centrality/scores, and exports results. If the GeoParquet has been filtered, the filtered file is the analysis input and its content hash invalidates the necessary descendants.

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

Default analysis behavior is PSA 2018 IO80, `transaction_preprocessing=none`, the full directed IO graph, managed Geofabrik roads, network-first spatial methods with graceful fallbacks, deterministic PSIC classification during `load`, balanced directed Katz centrality, and no LLM requirement.

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

The packaged catalog currently contains **1,645 areas**: 1,493 municipalities, 149 cities, and the three composites `metro_manila`, `metro_cebu`, and `metro_davao`.

### List every area

```powershell
sigma areas list
```

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
--voronoi-resolution FLOAT
--force
--json
```

This prepares the spatial branch through:

```text
spatial.centers
spatial.point_distances
spatial.partitions
```

with `spatial.points` and `spatial.clusters` as prerequisites.

The default spatial policy is **network-first with graceful Euclidean fallback**, preserving
the sigma-engine behavior:

```text
clustering:  network HDBSCAN -> Euclidean HDBSCAN fallback by road component
1-median:    network 1-median -> Euclidean centroid -> road/network snap fallback
Voronoi:     network Voronoi -> finer network retries -> planar Euclidean Voronoi fallback
```

Fallback is automatic, not an opt-in CLI mode.  Verbose progress and managed diagnostics
record recoveries.  If both the network method and its fallback fail for one independent
type/cluster, SIGMA skips that unit where downstream invariants permit and continues with
the remaining viable units.

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
--distance-tempering FLOAT
--min-cluster-size INTEGER
--min-samples INTEGER
--allow-single-cluster
--voronoi-resolution FLOAT
--force
--json
```

This runs through:

```text
analysis.x
analysis.centrality
analysis.scores
```

Canonical `--centrality-method katz` computes raw incoming and outgoing directed Katz, combines them with the geometric mean, and performs one final L2 normalization. Use `--centrality-method eigenvector` only when the older undirected-projection centrality is desired.

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
--allow-single-cluster
--voronoi-resolution FLOAT
--centrality-method VALUE        katz (default) or eigenvector
--centrality-direction VALUE     compatibility option; balanced Katz uses both directions
--distance-tempering FLOAT
--force
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
--json
```

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

sigma_run_metadata.json
sigma_manifest.json
OUTPUTS.txt
```

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
- `sigma_X_nodes.csv` — cluster-level spatial-economic nodes and graph measures.
- `sigma_X_edges.csv` — inferred directed cluster-to-cluster links with economic and road-distance attributes.
- `sigma_disconnected_overlap_pairs.csv` — candidate links that fail road-network connectivity.
- `sigma_spatial_outputs.gpkg` — GIS-ready partitions, X nodes, and X paths.
- `sigma_run_metadata.json` — workflow/profile counts, CRS metadata, artifact IDs, and run summary.
- `sigma_manifest.json` — reproducible lineage and file manifest for the exported bundle.

### QGIS presentation

For the built-in IO80 economy, the QGIS project uses the reviewed 80-sector color palette. `sigma_points` is categorized by mutually exclusive economic `type`, marker size follows `sigma_score`, and the point label expression is equivalent to:

```text
concat("canonical_name", '-', round(100 * "sigma_score", 2))
```

Partition layers are present per type but start unchecked. Centers remain one layer. Roads and boundary are visible by default.

---

# Methodology-to-Output Traceability

| Methodology milestone | Core SIGMA stages | Main outputs | Business interpretation |
|---|---|---|---|
| Geospatial Ecosystem Discovery | `places.*`, `transport.roads`, `spatial.points`, `spatial.clusters`, `spatial.centers`, `spatial.partitions` | classified POIs, clusters, centers, partitions | Where are the localized MSME ecosystems? |
| Network Influence Scoring | `analysis.x`, `analysis.centrality`, `analysis.scores` | X nodes, point centrality/scores | Which ecosystem nodes and establishments are influential acquisition entry points? |
| Graph Link Prediction / Structural Link Inference | `economy.graph`, `analysis.x` | X edges, road paths, disconnected-pair audit | Which ecosystems are structurally linked, in what direction, and by what spatial-economic pathway? |
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
