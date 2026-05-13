from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import Field

from ..base import AuditSchema, BasePromptSchema, OperationStatusSchema
from ..metadata import OperationMetadataSchema


class CommitResponseSchema(BasePromptSchema, AuditSchema, OperationStatusSchema):
    """Returned after a prompt is committed (published) to an environment."""

    other_sub_agents: Optional[List[Dict[str, Any]]] = Field(
        None, description="Other sub-agents already mapped to this prompt handle"
    )
    is_new_sub_agent: Optional[bool] = Field(
        None, description="True when the sub-agent is newly registered"
    )
    operation: OperationMetadataSchema = Field(..., description="Operation context")
