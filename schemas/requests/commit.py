from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from ..metadata import PromptMetadataSchema
from ..validators import (
    ValidatedEmail,
    ValidatedEnvironment,
    ValidatedPromptHandle,
    validate_labels_value,
    validate_prompt_data_value,
)


class CommitPromptRequest(BaseModel):
    """
    Publish a prompt permanently to a target environment.

    Mandatory fields  : metadata, prompt_data, environment, user_email, labels
    Optional fields   : prompt_handle (auto-generated if omitted), sub_agent,
                        description, tags
    """

    # ── Mandatory ─────────────────────────────────────────────────────────────
    metadata: PromptMetadataSchema = Field(
        ...,
        description="[REQUIRED] Prompt ownership and runtime metadata "
                    "(tenant_id, tenant_feature, model_name, model_provider, agent_name, label)",
    )
    prompt_data: Dict[str, Any] = Field(
        ...,
        description="[REQUIRED] Prompt payload as a JSON object. "
                    "Must contain at least one key. "
                    "Example: {\"system_prompt\": \"You are a helpful assistant.\", "
                    "\"user_content\": \"{{user_input}}\"}",
    )
    environment: ValidatedEnvironment = Field(
        ...,
        description="[REQUIRED] Target environment. "
                    "One of: development | test | uat | production",
    )
    user_email: ValidatedEmail = Field(
        ...,
        description="[REQUIRED] Email of the user committing the prompt. Used for audit trail.",
    )
    labels: List[str] = Field(
        ...,
        description="[REQUIRED] At least one categorisation label. "
                    "Example: [\"onboarding\", \"v2\"]",
    )

    # ── Optional ──────────────────────────────────────────────────────────────
    prompt_handle: ValidatedPromptHandle = Field(
        None,
        description="[OPTIONAL] Unique slug for this prompt (collection name in MongoDB). "
                    "Auto-generated from agent_name + model_provider + model_name if omitted. "
                    "Allowed: lowercase letters, digits, underscores, hyphens. Max 128 chars.",
    )
    sub_agent: Optional[str] = Field(
        None,
        description="[OPTIONAL] Sub-agent identifier. Allows multiple prompt variants "
                    "under the same prompt_handle. Omit if not using sub-agents.",
    )
    description: Optional[str] = Field(
        None,
        description="[OPTIONAL] Human-readable description of what this prompt does.",
    )
    tags: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="[OPTIONAL] Arbitrary key-value tags for filtering or grouping. "
                    "Example: {\"team\": \"nlp\", \"experiment\": \"A\"}",
    )

    # ── Field-level validators ─────────────────────────────────────────────────
    @field_validator("prompt_data", mode="after")
    @classmethod
    def check_prompt_data(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        return validate_prompt_data_value(v)

    @field_validator("labels", mode="after")
    @classmethod
    def check_labels(cls, v: List[str]) -> List[str]:
        return validate_labels_value(v)

    @field_validator("sub_agent", mode="before")
    @classmethod
    def strip_sub_agent(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if isinstance(v, str) else v
