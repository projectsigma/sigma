# Load-time institutional ownership evidence (production v1)

This is the **conservative production subset** of the opt-in shadow-registry QC
method (`shadow-evidence-v3`). It runs inside `sigma load`, **after** the normal
PSIC and hybrid IO tagging, but **before** final `economy_code` is assigned.
It never alters canonical PSIC codes or PSIC-derived IO candidate sets.

## What can change a public/private IO tag?

The production resolver promotes only:

1. An explicit source ownership attribute on the same establishment (or a
   structured Overture public/private school category).
2. An independently verified `canonical_id`-to-registry-ID link, supplied in a
   verified local links file (see below).
3. An exact official external institution ID match with a consistent name.

Exact normalized **name + city** matches (without a record ID), and government
operator tags, are **provisional or proxy evidence** and do not change IO tags.
They remain available in the separate `sigma_shadow_qc.py` report. A government
operator does not itself establish ownership. A contradictory identity, upstream
PSIC activity, IO candidate set, or economic level causes abstention; a stronger
existing PSIC/direct IO resolution is not overwritten.

The bundled `institution_registry.csv` copies the selective, independently
sourced QC registry and is **restricted to the Quezon City workspace**. No live
registry request is made during `sigma load`. Other areas can still use explicit
source attributes and independently verified canonical links. The registry is
not a comprehensive Philippines-wide list. Bundled records are historical and
may need updating from fresh DOH NHFR, DepEd, or CHED sources.

## Verified canonical links (optional)

For independently verified exact record-to-record matches, place a JSON file
under the target workspace at `references/institution_links.json` with the
following structure:

```json
{
  "schema": "sigma-verified-canonical-links-v1",
  "links": [
    {
      "verified": true,
      "canonical_id": "ss_EXAMPLE_REPLACE_ME",
      "domain": "education",
      "ownership": "public",
      "source_url": "https://www.deped.gov.ph/",
      "registry_id": "REAL_SCHOOL_ID_REQUIRED",
      "verified_as_of": "2026-11-03"
    }
  ]
}
```

The values above are **placeholders, not a valid verified link**. Only enter
records whose cross-dataset identity and official ownership were independently
verified. Unverified links or schema errors stop loading rather than being
silently accepted. Changes to the file affect the `places.classified` artifact
identity and trigger fresh tagging on a subsequent `sigma load`.

## Outputs and reproducibility

`places.classified` and the published `places.parquet` carry five additive
per-establishment audit columns:

- `institution_promotion_status` (`PROMOTED`, `CONFIRMED`,
  `PROVISIONAL_NOT_PROMOTED`, conflict/abstention status, or empty).
- `institution_evidence_basis` (whether source ownership, verified link,
  exact official ID, or provisional evidence was used).
- `institution_evidence_reference` (official source IDs when matched).
- `institution_evidence_source_urls` (source provenance URLs).
- `institution_baseline_conflict` (when the former name-based owner disagrees).

The classified artifact recipe includes the bundled reference fingerprint and
(optional) verified-link file hash. Only IO80/IO240 ownership-pair assignments,
sector labels, status/source and ownership reason may change; sector granularity,
HDBSCAN, Network X construction, and scoring formulas do not.

`sigma load quezon_city` applies this on load, recomputing only stale stages.
It **does not recalculate clustering, Network X, centrality or scores**. If the
new loaded tags must affect an existing scored workspace, a subsequent explicit
`sigma run quezon_city --refresh` is required. This may be expensive; do not
run it until after reviewing classification changes and coverage.

The prior 45-entity QC test supported investigation but does **not** validate
this narrower policy's out-of-sample performance. Most of that test's registry
improvements involved provisional name matches, which are intentionally *not*
promoted by this production policy.
