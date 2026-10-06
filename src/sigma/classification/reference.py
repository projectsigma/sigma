from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import unicodedata
from collections import Counter, defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from functools import cached_property
from importlib import resources

import pandas as pd

PSIC_LEVELS = ("section", "division", "group", "class", "subclass")
IO_LEVELS = ("section", "division", "group")
IO_RESOLUTIONS = ("io16", "io80", "io240")
_ALLOWED_CROSSWALK_SOURCES = frozenset({"osm", "overture"})
_CONCORDANCE_PSIC_VERSION = "2019 update to 2009 PSIC"
_CONFIDENCE_VALUES = frozenset(
    {"High", "High with caveat", "Medium-High", "Medium", "Low", "Not mapped", ""}
)
_BRIDGE_RELATIONS = frozenset(
    {"same", "recoded", "renamed", "changed_scope", "new", "no_counterpart"}
)
_BRIDGE_BASES = frozenset({"code_title_match", "draft", "reviewed"})
_CODE_RE = {
    "section": re.compile(r"[A-Z]"),
    "division": re.compile(r"[0-9]{2}"),
    "group": re.compile(r"[0-9]{3}"),
}
_IO_CODE_RE = {
    "io16": re.compile(r"[0-9]{2}"),
    "io80": re.compile(r"[0-9]{2}"),
    "io240": re.compile(r"[0-9]{3}"),
}


class ReferenceDataError(ValueError):
    """Raised when a bundled classification reference asset is absent or inconsistent."""


@dataclass(frozen=True, slots=True)
class PsicNode:
    code: str
    level: str
    title: str
    parent_code: str | None = None
    description: str = ""
    includes: str = ""
    excludes: str = ""
    source_url: str = ""
    scheme: str = "psic"
    version: str = "rev5"

    @property
    def retrieval_text(self) -> str:
        return "\n".join(
            value for value in (self.title, self.description, self.includes) if value
        ).strip()


@dataclass(frozen=True, slots=True)
class TaxonomyStructure:
    errors: tuple[str, ...] = ()
    level_gaps: tuple[str, ...] = ()


