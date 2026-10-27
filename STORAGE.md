# SIGMA workspace storage maintenance

Large libosmium node-location indexes are removed automatically after road and POI
extraction finishes, whether extraction succeeds or raises an exception. A Windows
file-lock failure yields a warning; it must not mask the extraction result.
Pre-existing indexes left behind by earlier versions are **not** retroactively cleaned
without a new extraction.
SIGMA's reusable stage artifacts are **not** disposable scratch: they may be
needed to resume expensive processing or explain a published result.

To inspect workspace disk use (including the largest artifact stages and the
largest individual files) and preview old temporary-file cleanup for **every**
initialized workspace:

```powershell
sigma storage report
sigma storage prune
```

To remove only recognized, abandoned SIGMA staging older than 30 days:

```powershell
# Close all SIGMA commands, viewers and GIS processes first.
sigma storage prune --apply
```

For a specific workspace:

```powershell
sigma storage report --workspace "$HOME\Documents\SIGMA\workspaces\pasig"
sigma storage prune --workspace "$HOME\Documents\SIGMA\workspaces\pasig" --apply
```

Optional flags also include `--quarantine` (old invalid-artifact quarantines)
and `--older-than-days N` (minimum age of the *newest* activity in each candidate).
All reports and prunes are read-only unless `--apply` is supplied.

To **preview** older, superseded stage artifacts:

```powershell
sigma storage report --obsolete
```

If the inventory correctly identifies old analytical results you no longer
need to reproduce, prune those explicitly:

```powershell
sigma storage prune --obsolete --apply
```

**Consequences of `--obsolete`:** This discards artifact versions that are not
reachable from the current `active.json` dependency graph. Current results
continue to work, but old runs/parameter sets may need recomputation and
historical reproducibility may be lost. If metadata is invalid or the workspace
has run archives, pruning old artifacts is disabled for that workspace. Back
up workspaces before opting in. Files in `output`, `places`, `state`, and `runs`
are not pruned.

The optional `--quarantine` flag is similarly opt-in for old invalid-artifact
quarantines. `--older-than-days N` changes the minimum *last activity* age;
the default is 30 days. Newer staging is never targeted. A cleaned workspace
is not smaller merely because Explorer, QGIS output and artifact versions
contain the same information: those are separately needed publication and
restart representations, so they remain intact.

**Note:** The storage command reports *logical* file sizes, not guaranteed disk
space reclaimed (sparse files, filesystem compression, and hardlinks differ).
It does not clean the shared `sources` directory, which includes the initialized
Geofabrik PBF, source identities, and reusable prepared OSM/Overture snapshots.
If legacy `*.nodes.cache` or `node-locations.cache` files remain there, stop all
SIGMA processes and remove *only those confirmed extraction indexes* manually;
do not delete `sources/` wholesale. Duplicate national PBFs must be verified
before manual deletion.
