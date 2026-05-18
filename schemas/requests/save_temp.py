from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator

from ..metadata import PromptMetadataSchema
from ..validators import (
    OptionalValidatedEmail,
    ValidatedPromptHandle,
    validate_prompt_data_value,
)


class SaveTempPromptRequest(BaseModel):
    """
    Save a temporary (draft) prompt for later review or promotion.

    Temp prompts auto-expire (TTL controlled by TEMP_PROMPT_RETENTION_MINUTES).
    Use /commit to persist permanently.

    Mandatory fields  : metadata, prompt_data
    Optional fields   : prompt_handle, user_email, description,
                        original_environment, original_version
    """

    # ── Mandatory ─────────────────────────────────────────────────────────────
    metadata: PromptMetadataSchema = Field(
        ...,
        description="[REQUIRED] Prompt ownership and runtime metadata.",
    )
    prompt_data: Dict[str, Any] = Field(
        ...,
        description="[REQUIRED] Prompt payload as a JSON object. Must not be empty.",
    )

    # ── Optional ──────────────────────────────────────────────────────────────
    prompt_handle: ValidatedPromptHandle = Field(
        None,
        description="[OPTIONAL] Slug for this prompt. Auto-generated if omitted.",
    )
    sub_agent: Optional[str] = Field(
        None,
        description="[OPTIONAL] Sub-agent identifier.",
    )
    user_email: OptionalValidatedEmail = Field(
        None,
        description="[OPTIONAL] User email for audit trail. Strongly recommended.",
    )
    description: Optional[str] = Field(
        None,
        description="[OPTIONAL] Human-readable description.",
    )
    original_environment: Optional[str] = Field(
        None,
        description="[OPTIONAL] Source environment this draft was derived from.",
    )
    original_version: Optional[int] = Field(
        None,
        ge=1,
        description="[OPTIONAL] Source prompt version this draft is based on.",
    )

    # ── Field-level validators ─────────────────────────────────────────────────
    @field_validator("prompt_data", mode="after")
    @classmethod
    def check_prompt_data(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        return validate_prompt_data_value(v)

    @field_validator("original_version", mode="before")
    @classmethod
    def check_version_positive(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 1:
            raise ValueError("original_version must be a positive integer (≥ 1)")
        return v
