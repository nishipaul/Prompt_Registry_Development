from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PromptMetadataSchema(BaseModel):
    """Identifies the prompt's ownership and runtime context."""

    tenant_id: str = Field(..., description="Unique tenant identifier")
    tenant_feature: str = Field(..., description="Tenant feature name")
    model_name: str = Field(..., description="Model used for the prompt (e.g. gpt-4)")
    model_provider: str = Field(..., description="Model provider (e.g. azure, openai)")
    label: List[str] = Field(..., description="Categorisation labels")
    agent_name: str = Field(..., description="Name of the agent using this prompt")
    framework: Optional[str] = Field(
        None, description="Orchestration framework (e.g. langchain)"
    )
    additional_metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Arbitrary extension metadata"
    )


class OperationMetadataSchema(BaseModel):
    """Captures who performed an operation and when — present on every response."""

    operation_type: str = Field(
        ...,
        description="Operation kind: create | read | update | delete | search | commit | save_temp | versions",
    )
    performed_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when the operation was executed",
    )
    performed_by: Optional[str] = Field(
        None, description="User (email) who triggered the operation"
    )
    request_id: Optional[str] = Field(
        None, description="Unique request ID for distributed tracing"
    )
