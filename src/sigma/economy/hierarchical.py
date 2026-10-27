"""Mutually exclusive IO240 -> IO80 -> IO16 residual aggregation.

The finest IO240 partition is the only source of economic transactions.  Retained
fine industries remain singletons; unused siblings within a split IO80 parent form
an IO80-Other residual; the remaining IO240 leaves within an IO16 parent form the
IO16(-Other) residual.  Row and column aggregation use the SAME partition.

An IO240 industry (or a whole IO80 parent) is retained only when at least
``min_places`` places support it.  ``min_places=1`` (the default) retains every
observed industry and reproduces the v2 partition exactly.  A larger value, for
example SIGMA's ``--min-cluster-size``, folds thinly observed industries into the
next coarser group, so their places are not lost as type-wise clustering noise.

An ambiguous/coarse tag does not identify an IO240 leaf.  A coarse place is
assigned exactly when one group contains every leaf of its tag; otherwise it is
assigned to the residual by convention.  The convention is not new evidence about
the true activity of an unclassified establishment.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from sigma.errors import EconomyValidationError
from .model import Economy, Sector, SectorCatalog

_COLUMNS = ("io240_code", "io80_code", "io16_code")
_REPORTED = 10


def _strings(series: pd.Series) -> pd.Series:
    """Treat missing codes as empty; do not coerce IO codes to integers."""
    return series.astype("string").fillna("").str.strip()


def _reference(crosswalk: pd.DataFrame, economy: Economy) -> pd.DataFrame:
    if not set(_COLUMNS).issubset(crosswalk):
        raise EconomyValidationError(f"hierarchy needs columns {', '.join(_COLUMNS)}")
    h = crosswalk.copy()
    for col in _COLUMNS:
        h[col] = _strings(h[col])
        if not h[col].ne("").all():
            raise EconomyValidationError(f"hierarchy {col} contains missing codes")
    if h.io240_code.duplicated().any():
        raise EconomyValidationError("each IO240 code must appear exactly once in hierarchy")
    universe = set(economy.sectors.codes)
    listed = set(h.io240_code)
    if universe != listed:
        raise EconomyValidationError(
            f"hierarchy IO240 universe mismatch; missing={sorted(universe-listed)[:8]}, "
            f"extra={sorted(listed-universe)[:8]}"
        )
    if h.groupby("io80_code").io16_code.nunique().gt(1).any():
        raise EconomyValidationError("each IO80 sector must belong to one IO16 sector")
    for col in ("io80_label", "io16_label"):
        if col in h.columns:
            h[col] = _strings(h[col])
            parent = "io80_code" if col == "io80_label" else "io16_code"
            # Blank optional labels mean "unspecified", not a competing name.
            specified = h.loc[h[col].ne("")]
            if specified.groupby(parent)[col].nunique().gt(1).any():
                raise EconomyValidationError(f"conflicting {col} values for the same parent")
            known_labels = specified.drop_duplicates(parent).set_index(parent)[col].to_dict()
            h[col] = h[parent].map(known_labels).fillna("").astype("string")
    return h.set_index("io240_code", drop=False).loc[list(economy.sectors.codes)].copy()


def _parent_labels(h: pd.DataFrame, level: str) -> dict[str, str]:
    """Crosswalk label first, then SIGMA's bundled PSA label for the same code."""
    from .builtin import load_builtin_sectors

    try:
        frame = load_builtin_sectors(level)
        pairs = zip(frame["code"], frame["label"], strict=True)
        labels = {str(c).strip(): str(v).strip() for c, v in pairs}
    except Exception:  # labels are presentation only; never block a build on them
        labels = {}
    column = f"{level}_label"
    if column in h.columns:
        for code, label in h.groupby(f"{level}_code", sort=False)[column].first().items():
            if label:
                labels[code] = label
    return labels


