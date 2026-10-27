"""Best-effort cleanup for libosmium's disk-backed node-location indexes."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path


def remove_temporary_node_index(
    path: Path, *, progress: Callable[[str], None] | None, label: str
) -> None:
    """Remove an intermediate index after extraction has finished, even if extraction failed.

    A failed deletion (notably a Windows file lock) must not fail a completed stage.
    """
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        if progress is not None:
            progress(f"{label}: could not delete temporary libosmium index {path}: {exc}")
