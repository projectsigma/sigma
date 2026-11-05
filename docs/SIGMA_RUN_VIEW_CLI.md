# `sigma run` and `sigma view`: CLI reference

This reference describes the canonical area workflow. `sigma run` executes pipeline stages 6–17: roads and snapping, network HDBSCAN*, zero-cluster (K=0) roll-up for generated hierarchies (stage 9), network Gap k-medoids refinement with four worker processes (stage 10, on by default), 1-median centers, network Voronoi, coefficients, numerical X, balanced Katz and establishment scores, followed by browser-native route publication. `sigma view` presents the published result. `sigma run --help` and `sigma view --help` list the options of the installed version.

## Mental model

| Command | What it does | Does it touch source classification? |
| --- | --- | --- |
| `sigma run AREA` | Reuses valid analytical artifacts and computes stages missing or invalid under their tracked recipes; publishes SIGMA outputs | No; expects existing loaded places |
| `sigma run AREA --refresh` | Recomputes normalized spatial points, clusters, centers, point distances, partitions, economic stages, X, centrality, and scores; republishes the result | No; retains loaded places and reused road preparation |
| `sigma run AREA --force` | **Legacy:** forces the terminal `analysis.scores` stage; upstream cached stages are normally reused | No |
| `sigma view AREA` | Validates the Explorer bundle against published outputs, rebuilding only if needed; starts local server | No |
| `sigma view AREA --refresh` | Unconditionally rebuilds Explorer browser data from published outputs; starts local server | No |
| `sigma view AREA --fast` | Copies newer Explorer interface assets into an existing bundle, keeping all its analytical/browser data unchanged | No |

**Important:** `sigma view --refresh` does not recompute clustering, graph edges, centrality or scores. Conversely, `sigma run --refresh` does **not deliberately force** source downloads, tagging, or road preparation: use `sigma load` and its own options for those operations. The normal dependency planner may still repair a missing/invalid prerequisite.

The existing artifact store is *immutable by recipe*. A refresh can be rejected when a changed implementation produces different bytes under an unchanged artifact recipe. This is a deliberate integrity check, **not** permission to delete or overwrite workspace artifacts. In that situation, update the affected stage's implementation/recipe version or diagnose its nondeterminism before rerunning. Do not erase artifact directories to bypass the check.

## `sigma run AREA` options

| Option | Default / meaning |
| --- | --- |
| `AREA` | Required area slug, e.g., `quezon_city` |
| `--workspace PATH` | Default: initialized SIGMA home `/workspaces/<area>`; use a specific existing workspace |
| `--roads FILE` | Use a custom road-network file rather than managed Geofabrik roads |
| `--managed-roads` | Explicitly choose the default managed Geofabrik source; mutually exclusive with `--roads` |
| `--roads-layer NAME` | Layer name for `--roads FILE`; requires `--roads` |
| `--output-dir PATH` | Override durable SIGMA output directory (subject to existing workspace-path constraints) |
| `--areas-file FILE` | Custom area catalog / boundary declarations |
| `--economy SPEC` | Choose `builtin:io80`, `builtin:io16`, or a custom economy directory; with no override, the workspace's recorded IO selection is used; a workspace without a recorded selection uses IO80 |
| `--transaction-preprocessing VALUE` | `none` (default) or `mwas_ras_fast` |
| `--equivalent` | Legacy Engine-equivalent configuration; cannot combine with non-`none` transaction preprocessing |
| `--mwas-method VALUE` | `fast` by default; only applies together with `--equivalent` |
| `--min-cluster-size INT` | `5`; HDBSCAN minimum cluster size |
| `--min-samples INT` | Unspecified by default; HDBSCAN core-density parameter |
| `--median-gap` / `--no-median-gap` | Stage 10; enabled by default for canonical runs; disabled by default for legacy `--equivalent` unless explicitly enabled |
| `--median-gap-workers INT` | Four worker processes by default; choose 1–4 |
| `--median-gap-max-k INT` | 6 candidate medoids maximum per original retained HDBSCAN cluster; not recursive |
| `--median-gap-replicates INT` | 10 reference draws |
| `--median-gap-max-sites INT` | At most 64 establishments sampled per parent for Gap fitting |
| `--median-gap-seed INT` | 20261105; deterministic random seed |
| `--iterative-rollup` / `--no-iterative-rollup` | Stage 9; automatic K=0 roll-up for generated hierarchies only; explicit override |
| `--allow-single-cluster` | `False`; permit selection of a single cluster where supported |
| `--voronoi-resolution FLOAT` | `500.0`; partition-resolution parameter |
| `--centrality-method METHOD` | `katz` (default) or `eigenvector` (legacy) |
| `--centrality-direction DIRECTION` | `incoming` (default) or `outgoing`; compatibility-only, ignored by current Katz and eigenvector implementations |
| `--x-distance-decay-lambda FLOAT` | `1.0`; exponent for inverse-distance attenuation of X edges |
| `--distance-tempering FLOAT` | `0.15`; score-distance tempering |
| `--route-geometry {browser,precomputed}` | `browser` by default; only changes downstream route publication, never numerical X weights |
| `--refresh` | Recompute *the downstream analytical stages* from already loaded places; reuse place-source and transport-road preparation |
| `--force` | Legacy behavior: recompute `analysis.scores`; may reuse cached predecessors |
| `--json` | Print machine-readable result metadata |
| `--help` | Show command-specific help |

