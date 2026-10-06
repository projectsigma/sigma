# SIGMA Unified Architecture

**Status:** implemented architecture for `sigma` 0.1.0.dev0.

SIGMA is one Python package for place acquisition and classification, road-network spatial analysis,
economic input-output modeling, and combined spatial-economic graph analysis. The public `Sigma`
facade coordinates domain pipelines; algorithms remain in domain modules and durable state is owned
by a workspace/artifact layer.

## Design principles

- One canonical area catalog and exact-boundary implementation.
- One shared content-addressed source store for external source snapshots.
- One dependency-aware stage graph with explicit artifact identities and selective recomputation.
- Domain algorithms stay separate from orchestration.
- Deterministic processing is the default; OpenAI-assisted classification is optional.
- The default economy is PSA 2018 IO80; IO16 is also built in.
- Transaction preprocessing defaults to `none`; `mwas_ras_fast` is optional.
- The economic graph is directed and may contain reciprocal edges and cycles.
- Managed roads from the shared Philippines Geofabrik PBF are the normal area-mode road source.
  A user-supplied projected road dataset is an explicit override.
- Compatibility readers/exporters are retained only where they preserve useful data/restart contracts;
  the former two-repository orchestration boundary is not shipped.

## Public surface

`Sigma(area, workspace=...)` is the normal entry point. It exposes coarse operations for place
preparation, network preparation, spatial analysis, economy preparation, final analysis, export,
status, exact-stage execution, and targeted recomputation. `Sigma.from_inputs(...)` and
`Sigma.from_partitions(...)` support explicit custom/restart inputs.

The CLI is intentionally thin and delegates to the same public Python API rather than maintaining a
second workflow implementation.

## State and execution

A `SigmaWorkspace` records the semantic area identity, source-store location, configuration identity,
and active artifact references. Derived outputs are immutable artifacts managed by `ArtifactStore`.
Each stage has:

- explicit dependencies;
- an implementation/schema version;
- source/resource identities;
- normalized parameters; and
- deterministic output metadata.

`ExecutionPlanner` recursively ensures prerequisites. An artifact is reused only when its recipe and
dependencies still match. Changing a narrow parameter therefore invalidates only that stage and its
descendants.

The principal managed stages are grouped as follows:

- **area/source:** area definition/boundary, Geofabrik PBF, OSM preparation, Overture snapshot;
- **places:** source clips, reconciliation, PSIC classification, economy tagging;
- **transport/spatial:** roads, normalized points, clusters, centers, point distances, partitions;
- **economy:** definition, raw/effective transactions, coefficients, directed economic graph;
- **analysis:** spatial-economic X graph, centrality, point scores; and
- **export:** the unified output bundle and manifest.

## Shared sources and roads

`SourceStore` owns immutable external source snapshots. The Philippines Geofabrik PBF is downloaded
lazily when a stage first requires it, stored once, content-identified, and reused by both OSM place
preparation and managed-road extraction.

For managed roads, SIGMA resolves the exact area boundary, selects a local metre-based UTM CRS,
buffers the boundary by 5 km, scans the PBF for the pinned motor-road classes in the corresponding
vicinity, projects the selected linework, and clips it to the exact buffered polygon. The buffer
allows legitimate shortest paths near administrative edges to leave and re-enter the selected area.
The current routing graph is undirected; OSM `oneway` is retained as audit metadata rather than used
to direct routing.

`FileRoadSource` remains supported for specialists who need to supply a projected road network. It is
an override, not the expected default workflow, and SIGMA does not claim numerical equivalence
between an arbitrary file road source and the managed Geofabrik extraction.

## Place classification

The place branch combines OSM and Overture observations, reconciles them into canonical places, then
classifies them against a separate `PsicTaxonomy` and selected `Economy`.

The bundled production classification resources are deliberately small and explicit:

- the bundled `psic_rev5.csv` classification audit/frequency table; deterministic runtime place-to-PSIC rules are maintained in `classification/source_rules.py`;
- PSIC Rev. 5 taxonomy nodes and official workbook;
- the Rev. 5-to-2019 bridge; and
- the 2019 PSIC-to-2018 IO concordance.

Suggestion/audit CSVs are not runtime
package resources. The classification manifest hashes every bundled production/reference asset.

## Economy and analysis

`Economy` represents sector codes/labels plus the numerical input-output system. PSIC is intentionally
separate from `Economy`; mapping resources connect the taxonomy to the chosen economy.

With the default `transaction_preprocessing="none"`, raw transactions are used directly and technical
coefficients are computed from that effective table. Optional `mwas_ras_fast` uses fast MWAS only as
a sparse-support proposal, repairs support deterministically when required, balances retained support
with RAS/IPF to preserve row and column margins, and then recomputes technical coefficients.

The canonical economic graph retains positive directed support, including reciprocal relationships and
cycles. The X graph instantiates qualifying economic relationships across spatial clusters using road
network distances. Centrality and point scoring are separate downstream stages so their policy changes
can be recomputed without rebuilding spatial/economic prerequisites.

## Resources and outputs

Packaged resources under `src/sigma/resources/` are product inputs, not build artifacts. They include
the Philippine area catalog/boundaries, PSIC reference data, classification crosswalks, and PSA 2018
IO16/IO80 resources.

Unified exports include spatial/economic tables and GIS outputs plus `sigma_manifest.json`, which
records artifact lineage for reproducibility. Compatibility publication remains available where it
preserves established downstream data contracts.
