# `sigma run` and `sigma view`: CLI reference

This reference describes the command signatures in `projectsigma/sigma` as inspected on **1 November 2026**, including `run --refresh` and the new `view --fast` alias for `--ui-only`. These CLI changes do not themselves alter the analytical formulas.

## Mental model

| Command | What it does | Does it touch source classification? |
| --- | --- | --- |
| `sigma run AREA` | Reuses valid analytical artifacts and computes stages missing or invalid under their tracked recipes; publishes SIGMA outputs | No; expects existing loaded places |
| `sigma run AREA --refresh` **(patch)** | Recomputes normalized spatial points, clusters, centers, point distances, partitions, economic stages, X, centrality, and scores; republishes the result | No; retains loaded places and reused road preparation |
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
| `--economy SPEC` | Choose `builtin:io80`, `builtin:io16`, or a custom economy directory; with no override, the workspace's recorded IO selection is honored; an unselected legacy IO80 workspace remains IO80 |
| `--transaction-preprocessing VALUE` | `none` (default) or `mwas_ras_fast` |
| `--equivalent` | Legacy Engine-equivalent configuration; cannot combine with non-`none` transaction preprocessing |
| `--mwas-method VALUE` | `fast` by default; only applies together with `--equivalent` |
| `--min-cluster-size INT` | `5`; HDBSCAN minimum cluster size |
| `--min-samples INT` | Unspecified by default; HDBSCAN core-density parameter |
| `--allow-single-cluster` | `False`; permit selection of a single cluster where supported |
| `--voronoi-resolution FLOAT` | `500.0`; partition-resolution parameter |
| `--centrality-method METHOD` | `katz` (default) or `eigenvector` (legacy) |
| `--centrality-direction DIRECTION` | `incoming` (default) or `outgoing`; compatibility-only, ignored by current Katz and eigenvector implementations |
| `--x-distance-decay-lambda FLOAT` | `1.0`; exponent for inverse-distance attenuation of X edges |
| `--distance-tempering FLOAT` | `0.15`; score-distance tempering |
| `--refresh` **(patch)** | Recompute *the downstream analytical stages* from already loaded places; reuse place-source and transport-road preparation |
| `--force` | Legacy behavior: recompute `analysis.scores`; may reuse cached predecessors |
| `--json` | Print machine-readable result metadata |
| `--help` | Show command-specific help |

There is also a deliberately hidden compatibility option `--source-store PATH`; it must match SIGMA's initialized source store and is **not** a supported way to switch datasets. Global options go *before* the command, e.g., `sigma --quiet run quezon_city`; global `--version` prints the version.

`--refresh` and `--force` are mutually exclusive with this patch, because they mean materially different things.

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

The previous `--ui-only` spelling remains supported as an alias for `--fast`.
