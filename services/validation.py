from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from schemas import validate_email_value, validate_environment_value
from utils.helpers import generate_prompt_handle
from utils.helpers import _clean_text


class ValidationService:

    @staticmethod
    def resolve_commit_data(request) -> Dict[str, Any]:
        """
        Resolve business-logic fields and serialize a Pydantic-validated
        CommitPromptRequest into a dict ready for the persistence layer.

        Field-level validation (environment, email, required fields) is
        already enforced by Pydantic — this method handles only
        prompt_handle resolution and serialization.
        """
        user_handle = getattr(request, "prompt_handle", None)
        prompt_handle = (
            _clean_text(user_handle.strip())
            if user_handle and user_handle.strip()
            else generate_prompt_handle(
                request.metadata.agent_name,
                request.metadata.model_provider,
                request.metadata.model_name,
            )
        )

        return {
            "prompt_handle": prompt_handle,
            "environment": request.environment,
            "sub_agent": getattr(request, "sub_agent", None),
            "metadata": request.metadata.model_dump(),
            "prompt_data": request.prompt_data,
            "description": request.description or None,
            "tags": request.tags or {},
            "user_email": request.user_email,
        }

    @staticmethod
    def validate_environment(environment: str) -> Tuple[bool, Optional[str]]:
        """Validate a raw environment string (e.g. from query/path params)."""
        if not environment:
            return False, "Environment is required"
        try:
            validate_environment_value(environment)
            return True, None
        except ValueError as exc:
            return False, str(exc)

    @staticmethod
    def validate_user_email(user_email: Optional[str]) -> Tuple[bool, Optional[str]]:
        """Validate a raw email string (e.g. from query/path params)."""
        if not user_email:
            return False, "user_email is required"
        try:
            validate_email_value(user_email)
            return True, None
        except ValueError as exc:
            return False, str(exc)
