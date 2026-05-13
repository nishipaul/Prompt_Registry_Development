from __future__ import annotations

from typing import Optional

from pydantic import Field

from ..base import TenantIdentifierSchema
from ..validators import OptionalValidatedEmail, ValidatedEnvironment


class DeletePromptRequest(TenantIdentifierSchema):
    """Remove a prompt (or a specific version) from an environment."""

    prompt_handle: str = Field(..., description="Prompt handle / collection name")
    environment: ValidatedEnvironment = Field(..., description="Target environment")
    user_email: OptionalValidatedEmail = Field(None, description="User email for audit trail")
    version: Optional[int] = Field(
        None, description="Version to delete; all versions if omitted"
    )
    sub_agent: Optional[str] = Field(None, description="Sub-agent filter")
    deletion_reason: Optional[str] = Field(None, description="Reason for deletion")
