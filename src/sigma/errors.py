"""Public exception hierarchy for SIGMA orchestration boundaries.

Low-level migrated algorithms should retain their precise existing exceptions unless
wrapping them adds useful domain or stage context.
"""


class SigmaError(Exception):
    """Base class for errors raised by unified SIGMA public boundaries."""


class ConfigurationError(SigmaError):
    """Raised when a SIGMA configuration is invalid or incomplete."""


class ValidationError(SigmaError):
    """Base class for validation failures at domain or artifact boundaries."""


class AreaValidationError(ValidationError):
    """Raised when an area or boundary definition is invalid."""


class EconomyValidationError(ValidationError):
    """Raised when an economy definition or numerical input is invalid."""


class TaxonomyValidationError(ValidationError):
    """Raised when a classification taxonomy is invalid."""


class ArtifactValidationError(ValidationError):
    """Raised when a managed artifact fails validation."""


class SourceError(SigmaError):
    """Raised when an external or managed source cannot be resolved safely."""


class StageExecutionError(SigmaError):
    """Raised at orchestration boundaries when a workflow stage fails."""


class CompatibilityError(SigmaError):
    """Raised when legacy compatibility inputs cannot be imported safely."""
