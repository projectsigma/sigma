from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ._version import __version__
from .errors import ArtifactValidationError
from .sources import SourceRef

ARTIFACT_MANIFEST_SCHEMA_VERSION = 1
_STAGE_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_HASH_CHUNK_SIZE = 8 * 1024 * 1024


def _canonicalize(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key): _canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, set):
        normalized = [_canonicalize(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True, default=str))
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"value is not JSON-canonicalizable: {type(value).__name__}")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        _canonicalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(_canonicalize(payload), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _validate_stage(stage: str) -> str:
    stage = str(stage).strip()
    if not stage or not _STAGE_RE.fullmatch(stage):
        raise ValueError("artifact stage must contain only letters, digits, '.', '_' or '-'")
    return stage


def _deep_freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _freeze_mapping(value: Mapping[str, object] | None) -> Mapping[str, object]:
    canonical = _canonicalize(value or {})
    assert isinstance(canonical, dict)
    frozen = _deep_freeze(canonical)
    assert isinstance(frozen, Mapping)
    return frozen


def _normalize_dependencies(
    dependencies: Mapping[str, ArtifactRef | Mapping[str, object] | str] | None,
) -> Mapping[str, object]:
    normalized: dict[str, object] = {}
    for name, value in (dependencies or {}).items():
        if isinstance(value, ArtifactRef):
            normalized[str(name)] = {
                "artifact_id": value.artifact_id,
                "stage": value.stage,
                "recipe_fingerprint": value.recipe_fingerprint,
            }
        elif isinstance(value, Mapping):
            normalized[str(name)] = dict(value)
        else:
            normalized[str(name)] = {"artifact_id": str(value)}
    return _freeze_mapping(normalized)


def _normalize_sources(
    sources: Mapping[str, SourceRef | Mapping[str, object] | str] | None,
) -> Mapping[str, object]:
    normalized: dict[str, object] = {}
    for name, value in (sources or {}).items():
        if isinstance(value, SourceRef):
            normalized[str(name)] = {
                "source_id": value.source_id,
                "sha256": value.sha256,
            }
        elif isinstance(value, Mapping):
            normalized[str(name)] = dict(value)
        else:
            normalized[str(name)] = {"source_id": str(value)}
    return _freeze_mapping(normalized)


@dataclass(frozen=True, slots=True)
class ArtifactRecipe:
    """Deterministic identity of the inputs and implementation for one stage result."""

    stage: str
    implementation_version: str
    artifact_schema_version: str = "1"
    producer_version: str = __version__
    parameters: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))
    dependencies: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))
    sources: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))
    resources: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))
    identities: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage", _validate_stage(self.stage))
        if not str(self.implementation_version).strip():
            raise ValueError("implementation_version must be nonblank")
        if not str(self.artifact_schema_version).strip():
            raise ValueError("artifact_schema_version must be nonblank")
        object.__setattr__(self, "parameters", _freeze_mapping(self.parameters))
        object.__setattr__(self, "dependencies", _freeze_mapping(self.dependencies))
        object.__setattr__(self, "sources", _freeze_mapping(self.sources))
        object.__setattr__(self, "resources", _freeze_mapping(self.resources))
        object.__setattr__(self, "identities", _freeze_mapping(self.identities))

    @classmethod
    def build(
        cls,
        stage: str,
        *,
        implementation_version: str,
        artifact_schema_version: str = "1",
        producer_version: str = __version__,
        parameters: Mapping[str, object] | None = None,
        dependencies: Mapping[str, ArtifactRef | Mapping[str, object] | str] | None = None,
        sources: Mapping[str, SourceRef | Mapping[str, object] | str] | None = None,
        resources: Mapping[str, object] | None = None,
        identities: Mapping[str, object] | None = None,
    ) -> "ArtifactRecipe":
        return cls(
            stage=stage,
            implementation_version=implementation_version,
            artifact_schema_version=artifact_schema_version,
            producer_version=producer_version,
            parameters=_freeze_mapping(parameters),
            dependencies=_normalize_dependencies(dependencies),
            sources=_normalize_sources(sources),
            resources=_freeze_mapping(resources),
            identities=_freeze_mapping(identities),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "artifact_schema_version": self.artifact_schema_version,
            "implementation_version": self.implementation_version,
            "producer_version": self.producer_version,
            "parameters": _canonicalize(self.parameters),
            "dependencies": _canonicalize(self.dependencies),
            "sources": _canonicalize(self.sources),
            "resources": _canonicalize(self.resources),
            "identities": _canonicalize(self.identities),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ArtifactRecipe":
        return cls(
            stage=str(payload["stage"]),
            artifact_schema_version=str(payload.get("artifact_schema_version") or "1"),
            implementation_version=str(payload["implementation_version"]),
            producer_version=str(payload.get("producer_version") or __version__),
            parameters=dict(payload.get("parameters") or {}),
            dependencies=dict(payload.get("dependencies") or {}),
            sources=dict(payload.get("sources") or {}),
            resources=dict(payload.get("resources") or {}),
            identities=dict(payload.get("identities") or {}),
        )

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.to_dict())


