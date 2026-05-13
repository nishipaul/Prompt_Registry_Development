from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from ..metadata import PromptMetadataSchema
from ..validators import OptionalValidatedEmail


class SaveTempPromptRequest(BaseModel):
    """Save a temporary (draft) prompt for later review or promotion."""

    prompt_handle: Optional[str] = Field(None, description="Prompt handle / collection name")
    sub_agent: Optional[str] = Field(None, description="Sub-agent mapped to the prompt")
    user_email: OptionalValidatedEmail = Field(None, description="User email for audit trail")
    metadata: PromptMetadataSchema = Field(
        ..., description="Prompt ownership and runtime metadata"
    )
    prompt_data: Dict[str, Any] = Field(..., description="Prompt payload / JSON structure")
    description: Optional[str] = Field(None, description="Human-readable description")
    original_environment: Optional[str] = Field(
        None, description="Source environment reference"
    )
    original_version: Optional[int] = Field(None, description="Source prompt version")
