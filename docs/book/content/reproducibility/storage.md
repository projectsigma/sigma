# Workspace storage and retention

SIGMA uses two distinct storage mechanisms: shared national and area source data
(`sources/`) and per-workspace, versioned analytical artifacts (`workspaces/<area>/`).
Large libosmium node indexes are **temporary**; immutable stage outputs, reviewed
establishments, exports, and Explorer bundles are **durable**. Their presence does
not mean they are unnecessary.

## Why disk use grows

- **Shared OSM extraction:** the compressed Philippines Geofabrik `.osm.pbf` is
  expanded into temporary disk-backed node-location indexes when extracting
  roads and nationwide places. The extraction code removes them on exit,
  including when extraction fails. An OS file lock may prevent deletion.
- **Artifact history:** each stage has an immutable recipe and hashed outputs.
  Changed source identities, parameters, or implementation versions can
  create additional versions; these are retained for restart and provenance.
- **Publication:** `output/` contains GIS and tabular deliverables; `explorer/`
  and `explorer-public/` contain derived browser-ready representations. Those
  duplicate some information deliberately and are not scratch files.
- **Interrupted operations:** failed processes can leave staging directories,
  export staging, old Explorer backups, and temporary files.

## Check where workspace space is going

```powershell
sigma storage report
sigma storage report --workspace "$HOME\Documents\SIGMA\workspaces\pasig"
sigma storage report --obsolete
sigma storage report --quarantine
```

`report` is read-only. It reports category totals, the largest artifact stages,
the largest individual files, and eligible cleanup candidates. Reported sizes
are **logical bytes**, not guaranteed space reclaimable on sparse/compressed/
hardlinked filesystems. Without `--workspace`, it checks initialized workspaces
beneath `SIGMA_HOME/workspaces` (normally `Documents\SIGMA\workspaces`).
It does not inventory or prune the shared `sources/` tree.

## Preview, then remove abandoned scratch

```powershell
sigma storage prune                         # preview; nothing deleted
sigma storage prune --apply                 # normal cleanup, aged >= 30 days
sigma storage prune --older-than-days 60    # preview with stricter age
sigma storage prune --workspace "$HOME\Documents\SIGMA\workspaces\pasig" --apply
```

Stop running SIGMA processes, Explorer jobs, and GIS tools first. The default
cleanup only considers recognizable SIGMA-owned staging that has had **no file
activity in at least 30 days**: artifact-store `.tmp/` directories, a leftover
`active.json.tmp` when the active index exists, `.sigma-export-*` staging,
Explorer staging/replaced backups with valid replacement bundles, and
`.sigma-ui-*` temporary assets. Symlinked or newly changed candidates are
skipped; Windows locks or other deletion failures are reported.

The following are **not removed** by ordinary cleanup:

| Retained | Why |
| --- | --- |
| `workspace.json`, `config.json`, active artifact index and manifests | State and provenance |
| Current immutable artifacts and their transitive dependencies | Correct restart/reuse |
| `places/`, `state/`, `runs/` | Review inputs and historical context |
| Published `output/` files and `explorer/`/`explorer-public/` | QGIS and browser deliverables |
| Shared `sources/` | PBF, OSM/Overture snapshots, source identity records |

## Opt-in pruning of superseded artifacts

```powershell
sigma storage report --obsolete
sigma storage prune --obsolete                # preview
sigma storage prune --obsolete --apply        # irreversible history pruning
sigma storage prune --quarantine --apply      # separate opt-in for old quarantines
```

`--obsolete` only offers aged artifact directories that are **not reachable**
from the active artifact dependency graph. If its metadata is incomplete,
unsafe, or inconsistent, SIGMA fails closed. If the workspace has contents in
`runs/`, obsolete-artifact pruning is disabled for that workspace.

Removing superseded artifacts can make older parameter sets or published-run
lineages harder or impossible to reproduce without recomputation. Back up the
workspace and review the paths before opting in. `--quarantine` is separately
required to prune old corrupt-artifact quarantine directories. Every deletion
still requires `--apply`.

## What to do with old shared indexes

The storage CLI deliberately **does not delete shared source data**. On a
successful or failed *new extraction attempt*, SIGMA removes the current
`geofabrik/road-node-index/*.nodes.cache` and
`prepared-osm-recipes/**/node-locations.cache` processing indexes. An older
or locked cache may remain if no extraction reruns or Windows prevents removal.

To inspect old large indexes manually:

```powershell
$root = Join-Path $HOME "Documents\SIGMA\sources"
Get-ChildItem "$root\geofabrik\road-node-index" -Filter "*.nodes.cache" -File -ErrorAction SilentlyContinue
Get-ChildItem "$root\prepared-osm-recipes" -Filter "node-locations.cache" -File -Recurse -ErrorAction SilentlyContinue
```

Delete only identified indexes when SIGMA is idle. Do not remove the initialized
managed national PBF, `source-index.json`, source manifests, or completed
prepared-OSM/Overture snapshots as a blanket storage-cleanup measure.

## Scope and limitations

These commands manage storage **locally**; they do not commit, push, or delete
anything from GitHub. They do not automatically compress GeoPackages, remove
published files, or remove historical artifact versions during ordinary runs.
Always inspect the candidate list before applying a cleanup.