@dataclass(frozen=True, slots=True)
class ArtifactFile:
    path: str
    size: int
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "size": int(self.size), "sha256": self.sha256}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ArtifactFile":
        return cls(path=str(payload["path"]), size=int(payload["size"]), sha256=str(payload["sha256"]))


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    artifact_id: str
    recipe: ArtifactRecipe
    created_at: str
    files: tuple[ArtifactFile, ...]
    metadata: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))
    provenance: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))
        object.__setattr__(self, "provenance", _freeze_mapping(self.provenance))

    @property
    def stage(self) -> str:
        return self.recipe.stage

    @property
    def recipe_fingerprint(self) -> str:
        return self.recipe.fingerprint

    def to_dict(self) -> dict[str, object]:
        return {
            "manifest_schema_version": ARTIFACT_MANIFEST_SCHEMA_VERSION,
            "artifact_id": self.artifact_id,
            "stage": self.stage,
            "recipe_fingerprint": self.recipe_fingerprint,
            "created_at": self.created_at,
            "recipe": self.recipe.to_dict(),
            "files": [item.to_dict() for item in self.files],
            "metadata": _canonicalize(self.metadata),
            "provenance": _canonicalize(self.provenance),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ArtifactManifest":
        if int(payload.get("manifest_schema_version", -1)) != ARTIFACT_MANIFEST_SCHEMA_VERSION:
            raise ArtifactValidationError("unsupported artifact manifest schema")
        recipe = ArtifactRecipe.from_dict(dict(payload["recipe"]))
        if str(payload.get("stage")) != recipe.stage:
            raise ArtifactValidationError("artifact manifest stage does not match recipe")
        if str(payload.get("recipe_fingerprint")) != recipe.fingerprint:
            raise ArtifactValidationError("artifact manifest recipe fingerprint is inconsistent")
        files = tuple(ArtifactFile.from_dict(item) for item in payload.get("files", []))
        manifest = cls(
            artifact_id=str(payload["artifact_id"]),
            recipe=recipe,
            created_at=str(payload["created_at"]),
            files=files,
            metadata=dict(payload.get("metadata") or {}),
            provenance=dict(payload.get("provenance") or {}),
        )
        if manifest.artifact_id != _artifact_id(recipe, files, manifest.metadata):
            raise ArtifactValidationError("artifact manifest identity is inconsistent")
        return manifest


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    artifact_id: str
    stage: str
    recipe_fingerprint: str
    path: Path
    manifest_path: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))
        object.__setattr__(self, "manifest_path", Path(self.manifest_path))


@dataclass(frozen=True, slots=True)
class ArtifactValidation:
    valid: bool
    status: str
    reason: str
    artifact_id: str | None = None
    expected_recipe_fingerprint: str | None = None
    actual_recipe_fingerprint: str | None = None
    details: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", _freeze_mapping(self.details))


@dataclass(frozen=True, slots=True)
class ArtifactWrite:
    stage: str
    recipe: ArtifactRecipe
    path: Path

    def output(self, relative_path: str | Path) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("artifact output path must be relative and stay inside the write directory")
        target = self.path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        return target


def _artifact_id(
    recipe: ArtifactRecipe,
    files: Sequence[ArtifactFile],
    metadata: Mapping[str, object] | None,
) -> str:
    digest = _fingerprint(
        {
            "stage": recipe.stage,
            "recipe_fingerprint": recipe.fingerprint,
            "files": [item.to_dict() for item in files],
            "metadata": dict(metadata or {}),
        }
    )
    return f"art-{digest}"


