from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from ..errors import SourceError
from ..paths import source_store_root

SOURCE_STORE_SCHEMA_VERSION = 1
_HASH_CHUNK_SIZE = 8 * 1024 * 1024
_SLUG_RE = re.compile(r"[^a-z0-9._-]+")
_SHAPEFILE_EXTENSIONS = (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix", ".sbn", ".sbx")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _slug(value: str) -> str:
    text = _SLUG_RE.sub("-", str(value).casefold()).strip("-._")
    return text or "source"


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _stat_key(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "device": int(getattr(stat, "st_dev", 0)),
        "inode": int(getattr(stat, "st_ino", 0)),
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _file_md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest().lower()


def _directory_identity(path: Path, hasher: Callable[[Path], str]) -> tuple[str, int, list[dict[str, object]]]:
    members: list[dict[str, object]] = []
    total_size = 0
    candidates = (
        p
        for p in path.rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and p.suffix.casefold() not in {".py", ".pyc"}
    )
    for member in sorted(candidates, key=lambda p: p.as_posix()):
        relative = member.relative_to(path).as_posix()
        size = int(member.stat().st_size)
        total_size += size
        members.append({"path": relative, "size": size, "sha256": hasher(member)})
    digest = hashlib.sha256(_canonical_json(members)).hexdigest()
    return digest, total_size, members


@dataclass(frozen=True, slots=True)
class SourceValidation:
    valid: bool
    reason: str
    expected_sha256: str
    actual_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Immutable identity for an external, packaged, or managed source snapshot."""

    source_id: str
    kind: str
    provider: str
    name: str
    sha256: str
    size: int
    path: Path
    version: str | None = None
    selection: Mapping[str, object] = MappingProxyType({})
    metadata: Mapping[str, object] = MappingProxyType({})
    managed: bool = False
    is_directory: bool = False
    manifest_path: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))
        object.__setattr__(self, "selection", MappingProxyType(dict(self.selection)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        if self.manifest_path is not None:
            object.__setattr__(self, "manifest_path", Path(self.manifest_path))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": SOURCE_STORE_SCHEMA_VERSION,
            "source_id": self.source_id,
            "kind": self.kind,
            "provider": self.provider,
            "name": self.name,
            "version": self.version,
            "sha256": self.sha256,
            "size": int(self.size),
            "path": str(self.path),
            "selection": dict(self.selection),
            "metadata": dict(self.metadata),
            "managed": bool(self.managed),
            "is_directory": bool(self.is_directory),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object], *, manifest_path: Path | None = None) -> "SourceRef":
        return cls(
            source_id=str(payload["source_id"]),
            kind=str(payload["kind"]),
            provider=str(payload["provider"]),
            name=str(payload["name"]),
            version=str(payload["version"]) if payload.get("version") not in (None, "") else None,
            sha256=str(payload["sha256"]),
            size=int(payload["size"]),
            path=Path(str(payload["path"])),
            selection=dict(payload.get("selection") or {}),
            metadata=dict(payload.get("metadata") or {}),
            managed=bool(payload.get("managed", False)),
            is_directory=bool(payload.get("is_directory", False)),
            manifest_path=manifest_path,
        )


@dataclass(frozen=True, slots=True)
class LegacyCacheAdoption:
    geofabrik: SourceRef | None
    overture: tuple[SourceRef, ...]
    prepared_osm: Mapping[str, object] | None

    def __post_init__(self) -> None:
        if self.prepared_osm is not None:
            object.__setattr__(self, "prepared_osm", MappingProxyType(dict(self.prepared_osm)))


class SourceStore:
    """Small content-addressed registry for reusable source snapshots.

    The store owns source identity and local references. It does not own derived
    workflow artifacts; those begin at C7 with ``ArtifactStore``.
    """

    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root is not None else self.default_root()
        self.root = self.root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._index_path = self.root / "source-index.json"
        self._index = self._load_index()

    @staticmethod
    def default_root() -> Path:
        return source_store_root()

    def _load_index(self) -> dict[str, object]:
        payload = _read_json(self._index_path)
        if payload.get("schema_version") != SOURCE_STORE_SCHEMA_VERSION:
            return {
                "schema_version": SOURCE_STORE_SCHEMA_VERSION,
                "sources": {},
                "hash_cache": {},
            }
        payload.setdefault("sources", {})
        payload.setdefault("hash_cache", {})
        return payload

    def _save_index(self) -> None:
        _atomic_json(self._index_path, self._index)

    def _remember_hash(self, path: Path, digest: str) -> None:
        path = path.expanduser().resolve()
        cache = self._index.setdefault("hash_cache", {})
        if not isinstance(cache, dict):
            cache = {}
            self._index["hash_cache"] = cache
        cache[str(path)] = {"stat": _stat_key(path), "sha256": digest}
        self._save_index()

    def _hash_file(self, path: Path, *, force: bool = False) -> str:
        path = path.expanduser().resolve()
        key = str(path)
        stat_key = _stat_key(path)
        cache = self._index.setdefault("hash_cache", {})
        if not isinstance(cache, dict):
            cache = {}
            self._index["hash_cache"] = cache
        prior = cache.get(key)
        if not force and isinstance(prior, dict):
            prior_stat = prior.get("stat")
            prior_hash = prior.get("sha256")
            if prior_stat == stat_key and isinstance(prior_hash, str) and len(prior_hash) == 64:
                return prior_hash

        digest = _file_sha256(path)
        cache[key] = {"stat": stat_key, "sha256": digest}
        self._save_index()
        return digest

    def _path_identity(self, path: Path, *, force: bool = False) -> tuple[str, int, list[dict[str, object]] | None]:
        path = path.expanduser().resolve()
        if not path.exists():
            raise SourceError(f"source path does not exist: {path}")
        if path.is_dir():
            digest, size, members = _directory_identity(
                path,
                lambda member: self._hash_file(member, force=force),
            )
            return digest, size, members
        if path.suffix.casefold() == ".shp":
            members: list[dict[str, object]] = []
            total_size = 0
            for suffix in _SHAPEFILE_EXTENSIONS:
                member = path.with_suffix(suffix)
                if not member.is_file():
                    continue
                size = int(member.stat().st_size)
                total_size += size
                members.append({
                    "path": member.name,
                    "size": size,
                    "sha256": self._hash_file(member, force=force),
                })
            if not members:
                raise SourceError(f"Shapefile dataset does not exist: {path}")
            digest = hashlib.sha256(_canonical_json(members)).hexdigest()
            return digest, total_size, members
        return self._hash_file(path, force=force), int(path.stat().st_size), None

    @staticmethod
    def _source_id(
        *,
        kind: str,
        provider: str,
        name: str,
        version: str | None,
        sha256: str,
        selection: Mapping[str, object] | None,
    ) -> str:
        identity = {
            "kind": kind,
            "provider": provider,
            "name": name,
            "version": version,
            "sha256": sha256,
            "selection": dict(selection or {}),
        }
        digest = hashlib.sha256(_canonical_json(identity)).hexdigest()
        return f"src-{digest}"

    def _manifest_dir(self, ref: SourceRef) -> Path:
        provider = _slug(ref.provider)
        name = _slug(ref.name)
        return self.root / "manifests" / provider / name / ref.source_id

    def _record(self, ref: SourceRef, *, manifest_dir: Path | None = None) -> SourceRef:
        target_dir = manifest_dir or self._manifest_dir(ref)
        manifest_path = target_dir / "source.json"
        payload = ref.to_dict()
        _atomic_json(manifest_path, payload)
        sources = self._index.setdefault("sources", {})
        if not isinstance(sources, dict):
            sources = {}
            self._index["sources"] = sources
        sources[ref.source_id] = str(manifest_path)
        self._save_index()
        return SourceRef.from_dict(payload, manifest_path=manifest_path)

    def register_path(
        self,
        path: Path | str,
        *,
        kind: str,
        provider: str,
        name: str,
        version: str | None = None,
        selection: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
        managed: bool = False,
        manifest_dir: Path | None = None,
        force_hash: bool = False,
    ) -> SourceRef:
        resolved = Path(path).expanduser().resolve()
        sha256, size, members = self._path_identity(resolved, force=force_hash)
        source_id = self._source_id(
            kind=kind,
            provider=provider,
            name=name,
            version=version,
            sha256=sha256,
            selection=selection,
        )
        source_metadata = dict(metadata or {})
        source_metadata.setdefault("registered_path", str(resolved))
        source_metadata.setdefault("registered_at", datetime.now(UTC).isoformat())
        if members is not None:
            source_metadata.setdefault("members", members)
        ref = SourceRef(
            source_id=source_id,
            kind=kind,
            provider=provider,
            name=name,
            version=version,
            sha256=sha256,
            size=size,
            path=resolved,
            selection=dict(selection or {}),
            metadata=source_metadata,
            managed=managed,
            is_directory=resolved.is_dir(),
        )
        return self._record(ref, manifest_dir=manifest_dir)

    def register_user_file(
        self,
        path: Path | str,
        *,
        name: str | None = None,
        layer: str | None = None,
        sheet: str | None = None,
        format: str | None = None,
        crs: str | None = None,
        schema: Mapping[str, object] | None = None,
    ) -> SourceRef:
        resolved = Path(path).expanduser().resolve()
        source_format = format or resolved.suffix.lstrip(".").casefold() or "unknown"
        selection = {
            key: value
            for key, value in {"layer": layer, "sheet": sheet, "format": source_format}.items()
            if value is not None
        }
        metadata: dict[str, object] = {"format": source_format}
        if crs is not None:
            metadata["crs"] = crs
        if schema is not None:
            metadata["schema"] = dict(schema)
        return self.register_path(
            resolved,
            kind="user-file",
            provider="user",
            name=name or resolved.name,
            selection=selection,
            metadata=metadata,
            managed=False,
        )

    def register_packaged_reference(
        self,
        name: str,
        path: Path | str,
        *,
        version: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> SourceRef:
        return self.register_path(
            path,
            kind="packaged-resource",
            provider="sigma",
            name=name,
            version=version,
            metadata=metadata,
            managed=False,
        )

    def register_builtin_references(self) -> dict[str, SourceRef]:
        """Register the packaged source bundles already audited by earlier checkpoints."""
        from importlib.resources import files

        roots = {
            "areas": files("sigma.resources.areas").joinpath("data"),
            "classification": files("sigma.resources.classification"),
            "economy-io80": files("sigma.resources.economy.psa_2018_io80"),
            "economy-io16": files("sigma.resources.economy.psa_2018_io16"),
            "tagging-compatibility": files("sigma.resources.tagging.compatibility"),
        }
        refs: dict[str, SourceRef] = {}
        for name, traversable in roots.items():
            refs[name] = self.register_packaged_reference(
                name,
                Path(str(traversable)),
                metadata={"package": "sigma"},
            )
        return refs

    def get(self, source_id: str) -> SourceRef:
        sources = self._index.get("sources")
        manifest_value = sources.get(source_id) if isinstance(sources, dict) else None
        if not isinstance(manifest_value, str):
            raise SourceError(f"unknown source id: {source_id}")
        manifest_path = Path(manifest_value)
        payload = _read_json(manifest_path)
        if not payload:
            raise SourceError(f"source manifest is missing or invalid: {manifest_path}")
        return SourceRef.from_dict(payload, manifest_path=manifest_path)

    def validate(self, ref_or_id: SourceRef | str, *, force_hash: bool = False) -> SourceValidation:
        ref = self.get(ref_or_id) if isinstance(ref_or_id, str) else ref_or_id
        if not ref.path.exists():
            return SourceValidation(False, "missing", ref.sha256, None)
        try:
            actual, size, _ = self._path_identity(ref.path, force=force_hash)
        except OSError:
            return SourceValidation(False, "unreadable", ref.sha256, None)
        if int(size) != int(ref.size):
            return SourceValidation(False, "size_changed", ref.sha256, actual)
        if actual != ref.sha256:
            return SourceValidation(False, "hash_mismatch", ref.sha256, actual)
        return SourceValidation(True, "valid", ref.sha256, actual)

    # ---- Geofabrik -----------------------------------------------------

    @property
    def _geofabrik_root(self) -> Path:
        return self.root / "geofabrik" / "philippines"

    def _geofabrik_current_path(self) -> Path:
        return self._geofabrik_root / "current.json"

    def current_geofabrik(self) -> SourceRef | None:
        payload = _read_json(self._geofabrik_current_path())
        source_id = str(payload.get("source_id") or "").strip()
        if not source_id:
            return None
        try:
            ref = self.get(source_id)
        except SourceError:
            return None
        return ref if self.validate(ref).valid else None

    def _set_current_geofabrik(self, ref: SourceRef) -> None:
        _atomic_json(
            self._geofabrik_current_path(),
            {"schema_version": SOURCE_STORE_SCHEMA_VERSION, "source_id": ref.source_id},
        )

    def _register_geofabrik(
        self,
        pbf_path: Path,
        *,
        metadata: Mapping[str, object],
        managed: bool,
    ) -> SourceRef:
        version = str(metadata.get("source_version") or "").strip() or None
        sha256 = self._hash_file(pbf_path, force=True)
        label = version or f"content-{sha256[:12]}"
        if managed:
            target_dir = self._geofabrik_root / f"{_slug(label)}-{sha256[:12]}"
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / "philippines.osm.pbf"
            if pbf_path.resolve() != target.resolve():
                if target.exists() and _file_sha256(target) != sha256:
                    raise SourceError(f"immutable Geofabrik target already contains different bytes: {target}")
                if not target.exists():
                    try:
                        os.replace(pbf_path, target)
                    except OSError:
                        shutil.copy2(pbf_path, target)
                pbf_path = target
            self._remember_hash(pbf_path, sha256)
            manifest_dir = target_dir
        else:
            manifest_dir = self._geofabrik_root / f"{_slug(label)}-{sha256[:12]}"

        ref = self.register_path(
            pbf_path,
            kind="provider-snapshot",
            provider="geofabrik",
            name="philippines-osm-pbf",
            version=version,
            metadata={**dict(metadata), "region": "philippines"},
            managed=managed,
            manifest_dir=manifest_dir,
            force_hash=False,
        )
        self._set_current_geofabrik(ref)
        return ref

    def adopt_legacy_geofabrik(self, cache_root: Path | str) -> SourceRef:
        from . import geofabrik

        cache_root = Path(cache_root).expanduser().resolve()
        pbf_path, meta_path = geofabrik.paths(cache_root)
        if not pbf_path.exists():
            raise SourceError(f"legacy Geofabrik PBF is missing: {pbf_path}")
        metadata = _read_json(meta_path)
        recorded_md5 = str(metadata.get("md5") or "").strip().casefold()
        if recorded_md5:
            actual_md5 = _file_md5(pbf_path)
            if actual_md5 != recorded_md5:
                raise SourceError(
                    "legacy Geofabrik PBF does not match its recorded MD5; adoption refused"
                )
            metadata = {**metadata, "md5_verified_on_adoption": True}
        metadata = {
            **metadata,
            "adopted_from": str(cache_root),
            "legacy_metadata_path": str(meta_path),
        }
        # Adoption records the existing bytes in place; validation catches later mutation.
        return self._register_geofabrik(pbf_path, metadata=metadata, managed=False)

    def ensure_geofabrik(
        self,
        *,
        refresh: bool = False,
        progress: Callable[[str], None] | None = None,
        downloader: Callable[..., Path] | None = None,
    ) -> SourceRef:
        current = self.current_geofabrik()
        if current is not None and not refresh:
            if progress is not None:
                progress(
                    f"Geofabrik: reusing initialized Philippines PBF {current.path} "
                    f"({current.size / 2**20:,.0f} MiB)"
                )
            return current

        from . import geofabrik

        acquire_root = self.root / ".acquire" / "geofabrik"
        acquire_root.mkdir(parents=True, exist_ok=True)
        acquire = downloader or geofabrik.ensure
        pbf_path = Path(acquire(acquire_root, refresh=True, progress=progress))
        _, meta_path = geofabrik.paths(acquire_root)
        metadata = _read_json(meta_path)
        if not metadata:
            metadata = {
                "source_version": None,
                "source_url": None,
                "content_length": pbf_path.stat().st_size,
            }
        return self._register_geofabrik(pbf_path, metadata=metadata, managed=True)

    # ---- Overture ------------------------------------------------------

    @staticmethod
    def _overture_client_version() -> str | None:
        try:
            return importlib.metadata.version("overturemaps")
        except importlib.metadata.PackageNotFoundError:
            return None

    @staticmethod
    def _policy_fingerprint() -> str:
        from ..places import overture_policy

        return _file_sha256(Path(overture_policy.__file__).resolve())

    def _overture_query_key(self, bbox: Sequence[float]) -> str:
        from ..places.overture import OVERTURE_NORMALIZATION_VERSION

        payload = {
            "bbox": [float(v) for v in bbox],
            "normalization_version": OVERTURE_NORMALIZATION_VERSION,
            "policy_fingerprint": self._policy_fingerprint(),
            "client_version": self._overture_client_version(),
        }
        return hashlib.sha256(_canonical_json(payload)).hexdigest()

    def _overture_query_pointer(self, bbox: Sequence[float]) -> Path:
        return self.root / "overture" / "places" / "queries" / f"{self._overture_query_key(bbox)}.json"

    def current_overture(self, bbox: Sequence[float]) -> SourceRef | None:
        payload = _read_json(self._overture_query_pointer(bbox))
        source_id = str(payload.get("source_id") or "").strip()
        if not source_id:
            return None
        try:
            ref = self.get(source_id)
        except SourceError:
            return None
        return ref if self.validate(ref).valid else None

    def register_overture_snapshot(
        self,
        cache_file: Path | str,
        *,
        bbox: Sequence[float] | None = None,
        managed: bool = False,
        metadata: Mapping[str, object] | None = None,
    ) -> SourceRef:
        from ..places.overture import OVERTURE_NORMALIZATION_VERSION

        cache_file = Path(cache_file).expanduser().resolve()
        bbox_marker = _read_json(cache_file.with_suffix(cache_file.suffix + ".meta.json"))
        policy_marker = _read_json(cache_file.with_suffix(cache_file.suffix + ".overture.json"))
        marker_bbox = bbox_marker.get("bbox") or policy_marker.get("bbox")
        effective_bbox = [float(v) for v in (bbox if bbox is not None else marker_bbox or [])]
        if len(effective_bbox) != 4:
            raise SourceError("Overture snapshot requires a four-value bbox identity")
        from .cache import cache_matches_bbox

        if not cache_matches_bbox(cache_file, tuple(effective_bbox)):
            raise SourceError("Overture generic bbox cache marker is missing or incompatible")
        if policy_marker.get("normalization_version") != OVERTURE_NORMALIZATION_VERSION:
            raise SourceError("Overture cache policy marker is missing or incompatible")
        if [float(v) for v in policy_marker.get("bbox", [])] != effective_bbox:
            raise SourceError("Overture policy marker bbox does not match the snapshot bbox")
        if bbox_marker and [float(v) for v in bbox_marker.get("bbox", [])] != effective_bbox:
            raise SourceError("Overture generic cache marker bbox does not match the snapshot bbox")

        sha256 = self._hash_file(cache_file, force=True)
        source_metadata: dict[str, object] = {
            "bbox": effective_bbox,
            "normalization_version": OVERTURE_NORMALIZATION_VERSION,
            "policy_fingerprint": self._policy_fingerprint(),
            "overturemaps_version": self._overture_client_version(),
            "raw_rows": policy_marker.get("raw_rows"),
            "accepted_rows": policy_marker.get("accepted_rows"),
            **dict(metadata or {}),
        }
        query_key = self._overture_query_key(effective_bbox)
        if managed:
            original_cache = cache_file
            sidecars = {
                suffix: _read_json(original_cache.with_suffix(original_cache.suffix + suffix))
                for suffix in (".meta.json", ".overture.json")
            }
            target_dir = self.root / "overture" / "places" / f"{query_key[:16]}-{sha256[:12]}"
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / "places.parquet"
            if cache_file.resolve() != target.resolve():
                if target.exists() and _file_sha256(target) != sha256:
                    raise SourceError(f"immutable Overture target already contains different bytes: {target}")
                if not target.exists():
                    try:
                        os.replace(cache_file, target)
                    except OSError:
                        shutil.copy2(cache_file, target)
                cache_file = target
            self._remember_hash(cache_file, sha256)
            for suffix, payload in sidecars.items():
                if payload:
                    _atomic_json(cache_file.with_suffix(cache_file.suffix + suffix), payload)
            manifest_dir = target_dir
        else:
            target_dir = self.root / "overture" / "places" / f"{query_key[:16]}-{sha256[:12]}"
            manifest_dir = target_dir

        ref = self.register_path(
            cache_file,
            kind="query-snapshot",
            provider="overture",
            name="places",
            version=None,
            selection={"bbox": effective_bbox},
            metadata=source_metadata,
            managed=managed,
            manifest_dir=manifest_dir,
            force_hash=False,
        )
        _atomic_json(
            self._overture_query_pointer(effective_bbox),
            {"schema_version": SOURCE_STORE_SCHEMA_VERSION, "source_id": ref.source_id},
        )
        return ref

    def fetch_overture_snapshot(
        self,
        bbox: Sequence[float],
        *,
        refresh: bool = False,
        progress: Callable[[str], None] | None = None,
        fetcher: Callable[..., object] | None = None,
    ) -> SourceRef:
        current = self.current_overture(bbox)
        if current is not None and not refresh:
            if progress is not None:
                progress(f"Overture Places: reusing cached area snapshot {current.path}")
            return current

        from ..places import overture

        query_key = self._overture_query_key(bbox)
        download_dir = self.root / ".acquire" / "overture"
        download_dir.mkdir(parents=True, exist_ok=True)
        cache_file = download_dir / f"{query_key}.parquet"
        fetch = fetcher or overture.fetch_overture
        frame = fetch(tuple(float(v) for v in bbox), cache_file, refresh=True, progress=progress)
        observed: dict[str, object] = {}
        columns = getattr(frame, "columns", ())
        if "overture_providers" in columns:
            providers: set[str] = set()
            for value in frame["overture_providers"].fillna(""):
                providers.update(part.strip() for part in str(value).split("|") if part.strip())
            observed["observed_providers"] = sorted(providers)
        if "upstream_license" in columns:
            licenses: set[str] = set()
            for value in frame["upstream_license"].fillna(""):
                licenses.update(part.strip() for part in str(value).split("|") if part.strip())
            observed["observed_licenses"] = sorted(licenses)
        return self.register_overture_snapshot(
            cache_file, bbox=bbox, managed=True, metadata=observed
        )

    # ---- National OSM preparation compatibility wrapper --------------

    @property
    def prepared_osm_cache_root(self) -> Path:
        """Shared compatibility cache used by the preserved resumable preparer.

        C8 promotes these checkpoints into explicit managed stage artifacts. Until then,
        keeping this cache under the shared source root ensures many workspaces reuse the
        same national preparation for one canonical PBF snapshot.
        """
        return self.root / "compat-prepared-osm"

    def load_prepared_osm_area(
        self,
        geofabrik_ref: SourceRef,
        *,
        area_slug: str,
        areas_file: Path | None = None,
        progress: Callable[[str], None] | None = None,
        loader: Callable[..., object] | None = None,
    ):
        if geofabrik_ref.provider != "geofabrik":
            raise SourceError("national OSM preparation requires a Geofabrik source ref")
        validation = self.validate(geofabrik_ref)
        if not validation.valid:
            raise SourceError(f"Geofabrik source is not valid: {validation.reason}")

        from . import osm_prepare

        cache_base = self.prepared_osm_cache_root
        adoption = _read_json(self.root / "legacy-cache-adoption.json")
        prepared = adoption.get("prepared_osm") if isinstance(adoption, dict) else None
        if (
            adoption.get("geofabrik_source_id") == geofabrik_ref.source_id
            and isinstance(prepared, dict)
            and bool(prepared.get("structurally_complete"))
        ):
            legacy_root = str(adoption.get("legacy_cache_root") or "").strip()
            if legacy_root:
                cache_base = Path(legacy_root)

        metadata_path = cache_base / "geofabrik" / "philippines-latest.meta.json"
        version = geofabrik_ref.version or f"sha256-{geofabrik_ref.sha256[:16]}"
        _atomic_json(
            metadata_path,
            {
                "source_version": version,
                "source_id": geofabrik_ref.source_id,
                "sha256": geofabrik_ref.sha256,
                "source_url": geofabrik_ref.metadata.get("source_url"),
            },
        )
        prepare = loader or osm_prepare.load_prepared_area_osm
        return prepare(
            cache_base=cache_base,
            pbf_file=geofabrik_ref.path,
            area_slug=area_slug,
            areas_file=areas_file,
            progress=progress,
        )

    # ---- Legacy cache adoption ---------------------------------------

    def _legacy_prepared_osm_info(self, cache_root: Path) -> dict[str, object] | None:
        prepared_root = cache_root / "geofabrik" / "prepared"
        current = _read_json(prepared_root / "current.json")
        version = str(current.get("source_version") or "").strip()
        if not version:
            return None
        directory = prepared_root / version
        manifest = _read_json(directory / "manifest.json")
        if not directory.is_dir() or not manifest:
            return None
        return {
            "source_version": version,
            "directory": str(directory),
            "manifest": manifest,
            "state": _read_json(directory / "state.json"),
            "structurally_complete": (
                manifest.get("status") == "complete"
                and str(manifest.get("source_version") or "") == version
                and (directory / "national-pois.parquet").exists()
                and (directory / "areas").is_dir()
            ),
        }

    def adopt_legacy_cache(self, cache_root: Path | str) -> LegacyCacheAdoption:
        cache_root = Path(cache_root).expanduser().resolve()
        geofabrik_ref: SourceRef | None = None
        try:
            geofabrik_ref = self.adopt_legacy_geofabrik(cache_root)
        except SourceError:
            geofabrik_ref = None

        overture_refs: list[SourceRef] = []
        for cache_file in sorted(cache_root.glob("*/overture.parquet")):
            try:
                overture_refs.append(self.register_overture_snapshot(cache_file, managed=False))
            except SourceError:
                continue

        prepared = self._legacy_prepared_osm_info(cache_root)
        _atomic_json(
            self.root / "legacy-cache-adoption.json",
            {
                "schema_version": SOURCE_STORE_SCHEMA_VERSION,
                "legacy_cache_root": str(cache_root),
                "geofabrik_source_id": geofabrik_ref.source_id if geofabrik_ref else None,
                "overture_source_ids": [ref.source_id for ref in overture_refs],
                "prepared_osm": prepared,
            },
        )
        return LegacyCacheAdoption(geofabrik_ref, tuple(overture_refs), prepared)
