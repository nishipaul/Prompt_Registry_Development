from __future__ import annotations

from typing import Optional

from pydantic import Field

from ..base import TenantIdentifierSchema
from ..validators import ValidatedEnvironment


class ReadPromptRequest(TenantIdentifierSchema):
    """
    Fetch a specific prompt by handle, version, and environment.

    Mandatory fields  : prompt_handle, environment, tenant_id, tenant_feature
    Optional fields   : version (latest if omitted), sub_agent
    """

    # ── Mandatory ─────────────────────────────────────────────────────────────
    prompt_handle: str = Field(
        ...,
        description="[REQUIRED] Prompt handle / collection name to retrieve.",
    )
    environment: ValidatedEnvironment = Field(
        ...,
        description="[REQUIRED] Environment to read from. "
                    "One of: development | test | uat | production | user_temp",
    )

    # ── Optional ──────────────────────────────────────────────────────────────
    version: Optional[int] = Field(
        None,
        ge=1,
        description="[OPTIONAL] Specific version to retrieve. "
                    "Omit to return ALL versions for this handle.",
    )
    sub_agent: Optional[str] = Field(
        None,
        description="[OPTIONAL] Filter results to a specific sub-agent.",
    )


class VersionsRequest(TenantIdentifierSchema):
    """
    List all available versions of a prompt in a given environment.

    Mandatory fields  : prompt_handle, environment, tenant_id, tenant_feature
    Optional fields   : sub_agent
    """

    # ── Mandatory ─────────────────────────────────────────────────────────────
    prompt_handle: str = Field(
        ...,
        description="[REQUIRED] Prompt handle / collection name.",
    )
    environment: ValidatedEnvironment = Field(
        ...,
        description="[REQUIRED] Environment to query. "
                    "One of: development | test | uat | production",
    )

    # ── Optional ──────────────────────────────────────────────────────────────
    sub_agent: Optional[str] = Field(
        None,
        description="[OPTIONAL] Narrow version list to a specific sub-agent.",
    )