def _tag_inputs(frame: pd.DataFrame, h: pd.DataFrame) -> pd.DataFrame:
    # IO240/IO80/IO16 codes are already conservative *singletons* from tagging.
    # Plural candidate columns are deliberately never consulted.
    if not set(_COLUMNS).issubset(frame.columns):
        raise EconomyValidationError(
            "classified places must have single-valued io240_code, io80_code, io16_code "
            "(run 'sigma load' with built-in PSA tagging first)"
        )
    data = pd.DataFrame({c: _strings(frame[c]) for c in _COLUMNS}, index=frame.index)
    valid240 = set(h.index)
    valid80 = set(h.io80_code)
    valid16 = set(h.io16_code)
    for col, known in (("io240_code", valid240), ("io80_code", valid80), ("io16_code", valid16)):
        unknown = sorted(set(data.loc[data[col].ne(""), col]) - known)
        if unknown:
            raise EconomyValidationError(f"unrecognized {col} codes: {unknown[:8]}")
    p80 = h.io80_code.to_dict()
    p16 = h.io16_code.to_dict()
    e80 = dict(zip(h.io80_code, h.io16_code, strict=True))
    # Report every inconsistent place at once instead of stopping at the first one.
    problems: list[str] = []
    kinds: Counter[str] = Counter()
    rows = zip(data.index, data.itertuples(index=False, name=None), strict=True)
    for index, (c240, c80, c16) in rows:
        found = []
        if c240 and c80 and p80[c240] != c80:
            found.append(f"conflicting IO240/IO80 tags (IO240 {c240} is under IO80 "
                         f"{p80[c240]}, place has {c80})")
        if c240 and c16 and p16[c240] != c16:
            found.append(f"conflicting IO240/IO16 tags (IO240 {c240} is under IO16 "
                         f"{p16[c240]}, place has {c16})")
        if c80 and c16 and e80[c80] != c16:
            found.append(f"conflicting IO80/IO16 tags (IO80 {c80} is under IO16 "
                         f"{e80[c80]}, place has {c16})")
        for item in found:
            kinds[item.split(" (", 1)[0]] += 1
        if found:
            problems.append(f"row {index!r}: " + "; ".join(found))
    if problems:
        summary = ", ".join(f"{k}: {n}" for k, n in sorted(kinds.items()))
        raise EconomyValidationError(
            f"{len(problems)} place(s) carry tags that disagree with the hierarchy ({summary}). "
            f"First {min(len(problems), _REPORTED)}: " + " | ".join(problems[:_REPORTED])
        )
    return data


def tagging_consistency(hierarchy: pd.DataFrame) -> dict[str, Any]:
    """Compare a crosswalk with the parent links implied by SIGMA's built-in tagging.

    SIGMA tags IO240, IO80 and IO16 separately.  Where one PSIC concordance row maps
    to a single IO240 code and a single IO80 code, a place classified by that row
    receives both codes; if the crosswalk places that IO240 code under a different
    IO80 parent, the build will reject the place.  This report lists every such
    disagreement in advance.  It is a diagnostic; it never changes the hierarchy.
    """
    from sigma.classification.io_mapping_compat import load_catalog
    from sigma.classification.reference import load_builtin_io_reference

    if not set(_COLUMNS).issubset(hierarchy):
        raise EconomyValidationError(f"hierarchy needs columns {', '.join(_COLUMNS)}")
    h = hierarchy.copy()
    for col in _COLUMNS:
        h[col] = _strings(h[col])
    up80 = dict(zip(h.io240_code, h.io80_code, strict=True))
    up16 = dict(zip(h.io80_code, h.io16_code, strict=False))
    io240_mismatch: dict[str, set[str]] = {}
    io80_mismatch: dict[str, set[str]] = {}
    tagged240: set[str] = set()
    tagged80: set[str] = set()
    for row in load_builtin_io_reference().concordance:
        tagged240.update(row.io240_codes)
        tagged80.update(row.io80_codes)
        if len(row.io240_codes) == 1 and len(row.io80_codes) == 1:
            child, parent = row.io240_codes[0], row.io80_codes[0]
            if child in up80 and up80[child] != parent:
                io240_mismatch.setdefault(child, set()).add(parent)
        if len(row.io80_codes) == 1 and len(row.io16_codes) == 1:
            child, parent = row.io80_codes[0], row.io16_codes[0]
            if child in up16 and up16[child] != parent:
                io80_mismatch.setdefault(child, set()).add(parent)
    for code, industry in load_catalog().items():
        tagged80.add(code)
        if code in up16 and up16[code] != industry.io16_code:
            io80_mismatch.setdefault(code, set()).add(industry.io16_code)
    report = {
        "io240_parent_mismatches": [
            {"io240_code": c, "hierarchy_io80": up80[c], "tagging_io80": sorted(v)}
            for c, v in sorted(io240_mismatch.items())
        ],
        "io80_parent_mismatches": [
            {"io80_code": c, "hierarchy_io16": up16[c], "tagging_io16": sorted(v)}
            for c, v in sorted(io80_mismatch.items())
        ],
        "tagging_io240_codes_missing_from_hierarchy": sorted(tagged240 - set(up80)),
        "tagging_io80_codes_missing_from_hierarchy": sorted(tagged80 - set(up16)),
    }
    report["consistent"] = not any(report[k] for k in list(report))
    return report


