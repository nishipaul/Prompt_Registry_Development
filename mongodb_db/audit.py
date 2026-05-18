from __future__ import annotations

from datetime import datetime

from mongoengine import (
    DateTimeField,
    DictField,
    Document,
    IntField,
    StringField,
)

_AUDIT_CACHE: dict = {}


def create_audit_log_model(environment: str) -> type:
    """
    Central audit log for ALL CRUD operations in one environment.

    DB alias  : <environment>_logs   (e.g. development_logs)
    Collection: operation_audit_log  (single collection per environment)

    Every operation — commit, save, read, search, update, delete — writes
    one entry so the full lifecycle of every prompt is traceable.
    """
    env = environment.lower()
    if env in _AUDIT_CACHE:
        return _AUDIT_CACHE[env]

    attrs = {
        # What happened
        "operation":      StringField(required=True),   # commit|save|read|search|update|delete|versions
        "status":         StringField(required=True, default="success"),   # success|failure
        # Who did it
        "user_email":     StringField(),
        # On what
        "prompt_handle":  StringField(required=True),
        "environment":    StringField(required=True),
        "version":        IntField(),
        "sub_agent":      StringField(),
        # When / how long
        "performed_at":   DateTimeField(default=datetime.utcnow),
        "duration_ms":    IntField(),
        # Extra context (request snapshot, result summary, error)
        "detail":         DictField(),
        "error":          StringField(),
        "meta": {
            "collection": "operation_audit_log",
            "db_alias":   f"{env}_logs",
            "indexes": [
                "operation",
                "prompt_handle",
                "user_email",
                "-performed_at",
                ("environment", "prompt_handle", "-performed_at"),
                ("user_email", "-performed_at"),
            ],
        },
    }

    model = type(f"AuditLog_{env}", (Document,), attrs)
    _AUDIT_CACHE[env] = model
    return model