class PsicTaxonomy:
    """Validated PSIC hierarchy used by later classification stages."""

    def __init__(self, nodes: Iterable[PsicNode]):
        node_list = list(nodes)
        if not node_list:
            raise ReferenceDataError("PSIC taxonomy is empty")

        self.nodes = {node.code: node for node in node_list}
        if len(self.nodes) != len(node_list):
            raise ReferenceDataError("PSIC taxonomy contains duplicate codes")

        schemes = {(node.scheme.casefold().strip(), str(node.version).strip()) for node in node_list}
        if len(schemes) != 1 or any(not part for pair in schemes for part in pair):
            raise ReferenceDataError(
                f"expected one nonblank taxonomy scheme/version, found {sorted(schemes)!r}"
            )
        self.scheme, self.version = next(iter(schemes))
        self.origin = "custom"
        self.asset_sha256 = None

        self._children: dict[str | None, list[str]] = defaultdict(list)
        for node in node_list:
            if node.level not in PSIC_LEVELS:
                raise ReferenceDataError(
                    f"PSIC code {node.code!r} has unknown level {node.level!r}"
                )
            if node.parent_code and node.parent_code not in self.nodes:
                raise ReferenceDataError(
                    f"PSIC code {node.code!r} refers to missing parent {node.parent_code!r}"
                )
            self._children[node.parent_code].append(node.code)
        for values in self._children.values():
            values.sort(key=lambda code: (len(code), code))

        self._root_paths: dict[str, tuple[str, ...]] = {}
        self._leaf_cache: dict[str, frozenset[str]] = {}
        self._branch_depth_cache: dict[str, int] = {}
        self._build_root_paths()

    def _build_root_paths(self) -> None:
        for code in self.nodes:
            if code in self._root_paths:
                continue
            chain: list[str] = []
            seen: set[str] = set()
            current: str | None = code
            while current is not None and current not in self._root_paths:
                if current in seen:
                    raise ReferenceDataError(f"cycle detected in PSIC hierarchy at {current}")
                seen.add(current)
                chain.append(current)
                current = self.nodes[current].parent_code
            suffix: tuple[str, ...] = () if current is None else self._root_paths[current]
            for member in reversed(chain):
                suffix = (member, *suffix)
                self._root_paths[member] = suffix

    @property
    def roots(self) -> list[str]:
        return list(self._children.get(None, ()))

    @cached_property
    def fingerprint(self) -> str:
        # Computed once: the taxonomy is not modified after construction, and the
        # classifier reads this value for every classified row.
        payload = [asdict(self.nodes[code]) for code in sorted(self.nodes)]
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]

    def get(self, code: str) -> PsicNode:
        return self.nodes[str(code)]

    def children(self, code: str | None) -> list[str]:
        return list(self._children.get(code, ()))

    def parent(self, code: str) -> str | None:
        return self.get(code).parent_code

    def has_children(self, code: str | None) -> bool:
        return bool(self._children.get(code))

    def level_of(self, code: str | None) -> str | None:
        return self.get(code).level if code is not None else None

    @property
    def max_depth(self) -> int:
        return max(self.depth(code) for code in self.nodes)

    def branch_max_depth(self, code: str) -> int:
        key = str(code)
        cached = self._branch_depth_cache.get(key)
        if cached is not None:
            return cached
        value = max(self.depth(leaf) for leaf in self.leaves(key))
        self._branch_depth_cache[key] = value
        return value

    def ancestors(self, code: str, *, include_self: bool = True) -> list[str]:
        path = self._root_paths[str(code)]
        return list(path if include_self else path[1:])

    def path_from_root(self, code: str) -> list[str]:
        return list(reversed(self._root_paths[str(code)]))

    def depth(self, code: str) -> int:
        return len(self._root_paths[str(code)])

    def descendants(self, code: str, *, include_self: bool = False) -> list[str]:
        out = [str(code)] if include_self else []
        queue = deque(self.children(str(code)))
        while queue:
            current = queue.popleft()
            out.append(current)
            queue.extend(self.children(current))
        return out

    def leaves(self, code: str) -> frozenset[str]:
        key = str(code)
        cached = self._leaf_cache.get(key)
        if cached is not None:
            return cached
        children = self.children(key)
        if not children:
            result = frozenset({key})
        else:
            values: set[str] = set()
            for child in children:
                values.update(self.leaves(child))
            result = frozenset(values)
        self._leaf_cache[key] = result
        return result

    def lca(self, codes: Iterable[str]) -> str | None:
        paths = [self.path_from_root(str(code)) for code in codes]
        if not paths:
            return None
        common: str | None = None
        for level in zip(*paths, strict=False):
            if len(set(level)) != 1:
                break
            common = level[0]
        return common

    def structural_report(self) -> TaxonomyStructure:
        rank = {level: index for index, level in enumerate(PSIC_LEVELS)}
        errors: list[str] = []
        gaps: list[str] = []
        for code, node in self.nodes.items():
            own_rank = rank[node.level]
            if own_rank == 0:
                if node.parent_code is not None:
                    errors.append(f"{code} is a section but has a parent")
                continue
            if node.parent_code is None:
                errors.append(f"{code} ({node.level}) has no parent")
                continue
            parent = self.nodes[node.parent_code]
            parent_rank = rank[parent.level]
            if parent_rank >= own_rank:
                errors.append(
                    f"{code} ({node.level}) has non-shallower parent "
                    f"{parent.code} ({parent.level})"
                )
                continue
            if code.isdigit() and parent.code.isdigit() and not code.startswith(parent.code):
                errors.append(
                    f"{code} ({node.level}) does not extend numeric parent {parent.code}"
                )
                continue
            if parent_rank != own_rank - 1:
                gaps.append(
                    f"{code} ({node.level}) attaches to {parent.code} ({parent.level}); "
                    f"missing intermediate {PSIC_LEVELS[own_rank - 1]} level"
                )
        return TaxonomyStructure(tuple(errors), tuple(gaps))

    @classmethod
    def from_frame(
        cls, frame: pd.DataFrame, *, origin: str = "custom", asset_sha256: str | None = None
    ) -> PsicTaxonomy:
        required = {"scheme", "version", "code", "level", "title", "parent_code"}
        missing = required - set(frame.columns)
        if missing:
            raise ReferenceDataError(
                f"PSIC taxonomy is missing columns {sorted(missing)}"
            )
        cleaned = frame.fillna("")
        nodes = [
            PsicNode(
                scheme=str(row.get("scheme", "")).casefold(),
                version=str(row.get("version", "")),
                code=str(row.get("code", "")),
                level=str(row.get("level", "")).casefold(),
                title=str(row.get("title", "")),
                parent_code=str(row.get("parent_code", "")) or None,
                description=str(row.get("description", "")),
                includes=str(row.get("includes", "")),
                excludes=str(row.get("excludes", "")),
                source_url=str(row.get("source_url", "")),
            )
            for row in cleaned.to_dict("records")
        ]
        taxonomy = cls(nodes)
        taxonomy.origin = str(origin or "custom")
        taxonomy.asset_sha256 = None if asset_sha256 is None else str(asset_sha256)
        return taxonomy

    @classmethod
    def builtin_rev5(cls) -> "PsicTaxonomy":
        return load_builtin_psic_taxonomy()

    @classmethod
    def from_directory(cls, directory) -> "PsicTaxonomy":
        from pathlib import Path
        root = Path(directory).expanduser().resolve()
        candidates = [root / "nodes.parquet", root / "nodes.csv"]
        path = next((p for p in candidates if p.is_file()), None)
        if path is None:
            raise FileNotFoundError(f"expected nodes.parquet or nodes.csv in {root}")
        frame = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path, dtype=str, keep_default_na=False)
        return cls.from_frame(frame, origin=f"directory:{root}")


