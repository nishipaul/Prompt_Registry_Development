from __future__ import annotations

from datetime import datetime

from mongoengine import (
    DateTimeField,
    DictField,
    Document,
    EmbeddedDocument,
    EmbeddedDocumentField,
    IntField,
    ListField,
    StringField,
)


class PromptMetadata(EmbeddedDocument):
    """Embedded document for prompt metadata."""

    tenant_id = StringField(required=True)
    tenant_feature = StringField(required=True)
    model_name = StringField(required=True)
    model_provider = StringField(required=True)
    label = ListField(StringField(), required=True)
    agent_name = StringField(required=True)
    framework = StringField()
    additional_metadata = DictField()


# ---------------------------------------------------------------------------
# Model caches — one entry per (prompt_handle, environment) pair
# ---------------------------------------------------------------------------

_ENV_MODEL_CACHE: dict = {}
_TEMP_MODEL_CACHE: dict = {}
_LOG_MODEL_CACHE: dict = {}


def _sanitize_collection_name(name: str) -> str:
    return name.replace("-", "_").replace(" ", "_")


def get_user_temp_collection_name(prompt_handle: str) -> str:
    return _sanitize_collection_name(prompt_handle)


# ---------------------------------------------------------------------------
# Dynamic model factories
# ---------------------------------------------------------------------------


def create_env_prompt_model(prompt_handle: str, environment: str) -> type:
    """
    Return a MongoEngine Document class that maps to:
      DB         = environment alias (development / test / uat / production)
      Collection = sanitized prompt_handle
    Models are cached to avoid re-creating the same class on every call.
    """
    prompt_handle = prompt_handle.lower().strip()
    cache_key = (prompt_handle, environment.lower())
    if cache_key in _ENV_MODEL_CACHE:
        return _ENV_MODEL_CACHE[cache_key]

    collection_name = _sanitize_collection_name(prompt_handle)
    db_alias = environment.lower()

    attrs = {
        "prompt_handle": StringField(required=True),
        "version": IntField(required=True, default=1),
        "sub_agent": StringField(),
        "metadata": EmbeddedDocumentField(PromptMetadata, required=True),
        "environment": StringField(required=True, default=db_alias),
        "prompt_data": DictField(required=True),
        "created_by": StringField(required=True),
        "created_at": DateTimeField(default=datetime.utcnow),
        "updated_by": StringField(),
        "updated_at": DateTimeField(),
        "description": StringField(),
        "tags": DictField(),
        "meta": {
            "collection": collection_name,
            "db_alias": db_alias,
            "indexes": [
                "prompt_handle",
                "sub_agent",
                "metadata.agent_name",
                "metadata.tenant_id",
                "metadata.tenant_feature",
                "created_at",
                {"fields": ["prompt_handle", "sub_agent", "version"], "unique": True},
            ],
        },
    }

    model = type(f"Prompt_{db_alias}_{collection_name}", (Document,), attrs)
    _ENV_MODEL_CACHE[cache_key] = model
    return model


def create_user_temp_prompt_model(prompt_handle: str) -> type:
    """
    Return a Document class for temporary user-specific storage.
    TTL cleanup is handled by MongoDB via the expires_at index.
    """
    collection_name = _sanitize_collection_name(prompt_handle)
    if collection_name in _TEMP_MODEL_CACHE:
        return _TEMP_MODEL_CACHE[collection_name]

    attrs = {
        "user_id": StringField(required=True),
        "prompt_handle": StringField(required=True),
        "metadata": EmbeddedDocumentField(PromptMetadata, required=True),
        "prompt_data": DictField(required=True),
        "original_environment": StringField(),
        "original_version": IntField(),
        "created_at": DateTimeField(default=datetime.utcnow),
        "expires_at": DateTimeField(required=True),
        "description": StringField(),
        "meta": {
            "collection": collection_name,
            "db_alias": "user_temp",
            "indexes": [
                "user_id",
                "prompt_handle",
                ("user_id", "prompt_handle"),
            ],
        },
    }

    model = type(f"TempPrompt_{collection_name}", (Document,), attrs)
    _TEMP_MODEL_CACHE[collection_name] = model
    return model


def create_log_model(prompt_handle: str, environment: str) -> type:
    """
    Return a Document class for deletion audit logs:
      DB         = <environment>_logs alias  (e.g. development_logs)
      Collection = sanitized prompt_handle
    """
    cache_key = (prompt_handle, environment.lower())
    if cache_key in _LOG_MODEL_CACHE:
        return _LOG_MODEL_CACHE[cache_key]

    collection_name = _sanitize_collection_name(prompt_handle)
    logs_alias = f"{environment.lower()}_logs"

    attrs = {
        "prompt_handle": StringField(required=True),
        "version": IntField(required=True),
        "sub_agent": StringField(),
        "environment": StringField(required=True),
        "metadata": EmbeddedDocumentField(PromptMetadata, required=True),
        "prompt_data": DictField(required=True),
        "original_created_by": StringField(),
        "original_created_at": DateTimeField(),
        "deleted_by": StringField(required=True),
        "deleted_at": DateTimeField(default=datetime.utcnow),
        "deletion_reason": StringField(),
        "additional_data": DictField(),
        "meta": {
            "collection": collection_name,
            "db_alias": logs_alias,
            "indexes": ["prompt_handle", "version", "deleted_at", "deleted_by"],
        },
    }

    model = type(f"PromptLog_{environment}_{collection_name}", (Document,), attrs)
    _LOG_MODEL_CACHE[cache_key] = model
    return model
