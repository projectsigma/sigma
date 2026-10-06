from __future__ import annotations

import platform
import sys
from typing import Any

from ._version import __version__


def runtime_provenance() -> dict[str, Any]:
    """Small, serializable runtime record suitable for artifact manifests."""
    return {
        "sigma_version": __version__,
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "executable": sys.executable,
    }