@dataclass(frozen=True, slots=True)
class IOBridgeRow:
    rev5_level: str
    rev5_code: str
    rev5_title: str
    psic2019_codes: tuple[str, ...]
    relation: str
    basis: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class IOConcordanceRow:
    psic_level: str
    psic_code: str
    psic_name: str
    io16_codes: tuple[str, ...]
    io16_names: tuple[str, ...]
    io16_confidence: str
    io80_codes: tuple[str, ...]
    io80_names: tuple[str, ...]
    io80_confidence: str
    io240_codes: tuple[str, ...]
    io240_names: tuple[str, ...]
    io240_confidence: str


@dataclass(frozen=True, slots=True)
class IOReferenceCatalog:
    bridge: tuple[IOBridgeRow, ...]
    concordance: tuple[IOConcordanceRow, ...]
    bridge_sha256: str
    concordance_sha256: str

    @property
    def bridge_level_counts(self) -> Mapping[str, int]:
        return dict(Counter(row.rev5_level for row in self.bridge))

    @property
    def concordance_level_counts(self) -> Mapping[str, int]:
        return dict(Counter(row.psic_level for row in self.concordance))

    def validate_against(self, taxonomy: PsicTaxonomy) -> list[str]:
        issues: list[str] = []
        for row in self.bridge:
            node = taxonomy.nodes.get(row.rev5_code)
            if node is None:
                issues.append(f"bridge code {row.rev5_code} is absent from PSIC rev5")
                continue
            if node.level != row.rev5_level:
                issues.append(
                    f"bridge code {row.rev5_code} says {row.rev5_level} "
                    f"but taxonomy says {node.level}"
                )
            if _title_key(node.title) != _title_key(row.rev5_title):
                issues.append(f"bridge title mismatch for PSIC rev5 code {row.rev5_code}")
        return issues


@dataclass(frozen=True, slots=True)
class CrosswalkFileReport:
    name: str
    rows: int
    source_counts: Mapping[str, int]
    sha256: str


@dataclass(frozen=True, slots=True)
class ClassificationReferenceReport:
    taxonomy_nodes: int
    taxonomy_level_counts: Mapping[str, int]
    taxonomy_roots: int
    taxonomy_fingerprint: str
    structural_level_gaps: int
    bridge_rows: int
    bridge_level_counts: Mapping[str, int]
    concordance_rows: int
    concordance_level_counts: Mapping[str, int]
    crosswalk_files: tuple[CrosswalkFileReport, ...]
    workbook_sha256: str
    nodes_sha256: str

    @property
    def crosswalk_rows(self) -> int:
        return sum(item.rows for item in self.crosswalk_files)


