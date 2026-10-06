"""Shared graph identifiers used by migrated analysis kernels.

``make_node_id`` was migrated in C2d because point scoring depends on that stable
identifier. C14 now owns X construction in :mod:`sigma.analysis.x_graph`;
centrality remains a separate C15 concern.
"""

from __future__ import annotations

from urllib.parse import quote


def make_node_id(type_value: str, cluster: int) -> str:
    """Encode a stable, reversible-enough textual key for ``[type, cluster]``.

    URL quoting prevents sector labels containing spaces, slashes, or the ``::`` delimiter
    from making audit files ambiguous.  ``type`` and ``cluster`` remain separate columns in
    every artifact, so consumers never need to parse this string to recover them.
    """
    return f"type={quote(str(type_value), safe='')}::cluster={int(cluster)}"