def require_sigma_io80_io16(hierarchy: pd.DataFrame) -> None:
    """Require the crosswalk's IO80/IO16 codes and IO80 -> IO16 links to equal SIGMA's.

    SIGMA's bundled PSA 2018 IO80 table aggregates exactly to its PSA IO16 table under
    the IO80 -> IO16 links in tagging/compatibility/industries.csv, and SIGMA's tagging
    uses the same codes.  Only the IO240 -> IO80 links are new information in a
    crosswalk, so any difference above IO80 is an error, not a diagnostic.
    """
    from sigma.classification.io_mapping_compat import load_catalog

    from .builtin import load_builtin_sectors

    if not set(_COLUMNS).issubset(hierarchy):
        raise EconomyValidationError(f"hierarchy needs columns {', '.join(_COLUMNS)}")
    io80 = _strings(hierarchy["io80_code"])
    io16 = _strings(hierarchy["io16_code"])
    known80 = set(load_builtin_sectors("io80")["code"])
    known16 = set(load_builtin_sectors("io16")["code"])
    expected = {code: item.io16_code for code, item in load_catalog().items()}
    problems: list[str] = []
    for level, found, known in (("IO80", set(io80), known80), ("IO16", set(io16), known16)):
        if found - known:
            problems.append(f"{level} codes not in SIGMA's PSA table: {sorted(found - known)[:10]}")
        if known - found:
            problems.append(f"{level} codes missing from crosswalk: {sorted(known - found)[:10]}")
    links = pd.DataFrame({"io80": io80, "io16": io16}).drop_duplicates()
    wrong = [
        f"IO80 {row.io80} -> IO16 {row.io16} (SIGMA/PSA: {expected[row.io80]})"
        for row in links.itertuples(index=False)
        if row.io80 in expected and row.io16 != expected[row.io80]
    ]
    if wrong:
        problems.append(f"{len(wrong)} IO80 -> IO16 link(s) differ from SIGMA's PSA nesting, "
                        f"e.g. {wrong[:5]}")
    if problems:
        raise EconomyValidationError("crosswalk does not match SIGMA's PSA IO80/IO16 structure: "
                                     + "; ".join(problems))


@dataclass(frozen=True)
class HierarchicalResult:
    economy: Economy
    places: pd.DataFrame
    membership: pd.DataFrame
    diagnostics: dict[str, Any]


def _label(level: str, code: str, name: str, *, other: bool = False) -> str:
    text = f"{level} {code} · {name}" if name else f"{level} {code}"
    return text + " · Other" if other else text



