"""Public PSIC taxonomy surface.

The proven hierarchy/reference implementation remains in ``reference.py`` during the
migration; this module provides the target architectural home without duplicating it.
"""
from .reference import PsicNode, PsicTaxonomy, ReferenceDataError, load_builtin_psic_taxonomy

__all__ = ["PsicNode", "PsicTaxonomy", "ReferenceDataError", "load_builtin_psic_taxonomy"]
