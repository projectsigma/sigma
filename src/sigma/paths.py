"""User-visible SIGMA data locations.

The default is intentionally not a hidden dot-directory.  Ordinary users should be
able to find the shared national source and understand where disk space is used.
Advanced deployments can set ``SIGMA_HOME`` explicitly.
"""
from __future__ import annotations

import os
from pathlib import Path


def sigma_home() -> Path:
    configured = os.getenv("SIGMA_HOME", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / "Documents" / "SIGMA").resolve()


def source_store_root() -> Path:
    return sigma_home() / "sources"


def initialization_path() -> Path:
    return sigma_home() / "config.json"
