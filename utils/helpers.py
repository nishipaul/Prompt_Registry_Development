from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _clean_text(value: str) -> str:
    """Replace non-alphanumeric characters with underscores and collapse runs."""
    value = re.sub(r"[^a-zA-Z0-9_]", "_", value.lower())
    return re.sub(r"_+", "_", value).strip("_")


# ---------------------------------------------------------------------------
# Public utilities
# ---------------------------------------------------------------------------


def generate_prompt_handle(
    agent_name: str, model_provider: str, model_name: str
) -> str:
    """
    Build a default prompt handle: <agent>_<provider>_<model>.
    Used when the caller does not supply an explicit prompt_handle.
    """
    return "_".join(
        _clean_text(part) for part in (agent_name, model_provider, model_name)
    )


def get_next_version(existing_versions: List[int]) -> int:
    """Return the next sequential version number given existing ones."""
    return max(existing_versions, default=0) + 1


def build_search_query(filters: Dict[str, Any]) -> Dict[str, Any]:
    """Translate API filter keys to MongoEngine field paths, dropping empty values."""
    field_mapping: Dict[str, str] = {
        "agent_name": "metadata__agent_name",
        "model_provider": "metadata__model_provider",
        "model_name": "metadata__model_name",
        "tenant_id": "metadata__tenant_id",
        "tenant_feature": "metadata__tenant_feature",
        "label": "metadata__label",
        "environment": "environment",
        "prompt_handle": "prompt_handle",
        "sub_agent": "sub_agent",
        "created_by": "created_by",
    }
    return {
        field_mapping.get(key, key): value
        for key, value in filters.items()
        if value is not None and value != ""
    }


def format_prompt_response(prompt_doc: Any) -> Dict[str, Any]:
    """Serialize a MongoEngine prompt document to an API-safe dict."""
    return {
        "prompt_handle": prompt_doc.prompt_handle,
        "version": prompt_doc.version,
        "sub_agent": prompt_doc.sub_agent,
        "environment": prompt_doc.environment,
        "info": getattr(prompt_doc, "info", None),
        "metadata": {
            "tenant_id": prompt_doc.metadata.tenant_id,
            "tenant_feature": prompt_doc.metadata.tenant_feature,
            "model_name": prompt_doc.metadata.model_name,
            "model_provider": prompt_doc.metadata.model_provider,
            "label": prompt_doc.metadata.label,
            "agent_name": prompt_doc.metadata.agent_name,
            "framework": prompt_doc.metadata.framework,
            "additional_metadata": prompt_doc.metadata.additional_metadata or {},
        },
        "prompt_data": prompt_doc.prompt_data,
        "labels": list(prompt_doc.metadata.label) if prompt_doc.metadata else [],
        "description": getattr(prompt_doc, "description", None),
        "tags": getattr(prompt_doc, "tags", None) or {},
        "created_by": prompt_doc.created_by,
        "created_at": prompt_doc.created_at,
        "updated_by": prompt_doc.updated_by,
        "updated_at": prompt_doc.updated_at,
    }
