"""Read-only, separately published browser visualization of SIGMA outputs.

The explorer deliberately never mutates SIGMA artifacts or runs analytical stages.
"""
from .builder import (
    build_web_bundle,
    bundle_is_current,
    bundle_profile,
    resolve_output_directory,
    source_fingerprint,
)
from .server import serve_bundle

__all__ = [
    "build_web_bundle",
    "bundle_is_current",
    "bundle_profile",
    "resolve_output_directory",
    "serve_bundle",
    "source_fingerprint",
]
