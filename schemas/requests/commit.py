from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..metadata import PromptMetadataSchema
from ..validators import ValidatedEmail, ValidatedEnvironment


class CommitPromptRequest(BaseModel):
    """Publish a prompt to a target environment."""

    metadata: PromptMetadataSchema = Field(
        ..., description="Prompt ownership and runtime metadata"
    )
    prompt_data: Dict[str, Any] = Field(..., description="Prompt payload / JSON structure")
    environment: ValidatedEnvironment = Field(..., description="Target environment")
    user_email: ValidatedEmail = Field(
        ..., description="Email of the user committing the prompt"
    )
    labels: List[str] = Field(..., description="Categorisation labels")
    prompt_handle: Optional[str] = Field(None, description="Prompt handle / collection name")
    sub_agent: Optional[str] = Field(None, description="Sub-agent mapped to the prompt")
    description: Optional[str] = Field(None, description="Human-readable description")
    tags: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional tags")
