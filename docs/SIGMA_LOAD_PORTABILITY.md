# SIGMA load portability: IO resolution chosen at load time

This page describes how `sigma load` chooses the economic model for an area, where the national and per-area data live, and how the national PSA IO240 reference is prepared and checked. It was added by the load portability patch v4.

## Commands

| Command | Behaviour |
| --- | --- |
| `sigma load AREA` | Classify places, then build the area's hierarchical IO240/IO80/IO16 economy from the packaged national IO240 reference. |
| `sigma load AREA --io-level 16` | Use the fixed national IO16 economy; write an IO16-tagged preview of the places. |
| `sigma load AREA --io-level 80` | Use the fixed national IO80 economy; write an IO80-tagged preview. |
| `sigma load AREA --io-level 240` | Use the fixed national IO240 economy; only places with an exact IO240 code are assigned, and `sigma load` reports how many. |
| `sigma load AREA --economy CUSTOM` | Existing custom economy option; cannot be combined with `--io-level`. |

`sigma run AREA` (without `--economy`) follows the choice recorded by `sigma load`.

## Where data live

National reference, versioned in Git:

```text
src/sigma/resources/economy/psa_2018_io240/
    economy/economy.yml
    economy/sectors.csv
    economy/transactions.csv
    economy/total_output.csv
    crosswalk.csv
    validation.json
    ATTRIBUTION.md
```

Settings, in the SIGMA data folder (not in Git):

```text
<SIGMA_HOME>/hierarchical-defaults.json
```

The first hierarchical `sigma load` creates this file if it does not exist. Its paths are the text `package:psa_2018_io240`, which SIGMA resolves to the installed reference when it reads the file, so the file stays valid if the repository moves. Its **new-install default** parameters are `coarse_policy=residual`, `min_places=5`,
`max_straddle_share=0.25`, `check_psa=true`. An existing explicit local configuration,
including explicitly selected `contain`, is not silently changed by code defaults. Edit the file, or run `sigma economy hierarchical-configure`, to change them. Without a local configuration, `read_profile()` remains `None` for backward compatibility.
The `contain` policy remains available explicitly. Only an explicit hierarchical `sigma load` adopts the packaged default and creates the
local configuration, after checking the actual reference inputs.

Per-area outputs, in the workspace (regenerable):

```text
<SIGMA_HOME>/workspaces/<area>/
    places/places.parquet                  # editable place handoff (IO80 economy codes)
    hierarchical/                          # area hierarchical economy and preview
    fixed-io/<16|80|240>/places.parquet    # fixed-resolution preview
    economy-selection.json                 # choice, recorded settings, coverage
```

## What `economy-selection.json` records

- `io_level`: `hierarchical`, `16`, `80`, `240` or `custom`.
- `places_sha256`: hash of the handoff when the selection was written.
- For fixed and custom levels: the national or custom economy fingerprint (and, for custom, its path or built-in name).
- For hierarchical: `profile_identity` — `coarse_policy`, `min_places`, `max_straddle_share` (for `contain`), crosswalk SHA-256, source economy fingerprint, and where the settings came from.
- For fixed levels: `coverage` — places with a code, total places, share.

## How `sigma run` uses the selection

- **Fixed levels:** `run` uses the national economy and the fixed preview. If you edited `places/places.parquet` after loading, the preview is regenerated from the edited file; your edits are kept.
- **Custom:** `run` uses the recorded economy; if that economy changed, `run` stops and asks for `sigma load ... --economy`.
- **Hierarchical, same settings:** if the hierarchy is missing or older than the handoff,
  `run` rebuilds it using the recorded settings and the verified reference source.
- **Hierarchical, different settings:** if the current settings differ from those recorded at load time and the hierarchy is stale, `run` stops with a message that lists the differences. To adopt the new settings and keep your handoff edits, run `sigma economy hierarchical-refresh --workspace <workspace>`; to reload the area, run `sigma load <area>`; or restore the previous settings.
- **No selection file** (areas loaded before the patch): `run` preserves the area's
  existing economic choice. A legacy IO80 workspace remains IO80; a prior hierarchy
  is not automatically reconstructed under a new policy. Run `sigma load AREA` to
  explicitly adopt the current default hierarchy. If an old hierarchy is stale,
  explicitly refresh or reload it rather than changing its typology implicitly.
