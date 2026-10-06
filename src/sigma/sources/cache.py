from __future__ import annotations

import json
import os
from pathlib import Path

CACHE_IDENTITY_VERSION = 1


def _metadata_path(cache_file: Path) -> Path:
    return cache_file.with_suffix(cache_file.suffix + ".meta.json")


def cache_identity(bbox: tuple[float, float, float, float]) -> dict[str, object]:
    return {
        "version": CACHE_IDENTITY_VERSION,
        "bbox": [float(value) for value in bbox],
    }


def cache_matches_bbox(
    cache_file: Path,
    bbox: tuple[float, float, float, float],
) -> bool:
    if not cache_file.exists():
        return False

    metadata = _metadata_path(cache_file)
    if not metadata.exists():
        return False

    try:
        payload = json.loads(metadata.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return payload == cache_identity(bbox)


def write_cache_identity(
    cache_file: Path,
    bbox: tuple[float, float, float, float],
) -> None:
    metadata = _metadata_path(cache_file)
    metadata.parent.mkdir(parents=True, exist_ok=True)
    temporary = metadata.with_suffix(metadata.suffix + ".part")
    temporary.write_text(
        json.dumps(cache_identity(bbox), indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, metadata)
