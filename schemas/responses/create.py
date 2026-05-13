from __future__ import annotations

from typing import Any, Dict, List

from pydantic import Field

from ..base import AuditSchema, BasePromptSchema


class CreateResponseSchema(BasePromptSchema, AuditSchema):
    """Represents a single stored prompt record (used in read / search results)."""

    prompt_data: Dict[str, Any] = Field(..., description="Prompt content / data")
    labels: List[str] = Field(..., description="Categorisation labels")
