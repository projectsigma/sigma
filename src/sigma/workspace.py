from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping

from .area import Area, BoundarySpec
from .artifacts import ArtifactManifest, ArtifactRecipe, ArtifactRef, ArtifactStore, ArtifactValidation
from .errors import ConfigurationError
from .sources import SourceStore

WORKSPACE_SCHEMA_VERSION = 1


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _area_payload(area: Area | None) -> dict[str, object] | None:
    if area is None:
        return None
    boundary = None
    if area.boundary is not None:
        boundary = {
            "gpkg": str(area.boundary.gpkg),
            "layer": area.boundary.layer,
            "field": area.boundary.field,
            "value": list(area.boundary.value) if isinstance(area.boundary.value, tuple) else area.boundary.value,
        }
    return {
        "slug": area.slug,
        "name": area.name,
        "kind": area.kind,
        "bbox": list(area.bbox),
        "psgc_code": area.psgc_code,
        "province": area.province,
        "aliases": list(area.aliases),
        "members": list(area.members),
        "boundary": boundary,
    }


def _area_from_payload(payload: Mapping[str, object] | None) -> Area | None:
    if not payload:
        return None
    boundary_payload = payload.get("boundary")
    boundary = None
    if isinstance(boundary_payload, Mapping):
        value = boundary_payload.get("value")
        if isinstance(value, list):
            value = tuple(str(item) for item in value)
        boundary = BoundarySpec(
            gpkg=Path(str(boundary_payload["gpkg"])),
            layer=str(boundary_payload["layer"]) if boundary_payload.get("layer") is not None else None,
            field=str(boundary_payload["field"]) if boundary_payload.get("field") is not None else None,
            value=value,
        )
    return Area(
        slug=str(payload["slug"]),
        name=str(payload["name"]),
        kind=str(payload["kind"]),
        bbox=tuple(float(item) for item in payload["bbox"]),
        psgc_code=str(payload["psgc_code"]) if payload.get("psgc_code") is not None else None,
        province=str(payload["province"]) if payload.get("province") is not None else None,
        aliases=tuple(str(item) for item in payload.get("aliases", [])),
        members=tuple(str(item) for item in payload.get("members", [])),
        boundary=boundary,
    )


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _area_identity_payload_from_payload(
    payload: Mapping[str, object] | None,
) -> dict[str, object] | None:
    if not payload:
        return None
    normalized = dict(payload)
    boundary = normalized.get("boundary")
    if isinstance(boundary, Mapping):
        boundary = dict(boundary)
        boundary.pop("gpkg", None)
        normalized["boundary"] = boundary
    return normalized


def _area_identity(area: Area | None) -> str | None:
    payload = _area_identity_payload_from_payload(_area_payload(area))
    return _fingerprint(payload) if payload is not None else None


