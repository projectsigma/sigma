"""Required, explicit initialization of SIGMA's shared national source."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from typing import Callable

from .errors import ConfigurationError
from .paths import initialization_path, sigma_home, source_store_root
from .sources import SourceRef, SourceStore

INITIALIZATION_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class Initialization:
    home: Path
    source_store: Path
    geofabrik: SourceRef
    initialized_at: str


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def initialize(*, refresh: bool = False, progress: Callable[[str], None] | None = None) -> Initialization:
    home = sigma_home()
    source_root = source_store_root()
    if progress is not None:
        progress(f"SIGMA shared data directory: {home}")
        progress(f"Shared source store: {source_root}")
        progress("Preparing the Philippines OpenStreetMap source used for both places and roads")
    home.mkdir(parents=True, exist_ok=True)
    store = SourceStore(source_root)
    geofabrik = store.ensure_geofabrik(refresh=refresh, progress=progress)
    initialized_at = datetime.now(UTC).isoformat()
    _atomic_json(
        initialization_path(),
        {
            "schema_version": INITIALIZATION_SCHEMA_VERSION,
            "initialized_at": initialized_at,
            "home": str(home),
            "source_store": str(source_root),
            "geofabrik_source_id": geofabrik.source_id,
            "geofabrik_version": geofabrik.version,
            "geofabrik_path": str(geofabrik.path),
            "geofabrik_size_bytes": int(geofabrik.size),
        },
    )
    if progress is not None:
        progress(
            f"Initialization complete: Philippines OSM PBF ready at {geofabrik.path} "
            f"({geofabrik.size / 2**20:,.0f} MiB)"
        )
    return Initialization(home, source_root, geofabrik, initialized_at)


def load_initialization() -> Initialization | None:
    path = initialization_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != INITIALIZATION_SCHEMA_VERSION:
        return None
    try:
        source_root = Path(str(payload["source_store"])).expanduser().resolve()
        source_id = str(payload["geofabrik_source_id"])
        initialized_at = str(payload["initialized_at"])
    except (KeyError, TypeError, ValueError):
        return None
    if source_root != source_store_root().resolve():
        return None
    try:
        store = SourceStore(source_root)
        ref = store.get(source_id)
        if ref.provider != "geofabrik" or not store.validate(ref).valid:
            return None
        current = store.current_geofabrik()
        if current is None:
            return None
        ref = current
    except Exception:
        return None
    return Initialization(sigma_home(), source_root, ref, initialized_at)


def require_initialization() -> Initialization:
    state = load_initialization()
    if state is None:
        raise ConfigurationError(
            "SIGMA has not been initialized. Run 'sigma init' first. "
            "Initialization creates the visible shared data directory and downloads the "
            "Philippines OpenStreetMap PBF used for places and roads."
        )
    return state
