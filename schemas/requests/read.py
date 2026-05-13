from __future__ import annotations

from typing import Optional

from pydantic import Field

from ..base import TenantIdentifierSchema
from ..validators import ValidatedEnvironment


class ReadPromptRequest(TenantIdentifierSchema):
    """Fetch a specific prompt by handle, version, and environment."""

    prompt_handle: str = Field(..., description="Prompt handle / collection name")
    environment: ValidatedEnvironment = Field(..., description="Target environment")
    version: Optional[int] = Field(
        None, description="Specific version to retrieve; latest if omitted"
    )
    sub_agent: Optional[str] = Field(None, description="Sub-agent filter")


class VersionsRequest(TenantIdentifierSchema):
    """List all available versions of a prompt in a given environment."""

    prompt_handle: str = Field(..., description="Prompt handle / collection name")
    environment: ValidatedEnvironment = Field(..., description="Target environment")
    sub_agent: Optional[str] = Field(None, description="Sub-agent filter")
