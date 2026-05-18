from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import Field, field_validator

from ..base import TenantIdentifierSchema
from ..validators import ValidatedEnvironment


class SearchPromptRequest(TenantIdentifierSchema):
    """
    Attribute-based search for prompts within a tenant scope.

    Mandatory fields  : environment, tenant_id, tenant_feature,
                        agent_name, model_provider, model_name
    Optional filters  : prompt_handle, label, sub_agent, created_by,
                        version, created_after, created_before
    """

    # ── Mandatory ─────────────────────────────────────────────────────────────
    environment: ValidatedEnvironment = Field(
        ...,
        description="[REQUIRED] Target environment. "
                    "One of: development | test | uat | production",
    )
    agent_name: str = Field(
        ...,
        description="[REQUIRED] Filter by agent name.",
    )
    model_provider: str = Field(
        ...,
        description="[REQUIRED] Filter by model provider (e.g. openai, azure).",
    )
    model_name: str = Field(
        ...,
        description="[REQUIRED] Filter by model name (e.g. gpt-4).",
    )

    # ── Optional filters ──────────────────────────────────────────────────────
    prompt_handle: Optional[str] = Field(
        None,
        description="[OPTIONAL] Narrow to a specific prompt handle (collection).",
    )
    label: Optional[str] = Field(
        None,
        description="[OPTIONAL] Filter by a single label value.",
    )
    sub_agent: Optional[str] = Field(
        None,
        description="[OPTIONAL] Filter by sub-agent name.",
    )
    created_by: Optional[str] = Field(
        None,
        description="[OPTIONAL] Filter by the email of the user who created the prompt.",
    )
    version: Optional[int] = Field(
        None,
        ge=1,
        description="[OPTIONAL] Exact version number to match.",
    )
    created_after: Optional[datetime] = Field(
        None,
        description="[OPTIONAL] Return prompts created on or after this UTC datetime. "
                    "ISO-8601 format. Example: '2025-01-01T00:00:00'",
    )
    created_before: Optional[datetime] = Field(
        None,
        description="[OPTIONAL] Return prompts created strictly before this UTC datetime. "
                    "ISO-8601 format. Example: '2025-12-31T23:59:59'",
    )

    # ── Cross-field validation ─────────────────────────────────────────────────
    @field_validator("created_before", mode="after")
    @classmethod
    def check_date_range(cls, v: Optional[datetime], info) -> Optional[datetime]:
        after = info.data.get("created_after")
        if v is not None and after is not None and v <= after:
            raise ValueError("created_before must be later than created_after")
        return v
