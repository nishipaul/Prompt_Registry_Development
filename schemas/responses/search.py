from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from ..metadata import OperationMetadataSchema
from .create import CreateResponseSchema


class SearchResponseSchema(BaseModel):
    """Returned from a prompt search or version-list query."""

    total_results: int = Field(..., description="Total number of matching prompts")
    prompts: List[CreateResponseSchema] = Field(..., description="Matching prompt records")
    operation: OperationMetadataSchema = Field(..., description="Operation context")
