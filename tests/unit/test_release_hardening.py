from __future__ import annotations

from pathlib import Path

from sigma import __version__
from sigma.config import DEFAULT_DOWNLOAD_USER_AGENT
from sigma.export.spatial import write_outputs_description
from sigma.places.pipeline import _attribution_text


def test_default_download_user_agent_uses_unified_package_identity() -> None:
    assert DEFAULT_DOWNLOAD_USER_AGENT == f"SIGMA/{__version__}"
    assert "Siphon" not in DEFAULT_DOWNLOAD_USER_AGENT


def test_outputs_description_uses_unified_sigma_version(tmp_path: Path) -> None:
    target = tmp_path / "OUTPUTS.txt"
    write_outputs_description(
        target,
        metadata={
            "created_at": "2026-10-05T00:00:00+00:00",
            "sigma_version": __version__,
            "workflow_version": "unified-c17-v1",
        },
        output_paths={},
    )
    text = target.read_text(encoding="utf-8")
    assert text.startswith("SIGMA OUTPUTS\n")
    assert f"SIGMA version: {__version__}" in text
    assert "SIGMA Engine version" not in text


def test_attribution_uses_unified_product_identity() -> None:
    import pandas as pd

    tagged = pd.DataFrame({"overture_providers": [""]})
    text = _attribution_text(tagged)
    assert text.startswith("SIGMA output source attribution\n")
    assert "SIGMA software is proprietary" in text
    assert "Sigma Siphon" not in text
