from __future__ import annotations

from typing import Optional

from pydantic import Field

from ..base import TenantIdentifierSchema
from ..validators import OptionalValidatedEmail, ValidatedEnvironment


class DeletePromptRequest(TenantIdentifierSchema):
    """
    Remove a specific prompt version from an environment (permanently).

    The deletion is always audit-logged in the environment's log database.

    Mandatory fields  : prompt_handle, environment, version, tenant_id, tenant_feature
    Optional fields   : user_email, sub_agent, deletion_reason
    """

    # ── Mandatory ─────────────────────────────────────────────────────────────
    prompt_handle: str = Field(
        ...,
        description="[REQUIRED] Prompt handle / collection name.",
    )
    environment: ValidatedEnvironment = Field(
        ...,
        description="[REQUIRED] Environment to delete from. "
                    "One of: development | test | uat | production",
    )
    version: int = Field(
        ...,
        ge=1,
        description="[REQUIRED] Exact version number to delete. "
                    "Use /versions to discover available versions before deleting.",
    )

    # ── Optional ──────────────────────────────────────────────────────────────
    user_email: OptionalValidatedEmail = Field(
        None,
        description="[OPTIONAL] User email for audit trail. "
                    "Strongly recommended — recorded in deletion log.",
    )
    sub_agent: Optional[str] = Field(
        None,
        description="[OPTIONAL] Sub-agent filter — scope deletion to a specific sub-agent.",
    )
    deletion_reason: Optional[str] = Field(
        None,
        description="[OPTIONAL] Human-readable reason for deletion. "
                    "Strongly recommended — recorded in audit log for compliance.",
    )
