from __future__ import annotations

from typing import Optional

from pydantic import Field

from ..base import OperationStatusSchema
from ..metadata import OperationMetadataSchema, PromptMetadataSchema


class DeleteResponseSchema(OperationStatusSchema):
    """Returned after a prompt (or version) is deleted."""

    deleted_prompt_handle: str = Field(..., description="Handle of the deleted prompt")
    deleted_version: int = Field(..., description="Version that was deleted")
    deleted_environment: str = Field(
        ..., description="Environment the prompt was deleted from"
    )
    deleted_sub_agent: Optional[str] = Field(
        None, description="Sub-agent scope of the deleted prompt"
    )
    metadata: PromptMetadataSchema = Field(
        ..., description="Metadata of the deleted prompt"
    )
    info: Optional[str] = Field(None, description="Additional deletion information")
    operation: OperationMetadataSchema = Field(..., description="Operation context")
