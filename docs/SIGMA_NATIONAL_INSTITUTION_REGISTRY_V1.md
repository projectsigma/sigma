# National hospital registry and separate school index

SIGMA uses two independent identity references, not a combined school-and-hospital list.

- **Hospitals:** 125 Level 3 hospitals from the PhilHealth September 30, 2026 accreditation publication. Sixty-three are government and 62 private. Publication serials are **not** official facility identifiers, so name matching does not verify a site. Source: https://www.philhealth.gov.ph/partners/providers/facilities/accredited/HOSP_093026.pdf
- **Schools:** 30,364 school identities in a separately packaged BEIS-format compact file (`school_id`, `school_name`, `town_psgc`). This user-supplied extract lacks independently verified publication date, official snapshot URL and redistribution permission. Ownership hints based on IDs remain provisional. Do not claim these records came from an independently verified source.

The shared runtime national registry in `SIGMA_HOME/references/institution_national_v1.csv` contains **hospitals only**. Verified links must be independently documented; identity, ownership, and PSIC/IO safeguards remain in force. The four separately reviewed QC hospital links live in the QC workspace and are not part of the national reference or repository.

Do not publish bundled reference data without applicable data-rights review. The change does not recompute classifications, X, Voronoi, clustering or scores.