def _canonical_sparse_key(old_key: str, leaves: list[str],
                          parent80: dict[str, str], parent16: dict[str, str]) -> str:
    """Rename a complete hierarchy group using its actual validated ancestry.

    Historical nonnumeric test/custom group codes stay unchanged. Sector identity
    is constructed *once* at the partition boundary; downstream artifacts use it.
    """
    chunks = old_key.split(":")
    if len(chunks) < 2 or chunks[0] not in {"240", "80", "16"}:
        raise EconomyValidationError(f"unrecognized generated hierarchy sector: {old_key}")
    level, old_id = chunks[:2]
    residual = len(chunks) == 3 and chunks[2].upper() in {"O", "OTHER"}
    if len(chunks) > 3 or (len(chunks) == 3 and not residual):
        raise EconomyValidationError(f"invalid generated hierarchy sector: {old_key}")
    # Preserve historical flexibility for tiny, symbolic research fixtures;
    # the validated national IO240 hierarchy always uses zero-padded digits.
    if not (old_id.isdecimal() and all(
            leaf.isdecimal() and parent80[leaf].isdecimal()
            and parent16[leaf].isdecimal() for leaf in leaves)):
        return old_key
    broad = {parent16[leaf] for leaf in leaves}
    middle = {parent80[leaf] for leaf in leaves}
    if len(broad) != 1 or (level != "16" and len(middle) != 1):
        raise EconomyValidationError(f"hierarchical ancestry is ambiguous for {old_key}")
    top = next(iter(broad))
    if level == "240":
        if residual or len(leaves) != 1 or leaves[0] != old_id:
            raise EconomyValidationError(f"invalid detailed sector membership: {old_key}")
        return f"{top}:{parent80[old_id]}:{old_id}"
    if level == "80":
        if old_id != next(iter(middle)):
            raise EconomyValidationError(f"invalid parent sector membership: {old_key}")
        return f"{top}:{old_id}" + (":o" if residual else "")
    if old_id != top:
        raise EconomyValidationError(f"invalid broad sector membership: {old_key}")
    return top + (":o" if residual else "")

