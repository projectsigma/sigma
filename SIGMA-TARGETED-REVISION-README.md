# SIGMA hierarchical IO tagging — targeted second-pass revision

Source: the uploaded 27-file tagging overlay, relative to repository base `2acaece`.
This is a **full replacement overlay**, not an incremental overlay on top of the
first ZIP. Apply **only this revised ZIP** to a clean checkout of `2acaece`.
All paths are repository relative; no deletion is required.

## Fixes

1. Disjoint `io240_codes` / IO80 or IO16 parent evidence becomes
   `UNASSIGNED_CANDIDATE_CONFLICT`, never a fallback to all parent leaves or a
   legacy `Other` sector. The strict mode raises an error. The audit counts it.
2. Ownership inference v2 drops several nonspecific heuristics (`elementary
   school`, generic `health center`, generic `clinic`, generic `academy`), adds
   explicit public/private school or facility indicators and continues to abstain
   on contradictory evidence. **It is still heuristic** and not registry proof.
3. Historical saved profiles missing `coarse_policy` are interpreted as
   `residual`, the policy under which they were created. Explicit newly saved
   profiles continue to select `contain` by default. This prevents an automatic
   partition-policy migration solely from loading a historical profile.
4. Classified preview adds `economy_evidence`, `economy_evidence_flags`, `economy_review_required`,
   `economy_candidate_io240`, `economy_candidate_local_sectors` and
   `economy_candidate_source`. `audit.json` counts evidence flags. Classified
   `pois.parquet` carries them when published; local Explorer joins provenance
   by canonical ID from `pois.parquet` onto scored points. It does not change
   any score, cluster, or final sector. `sigma_points.parquet` itself is **not
   retrofitted**; consumers should join to `pois.parquet`.
5. A read-only before/after comparison script for saved real workspaces, with
   optional `sigma_points.parquet` comparison of scored membership and changes.

**Separate workstream (not included):** the broader
`overture=professional_service` versus precise establishment-name precedence
problem from the QC audit. The review's narrower hotel C4 fix is still included.

## Validation

From a clean checkout, unzip this replacement ZIP over the repository root.
Review with `git diff` and then run:

```powershell
python -m pytest -q tests/economy/test_hierarchical_contain.py `
  tests/economy/test_compare_hierarchical_tagging.py `
  tests/unit/classification/test_io_tagging_fixes.py
python -m pytest -q

```

For a preserved real Quezon City baseline and a **separately generated** post-change
hierarchical preview, compare without overwriting either:

```powershell
python scripts/compare_hierarchical_tagging.py `
  --before "$HOME\Documents\SIGMA\snapshots\qc-before\hierarchical" `
  --after "$HOME\Documents\SIGMA\workspaces\quezon_city\hierarchical" `
  --before-output "$HOME\Documents\SIGMA\snapshots\qc-before\output" `
  --after-output "$HOME\Documents\SIGMA\workspaces\quezon_city\output"

```

These two paths are examples; a true before snapshot and refreshed after snapshot
must exist. The script prints aggregate JSON, creates no files, and never reads
or exports names or coordinates. No actual Quezon City comparison is claimed;
the workspace files were **not** provided in this chat. With the optional
`--before-output` and `--after-output` inputs it also reports score, type and
cluster-label changes for shared establishments. Cluster-label changes are not,
by themselves, evidence of improved clustering. These output paths are
illustrative: use the real configured output directories.

### Scope and caution

The existing national input–output reference and raw transaction aggregation
are unchanged. A machine-read status of `exact_tag_unverified` is not evidence
that an establishment's economic activity was independently validated. Draft
concordances and inferred ownership remain operative under the existing
assignment policy but are explicitly marked for review. If the desired policy
is to **exclude** them from scoring, that is a separate modelling change not
made here.
