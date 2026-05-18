from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import Field, field_validator

from ..base import TenantIdentifierSchema
from ..validators import OptionalValidatedEmail, ValidatedEnvironment, validate_prompt_data_value


class UpdatePromptRequest(TenantIdentifierSchema):
    """
    Patch one or more fields on an existing prompt version, then save the
    result to the temp collection. Use /commit afterwards to persist permanently.

    Mandatory fields  : prompt_handle, environment, version, tenant_id, tenant_feature
    Optional fields   : user_email, sub_agent, prompt_data, description, tags
    """

    # ── Mandatory ─────────────────────────────────────────────────────────────
    prompt_handle: str = Field(
        ...,
        description="[REQUIRED] Prompt handle / collection name to update.",
    )
    environment: ValidatedEnvironment = Field(
        ...,
        description="[REQUIRED] Environment to read the source prompt from.",
    )
    version: int = Field(
        ...,
        ge=1,
        description="[REQUIRED] Version number to update. "
                    "Must be a positive integer. "
                    "If unsure, use /versions to list available versions first.",
    )

    # ── Optional ──────────────────────────────────────────────────────────────
    user_email: OptionalValidatedEmail = Field(
        None,
        description="[OPTIONAL] User email for audit trail. Strongly recommended.",
    )
    sub_agent: Optional[str] = Field(
        None,
        description="[OPTIONAL] Sub-agent filter — scope update to a specific sub-agent.",
    )
    prompt_data: Optional[Dict[str, Any]] = Field(
        None,
        description="[OPTIONAL] New prompt payload. If omitted, the original prompt_data is kept.",
    )
    description: Optional[str] = Field(
        None,
        description="[OPTIONAL] Updated human-readable description.",
    )
    tags: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="[OPTIONAL] Updated tags. If omitted, the original tags are kept.",
    )

    # ── Field-level validators ─────────────────────────────────────────────────
    @field_validator("prompt_data", mode="after")
    @classmethod
    def check_prompt_data(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if v is not None:
            return validate_prompt_data_value(v)
        return v
