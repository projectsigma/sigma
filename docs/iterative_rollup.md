# Conditional hierarchical roll-up — default for hierarchical SIGMA runs

## Purpose

SIGMA's initial hierarchical economic classification uses place-support counts to
choose a mutually exclusive IO240/IO80/IO16 sector partition. Network HDBSCAN
may nevertheless retain zero clusters in some sectors. `sigma run AREA
--iterative-rollup` supplies a conservative, deterministic *second pass* that
reclusters only failed sectors into an existing economically related residual.

This second-pass procedure is **enabled by default only for generated hierarchical
Economies** during `sigma run`. Use `--no-iterative-rollup` to preserve the original
partition. Fixed/custom/equivalent Economies and the initial `sigma load`
hierarchy remain unchanged. `sigma load` itself does not cluster points.

## Algorithm

1. Ensure the **baseline** immutable `spatial.clusters` artifact, based on the
   original generated hierarchical economy and places preview.
2. Load the exact `spatial.points` dependency, saved sparse road graph, snaps,
   baseline cluster assignments, audit and clustering parameters.
3. Identify active economic sectors whose final cluster count is zero. Search
   for an existing sparse-code residual under the closest IO80 ancestor,
   otherwise under the IO16 ancestor. Never create an arbitrary residual or
   fold into an unrelated sector.
4. Group failed sectors targeting the same residual into **one** trial. Replay
   original affected sectors and verify their exact baseline assignments;
   fail without publishing if local code no longer reproduces the saved result.
5. On the unchanged road graph/snaps and HDBSCAN settings, recluster the union
   of the failed sector(s) and destination residual. Do not recluster any other
   sector or collapse successful siblings. A candidate is accepted iff it
   strictly increases **total retained establishments** in the affected union.
   Gross recovery of former failed establishments is recorded separately from
   displacement of establishments from the original residual.
6. If the closest residual is rejected, test the next existing residual ancestor. Repeat while more positive-net residual merges are possible. Each accepted
   iteration strictly reduces the number of sectors; the loop therefore ends.
   No `min_cluster_size`, radii, EOM/leaf behavior, or other spatial parameters
   are changed. Failed sectors without a compatible residual remain unclustered.
7. Validate the **economic** membership against the original full IO240
   membership file. Reassign each folded IO240 industry to exactly one remaining
   residual. Build the **effective** economic table by incidence aggregation:

   `Z_effective = M @ Z_original @ M.T`, `x_effective = M @ x_original`.

   This is equivalent to aggregating the original IO240 table through the
   composed membership matrix. Technical coefficients are **recomputed** in the
   existing economy pipeline from this resulting table and gross output; they
   are never averaged.
8. Write a separate, content-addressed package under
   `hierarchical/iterative_rollup/<recipe-hash>/`: `places.parquet`,
   `economy/economy.yml`, `sectors.csv`, `transactions.csv`,
   `total_output.csv`, `membership.csv`, `rollup_audit.json`, and
   `rollup_manifest.json`. The original `hierarchical/places.parquet`, original
   economic package, user-editable `places/places.parquet`, original tags,
   saved clustering artifacts, and Git files are not overwritten by this stage.
9. Re-create the normal SIGMA job against the **new** Economy/places pair. Its
   fingerprint drives the regular spatial, economic, X, Katz and export stages.
   The final cluster count is checked against the roll-up diagnostic prediction
   **before** network X, routing geometry and exports; it is checked again after
   the run completes.

## Use

```powershell
sigma run quezon_city  # default for hierarchical IO
# Equivalent explicit form: sigma run quezon_city --iterative-rollup
```

For an explicit analytical refresh:

```powershell
sigma run quezon_city --iterative-rollup --refresh
```

To use the original economic partition, explicitly disable the default:

```powershell
sigma run quezon_city --no-iterative-rollup
```

No source data must be restored. Standard cached artifacts can be reused.

## Limits and interpretation

- This procedure measures **retention**, not cluster compactness, Voronoi
  footprint, score concentration, or correctness of economic influence.
- A recovered establishment becomes part of a **broader sector** cluster, not
  evidence that its original fine industry forms a separate spatial agglomeration.
- Sectors with a positive but small number of clusters are not altered.
- Whole-parent merges are deliberately excluded from this first patch.
- The procedure does **not** alter how X edges are weighted. Its new partition
  necessarily invalidates downstream cluster, Voronoi, economic and X artifacts;
  a complete updated SIGMA run can consume considerable disk and CPU.
- All comparison results are specific to the area, source data and clustering
  configuration. Other workspaces may produce different accepted mergers.

## Revision and recovery

`git diff` previews only `src/sigma/cli.py`,
`src/sigma/economy/hierarchical_auto.py`, and the new files supplied by this
patch. Do not commit or push until tests and the Quezon City smoke check pass.
The installer never stages files, commits, resets branches, or rewrites baseline
workspace outputs. Revert the code with Git, and omit the option to restore the
previous algorithm. Derived roll-up packages remain inert if unselected; remove
only after confirming they are no longer in use.


## Original classifications and Explorer

Each rolled-up classified establishment preserves its `original_economy_code`,
while its effective `economy_code` identifies the residual used for clustering,
network X and SIGMA scores. Explorer expands an affected parent to show original
industry labels, original sparse codes and establishment counts, including its
own preexisting residual. These child rows are **provenance only**: they do not
represent separate HDBSCAN clusters, Voronoi cells or SIGMA scores.

This is provided by the companion Explorer provenance module and does not
rewrite immutable rolled-up packages. See the source-package README for a
metadata-only refresh of an already published Explorer, without rebuilding the
large route geometry files.

<!-- SIGMA_ROLLUP_DEFAULT_AND_ORIGINAL_TAGS_V2 -->
