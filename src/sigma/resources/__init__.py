"""Access to resources packaged with :mod:`sigma`.

Resource bytes are migrated only at their owning checkpoints. This module establishes
one importlib.resources-based access mechanism so migrated code does not depend on
checkout-relative paths.
"""

from importlib.resources import files
from importlib.resources.abc import Traversable


def resource_root() -> Traversable:
    """Return the traversable root of SIGMA's packaged resources."""

    return files(__package__)


__all__ = ["resource_root"]