@dataclass(frozen=True, slots=True)
class _TextAsset:
    name: str
    raw: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.raw).hexdigest()

    @property
    def text(self) -> str:
        return self.raw.decode("utf-8-sig")


def _data_resource(*parts: str):
    return resources.files("sigma.resources.classification").joinpath(*parts)


def _resource_bytes(*parts: str) -> bytes:
    target = _data_resource(*parts)
    try:
        return target.read_bytes()
    except (FileNotFoundError, OSError) as exc:
        raise ReferenceDataError(
            f"missing bundled classification asset: {'/'.join(parts)}"
        ) from exc


def _canonical_manifest_bytes(relative_name: str, raw: bytes) -> bytes:
    """Return the canonical byte representation used by the asset manifest.

    CSV resources are text assets and may be materialized with either LF or CRLF
    line endings depending on the checkout/apply environment.  The manifest records
    the canonical LF form so validation remains strict about content while staying
    cross-platform.
    """
    if str(relative_name).casefold().endswith(".csv"):
        return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return raw


def _verify_asset_manifest() -> None:
    try:
        payload = json.loads(_resource_bytes("manifest.json").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReferenceDataError("bundled classification manifest is unreadable") from exc

    if payload.get("schema_version") != 1 or not isinstance(payload.get("assets"), dict):
        raise ReferenceDataError("bundled classification manifest has an unsupported schema")

    for relative_name, expected in payload["assets"].items():
        parts = tuple(str(relative_name).split("/"))
        raw = _resource_bytes(*parts)
        canonical = _canonical_manifest_bytes(str(relative_name), raw)
        digest = hashlib.sha256(canonical).hexdigest()
        if digest != str(expected.get("sha256", "")):
            raise ReferenceDataError(
                f"classification asset checksum mismatch: {relative_name}"
            )
        if len(canonical) != int(expected.get("size_bytes", -1)):
            raise ReferenceDataError(
                f"classification asset size mismatch: {relative_name}"
            )


def _title_key(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip().casefold()


def _split_semicolon(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in str(value or "").split(";") if part.strip())


def _csv_rows(asset: _TextAsset, required: set[str], label: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(asset.text, newline=""))
    missing = required - set(reader.fieldnames or ())
    if missing:
        raise ReferenceDataError(f"{label} is missing columns {sorted(missing)}")
    rows: list[dict[str, str]] = []
    for record in reader:
        cleaned = {
            key: str(value or "").strip()
            for key, value in record.items()
            if key is not None
        }
        if any(cleaned.values()):
            rows.append(cleaned)
    return rows


def load_builtin_psic_taxonomy() -> PsicTaxonomy:
    raw = _resource_bytes("psic_rev5", "nodes.parquet")
    try:
        frame = pd.read_parquet(io.BytesIO(raw))
    except ImportError as exc:
        raise ReferenceDataError(
            "cannot read bundled PSIC taxonomy because no Parquet engine is available; "
            "install the declared pyarrow dependency"
        ) from exc
    except Exception as exc:
        raise ReferenceDataError(f"cannot read bundled PSIC taxonomy: {exc}") from exc
    return PsicTaxonomy.from_frame(
        frame,
        origin="builtin:psic_rev5",
        asset_sha256=hashlib.sha256(raw).hexdigest(),
    )


def load_builtin_io_reference() -> IOReferenceCatalog:
    bridge_asset = _TextAsset(
        "psic_rev5_to_psic_2019.csv",
        _resource_bytes("io", "psic_rev5_to_psic_2019.csv"),
    )
    concordance_asset = _TextAsset(
        "psic_2019_to_io_2018.csv",
        _resource_bytes("io", "psic_2019_to_io_2018.csv"),
    )

    bridge_required = {
        "rev5_level",
        "rev5_code",
        "rev5_title",
        "psic2019_codes",
        "relation",
        "basis",
        "note",
    }
    concordance_required = {
        "psic_version",
        "psic_level",
        "psic_code",
        "psic_name",
        *(
            f"{resolution}_{field}"
            for resolution in IO_RESOLUTIONS
            for field in ("codes", "names", "confidence")
        ),
    }

    bridge_records = _csv_rows(bridge_asset, bridge_required, "PSIC rev5-to-2019 bridge")
    concordance_records = _csv_rows(
        concordance_asset, concordance_required, "PSIC 2019-to-I-O concordance"
    )

    bridge: list[IOBridgeRow] = []
    bridge_keys: set[tuple[str, str]] = set()
    for line_no, record in enumerate(bridge_records, start=2):
        level = record["rev5_level"].casefold()
        code = record["rev5_code"]
        where = f"PSIC bridge line {line_no}"
        if level not in IO_LEVELS:
            raise ReferenceDataError(f"{where}: unsupported rev5 level {level!r}")
        if not _CODE_RE[level].fullmatch(code):
            raise ReferenceDataError(f"{where}: malformed rev5 code {code!r}")
        key = (level, code)
        if key in bridge_keys:
            raise ReferenceDataError(f"{where}: duplicate rev5 code {code!r}")
        bridge_keys.add(key)

        relation = record["relation"]
        basis = record["basis"]
        if relation not in _BRIDGE_RELATIONS:
            raise ReferenceDataError(f"{where}: unknown relation {relation!r}")
        if basis not in _BRIDGE_BASES:
            raise ReferenceDataError(f"{where}: unknown basis {basis!r}")
        targets = _split_semicolon(record["psic2019_codes"])
        if relation == "no_counterpart":
            if targets:
                raise ReferenceDataError(f"{where}: no_counterpart row has PSIC 2019 codes")
        elif not targets:
            raise ReferenceDataError(f"{where}: relation {relation!r} requires PSIC 2019 codes")
        for target in targets:
            target_level = (
                "section" if re.fullmatch(r"[A-Z]", target)
                else "division" if re.fullmatch(r"[0-9]{2}", target)
                else "group" if re.fullmatch(r"[0-9]{3}", target)
                else None
            )
            if target_level is None:
                raise ReferenceDataError(f"{where}: malformed PSIC 2019 code {target!r}")
        if not record["rev5_title"]:
            raise ReferenceDataError(f"{where}: blank rev5 title")
        bridge.append(
            IOBridgeRow(
                rev5_level=level,
                rev5_code=code,
                rev5_title=record["rev5_title"],
                psic2019_codes=targets,
                relation=relation,
                basis=basis,
                note=record["note"],
            )
        )

    concordance: list[IOConcordanceRow] = []
    concordance_keys: set[tuple[str, str]] = set()
    for line_no, record in enumerate(concordance_records, start=2):
        where = f"I-O concordance line {line_no}"
        if record["psic_version"] != _CONCORDANCE_PSIC_VERSION:
            raise ReferenceDataError(
                f"{where}: unexpected PSIC version {record['psic_version']!r}"
            )
        level = record["psic_level"].casefold()
        code = record["psic_code"]
        if level not in IO_LEVELS or not _CODE_RE[level].fullmatch(code):
            raise ReferenceDataError(f"{where}: malformed PSIC {level!r} code {code!r}")
        key = (level, code)
        if key in concordance_keys:
            raise ReferenceDataError(f"{where}: duplicate PSIC code {code!r}")
        concordance_keys.add(key)
        if not record["psic_name"]:
            raise ReferenceDataError(f"{where}: blank PSIC name")

        parsed_codes: dict[str, tuple[str, ...]] = {}
        parsed_names: dict[str, tuple[str, ...]] = {}
        parsed_confidence: dict[str, str] = {}
        for resolution in IO_RESOLUTIONS:
            codes = _split_semicolon(record[f"{resolution}_codes"])
            names = tuple(
                part.strip()
                for part in str(record[f"{resolution}_names"] or "").split("|")
                if part.strip()
            )
            malformed = [
                value for value in codes if not _IO_CODE_RE[resolution].fullmatch(value)
            ]
            if malformed:
                raise ReferenceDataError(f"{where}: malformed {resolution} codes {malformed}")
            if codes and len(codes) != len(names):
                raise ReferenceDataError(
                    f"{where}: {resolution} has {len(codes)} codes but {len(names)} names"
                )
            confidence = record[f"{resolution}_confidence"]
            if confidence not in _CONFIDENCE_VALUES:
                raise ReferenceDataError(
                    f"{where}: unknown {resolution} confidence {confidence!r}"
                )
            parsed_codes[resolution] = codes
            parsed_names[resolution] = names
            parsed_confidence[resolution] = confidence if codes else "Not mapped"

        concordance.append(
            IOConcordanceRow(
                psic_level=level,
                psic_code=code,
                psic_name=record["psic_name"],
                io16_codes=parsed_codes["io16"],
                io16_names=parsed_names["io16"],
                io16_confidence=parsed_confidence["io16"],
                io80_codes=parsed_codes["io80"],
                io80_names=parsed_names["io80"],
                io80_confidence=parsed_confidence["io80"],
                io240_codes=parsed_codes["io240"],
                io240_names=parsed_names["io240"],
                io240_confidence=parsed_confidence["io240"],
            )
        )

    return IOReferenceCatalog(
        bridge=tuple(bridge),
        concordance=tuple(concordance),
        bridge_sha256=bridge_asset.sha256,
        concordance_sha256=concordance_asset.sha256,
    )


def _crosswalk_reports() -> tuple[CrosswalkFileReport, ...]:
    folder = _data_resource("crosswalks")
    reports: list[CrosswalkFileReport] = []
    names = sorted(
        entry.name
        for entry in folder.iterdir()
        if entry.name.startswith("psic_rev5") and entry.name.endswith(".csv")
    )
    if not names:
        raise ReferenceDataError("no bundled PSIC crosswalk/reference CSV files found")

    for name in names:
        raw = _resource_bytes("crosswalks", name)
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
        if "source" not in set(reader.fieldnames or ()):
            raise ReferenceDataError(f"crosswalk reference {name} has no source column")
        counts: Counter[str] = Counter()
        rows = 0
        for record in reader:
            if not any(str(value or "").strip() for value in record.values()):
                continue
            source = str(record.get("source") or "").strip().casefold()
            rows += 1
            counts[source] += 1
            if source not in _ALLOWED_CROSSWALK_SOURCES:
                raise ReferenceDataError(
                    f"crosswalk reference {name} contains excluded source {source!r}"
                )
        reports.append(
            CrosswalkFileReport(
                name=name,
                rows=rows,
                source_counts=dict(sorted(counts.items())),
                sha256=hashlib.sha256(raw).hexdigest(),
            )
        )
    return tuple(reports)


def validate_builtin_classification_reference() -> ClassificationReferenceReport:
    _verify_asset_manifest()
    taxonomy = load_builtin_psic_taxonomy()
    structure = taxonomy.structural_report()
    if structure.errors:
        preview = "; ".join(structure.errors[:5])
        raise ReferenceDataError(
            f"bundled PSIC taxonomy has {len(structure.errors)} structural error(s): {preview}"
        )

    io_reference = load_builtin_io_reference()
    io_issues = io_reference.validate_against(taxonomy)
    if io_issues:
        preview = "; ".join(io_issues[:5])
        raise ReferenceDataError(
            f"bundled PSIC/I-O bridge has {len(io_issues)} taxonomy mismatch(es): {preview}"
        )

    crosswalk_files = _crosswalk_reports()
    level_counts = Counter(node.level for node in taxonomy.nodes.values())
    return ClassificationReferenceReport(
        taxonomy_nodes=len(taxonomy.nodes),
        taxonomy_level_counts={level: int(level_counts.get(level, 0)) for level in PSIC_LEVELS},
        taxonomy_roots=len(taxonomy.roots),
        taxonomy_fingerprint=taxonomy.fingerprint,
        structural_level_gaps=len(structure.level_gaps),
        bridge_rows=len(io_reference.bridge),
        bridge_level_counts=io_reference.bridge_level_counts,
        concordance_rows=len(io_reference.concordance),
        concordance_level_counts=io_reference.concordance_level_counts,
        crosswalk_files=crosswalk_files,
        workbook_sha256=hashlib.sha256(
            _resource_bytes(
                "psic_rev5", "PSIC_Revision_5_Detailed_Structure_30July2026.xlsx"
            )
        ).hexdigest(),
        nodes_sha256=hashlib.sha256(
            _resource_bytes("psic_rev5", "nodes.parquet")
        ).hexdigest(),
    )