def build_hierarchical_economy(
    classified_places: pd.DataFrame,
    io240: Economy,
    hierarchy: pd.DataFrame,
    *,
    strict_coarse: bool = False,
    min_places: int = 1,
) -> HierarchicalResult:
    """Build adaptive sectors and retag places without editing the supplied inputs.

    IO240 raw transactions and gross outputs are mandatory.  An IO240 child is
    retained when at least ``min_places`` places resolve to it.  If an IO80 parent
    has retained children, its other IO240 children become '80-Other'.  An IO80
    parent without retained children is kept whole when its IO80-only places plus
    places of its folded children reach ``min_places``.  Remaining IO240 children
    within each IO16 parent are aggregated to '16(-Other)'.

    All IO240 sectors are partitioned exactly once, including sectors without any
    observed establishments, so national IO totals are not silently discarded.
    An IO80/IO16-only place with zero compatible residual remains explicitly
    unassigned by default; strict_coarse=True makes this a validation error.
    """
    integral = isinstance(min_places, (int, np.integer)) and not isinstance(min_places, bool)
    if not integral or min_places < 1:
        raise ValueError("min_places must be an integer >= 1")
    if io240.x is None:
        raise EconomyValidationError("hierarchical economy requires IO240 total output x")
    h = _reference(hierarchy, io240)
    tags = _tag_inputs(classified_places, h)
    up80 = h.io80_code.to_dict()
    up16 = h.io16_code.to_dict()

    fine = tags.io240_code.ne("")
    count240 = Counter(tags.loc[fine, "io240_code"])
    retained240 = {code for code, n in count240.items() if n >= min_places}
    folded240 = set(count240) - retained240
    support80 = Counter(tags.loc[~fine & tags.io80_code.ne(""), "io80_code"])
    for code in folded240:
        support80[up80[code]] += count240[code]
    labels240 = {s.code: s.label for s in io240.sectors}
    labels80 = _parent_labels(h, "io80")
    labels16 = _parent_labels(h, "io16")

    # Build a partition of the underlying (exhaustive) IO240 set.
    groups: list[tuple[str, str, list[str]]] = []
    for p16 in dict.fromkeys(h.io16_code):
        children16 = h.loc[h.io16_code.eq(p16)]
        taken16: set[str] = set()
        for p80 in dict.fromkeys(children16.io80_code):
            children80 = list(children16.loc[children16.io80_code.eq(p80), "io240_code"])
            precise = [c for c in children80 if c in retained240]
            for c in precise:
                groups.append((f"240:{c}", _label("IO240", c, labels240[c]), [c]))
                taken16.add(c)
            leftover = [c for c in children80 if c not in retained240]
            if precise and leftover:
                label = _label("IO80", p80, labels80.get(p80, ""), other=True)
                groups.append((f"80:{p80}:OTHER", label, leftover))
                taken16.update(leftover)
            elif not precise and support80[p80] >= min_places:
                groups.append((f"80:{p80}", _label("IO80", p80, labels80.get(p80, "")), children80))
                taken16.update(children80)
        remainder = [c for c in children16.io240_code if c not in taken16]
        if remainder:
            key = f"16:{p16}:O" if taken16 else f"16:{p16}"
            label = _label("IO16", p16, labels16.get(p16, ""), other=bool(taken16))
            groups.append((key, label, remainder))

    original = list(io240.sectors.codes)
    reverse: dict[str, str] = {}
    for key, _, leaves in groups:
        for leaf in leaves:
            if leaf in reverse:
                raise EconomyValidationError(f"IO240 leaf {leaf} has duplicate membership")
            reverse[leaf] = key
    if set(reverse) != set(original) or len(groups) > len(original):
        raise EconomyValidationError("hierarchical sectors do not partition the IO240 universe")
    for key, _, leaves in groups:
        if not key.startswith("16:") and len({up80[c] for c in leaves}) != 1:
            raise EconomyValidationError(
                f"hierarchical group {key} improperly crosses IO80 boundaries"
            )

    available = {g[0] for g in groups}
    leaves80 = {p: list(g) for p, g in h.groupby("io80_code", sort=False).io240_code}
    leaves16 = {p: list(g) for p, g in h.groupby("io16_code", sort=False).io240_code}

    def _containing(leaves: list[str]) -> str:
        """The single group holding every leaf of a coarse tag, else ''."""
        owners = {reverse[leaf] for leaf in leaves}
        return next(iter(owners)) if len(owners) == 1 else ""

    final_codes: list[str] = []
    provenance: list[str] = []
    for a, b, c in tags.itertuples(index=False):
        if a:
            key = reverse[a]
            how = "IO240" if key == f"240:{a}" else "IO240_FOLDED"
        elif b:
            key = _containing(leaves80[b])
            if key:
                how = ("IO80" if key == f"80:{b}" else
                       "IO80_SINGLE_MEMBER" if key.startswith("240:") else "IO80_FOLDED")
            else:
                key = f"80:{b}:OTHER" if f"80:{b}:OTHER" in available else ""
                how = "IO80_RESIDUAL" if key else "IO80_UNASSIGNABLE"
        elif c:
            key = _containing(leaves16[c])
            if key:
                how = "IO16" if key == f"16:{c}" else "IO16_SINGLE_MEMBER"
            else:
                key = f"16:{c}:O" if f"16:{c}:O" in available else ""
                how = "IO16_RESIDUAL" if key else "IO16_UNASSIGNABLE"
        else:
            key, how = "", "UNRESOLVED"
        if (a or b or c) and (not key or key not in available):
            if strict_coarse or a:
                raise EconomyValidationError(
                    f"place at {how} resolution cannot be assigned: "
                    f"no unambiguous residual or single sector for IO240={a!r}, "
                    f"IO80={b!r}, IO16={c!r}"
                )
            key = ""
            how = "UNASSIGNED_IO80_NO_RESIDUAL" if b else "UNASSIGNED_IO16_NO_RESIDUAL"
        final_codes.append(key)
        provenance.append(how)

    # sigma-canonical-sparse-hierarchy-v1: convert final partition identities before
    # constructing the economy, labelled places, memberships, matrices or hashes.
    # Keep the internal grouping logic above stable, and migrate only the complete
    # mutually exclusive partition. No old published artifact is ever rewritten.
    remap = {
        old: _canonical_sparse_key(old, leaves, up80, up16)
        for old, _label_text, leaves in groups
    }
    if len(set(remap.values())) != len(groups):
        raise EconomyValidationError("sparse hierarchical sector codes are not unique")
    # Keep original descriptive sector labels in the economic package: those
    # labels are unique and remain valid for historical external consumers.
    # The Explorer and tutorial clean prefixes for human presentation.
    groups = [(remap[old], label, leaves) for old, label, leaves in groups]
    final_codes = [remap.get(key, key) for key in final_codes]
    code_scheme = "sparse-v1" if any(k != v for k, v in remap.items()) else "legacy"

    # Incidence aggregation M Z M.T and M x, never aggregate technical coefficients.
    membership = np.zeros((len(groups), len(original)), dtype=np.float64)
    col = {code: index for index, code in enumerate(original)}
    for row, (_, _, leaves) in enumerate(groups):
        membership[row, [col[c] for c in leaves]] = 1.0
    z = io240.Z_raw.to_numpy(dtype=float)
    x = io240.x.to_numpy(dtype=float)
    codes = [g[0] for g in groups]
    agg_z = pd.DataFrame(membership @ z @ membership.T, index=codes, columns=codes)
    agg_x = pd.Series(membership @ x, index=codes, name="total_output")
    if not np.isclose(agg_z.to_numpy().sum(), z.sum(), rtol=1e-12, atol=1e-8):
        raise EconomyValidationError("hierarchical transactions do not conserve IO240 total")
    if not np.isclose(agg_x.sum(), x.sum(), rtol=1e-12, atol=1e-8):
        raise EconomyValidationError("hierarchical output does not conserve IO240 gross output")
    # Exclusive membership conserves the whole table; verify the IO16 roll-up cell by cell.
    parent_codes = list(dict.fromkeys(h.io16_code))
    parent_by_group = {key: up16[leaves[0]] for key, _, leaves in groups}
    for key, _, leaves in groups:
        if any(up16[c] != parent_by_group[key] for c in leaves):
            raise EconomyValidationError(
                f"hierarchical group {key} improperly crosses io16_code boundaries"
            )
    group_parent = pd.Index([parent_by_group[c] for c in codes])
    source_parent = pd.Index(list(h.io16_code))
    expanded = (agg_z.groupby(group_parent, sort=False).sum().T
                .groupby(group_parent, sort=False).sum().T
                .reindex(index=parent_codes, columns=parent_codes))
    original_aggregated = (io240.Z_raw.groupby(source_parent, sort=False).sum().T
                           .groupby(source_parent, sort=False).sum().T
                           .reindex(index=parent_codes, columns=parent_codes))
    if not np.allclose(expanded.to_numpy(), original_aggregated.to_numpy(), rtol=1e-12, atol=1e-7):
        raise EconomyValidationError("hierarchical transactions violate io16_code aggregation")

    sector_catalog = SectorCatalog(Sector(key, label) for key, label, _ in groups)
    hierarchy_digest = hashlib.sha256(
        h[list(_COLUMNS)].to_csv(index=False, lineterminator="\n").encode()
    ).hexdigest()
    partition_digest = hashlib.sha256(json.dumps(
        [[key, leaves] for key, _, leaves in groups], separators=(",", ":")
    ).encode()).hexdigest()
    economy = Economy(
        economy_id=f"{io240.economy_id}-hierarchical-{partition_digest[:12]}",
        sectors=sector_catalog, raw_transactions=agg_z, total_output=agg_x,
        label=f"Hierarchical residual aggregation of {io240.label}",
        version=io240.version, reference_year=io240.reference_year,
        provenance={"source_kind": "hierarchical_io240_residual",
                    "base_economy_id": io240.economy_id,
                    "base_economy_fingerprint": io240.economy_fingerprint,
                    "hierarchy_sha256": hierarchy_digest,
                    "partition_sha256": partition_digest,
                    "min_places": int(min_places),
                    "sector_code_scheme": code_scheme,
                    "method": "M @ Z240 @ M.T; M @ x240"},
    )
    tagged = classified_places.copy()
    tagged["economy_code"] = pd.Series(final_codes, index=tagged.index, dtype="string")
    label_map = {s.code: s.label for s in economy.sectors}
    tagged["economy_label"] = tagged.economy_code.map(label_map).fillna("").astype("string")
    tagged["economy_status"] = pd.Series(provenance, index=tagged.index, dtype="string")
    tagged["economy_source"] = "hierarchical_io240_io80_io16"
    members = pd.DataFrame([
        {"economy_code": key, "economy_label": label, "io240_code": leaf,
         "io80_code": up80[leaf], "io16_code": up16[leaf]}
        for key, label, leaves in groups for leaf in leaves
    ])
    counts = tagged.economy_status.value_counts().to_dict()
    assigned = tagged.loc[tagged.economy_code.ne(""), "economy_code"].value_counts()
    thin_groups = [
        {"economy_code": code, "assigned_places": int(count)}
        for code, count in assigned.items()
        if count < min_places
    ]
    # min_places selects branches from observed support but cannot guarantee that
    # the FINAL spatial types all meet a clustering threshold: coarse assignments,
    # residuals, and geographic connectivity can still produce empty/noisy groups.
    assumed_coarse = sum(s in ("IO80_RESIDUAL", "IO16_RESIDUAL") for s in provenance)
    return HierarchicalResult(economy, tagged, members, {
        "sector_code_scheme": code_scheme,
        "original_io240_sector_count": len(original), "final_sector_count": len(groups),
        "min_places": int(min_places),
        "retained_io240_codes": sorted(retained240),
        "folded_io240_codes": sorted(folded240),
        "place_counts_by_resolution": {str(k): int(v) for k, v in counts.items()},
        "transaction_total_io240": float(z.sum()),
        "transaction_total_hierarchical": float(agg_z.to_numpy().sum()),
        "gross_output_total_io240": float(x.sum()),
        "gross_output_total_hierarchical": float(agg_x.sum()),
        "hierarchy_sha256": hierarchy_digest, "partition_sha256": partition_digest,
        "unresolved_place_count": int(sum(not c for c in final_codes)),
        "unassigned_coarse_place_count": int(sum(status.startswith("UNASSIGNED_") for status in provenance)),
        "coarse_residual_assumption_place_count": int(assumed_coarse),
        "assigned_place_count": int(sum(bool(code) for code in final_codes)),
        "assigned_places_by_final_sector": {str(c): int(n) for c, n in assigned.items()},
        "observed_sectors_below_min_places": thin_groups,
        "note": "min_places is an industry-selection threshold, not a guarantee of HDBSCAN clusters",
    })