def _recipe_difference(actual: ArtifactRecipe, expected: ArtifactRecipe) -> tuple[str, dict[str, object]]:
    if actual.stage != expected.stage:
        return "stage_changed", {"actual": actual.stage, "expected": expected.stage}
    if actual.artifact_schema_version != expected.artifact_schema_version:
        return "schema_changed", {
            "actual": actual.artifact_schema_version,
            "expected": expected.artifact_schema_version,
        }
    if (
        actual.implementation_version != expected.implementation_version
        or actual.producer_version != expected.producer_version
    ):
        return "implementation_version_changed", {
            "actual_implementation": actual.implementation_version,
            "expected_implementation": expected.implementation_version,
            "actual_producer": actual.producer_version,
            "expected_producer": expected.producer_version,
        }
    if dict(actual.parameters) != dict(expected.parameters):
        return "parameter_changed", {}
    if dict(actual.dependencies) != dict(expected.dependencies):
        return "dependency_changed", {}
    if dict(actual.sources) != dict(expected.sources):
        return "source_changed", {}
    if dict(actual.resources) != dict(expected.resources):
        return "resource_changed", {}
    if dict(actual.identities) != dict(expected.identities):
        return "identity_changed", {}
    return "recipe_changed", {}


class ArtifactStore:
    """Manifest-backed immutable derived-artifact store for one workspace."""

    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._tmp_root = self.root / ".tmp"
        self._state_root = self.root / ".state"
        self._corrupt_root = self.root / ".corrupt"
        self._tmp_root.mkdir(parents=True, exist_ok=True)
        self._state_root.mkdir(parents=True, exist_ok=True)
        self._corrupt_root.mkdir(parents=True, exist_ok=True)
        self._active_path = self._state_root / "active.json"

    def _stage_dir(self, stage: str) -> Path:
        return self.root / _validate_stage(stage)

    def _artifact_dir(self, stage: str, recipe_fingerprint: str) -> Path:
        return self._stage_dir(stage) / recipe_fingerprint

    def begin_write(self, recipe: ArtifactRecipe) -> ArtifactWrite:
        prefix = f"{recipe.stage.replace('.', '-')}-{recipe.fingerprint[:12]}-"
        path = Path(tempfile.mkdtemp(prefix=prefix, dir=self._tmp_root))
        return ArtifactWrite(stage=recipe.stage, recipe=recipe, path=path)

    def abort(self, write: ArtifactWrite) -> None:
        if write.path.parent == self._tmp_root and write.path.exists():
            shutil.rmtree(write.path)

    def _collect_files(self, directory: Path) -> tuple[ArtifactFile, ...]:
        files: list[ArtifactFile] = []
        for path in sorted(directory.rglob("*"), key=lambda value: value.as_posix()):
            if not path.is_file() or path.name == "artifact.json":
                continue
            if path.is_symlink():
                raise ArtifactValidationError("artifact outputs may not contain symbolic links")
            relative = path.relative_to(directory).as_posix()
            files.append(ArtifactFile(relative, path.stat().st_size, _file_sha256(path)))
        if not files:
            raise ArtifactValidationError("cannot commit an artifact with no output files")
        return tuple(files)

    def commit(
        self,
        write: ArtifactWrite,
        *,
        metadata: Mapping[str, object] | None = None,
        provenance: Mapping[str, object] | None = None,
        make_active: bool = False,
        logical_key: str | None = None,
    ) -> ArtifactRef:
        if write.recipe.stage != write.stage:
            raise ArtifactValidationError("artifact write stage and recipe stage differ")
        if not write.path.is_dir() or write.path.parent != self._tmp_root:
            raise ArtifactValidationError("artifact write is not an active store temporary directory")
        files = self._collect_files(write.path)
        metadata = dict(metadata or {})
        provenance_payload = {
            "sigma_version": __version__,
            **dict(provenance or {}),
        }
        artifact_id = _artifact_id(write.recipe, files, metadata)
        manifest = ArtifactManifest(
            artifact_id=artifact_id,
            recipe=write.recipe,
            created_at=datetime.now(UTC).isoformat(),
            files=files,
            metadata=metadata,
            provenance=provenance_payload,
        )
        _atomic_json(write.path / "artifact.json", manifest.to_dict())

        target = self._artifact_dir(write.stage, write.recipe.fingerprint)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            existing: ArtifactRef | None = None
            validation: ArtifactValidation | None = None
            try:
                existing = self._ref_from_directory(target)
                validation = self.validate(existing, expected_recipe=write.recipe)
            except ArtifactValidationError:
                validation = ArtifactValidation(False, "corrupt", "manifest_invalid")

            if validation.valid and existing is not None and existing.artifact_id == artifact_id:
                shutil.rmtree(write.path)
                if make_active:
                    self._mark_active_validated(logical_key or write.stage, existing)
                return existing
            if validation.valid:
                existing_manifest = self.manifest(existing) if existing is not None else None
                if existing_manifest is None or existing_manifest.metadata.get("cache_reusable") is not False:
                    shutil.rmtree(write.path)
                    raise ArtifactValidationError(
                        "an immutable artifact already exists for this recipe with different output"
                    )

            quarantine = self._corrupt_root / write.stage / (
                f"{write.recipe.fingerprint}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}"
            )
            quarantine.parent.mkdir(parents=True, exist_ok=True)
            os.replace(target, quarantine)

        os.replace(write.path, target)
        ref = self._ref_from_directory(target)
        if ref.artifact_id != artifact_id:
            raise ArtifactValidationError("committed artifact identity changed during promotion")
        if make_active:
            # ``_collect_files`` hashed every file of this artifact before the move above.
            self._mark_active_validated(logical_key or write.stage, ref)
        return ref

    def _read_manifest_path(self, manifest_path: Path) -> ArtifactManifest:
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ArtifactValidationError(f"artifact manifest is missing: {manifest_path}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactValidationError(f"artifact manifest is unreadable: {manifest_path}") from exc
        if not isinstance(payload, dict):
            raise ArtifactValidationError("artifact manifest must be a JSON object")
        try:
            return ArtifactManifest.from_dict(payload)
        except ArtifactValidationError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ArtifactValidationError(
                f"artifact manifest is invalid: {manifest_path}"
            ) from exc

    def _ref_from_directory(self, directory: Path) -> ArtifactRef:
        manifest_path = directory / "artifact.json"
        manifest = self._read_manifest_path(manifest_path)
        return ArtifactRef(
            artifact_id=manifest.artifact_id,
            stage=manifest.stage,
            recipe_fingerprint=manifest.recipe_fingerprint,
            path=directory,
            manifest_path=manifest_path,
        )

    def manifest(self, ref: ArtifactRef) -> ArtifactManifest:
        return self._read_manifest_path(ref.manifest_path)

    def lookup(self, stage: str, recipe_fingerprint: str) -> ArtifactRef | None:
        directory = self._artifact_dir(stage, recipe_fingerprint)
        if not directory.is_dir() or not (directory / "artifact.json").is_file():
            return None
        try:
            ref = self._ref_from_directory(directory)
        except ArtifactValidationError:
            return None
        if ref.stage != stage or ref.recipe_fingerprint != recipe_fingerprint:
            return None
        return ref

    def validate(
        self,
        ref: ArtifactRef,
        *,
        expected_recipe: ArtifactRecipe | None = None,
        verify_content: bool = True,
    ) -> ArtifactValidation:
        if not ref.path.is_dir():
            return ArtifactValidation(False, "missing", "artifact_directory_missing", ref.artifact_id)
        try:
            manifest = self.manifest(ref)
        except ArtifactValidationError as exc:
            return ArtifactValidation(False, "corrupt", "manifest_invalid", ref.artifact_id, details={"error": str(exc)})
        if manifest.artifact_id != ref.artifact_id:
            return ArtifactValidation(False, "corrupt", "artifact_id_mismatch", ref.artifact_id)
        if manifest.stage != ref.stage or manifest.recipe_fingerprint != ref.recipe_fingerprint:
            return ArtifactValidation(False, "corrupt", "reference_manifest_mismatch", ref.artifact_id)

        if verify_content:
            declared = {item.path: item for item in manifest.files}
            actual_paths = {
                path.relative_to(ref.path).as_posix()
                for path in ref.path.rglob("*")
                if path.is_file() and path.name != "artifact.json"
            }
            if actual_paths != set(declared):
                return ArtifactValidation(
                    False,
                    "corrupt",
                    "artifact_file_set_changed",
                    ref.artifact_id,
                    details={"declared": sorted(declared), "actual": sorted(actual_paths)},
                )
            for relative, item in declared.items():
                path = ref.path / relative
                if path.stat().st_size != item.size:
                    return ArtifactValidation(False, "corrupt", "artifact_size_changed", ref.artifact_id, details={"path": relative})
                actual_hash = _file_sha256(path)
                if actual_hash != item.sha256:
                    return ArtifactValidation(
                        False,
                        "corrupt",
                        "artifact_hash_mismatch",
                        ref.artifact_id,
                        details={"path": relative, "expected": item.sha256, "actual": actual_hash},
                    )

        if expected_recipe is not None and manifest.recipe_fingerprint != expected_recipe.fingerprint:
            reason, details = _recipe_difference(manifest.recipe, expected_recipe)
            return ArtifactValidation(
                False,
                "stale",
                reason,
                ref.artifact_id,
                expected_recipe.fingerprint,
                manifest.recipe_fingerprint,
                details,
            )
        return ArtifactValidation(
            True,
            "complete",
            "valid",
            ref.artifact_id,
            expected_recipe.fingerprint if expected_recipe is not None else None,
            manifest.recipe_fingerprint,
        )

    def _load_active_payload(self) -> dict[str, object]:
        if not self._active_path.exists():
            return {"schema_version": 1, "artifacts": {}}
        try:
            payload = json.loads(self._active_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactValidationError(
                f"active artifact index is unreadable: {self._active_path}"
            ) from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ArtifactValidationError("active artifact index has an unsupported schema")
        if not isinstance(payload.get("artifacts"), dict):
            raise ArtifactValidationError("active artifact index has an invalid artifacts table")
        return payload

    def _write_active(self, logical_key: str, ref: ArtifactRef) -> None:
        logical_key = str(logical_key).strip()
        if not logical_key:
            raise ValueError("logical artifact key must be nonblank")
        payload = self._load_active_payload()
        artifacts = payload["artifacts"]
        assert isinstance(artifacts, dict)
        artifacts[logical_key] = {
            "artifact_id": ref.artifact_id,
            "stage": ref.stage,
            "recipe_fingerprint": ref.recipe_fingerprint,
            "manifest": ref.manifest_path.relative_to(self.root).as_posix(),
        }
        _atomic_json(self._active_path, payload)

    def _mark_active_validated(self, logical_key: str, ref: ArtifactRef) -> None:
        """Activate a reference whose content was validated by the immediate caller."""
        self._write_active(logical_key, ref)

    def mark_active(self, logical_key: str, ref: ArtifactRef) -> None:
        """Record ``ref`` as active after validating its immutable content."""
        validation = self.validate(ref)
        if not validation.valid:
            raise ArtifactValidationError(f"cannot activate invalid artifact: {validation.reason}")
        self._write_active(logical_key, ref)

    def _active_entry(self, logical_key: str) -> Mapping[str, object] | None:
        payload = self._load_active_payload()
        artifacts = payload.get("artifacts")
        entry = artifacts.get(logical_key) if isinstance(artifacts, dict) else None
        return entry if isinstance(entry, dict) else None

    def active(self, logical_key: str) -> ArtifactRef | None:
        entry = self._active_entry(logical_key)
        if entry is None:
            return None
        relative = str(entry.get("manifest") or "").strip()
        if not relative:
            return None
        manifest_path = self.root / relative
        try:
            ref = self._ref_from_directory(manifest_path.parent)
        except ArtifactValidationError:
            return None
        if (
            ref.artifact_id != entry.get("artifact_id")
            or ref.stage != entry.get("stage")
            or ref.recipe_fingerprint != entry.get("recipe_fingerprint")
        ):
            return None
        return ref

    def active_keys(self) -> tuple[str, ...]:
        payload = self._load_active_payload()
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, dict):
            return ()
        return tuple(sorted(str(key) for key in artifacts))

    def status(
        self,
        expected_recipes: Mapping[str, ArtifactRecipe] | None = None,
    ) -> dict[str, ArtifactValidation]:
        expected_recipes = dict(expected_recipes or {})
        keys = set(self.active_keys()) | set(expected_recipes)
        result: dict[str, ArtifactValidation] = {}
        for key in sorted(keys):
            entry = self._active_entry(key)
            ref = self.active(key)
            expected = expected_recipes.get(key)
            if ref is None:
                if entry is not None:
                    result[key] = ArtifactValidation(
                        False,
                        "corrupt",
                        "active_reference_invalid",
                        artifact_id=str(entry.get("artifact_id") or "") or None,
                        expected_recipe_fingerprint=expected.fingerprint if expected else None,
                    )
                else:
                    result[key] = ArtifactValidation(
                        False,
                        "missing",
                        "no_active_artifact",
                        expected_recipe_fingerprint=expected.fingerprint if expected else None,
                    )
                continue
            result[key] = self.validate(ref, expected_recipe=expected)
        return result
