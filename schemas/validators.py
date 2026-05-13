from __future__ import annotations

from typing import Annotated, List, Optional

from pydantic.functional_validators import AfterValidator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_ENVIRONMENTS: List[str] = ["development", "test", "uat", "production", "user_temp"]

# ---------------------------------------------------------------------------
# Validator functions — single source of truth, reused by Pydantic and
# the service layer alike
# ---------------------------------------------------------------------------


def validate_environment_value(value: str) -> str:
    """Normalize and validate an environment string. Raises ValueError on failure."""
    value = value.lower()
    if value not in VALID_ENVIRONMENTS:
        raise ValueError(
            f"Invalid environment '{value}'. Must be one of: {VALID_ENVIRONMENTS}"
        )
    return value


def validate_email_value(value: str) -> str:
    """Normalize and validate an email string. Raises ValueError on failure."""
    value = value.strip().lower()
    if "@" not in value or value.startswith("@") or value.endswith("@"):
        raise ValueError("Must be a valid email address")
    return value


# ---------------------------------------------------------------------------
# Annotated types — apply validation automatically on any field that uses them
# ---------------------------------------------------------------------------

ValidatedEnvironment = Annotated[str, AfterValidator(validate_environment_value)]
ValidatedEmail = Annotated[str, AfterValidator(validate_email_value)]
OptionalValidatedEmail = Annotated[
    Optional[str],
    AfterValidator(lambda v: validate_email_value(v) if v is not None else v),
]
