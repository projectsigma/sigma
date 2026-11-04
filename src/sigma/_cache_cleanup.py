"""Best-effort cleanup for libosmium's disk-backed node-location indexes."""
from __future__ import annotations

import gc
import time
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

# Windows can keep a just-closed file locked for a moment (for example while a virus
# scanner reads it), so a failed deletion is retried after these waits (seconds).
_RETRY_WAITS = (0.2, 0.5, 1.0)

def remove_temporary_node_index(
    path: Path, *, progress: Callable[[str], None] | None, label: str, retry: bool = True
) -> None:
    """Remove an intermediate index after extraction has finished, even if extraction failed.

    A failed deletion (notably a Windows file lock) must not fail a completed stage.
    """
    waits = _RETRY_WAITS if retry else ()
    for attempt in range(len(waits) + 1):
        try:
            path.unlink(missing_ok=True)
            return
        except OSError as exc:
            if attempt == len(waits):
                if progress is not None:
                    progress(f"{label}: could not delete temporary libosmium index {path}: {exc}")
                return
            gc.collect()  # release any index object still referenced from Python
            time.sleep(waits[attempt])


def new_road_node_index(sources_root: Path, pbf_sha256: str) -> Path:
    """A node-index path owned by exactly one road scan.

    libosmium appends to an existing index file, so a scan must never reopen an index
    left by another scan; a unique name also keeps concurrent scans apart.
    """
    return (Path(sources_root) / "geofabrik" / "road-node-index"
            / f"{pbf_sha256}.{uuid4().hex}.nodes.cache")
