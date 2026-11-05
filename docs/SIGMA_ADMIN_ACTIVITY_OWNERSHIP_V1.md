# SIGMA: administrative activity before institutional ownership (v1)

Pipeline stages 3–4 of 17 (`sigma load`). See also [Institutional activity and ownership evidence](book/content/methods/shadow_classification.md).

## Findings and scope

Audit of Quezon City: 87,608 establishments, 1,418 review candidates, 22 names that appeared misclassified as health/education, 27 office/service-category conflicts. These are lexical audit findings, **not** 1,418 confirmed errors. The audit includes false positives (for example DOH-accredited private clinics and DepEd schools).

Policy `admin-function-v1` adds conservative government-administration function evidence at the `places.psic` stage (stage 3). Clear government department/regional/division administrative names map to PSIC 84120 from the installed taxonomy, **before** IO candidates and the ownership resolver are calculated. The PSIC-to-IO mapping determines the sector; no IO code is hardcoded or forced downstream.

The rule does **not** recode `office=educational_institution` in bulk, since this category contains genuine education providers, university academic units, and training centers. Nor does it recode all establishments mentioning DOH/DepEd. Ambiguous function names and conflicting canonical/source names receive `admin_activity_status=REVIEW` with an explanatory reason; these do not modify PSIC.

## Ownership heuristics

Name-only `DOH` / `Department of Health` and `DepEd` / `Department of Education` are not proofs of ownership. Administrative office terms are not healthcare/education ownership signals. Generic religious prefixes (`Holy`, `Saint`, `St.`, etc.) and `Our Lady` are not private ownership signals. The public-health pattern does not treat `health office` and `health department` like service-delivery health centers. Specific school and hospital name patterns are kept.

**Official registry identity policy:** exact name+city matches are provisional; only explicit ownership fields, independently verified canonical links, and exact official external IDs are promotable (stage 4). This rule does not solve the registry evidence coverage problem: a separate reviewed identity-link workflow is required before provisional cases (187 in the Quezon City audit) can be responsibly promoted. No source information is invented.

## Reproducibility and output fields

The PSIC and classified stage implementation identities include this rule, so stage artifacts built without it are not reused by `sigma load`. The output has three fields:

- `admin_activity_status`: REASSIGNED, CONFIRMED, REVIEW, or blank; an already-administrative PSIC 84 code is kept at its existing specificity
- `admin_activity_reason`: specific role evidence or review reason
- `admin_original_psic`: former PSIC code for reassignments

The original classifier evidence is kept in `psic_audit`, together with the classifier flags. Ownership and economic assignment use the standard pipelines; network algorithms, UI, hierarchical partition, clustering, Voronoi, Katz and SIGMA scoring are not affected.

## Caution

`sigma load` republishes `places/places.parquet` and may overwrite manual modifications or augmentation. Save a workspace-specific backup and review impacts before reloading an area. `sigma run --refresh` after a reload is expensive.

Run `python -m pytest -q tests/unit/classification/test_administrative_activity.py` and the related regression tests before committing changes to the rule.
