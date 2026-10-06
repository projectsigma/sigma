from dataclasses import FrozenInstanceError

import pytest

import sigma
from sigma.config import SigmaConfig
from sigma.errors import (
    AreaValidationError,
    ArtifactValidationError,
    CompatibilityError,
    ConfigurationError,
    EconomyValidationError,
    SigmaError,
    SourceError,
    StageExecutionError,
    TaxonomyValidationError,
    ValidationError,
)
from sigma.resources import resource_root


def test_package_import_and_version() -> None:
    assert sigma.__version__ == "0.1.0.dev0"


def test_root_config_is_immutable() -> None:
    config = SigmaConfig()
    with pytest.raises((FrozenInstanceError, AttributeError)):
        config.unplanned = True  # type: ignore[attr-defined]


def test_exception_hierarchy() -> None:
    assert issubclass(ConfigurationError, SigmaError)
    assert issubclass(ValidationError, SigmaError)
    assert issubclass(AreaValidationError, ValidationError)
    assert issubclass(EconomyValidationError, ValidationError)
    assert issubclass(TaxonomyValidationError, ValidationError)
    assert issubclass(ArtifactValidationError, ValidationError)
    assert issubclass(SourceError, SigmaError)
    assert issubclass(StageExecutionError, SigmaError)
    assert issubclass(CompatibilityError, SigmaError)


def test_packaged_resource_mechanism() -> None:
    text = resource_root().joinpath("README.txt").read_text(encoding="utf-8")
    assert "SIGMA packaged resources" in text
    assert "canonical area catalog/boundaries" in text
    assert "artifact provenance" in text


def test_c16_public_domain_models_and_facade_are_exposed() -> None:
    assert hasattr(sigma, "Economy")
    assert hasattr(sigma, "Sector")
    assert hasattr(sigma, "SectorCatalog")
    assert hasattr(sigma, "Area")
    assert hasattr(sigma, "BoundarySpec")
    assert hasattr(sigma, "AreaCatalog")
    assert hasattr(sigma, "BoundaryResolver")
    assert hasattr(sigma, "Sigma")
    assert hasattr(sigma, "SigmaWorkspace")
    assert not hasattr(sigma, "ExecutionPlanner")
    assert not hasattr(sigma, "ArtifactStore")
