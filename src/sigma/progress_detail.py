"""Small, optional progress reporter for SIGMA's long-running analytical stages.

No changes to analytics. Background thread merely reports elapsed time when a
single opaque computation blocks, and stops immediately on exit or exceptions.
"""
from __future__ import annotations

from contextlib import contextmanager
from threading import Event, Thread
from time import monotonic
from typing import Callable, Iterator


def _elapsed(seconds: float) -> str:
    minutes, secs = divmod(max(0, int(seconds)), 60)
    return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"


@contextmanager
def detail_phase(
    progress: Callable[[str], None] | None,
    label: str,
    *,
    heartbeat_seconds: float = 45.0,
) -> Iterator[None]:
    """Describe one phase, with periodic elapsed-time updates (not fake percentages)."""
    if progress is None:
        yield
        return
    started = monotonic()
    progress(f"{label}: started")
    stop = Event()

    def heartbeat() -> None:
        while not stop.wait(heartbeat_seconds):
            try:
                progress(f"{label}: still running ({_elapsed(monotonic() - started)} elapsed)")
            except Exception:
                # Output failures must never interrupt the analytical computation.
                pass

    thread = Thread(target=heartbeat, name="sigma-progress-detail", daemon=True)
    thread.start()
    try:
        yield
    except BaseException:
        progress(f"{label}: failed after {_elapsed(monotonic() - started)}")
        raise
    else:
        progress(f"{label}: complete ({_elapsed(monotonic() - started)})")
    finally:
        stop.set()
        thread.join(timeout=1.0)
