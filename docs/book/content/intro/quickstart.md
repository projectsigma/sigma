# Quickstart

SIGMA's ordinary area-mode workflow is intentionally short at the command line. The analytical detail lives in the stages and their artifact manifests rather than in a long list of mandatory arguments.

## 1. Install

From a source checkout:

```bash
python -m pip install -e .
```

For development:

```bash
python -m pip install -e ".[dev]"
```

## 2. Initialize shared source data

```bash
sigma init
```

Initialization creates SIGMA's shared data directory and prepares the national Geofabrik Philippines PBF used by both OSM place extraction and managed roads.

## 3. Load, then run an area

Load places before running analysis. For example:

```bash
sigma load pasig
sigma run pasig
```

`sigma load` runs stages 1–5: it acquires and reconciles OSM/Overture establishments, classifies their activity, attaches IO tags and ownership evidence, and writes the editable `places/places.parquet` handoff. `sigma run` runs stages 6–17 and publishes the results. Without `--io-level` or
`--economy`, it also builds a **per-area hierarchical PSA 2018 economy** from
the packaged IO240 reference: exact IO240 sectors where supported, with IO80,
IO16, and residual groups elsewhere. The hierarchical settings
(`coarse_policy=residual`, `min_places=5`) are recorded under the SIGMA
data directory and the area selection is recorded in `economy-selection.json`.
To choose a fixed national resolution instead, use one of:

```bash
sigma load pasig --io-level 16
sigma load pasig --io-level 80
sigma load pasig --io-level 240
```

These are alternatives to, not additional steps after, the default load.
Fixed IO240 retains only exact IO240 tags as assigned establishments. A custom
`--economy` is also supported and is mutually exclusive with `--io-level`.
`sigma run` follows the selection made by `sigma load`; **a workspace without a recorded selection keeps IO80 and is not silently converted to a hierarchy**. See
[Hierarchical economy](../methods/hierarchical.md) and the
[load selection guide](https://github.com/projectsigma/sigma/blob/main/docs/SIGMA_LOAD_PORTABILITY.md).

### Zero-cluster roll-up at `sigma run` (stage 9)

For a generated **hierarchical** area, `sigma run pasig` merges a sector into an existing residual only when the sector has **zero retained HDBSCAN* clusters** and the merge strictly increases the number of retained establishments. This is separate from the `min_places=5` support rule of `sigma load`: a sector that ends with only 5–9 places passes that rule but cannot form a cluster under the default HDBSCAN* settings. To keep exactly the stage 5 sectors:

```bash
sigma run pasig --no-iterative-rollup
```

`sigma run pasig --iterative-rollup` requests the default explicitly. Fixed `--io-level 16`, `80`, `240` and custom economies are not rolled up. Rerunning with a different switch changes analytical results; displaying an already-published run does not trigger clustering.

The ordinary selected-economy run uses:

- `transaction_preprocessing=none` and the full positive directed technical-coefficient graph;
- deterministic PSIC classification at `load` (not again at `run`);
- managed Geofabrik roads;
- type-wise road-network HDBSCAN* (stage 8; its unrefined results decide the hierarchical K=0 roll-up of stage 9);
- **default-on, single-pass Gap k-medoid refinement** of retained clusters using **up to four worker processes** (stage 10);
- network-node 1-median cluster centers, computed for every final cluster (stage 11);
- network-Voronoi surface partitions (stage 12);
- X weights based on technical coefficients, both clustered-sector shares, and mean hub-mediated road distance (stages 13–14);
- balanced sender-receiver weighted Katz (stages 15–16);
- establishment distance tempering `lambda = 0.15` (stage 17); and
- browser route publication: a compact routing graph, with routes drawn on request (`--route-geometry precomputed` writes all routes at export instead).

Use `sigma run pasig --no-median-gap` to compare the original HDBSCAN
partition, or `--median-gap-workers 1` to use the same refinement serially.
The legacy `--equivalent` profile stays unrefined unless Gap is explicitly enabled.
[Gap refinement](../methods/network_gap_medians.md) gives the selection rule,
search limits and auditing fields. These switches change the requested run,
not an already-published Explorer bundle.

Use `sigma run pasig --refresh` only when downstream recomputation is actually
needed from loaded places; it does not reclassify establishments. A matching
immutable artifact cannot be overwritten with different output bytes.
Use `sigma view pasig --refresh` to rebuild only the browser bundle. These are
different operations.

### Optional: add user-supplied places after `sigma load`

To combine an existing loaded area with a registry or another CSV/Parquet source, run `sigma augment` **after** `sigma load` and **before** `sigma run`:

```bash
sigma load quezon_city
sigma augment quezon_city path/to/registry.csv --source company_registry --check
sigma augment quezon_city path/to/registry.csv --source company_registry
sigma run quezon_city
```

`--check` validates the input and previews matches without writing. Required columns are `source_id`, `name`, `lon`, `lat`; optional `io16`, `io80`, and `io240` columns allow explicit hierarchical IO classification, and arbitrary extra fields are preserved for later use. See [Augment user-provided places](../methods/augmentation.md) for the complete contract and conflict handling.

## 4. Inspect the published results

```bash
sigma status pasig
sigma view pasig
```

`view` opens **[SIGMA Explorer](explorer.md)**, a local browser map synchronized with the directed cluster network. In the default browser-routing mode, a Web Worker reconstructs exact center-to-center road paths on demand and validates their lengths against published X distances. Only explicit `sigma run AREA --route-geometry precomputed` creates per-edge GIS route geometries at export. The analysis is not rerun. For traditional GIS inspection, open `pasig.qgz` in the workspace output directory. To generate a portable static bundle, use `sigma export-web pasig`; `--public` omits establishment-level records but still requires publication review.

The artifact DAG means a repeated run does not blindly rerun every computation. A stage is reused when the recipe fingerprint and stored files still match the requested inputs, parameters, source identities, and implementation version.

## 5. Inspect storage without disturbing results

```bash
sigma storage report                 # disk inventory and largest files
sigma storage prune                  # preview; does not delete
sigma storage prune --apply          # aged, abandoned temporary files only
sigma storage report --obsolete      # optionally review historical artifacts
```

Shared OSM node-location indexes are discarded after extraction; versioned artifacts and
published Explorer/QGIS outputs are retained. The `--obsolete` flag is a separate,
explicit decision that may sacrifice older-run reproducibility. See the
[storage and retention guide](../reproducibility/storage.md) before opting in.

## Read one run as a scientific object

A useful way to audit a result is to follow this sequence:

1. verify the selected area and exact boundary;
2. inspect source counts and canonical-place matching diagnostics, including any augmentation source;
3. inspect PSIC classification, administrative-office changes (`admin_activity_status`), ownership evidence (`institution_promotion_status`), area sectors (`economy_status`, `economy_review_required`) and any human-reviewed point file;
4. inspect road snapping and disconnected components;
5. inspect baseline HDBSCAN cluster/noise and adaptive-distance diagnostics;
6. for generated hierarchies, inspect K=0 roll-up decisions, original/effective sectors, then `median_gap_audit.json` and final child IDs;
7. inspect `center_method` and `surface_method` for fallbacks;
8. inspect the effective transaction table and technical coefficients;
9. inspect X-edge overlap, road distance, and weight;
10. inspect `katz_in_raw`, `katz_out_raw`, and final centrality; and
11. inspect establishment distance tempering and final `sigma_score`.

The remainder of this book explains why each item exists and how it is computed.
