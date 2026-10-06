"""Shared immutable source identities and preserved acquisition helpers.

The package initializer is intentionally thin: optional heavy source dependencies are
loaded only by the source operation that needs them.
"""

from .store import SourceRef, SourceStore, SourceValidation

__all__ = ["SourceRef", "SourceStore", "SourceValidation"]
