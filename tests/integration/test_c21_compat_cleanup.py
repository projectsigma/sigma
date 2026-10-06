from __future__ import annotations

from pathlib import Path

import pytest

from sigma import AreaCatalog, Sigma
from sigma.spatial.restart import RestartSpatialPipeline


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def test_legacy_orchestration_namespaces_are_not_shipped() -> None:
    assert not (SRC / "sigma_siphon").exists()
    assert not (SRC / "sigma_engine").exists()
    assert not (SRC / "sigma" / "area" / "compat.py").exists()


def test_runtime_source_has_no_cross_repository_bridge() -> None:
    runtime = SRC / "sigma"
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in runtime.rglob("*.py")
    )
    assert "SIGMA_SIPHON_ROOT" not in text
    assert "import subprocess" not in text
    assert "subprocess.run" not in text
    assert "from sigma_siphon" not in text
    assert "import sigma_siphon" not in text
    assert "from sigma_engine" not in text
    assert "import sigma_engine" not in text


def test_area_model_exposes_only_canonical_boundary_spec() -> None:
    area = AreaCatalog().resolve("quezon_city")
    assert area.boundary is not None
    for old_name in ("boundary_gpkg", "boundary_layer", "boundary_field", "boundary_values"):
        assert not hasattr(area, old_name)


def test_legacy_data_restart_boundary_is_intentionally_retained() -> None:
    assert callable(Sigma.from_partitions)
    assert RestartSpatialPipeline.__doc__


def test_unknown_area_guidance_uses_unified_cli() -> None:
    with pytest.raises(KeyError, match=r"sigma areas list --search"):
        AreaCatalog().resolve("definitely-not-an-area")
