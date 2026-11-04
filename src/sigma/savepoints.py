"""Durable, recipe-scoped recovery units for expensive SIGMA stage execution.

These are *not* public artifacts.  A unit becomes reusable only after its checksum
manifest is atomically written.  The immutable artifact store is still the final
source of truth; completed stage savepoints are cleared after artifact commit.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Mapping
from uuid import uuid4

SCHEMA_VERSION = 1

# Resume units must also be invalidated if local Python implementation changes
# without a producer-version bump (e.g., a freshly applied local formula patch).
_STAGE_CODE = {
    "spatial.clusters": (
        "spatial/pipeline.py", "spatial/clustering.py", "spatial/_sparse_hdbscan.py",
        "transport/_sparse_network.py",
    ),
    "spatial.partitions": ("spatial/pipeline.py", "spatial/voronoi.py"),
    "analysis.x": ("analysis/pipeline.py", "analysis/x_graph.py", "transport/network.py"),
    "export.bundle": ("export/compatibility.py", "export/qgis.py", "export/spatial.py"),
}


def _code_signature(stage: str) -> str:
    root = Path(__file__).resolve().parent
    h = hashlib.sha256()
    for path in (Path(__file__), *(root / rel for rel in _STAGE_CODE.get(stage, ()))):
        if not path.is_file():
            # An absent optional implementation path is itself a distinct signature.
            h.update(f"missing:{path.as_posix()}".encode("utf-8"))
            continue
        h.update(str(path.name).encode("utf-8"))
        with path.open("rb") as handle:
            while data := handle.read(8 * 1024 * 1024):
                h.update(data)
    return h.hexdigest()[:16]


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class StageSavepoints:
    """Atomic and integrity-checked unit storage, isolated by artifact recipe."""

    def __init__(self, workspace_root: Path | str, stage: str, fingerprint: str):
        if (not stage or fingerprint in {"", ".", ".."} or
                any(p in {"", ".", ".."} for p in stage.split("/"))):
            raise ValueError("invalid stage savepoint identity")
        if "/" in stage or "\\" in stage or "/" in fingerprint or "\\" in fingerprint:
            raise ValueError("savepoint identity may not contain path separators")
        self.stage = stage
        # The recipe identity guards data/config; the code signature guards
        # uncommitted local edits to the long-running implementation.
        self.fingerprint = f"{fingerprint}-{_code_signature(stage)}"
        self.root = Path(workspace_root) / "state" / "savepoints" / stage / self.fingerprint

    def _key(self, unit: str) -> str:
        if not isinstance(unit, str) or not unit:
            raise ValueError("savepoint work-unit key is empty")
        return hashlib.sha256(unit.encode("utf-8")).hexdigest()

    def read(self, unit: str) -> dict[str, bytes] | None:
        """Read a *complete* matching unit or return None if missing/corrupt."""
        stem = self._key(unit)
        try:
            manifest = json.loads((self.root / f"{stem}.json").read_text("utf-8"))
            if not isinstance(manifest, dict) or any((
                manifest.get("schema") != SCHEMA_VERSION,
                manifest.get("stage") != self.stage,
                manifest.get("fingerprint") != self.fingerprint,
                manifest.get("unit") != unit,
                not isinstance(manifest.get("files"), dict),
            )):
                return None
            out = {}
            if not manifest["files"]:
                return None
            for name, info in manifest["files"].items():
                if not isinstance(name, str) or not isinstance(info, dict):
                    return None
                filename = info.get("filename")
                if not isinstance(filename, str) or "/" in filename or "\\" in filename:
                    return None
                if not filename.startswith(stem + "-"):
                    return None
                data = (self.root / filename).read_bytes()
                if len(data) != info.get("size") or _digest(data) != info.get("sha256"):
                    return None
                out[name] = data
            return out
        except (OSError, ValueError, TypeError, KeyError, UnicodeDecodeError):
            return None

    def save(self, unit: str, files: Mapping[str, bytes]) -> None:
        """Write immutable content blobs, then publish one atomic commit marker."""
        stem = self._key(unit)
        if not files:
            raise ValueError("savepoint must contain at least one file")
        self.root.mkdir(parents=True, exist_ok=True)
        meta = {}
        for name, data in files.items():
            if not isinstance(name, str) or not name or not name.replace("_", "").replace(".", "").isalnum():
                raise ValueError(f"invalid savepoint file identifier: {name!r}")
            if not isinstance(data, bytes):
                raise TypeError("savepoint files must contain bytes")
            sha = _digest(data)
            filename = f"{stem}-{name}-{sha}.blob"
            target = self.root / filename
            # An existing digest-named blob might itself have been corrupted.
            # Verify before reuse; otherwise a recomputation could never repair it.
            valid_existing = False
            if target.is_file():
                try:
                    existing_hash = hashlib.sha256()
                    existing_size = 0
                    with target.open("rb") as handle:
                        while part := handle.read(8 * 1024 * 1024):
                            existing_size += len(part)
                            existing_hash.update(part)
                    valid_existing = existing_size == len(data) and existing_hash.hexdigest() == sha
                except OSError:
                    valid_existing = False
            if not valid_existing:
                temp = self.root / f".{uuid4().hex}.tmp"
                try:
                    with temp.open("wb") as handle:
                        handle.write(data)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temp, target)
                finally:
                    temp.unlink(missing_ok=True)
            meta[name] = {"filename": filename, "size": len(data), "sha256": sha}
        manifest = {"schema": SCHEMA_VERSION, "stage": self.stage,
                    "fingerprint": self.fingerprint, "unit": unit, "files": meta}
        marker = self.root / f"{stem}.json"
        temp = self.root / f".{uuid4().hex}.tmp"
        try:
            with temp.open("w", encoding="utf-8") as handle:
                json.dump(manifest, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, marker)
        finally:
            temp.unlink(missing_ok=True)

    def restore_file(self, unit: str, target: Path | str) -> bool:
        """Verify and copy a potentially huge output without materializing in memory."""
        stem = self._key(unit)
        try:
            manifest = json.loads((self.root / f"{stem}.json").read_text("utf-8"))
            if (manifest.get("schema") != SCHEMA_VERSION or
                manifest.get("stage") != self.stage or
                manifest.get("fingerprint") != self.fingerprint or
                manifest.get("unit") != unit or
                set(manifest.get("files", {})) != {"output"}):
                return False
            info = manifest["files"]["output"]
            filename = info["filename"]
            if (not isinstance(filename, str) or
                    not filename.startswith(stem + "-") or
                    "/" in filename or "\\" in filename):
                return False
            source = self.root / filename
            hasher = hashlib.sha256()
            size = 0
            with source.open("rb") as handle:
                while data := handle.read(8 * 1024 * 1024):
                    size += len(data)
                    hasher.update(data)
            if size != info["size"] or hasher.hexdigest() != info["sha256"]:
                return False
        except (OSError, ValueError, TypeError, KeyError):
            return False
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + f".{uuid4().hex}.tmp")
        try:
            try:
                os.link(source, temp)
            except OSError:
                shutil.copyfile(source, temp)
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
        return True

    def save_file(self, unit: str, source: Path | str) -> None:
        """Checkpoint a large output with a hard link when possible, else stream copy.

        The staging file must not be modified after saving this checkpoint.  Both
        files reside inside the same workspace, so NTFS/ext4 hard links avoid
        duplicating very large GeoPackages when supported by the filesystem.
        """
        stem = self._key(unit)
        self.root.mkdir(parents=True, exist_ok=True)
        source = Path(source)
        sha = hashlib.sha256()
        size = 0
        with source.open("rb") as src:
            while part := src.read(8 * 1024 * 1024):
                sha.update(part)
                size += len(part)
        filename = f"{stem}-output-{sha.hexdigest()}.blob"
        target = self.root / filename
        temp = self.root / f".{uuid4().hex}.tmp"
        try:
            try:
                os.link(source, temp)
            except OSError:
                shutil.copyfile(source, temp)
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
        manifest = {"schema": SCHEMA_VERSION, "stage": self.stage,
                    "fingerprint": self.fingerprint, "unit": unit, "files": {
                        "output": {"filename": filename, "size": size,
                                   "sha256": sha.hexdigest()}}}
        marker = self.root / f"{stem}.json"
        temp = self.root / f".{uuid4().hex}.tmp"
        try:
            with temp.open("w", encoding="utf-8") as handle:
                json.dump(manifest, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, marker)
        finally:
            temp.unlink(missing_ok=True)

    def clear(self) -> None:
        """Best-effort cleanup after successful immutable artifact commit."""
        try:
            shutil.rmtree(self.root)
        except FileNotFoundError:
            pass
        except OSError:
            # A Windows filesystem lock must not invalidate an already committed artifact.
            pass


def clear_stage_savepoints(root: Path | str, stage: str, fingerprint: str) -> None:
    StageSavepoints(root, stage, fingerprint).clear()