def reconciliation(io240: Economy, hierarchy: pd.DataFrame, reference: Economy, *,
                   resolution: str) -> dict[str, Any]:
    """Check original IO240 aggregation against an external IO80/IO16 matrix.

    Mismatches are diagnostic, not secretly used to modify the economic model.
    Differences can stem from distinct official releases, valuation, or rounding.
    """
    if resolution not in ("io80", "io16"):
        raise ValueError("resolution must be io80 or io16")
    h = _reference(hierarchy, io240)
    parents = h[f"{resolution}_code"].tolist()
    known = list(reference.sectors.codes)
    if not set(parents).issubset(set(known)):
        raise EconomyValidationError(f"hierarchy contains {resolution} codes absent from reference table")
    source = io240.Z_raw.copy()
    z80 = source.groupby(pd.Index(parents), sort=False).sum().T.groupby(pd.Index(parents), sort=False).sum().T
    z80 = z80.reindex(index=known, columns=known, fill_value=0.0)
    delta = z80.to_numpy(dtype=float) - reference.Z_raw.to_numpy(dtype=float)
    outputs = None
    if io240.x is not None and reference.x is not None:
        x = io240.x.groupby(pd.Index(parents), sort=False).sum().reindex(known, fill_value=0.0)
        output_delta = x.to_numpy(dtype=float) - reference.x.to_numpy(dtype=float)
        outputs = {
            "max_absolute_output_difference": float(np.abs(output_delta).max()),
            "gross_output_total_difference": float(output_delta.sum()),
        }
    return {"resolution": resolution,
            "max_absolute_transaction_difference": float(np.abs(delta).max()),
            "sum_absolute_transaction_difference": float(np.abs(delta).sum()),
            "transaction_total_difference": float(delta.sum()),
            **(outputs or {})}