class SigmaWorkspace:
    """Durable per-area/custom-run state without algorithm execution responsibilities."""

    def __init__(self, root: Path | str, payload: Mapping[str, object]):
        self.root = Path(root).expanduser().resolve()
        self._payload = dict(payload)
        self._workspace_path = self.root / "workspace.json"
        self._artifacts = ArtifactStore(self.root / "artifacts")
        source_root = Path(str(self._payload["source_store_root"]))
        self._sources = SourceStore(source_root)

    @classmethod
    def create(
        cls,
        root: Path | str,
        *,
        area: Area | None = None,
        area_identity: str | None = None,
        source_store: Path | str | None = None,
        output_dir: Path | str | None = None,
        economy_fingerprint: str | None = None,
        taxonomy_fingerprint: str | None = None,
        tagging_fingerprint: str | None = None,
        config_fingerprint: str | None = None,
    ) -> "SigmaWorkspace":
        root = Path(root).expanduser().resolve()
        workspace_path = root / "workspace.json"
        if workspace_path.exists():
            raise ConfigurationError(f"workspace already exists: {workspace_path}")
        root.mkdir(parents=True, exist_ok=True)
        source_root = Path(source_store).expanduser().resolve() if source_store is not None else SourceStore.default_root()
        output_root = Path(output_dir).expanduser().resolve() if output_dir is not None else root / "output"
        area_payload = _area_payload(area)
        effective_area_identity = area_identity or _area_identity(area)
        created_at = datetime.now(UTC).isoformat()
        payload: dict[str, object] = {
            "workspace_schema_version": WORKSPACE_SCHEMA_VERSION,
            "workspace_id": f"ws-{uuid.uuid4().hex}",
            "created_at": created_at,
            "last_opened_at": created_at,
            "area": area_payload,
            "area_identity": effective_area_identity,
            "economy_fingerprint": economy_fingerprint,
            "taxonomy_fingerprint": taxonomy_fingerprint,
            "tagging_fingerprint": tagging_fingerprint,
            "config_fingerprint": config_fingerprint,
            "source_store_root": str(source_root),
            "artifact_store_root": str(root / "artifacts"),
            "output_dir": str(output_root),
        }
        _atomic_json(workspace_path, payload)
        (root / "runs").mkdir(exist_ok=True)
        return cls(root, payload)

    @classmethod
    def open(
        cls,
        root: Path | str,
        *,
        area: Area | None = None,
        area_identity: str | None = None,
    ) -> "SigmaWorkspace":
        root = Path(root).expanduser().resolve()
        workspace_path = root / "workspace.json"
        try:
            payload = json.loads(workspace_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ConfigurationError(f"workspace does not exist: {workspace_path}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationError(f"workspace metadata is unreadable: {workspace_path}") from exc
        if not isinstance(payload, dict) or payload.get("workspace_schema_version") != WORKSPACE_SCHEMA_VERSION:
            raise ConfigurationError("workspace schema is unsupported or invalid")
        required = {"workspace_id", "source_store_root", "artifact_store_root", "output_dir"}
        missing = sorted(required - set(payload))
        if missing:
            raise ConfigurationError(f"workspace metadata is missing required fields: {', '.join(missing)}")
        requested_area = _area_payload(area)
        requested_identity = area_identity or _area_identity(area)
        stored_identity = payload.get("area_identity")
        if requested_identity is not None and stored_identity not in (None, requested_identity):
            migrated = False
            stored_area = payload.get("area")
            if area_identity is None and isinstance(stored_area, Mapping):
                legacy_identity = _fingerprint(stored_area)
                stored_semantic = _fingerprint(
                    _area_identity_payload_from_payload(stored_area)
                )
                if stored_identity == legacy_identity and requested_identity == stored_semantic:
                    payload["area_identity"] = requested_identity
                    if requested_area is not None:
                        payload["area"] = requested_area
                    migrated = True
            if not migrated:
                raise ConfigurationError(
                    "workspace area identity does not match the requested area/custom boundary identity"
                )
        elif requested_area is not None and isinstance(payload.get("area"), Mapping):
            stored_semantic = _area_identity_payload_from_payload(payload.get("area"))
            requested_semantic = _area_identity_payload_from_payload(requested_area)
            if stored_semantic == requested_semantic:
                payload["area"] = requested_area
        payload["last_opened_at"] = datetime.now(UTC).isoformat()
        _atomic_json(workspace_path, payload)
        return cls(root, payload)

    @property
    def identity(self) -> str:
        return str(self._payload["workspace_id"])

    @property
    def area_identity(self) -> str | None:
        value = self._payload.get("area_identity")
        return str(value) if value not in (None, "") else None

    @property
    def area(self) -> Area | None:
        payload = self._payload.get("area")
        return _area_from_payload(payload if isinstance(payload, Mapping) else None)

    @property
    def artifacts(self) -> ArtifactStore:
        return self._artifacts

    @property
    def sources(self) -> SourceStore:
        return self._sources

    @property
    def output_dir(self) -> Path:
        return Path(str(self._payload["output_dir"]))

    def artifact(self, stage: str) -> ArtifactRef | None:
        return self._artifacts.active(stage)

    def manifest(self, stage: str) -> ArtifactManifest | None:
        ref = self.artifact(stage)
        return self._artifacts.manifest(ref) if ref is not None else None

    def status(
        self,
        expected_recipes: Mapping[str, ArtifactRecipe] | None = None,
    ) -> dict[str, ArtifactValidation]:
        return self._artifacts.status(expected_recipes)
