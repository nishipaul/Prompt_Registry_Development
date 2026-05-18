from __future__ import annotations

import re
from typing import Annotated, Any, Dict, List, Optional

from pydantic.functional_validators import AfterValidator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_ENVIRONMENTS: List[str] = ["development", "test", "uat", "production", "user_temp"]

# prompt_handle: lowercase alphanumeric + underscore + hyphen, max 128 chars
_HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,127}$")

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


def validate_prompt_handle_value(value: Optional[str]) -> Optional[str]:
    """
    Normalize and validate a prompt handle.
    Allowed: lowercase letters, digits, underscores, hyphens. 1-128 chars.
    Raises ValueError on invalid input; returns None unchanged.
    """
    if value is None:
        return None
    value = value.strip().lower()
    if not value:
        return None
    if not _HANDLE_RE.match(value):
        raise ValueError(
            f"Invalid prompt_handle '{value}'. "
            "Must be 1-128 characters: lowercase letters, digits, underscores, or hyphens. "
            "Must start with a letter or digit."
        )
    return value


def validate_prompt_data_value(value: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate prompt_data structure:
    - Must not be empty.
    - All keys must be non-empty strings.
    - Values must be serialisable primitives or collections (no callables / class instances).
    """
    if not value:
        raise ValueError("prompt_data must not be empty — provide at least one key-value pair")
    for k in value:
        if not isinstance(k, str) or not k.strip():
            raise ValueError(
                f"prompt_data keys must be non-empty strings, got: {type(k).__name__!r}"
            )
    return value


def validate_labels_value(value: List[str]) -> List[str]:
    """At least one non-empty label is required."""
    cleaned = [lbl.strip() for lbl in (value or []) if lbl.strip()]
    if not cleaned:
        raise ValueError("labels must contain at least one non-empty string")
    return cleaned


# ---------------------------------------------------------------------------
# Annotated types — apply validation automatically on any field that uses them
# ---------------------------------------------------------------------------

ValidatedEnvironment      = Annotated[str,            AfterValidator(validate_environment_value)]
ValidatedEmail            = Annotated[str,            AfterValidator(validate_email_value)]
ValidatedPromptHandle     = Annotated[Optional[str],  AfterValidator(validate_prompt_handle_value)]
OptionalValidatedEmail    = Annotated[
    Optional[str],
    AfterValidator(lambda v: validate_email_value(v) if v is not None else v),
]