def write_hierarchical_package(result: HierarchicalResult, directory: str | Path) -> None:
    """Write a standard Economy.from_directory-compatible package, without activation.

    economy.yml is written with a YAML serializer and carries a ``derivation`` block,
    so 'sigma run' records the IO240 base, crosswalk and partition in its provenance.
    """
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    e = result.economy
    e.sectors.to_frame().to_csv(root / "sectors.csv", index=False, lineterminator="\n")
    e.Z_raw.to_csv(root / "transactions.csv", index_label="sector", float_format="%.17g", lineterminator="\n")
    e.x.rename_axis("sector").reset_index().to_csv(root / "total_output.csv", index=False, float_format="%.17g", lineterminator="\n")
    meta: dict[str, Any] = {"id": e.economy_id, "label": e.label}
    if e.version is not None:
        meta["version"] = e.version
    if e.reference_year is not None:
        meta["reference_year"] = int(e.reference_year)
    meta.update(sectors="sectors.csv", transactions="transactions.csv",
                total_output="total_output.csv")
    meta["derivation"] = {str(k): v for k, v in e.provenance.items()}
    (root / "economy.yml").write_text(
        yaml.safe_dump(meta, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    result.membership.to_csv(root / "membership.csv", index=False, lineterminator="\n")
    (root / "audit.json").write_text(
        json.dumps(result.diagnostics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _file_sha256(path: Path) -> str:
    """Stream a content hash instead of loading a potentially huge GeoParquet."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def activate_hierarchical_places(
    original: str | Path, preview: str | Path, *, expected_original_sha256: str | None = None
) -> Path:
    """Back up a loaded handoff once, then atomically switch to the preview.

    A failed copy or rename leaves the original in place, and removes any new
    backup. Pre-existing backups are never overwritten. The caller must validate
    its chosen economy directory independently before calling this helper.
    """
    import os
    import shutil

    original = Path(original).expanduser().resolve()
    preview = Path(preview).expanduser().resolve()
    if not original.is_file() or not preview.is_file():
        raise FileNotFoundError("both original and hierarchical preview must exist")
    if original == preview:
        raise ValueError("hierarchical preview must not overwrite itself")
    if expected_original_sha256 is not None and _file_sha256(original) != expected_original_sha256:
        raise ValueError("loaded places changed after the hierarchical preview was constructed; refusing activation")
    backup = original.with_name("places.pre-hierarchical.parquet")
    if backup.exists():
        raise FileExistsError(f"activation backup already exists: {backup}")
    backup_tmp = backup.with_suffix(backup.suffix + ".tmp")
    active_tmp = original.with_suffix(original.suffix + ".hierarchical.tmp")
    if backup_tmp.exists() or active_tmp.exists():
        raise FileExistsError("stale activation temporary file exists; inspect it before retrying")
    backed_up = False
    activated = False
    try:
        shutil.copy2(original, backup_tmp)
        shutil.copy2(preview, active_tmp)
        # Detect a concurrent change between preflight and snapshot creation.
        if expected_original_sha256 is not None and _file_sha256(backup_tmp) != expected_original_sha256:
            raise ValueError("loaded places changed during activation; refusing to switch")
        # Both copies succeeded before changing any of the visible handoffs.
        os.replace(backup_tmp, backup)
        backed_up = True
        os.replace(active_tmp, original)
        activated = True
        return backup
    finally:
        # An interrupted attempt must not leave a backup which blocks retrying
        # when the original was never changed.
        if not activated and backed_up:
            backup.unlink(missing_ok=True)
        backup_tmp.unlink(missing_ok=True)
        active_tmp.unlink(missing_ok=True)