There is also a deliberately hidden compatibility option `--source-store PATH`; it must match SIGMA's initialized source store and is **not** a supported way to switch datasets. Global options go *before* the command, e.g., `sigma --quiet run quezon_city`; global `--version` prints the version.

`--refresh` and `--force` are mutually exclusive, because they mean materially different things.

## Zero-cluster roll-up controls (stage 9)

`sigma load AREA` creates the baseline hierarchy (stage 5). For a generated hierarchical economy only, normal `sigma run AREA` enables residual-first iterative roll-up on sectors with **zero retained HDBSCAN clusters** (`K=0`). A small positive cluster count does not trigger a roll-up. The default does not apply to fixed IO16, IO80, IO240, explicit custom or legacy-equivalent economies. A merge is accepted only when it satisfies the positive net-retention condition; no place is assigned to the nearest Voronoi center by this option. See [Zero-cluster roll-up](book/content/methods/iterative_rollup.md).

```powershell
sigma run quezon_city                   # default hierarchical roll-up
sigma run quezon_city --iterative-rollup # explicit on
sigma run quezon_city --no-iterative-rollup # preserve baseline hierarchy
```

These commands are **analysis operations**, not Explorer toggles. The CLI switch determines which effective economy and clustered network are published. Explorer's original-child checkboxes only change **point visibility** within the published roll-up, not model assignments. Use `sigma view AREA --fast` only for changes to static frontend assets, not as a way to select a different analytical run.

## `sigma view AREA` options

| Option | Default / meaning |
| --- | --- |
| `AREA` | Required area slug |
| `--workspace PATH` | Resolve published outputs from this workspace; by default uses initialized area workspace |
| `--source-dir PATH` | Read an explicit published SIGMA output directory |
| `--output-dir PATH` | Explorer bundle directory; by default `<published outputs>/explorer` (`explorer-public` when `--public`) |
| `--port INT` | `8765`; binds to localhost, with next available port used if occupied; `0` requests an ephemeral port |
| `--no-browser` | Serve without opening a browser tab |
| `--fast` | Refresh interface assets only; do not rebuild data or check data freshness |
| `--refresh` | Rebuild Explorer data even if the bundle appears current |
| `--roads` / `--no-roads` | Force inclusion/exclusion of published road graphics; default is automatic |
| `--public` | Use the public-profile bundle, excluding establishment-level identities and positions from the public output; still requires data-rights review before publication |
| `--help` | Show command-specific help |

`--fast` and `--refresh` cannot be combined. Plain `view` automatically rebuilds the bundle if the underlying published outputs changed.

## Recommended everyday commands

```powershell
# Normal SIGMA pipeline: reuse intact computations
sigma run quezon_city

# After changing clustering, scoring, or other analysis code, recompute the managed analysis
sigma run quezon_city --refresh

# View the latest published results (rebuild browser data if stale)
sigma view quezon_city

# Refresh browser data even if it looks current
sigma view quezon_city --refresh

# After CSS/JS/HTML-only Explorer changes
sigma view quezon_city --fast

# Keep the local server on an alternative port
sigma view quezon_city --port 8766
```

For changes to classification/tagging inputs and rules, first run `sigma load AREA` with the appropriate source/force options, review the loaded places, then `sigma run AREA --refresh`. Updating `run` alone does not reclassify establishments.

`--ui-only` is an alias for `--fast`.


## Network Gap k-medoids refinement (stage 10, canonical default)

Normal `sigma run AREA` applies **one Gap-statistic-guided k-medoid pass** after HDBSCAN extraction and after any generated-hierarchy K=0 roll-up. Only retained clusters with at least `2 × min_cluster_size` members and 3 distinct road positions are tested, with four parallel worker processes, up to k=6, 10 reference draws, up to 64 fitted observations, and deterministic seed 20261105. Accepted children are assigned by exact road distance; their own full-network 1-medians are computed in stage 11. HDBSCAN noise stays noise. The process is not recursive. `--no-median-gap` keeps the unrefined HDBSCAN partition, and `--median-gap-workers 1` runs serially with identical results; `--equivalent` keeps unrefined clusters unless explicitly overridden.

## Route publication

The numerical `analysis.x` computation (stage 14) needs no route geometry. The CLI defaults to `--route-geometry browser`: the exporter publishes a compact graph for on-demand shortest-path reconstruction inside Explorer. Use `--route-geometry precomputed` to write GIS route geometries explicitly. Both modes keep the same X distance and edge weight values. See [Network Gap method](book/content/methods/network_gap_medians.md), [Network X](book/content/methods/x_graph.md) and [Route publication](book/content/methods/routing.md).
