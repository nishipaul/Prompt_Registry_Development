from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from .metadata import PromptMetadataSchema
from .validators import ValidatedEnvironment


class TenantIdentifierSchema(BaseModel):
    """Reusable tenant-scoping mixin — included in all tenant-scoped requests."""

    tenant_id: str = Field(..., description="Tenant identifier")
    tenant_feature: str = Field(..., description="Tenant feature name")


class BasePromptSchema(BaseModel):
    """Common fields present on every prompt entity."""

    prompt_handle: str = Field(..., description="Unique handle / collection name for the prompt")
    version: int = Field(..., description="Prompt version number")
    environment: ValidatedEnvironment = Field(..., description="Deployment environment")
    metadata: PromptMetadataSchema = Field(
        ..., description="Prompt ownership and runtime metadata"
    )
    sub_agent: Optional[str] = Field(None, description="Sub-agent scoped to this prompt")
    info: Optional[str] = Field(None, description="Human-readable supplementary information")


class AuditSchema(BaseModel):
    """Lifecycle tracking for create / update operations."""

    created_at: datetime = Field(..., description="UTC timestamp of creation")
    created_by: Optional[str] = Field(None, description="User who created the record")
    updated_at: Optional[datetime] = Field(None, description="UTC timestamp of last update")
    updated_by: Optional[str] = Field(None, description="User who last updated the record")


class OperationStatusSchema(BaseModel):
    """Minimal success/failure envelope for mutation responses."""

    success: bool = Field(..., description="Whether the operation succeeded")
    message: str = Field(..., description="Human-readable result message")
