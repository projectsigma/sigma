# SIGMA: administrative activity before institutional ownership (v1)

## Findings and scope

Audit: 87,608 QC establishments, 1,418 review candidates, 22 names appearing
misclassified as health/education, 27 office/service-category conflicts. These
are lexical audit findings, **not** 1,418 confirmed errors. The audit includes
false positives (e.g. DOH-accredited private clinics and DepEd schools).

This patch introduces conservative government-administration function evidence
at the `places.psic` stage. Clear government department/regional/division
administrative names map to PSIC 84120 from the installed taxonomy, **before**
IO candidates and the ownership resolver are calculated. The existing PSIC-to-IO
mapping determines the sector; no IO code is hardcoded or forced downstream.

The patch does **not** recode `office=educational_institution` in bulk, since
this category contains genuine education providers, university academic
units, and training centers. Nor does it recode all establishments mentioning
DOH/DepEd. Ambiguous function names and conflicting canonical/source names
receive `admin_activity_status=REVIEW` with an explanatory reason; these do
not modify PSIC.

## Ownership heuristic correction

Name-only `DOH` / `Department of Health` and `DepEd` / `Department of
Education` are removed as proofs of ownership. Administrative office terms
are not healthcare/education ownership signals. Generic religious prefixes
(`Holy`, `Saint`, `St.`, etc.) and `Our Lady` are removed as private ownership
signals. The public-health pattern no longer treats `health office` and
`health department` like service-delivery health centers. Existing specific
school and hospital name patterns are otherwise preserved.

**Official registry identity policy is unchanged.** Exact name+city matches
are provisional; only explicit ownership fields, independently verified
canonical links, and exact official external IDs are promotable. This patch
does not claim to solve the registry evidence coverage problem. A separate
reviewed identity-link workflow is required before those 187 provisional
cases can be responsibly promoted. No source information is invented.

## Reproducibility and impact

Bumps both the PSIC and classified stage implementation identities, making
stale stage artifacts ineligible for reuse on a subsequent `sigma load`.
Output gains three additive fields:

- `admin_activity_status`: REASSIGNED, CONFIRMED, REVIEW, or blank; already-administrative PSIC 84 is retained at its existing specificity
- `admin_activity_reason`: specific role evidence or review reason
- `admin_original_psic`: former PSIC code for reassignments

The original classifier evidence is retained in `psic_audit` and former flags
are preserved. Ownership and economic assignment still use the standard
pipelines; no edits to network algorithms, UI, hierarchical partition,
clustering, Voronoi, Katz, or SIGMA scoring.

## Important caution

Do **not** run `sigma load` automatically after installing. SIGMA's existing
`sigma load` command republishes `places/places.parquet` and may overwrite
manual modifications or augmentation. Save a workspace-specific backup and
review impacts first. `sigma run --refresh` is likewise **not** part of patch
installation and would be expensive.

## Install / revert

Use `python sigma_admin_ownership_patch.py --repo <repo> --check` and
`--apply` only after review; `--revert` restores exact backed-up files if
installed bytes are unchanged. Backups are kept in Downloads, outside git.
The installer refuses when anchors differ or files collide. It never reads,
writes or recomputes a workspace.

Run `python -m pytest -q tests/unit/classification/test_administrative_activity.py`
and existing relevant regression tests before committing.
