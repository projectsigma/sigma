# Standalone SIGMA Explorer distribution

SIGMA bundles are named `<area>-explorer` by default; for example
`metro_manila-explorer`. Public-profile bundles use `<area>-explorer-public`.
`--output-dir` remains authoritative and bypasses the default naming rule.

```
metro_manila-explorer/
  sigma.exe
  index.html
  .sigma-explorer
  about.html
  app.js
  data/
  vendor/
```

Double-click **sigma.exe** inside the folder on Windows. The bundled native
launcher runs a read-only web server, opens `http://localhost:8765/` (or a free
port through 8784), and adds a tray icon. **Exit SIGMA** in that tray menu
closes the local server; closing the browser tab alone does not. The HTTP
listener binds to local loopback only. No Python or SIGMA command is needed to
view an existing bundle.

Existing `explorer` / `explorer-public` folders are renamed automatically on
`SIGMA view <area>` when the new default folder does not exist, the old marker
is valid, the privacy profile matches, and no `--output-dir` is specified.
No analytical data are recomputed during the rename. After migration,
`sigma view <area> --fast` refreshes the UI assets and places sigma.exe inside
the renamed folder without rebuilding the analytical data. The rename fails
closed if the old folder is malformed, and no existing named folder is
replaced. Stop any running native SIGMA instance before refreshing files.

`SIGMA export-web <area>` creates the named folder directly. A normal
`SIGMA view <area>` can rebuild data when the source fingerprint changed.
The packaged executable is **unsigned**; it may still trigger Windows
SmartScreen warnings. Public-profile bundles intentionally exclude
establishment-level identities and locations. Do not share local-profile
bundles without reviewing data rights.

On Explorer startup, the selected network depth defaults to **Two steps**;
users can still select Direct links, Three steps, or Custom.
