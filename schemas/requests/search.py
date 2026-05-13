from __future__ import annotations

from typing import Optional

from pydantic import Field

from ..base import TenantIdentifierSchema
from ..validators import ValidatedEnvironment


class SearchPromptRequest(TenantIdentifierSchema):
    """Attribute-based search for prompts within a tenant scope."""

    environment: ValidatedEnvironment = Field(..., description="Target environment")
    agent_name: str = Field(..., description="Agent name filter")
    model_provider: str = Field(..., description="Model provider filter")
    model_name: str = Field(..., description="Model name filter")
    prompt_handle: Optional[str] = Field(None, description="Prompt handle filter")
    label: Optional[str] = Field(None, description="Label filter")
    sub_agent: Optional[str] = Field(None, description="Sub-agent filter")
