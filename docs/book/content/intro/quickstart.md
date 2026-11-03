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

`sigma load` acquires and reconciles OSM/Overture establishments, classifies them,
and writes the editable `places/places.parquet` handoff. Without `--io-level` or
`--economy`, it also builds a **per-area hierarchical PSA 2018 economy** from
the packaged IO240 reference: exact IO240 sectors where supported, with IO80,
IO16, and residual groups elsewhere. New hierarchical profiles use
`coarse_policy=residual` and `min_places=5`; they are recorded under the SIGMA
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
`sigma run` follows the selection made by `sigma load`; **existing unselected
legacy IO80 workspaces are not silently converted to hierarchy**. See
[Hierarchical economy](../methods/hierarchical.md) and the
[load selection guide](https://github.com/projectsigma/sigma/blob/main/docs/SIGMA_LOAD_PORTABILITY.md).

<!-- sigma-docs-20261104-v1:begin -->
### Default zero-cluster roll-up at `sigma run`

For a newly generated **hierarchical** area, `sigma run pasig` now attempts
residual-first iterative roll-up only for economic sectors with **zero
retained HDBSCAN clusters**, accepting valid coarsening under its positive
net-retention rule. This is distinct from the `sigma load` hierarchy's
`min_places=5` support rule. To keep precisely the baseline hierarchy:

```bash
sigma run pasig --no-iterative-rollup
```

To request the same default explicitly, use
`sigma run pasig --iterative-rollup`. Fixed `--io-level 16`, `80`, `240`
and custom economies are not rolled up implicitly. Re-running can change
analytical results, so use these switches intentionally; displaying an
already-published run does not trigger clustering.
<!-- sigma-docs-20261104-v1:end -->

The ordinary selected-economy run uses:

- `transaction_preprocessing=none` and the full positive directed technical-coefficient graph;
- deterministic PSIC classification at `load` (not again at `run`);
- managed Geofabrik roads;
- type-wise road-network HDBSCAN*;
- network-node 1-median cluster centers;
- network-Voronoi surface partitions;
- X weights based on technical coefficients, both clustered-sector shares, and mean hub-mediated road distance;
- balanced sender-receiver weighted Katz; and
- establishment distance tempering `lambda = 0.15`.

Use `sigma run pasig --refresh` to recompute downstream analysis from loaded
places without deliberately reloading sources or reclassifying establishments.
Use `sigma view pasig --refresh` to rebuild only the browser bundle. These are
different operations.

<!-- sigma-augment-docs-v1:begin:quickstart -->
### Optional: add user-supplied places after `sigma load`

To combine an existing loaded area with a registry or another CSV/Parquet source, run `sigma augment` **after** `sigma load` and **before** `sigma run`:

```bash
sigma load quezon_city
sigma augment quezon_city path/to/registry.csv --source company_registry --check
sigma augment quezon_city path/to/registry.csv --source company_registry
sigma run quezon_city
```

`--check` validates the input and previews matches without writing. Required columns are `source_id`, `name`, `lon`, `lat`; optional `io16`, `io80`, and `io240` columns allow explicit hierarchical IO classification, and arbitrary extra fields are preserved for later use. See [Augment user-provided places](../methods/augmentation.md) for the complete contract and conflict handling.
<!-- sigma-augment-docs-v1:end:quickstart -->

## 4. Inspect the published results

```bash
sigma status pasig
sigma view pasig
```

`view` opens **[SIGMA Explorer](explorer.md)**, a local browser map synchronized with the directed cluster network and exact road paths. The analysis is not rerun. For traditional GIS inspection, open `pasig.qgz` in the workspace output directory. To generate a portable static bundle, use `sigma export-web pasig`; `--public` omits establishment-level records but still requires publication review.

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
2. inspect source counts and canonical-place matching diagnostics;
3. inspect PSIC/economy classification and any human-reviewed point file;
4. inspect road snapping and disconnected components;
5. inspect HDBSCAN cluster/noise and adaptive-distance diagnostics;
6. inspect `center_method` and `surface_method` for fallbacks;
7. inspect the effective transaction table and technical coefficients;
8. inspect X-edge overlap, road distance, and weight;
9. inspect `katz_in_raw`, `katz_out_raw`, and final centrality; and
10. inspect establishment distance tempering and final `sigma_score`.

The remainder of this book explains why each item exists and how it is computed.
