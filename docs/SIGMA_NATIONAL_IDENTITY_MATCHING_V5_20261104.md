# Hospital identity and branch review

A national hospital listing is not proof that an OSM/Overture point is the same registered establishment. Name and locality candidates remain provisional. Cross-locality listings may indicate a branch, affiliate or distinct site and require independent evidence. PhilHealth PDF publication-row numbers are not facility codes.

`NationalRegistryIndex` preserves `EXACT_NAME_CITY`, `NAME_LOCATION_UNVERIFIED`, `EXTERNAL_ID_LOCALITY_REVIEW`, `IDENTITY_AMBIGUOUS`, and related non-promotable statuses. Only genuine NHFR codes and independently verified canonical links, subject to PSIC/IO guards, may be eligible for ownership promotion.

`scripts/sigma_national_identity_review.py` is a read-only candidate triage report. Its output never installs verified links or recomputes classification. Education/school identity is handled separately by the conservative school index.