- **Fixed IO16/IO80 or custom:** opening the global hierarchy configuration does not
  verify or load the national IO240 reference. These modes run even if IO240 files
  are temporarily unavailable (provided their own required references exist).
- When `run` or `load` rebuilds a hierarchy, the build report is written to stderr, so `--json` output on stdout stays one JSON document.

## Preparing the national IO240 reference

Download both official workbooks from the PSA 2018 Input-Output Tables page (https://psa.gov.ph/statistics/supply-and-use-input-output/tables): *240-Industry Transaction Table, 2018* and *2018 Input-Output Industry Classification*. Then:

```powershell
python scripts/sigma_pack_io240_repo.py --repo . `
    --transactions-xlsx "PATH\240-Industry Transaction Table, 2018.xlsx" `
    --classification-xlsx "PATH\2018 Input-Output Industry Classification.xlsx"
```

Use `--replace-existing` to rebuild a package written by an older packager (for example patch v2).

The packager accepts the 240 table only if, under SIGMA's `io240_parents.csv` parents, it aggregates to SIGMA's bundled IO80 and IO16 transaction matrices and gross-output vectors. Each check passes if either criterion holds:

1. **Relative:** maximum relative error and L1 relative error (sum of absolute cell differences divided by sum of absolute reference cells) are both at most 2×10⁻⁷.
2. **Rounding envelope:** the 240 table is rounded to a fixed number of decimals *d*, and every aggregated cell differs from the reference by no more than 0.5×10⁻ᵈ for each 240 cell summed into it (plus the reference's own rounding and floating-point noise).

On failure the packager lists the IO80 rows, columns and cells with the largest differences, says whether the pattern fits one wrong parent link (differences concentrated in two rows) or rounding or a different table version (differences spread out), and names a power-of-ten factor between totals as a likely unit difference. It never rescales the table or changes parent links.

Sector labels come from `io240_parents.csv` (without a code prefix); the workbook fills a label only where that file has none.

`validation.json` records the criteria and results, the published decimals, label sources, component fingerprints (sector, transactions, output) and SHA-256 digests. Digests of stored files are computed after converting CRLF to LF, and `.gitattributes` keeps these files LF in Git, so Windows and Linux checkouts verify the same package.

## Checks before committing

```powershell
python -m pytest -q
git add --intent-to-add src/sigma/economy/load_policy.py scripts/sigma_pack_io240_repo.py docs/SIGMA_LOAD_PORTABILITY.md tests/economy/test_load_policy.py tests/economy/test_io240_packager.py src/sigma/resources/economy/psa_2018_io240
git diff --check
python -m build --wheel
```

`git add --intent-to-add` records the new paths in Git's index without staging their content, so `git diff --check` covers them.

## Early preflight and compatibility safeguards (v4)

A hierarchical `sigma load` validates its intended source economy and crosswalk
**before** OSM/Overture reconciliation or economic tagging. This includes the
packaged SHA-256 manifest (if using packaged references), all 240 source sectors,
parent consistency with the committed PR #17 IO240→IO80→IO16 table, and consistency
with the current PSIC/IO tagging references. Missing old absolute paths fail
with instructions to migrate to `package:psa_2018_io240`.

The builder and classifiers from PRs #15, #17 and #18 are not modified.
`X:Y:Z`, `X:Y:o`, `X:Y`, `X:o` and `X` remain the canonical sparse identities
assigned by the existing hierarchical builder. The area-specific transactions
are still generated as `M Z Mᵀ`, and outputs as `M x`.

The source bodies of `sigma init` and `sigma run` are unchanged. The shared
`profile_is_current` and `auto_economy` helpers now distinguish an explicit
hierarchical choice from a legacy area, avoiding implicit IO80→hierarchy migration.

A previously created `economy-selection.json` with a hierarchical choice but
without a recorded policy/source fingerprint cannot be silently rebuilt under
v4. It must be deliberately reloaded or refreshed.
