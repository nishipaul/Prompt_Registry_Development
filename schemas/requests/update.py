from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import Field

from ..base import TenantIdentifierSchema
from ..validators import OptionalValidatedEmail, ValidatedEnvironment


class UpdatePromptRequest(TenantIdentifierSchema):
    """Patch one or more fields on an existing prompt version."""

    prompt_handle: str = Field(..., description="Prompt handle / collection name")
    environment: ValidatedEnvironment = Field(..., description="Target environment")
    user_email: OptionalValidatedEmail = Field(None, description="User email for audit trail")
    version: Optional[int] = Field(None, description="Version to update; latest if omitted")
    sub_agent: Optional[str] = Field(None, description="Sub-agent filter")
    prompt_data: Optional[Dict[str, Any]] = Field(None, description="Updated prompt payload")
    description: Optional[str] = Field(None, description="Updated description")
    tags: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional tags")
