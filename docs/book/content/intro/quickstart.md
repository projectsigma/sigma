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

## 3. Run an area

For example:

```bash
sigma run pasig
```

The default run uses:

- PSA 2018 IO80;
- `transaction_preprocessing=none`;
- deterministic PSIC classification;
- managed Geofabrik roads;
- type-wise road-network HDBSCAN*;
- network-node 1-median cluster centers;
- network-Voronoi surface partitions;
- the full directed technical-coefficient economy;
- balanced sender-receiver weighted Katz; and
- distance tempering `lambda = 0.15`.

## 4. Inspect and export

```bash
sigma status pasig
sigma export pasig --out output/pasig
```

The artifact DAG means a repeated run does not blindly rerun every computation. A stage is reused when the recipe fingerprint and stored files still match the requested inputs, parameters, source identities, and implementation version.

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
