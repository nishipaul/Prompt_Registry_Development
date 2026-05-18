from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, status

from schemas import (
    VALID_ENVIRONMENTS,
    CommitPromptRequest,
    CommitResponseSchema,
    DeletePromptRequest,
    DeleteResponseSchema,
    OperationMetadataSchema,
    ReadPromptRequest,
    SaveTempPromptRequest,
    SearchPromptRequest,
    SearchResponseSchema,
    UpdatePromptRequest,
    VersionsRequest,
)
from services import PromptService, ValidationService

router = APIRouter(prefix="/api/v1/prompts", tags=["prompts"])


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    return {
        "status": "healthy",
        "service": "Prompt Management System",
        "available_environments": VALID_ENVIRONMENTS,
        "endpoints": {
            "save": "Temporary storage (auto-deleted by MongoDB TTL)",
            "commit": "Permanent storage in environment database (version auto-incremented)",
            "read": "Read from environment database (latest version by default)",
            "search": "Search by metadata in environment database",
            "update": "Read from env → save to temp",
            "delete": "Delete from env (audit logged)",
        },
    }


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------


@router.post("/validate", response_model=Dict[str, Any])
async def validate_commit_request(request: CommitPromptRequest) -> Dict[str, Any]:
    """Dry-run validate a commit request without persisting anything."""
    validated_data = ValidationService.resolve_commit_data(request)
    return {
        "success": True,
        "message": "Validation passed",
        "validated_data": {
            "prompt_handle": validated_data["prompt_handle"],
            "environment": validated_data["environment"],
            "user_email": validated_data["user_email"],
            "sub_agent": validated_data.get("sub_agent"),
        },
    }


# ---------------------------------------------------------------------------
# Commit (permanent)
# ---------------------------------------------------------------------------


@router.post("/commit", response_model=CommitResponseSchema)
async def commit_prompt(request: CommitPromptRequest) -> CommitResponseSchema:
    """
    Commit a prompt permanently to an environment database.

    Version is auto-incremented per (prompt_handle, sub_agent) pair.
    Available environments: development, test, uat, production.
    """
    validated_data = ValidationService.resolve_commit_data(request)
    sub_agent = request.sub_agent.strip() if request.sub_agent else None
    validated_data["sub_agent"] = sub_agent

    try:
        result = PromptService.commit_prompt(validated_data)

        other_sub_agents = None
        if sub_agent and result.get("is_new_sub_agent"):
            existing = PromptService._get_existing_sub_agents(
                validated_data["prompt_handle"], validated_data["environment"],
            )
            others = [s for s in existing if s["sub_agent"] != sub_agent]
            if others:
                other_sub_agents = others
                result["info"] = (
                    f"New sub_agent '{sub_agent}' created. "
                    "Other existing sub_agents in this collection are listed below."
                )

        return CommitResponseSchema(
            prompt_handle=result["prompt_handle"],
            version=result["version"],
            environment=result["environment"],
            metadata=request.metadata,
            sub_agent=result.get("sub_agent"),
            info=result.get("info"),
            success=result["success"],
            message=result["message"],
            created_at=result["created_at"],
            created_by=result["committed_by"],
            is_new_sub_agent=result.get("is_new_sub_agent"),
            other_sub_agents=other_sub_agents,
            operation=OperationMetadataSchema(
                operation_type="commit",
                performed_by=validated_data["user_email"],
            ),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error committing prompt: {e}",
        )


# ---------------------------------------------------------------------------
# Save (temporary)
# ---------------------------------------------------------------------------


@router.post("/save", response_model=Dict[str, Any])
async def save_temp_prompt(request: SaveTempPromptRequest) -> Dict[str, Any]:
    """
    Save a prompt to a temporary collection (auto-deleted by MongoDB TTL).
    Use /commit to persist permanently.
    """
    result = PromptService.save_temp_prompt(
        user_email=request.user_email,
        metadata=PromptService.build_metadata(request.metadata.model_dump()),
        prompt_data=request.prompt_data,
        prompt_handle=request.prompt_handle,
        original_environment=request.original_environment,
        original_version=request.original_version,
        description=request.description,
    )

    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result["message"],
        )
    return result


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


@router.post("/read")
async def read_prompt(request: ReadPromptRequest) -> Any:
    """
    Read prompt(s) from an environment database.

    - Omit version → all versions for the prompt_handle.
    - Supply version → that single version.
    - Supply sub_agent → filter to that sub_agent.
    """
    if request.sub_agent is not None:
        valid, error_payload = PromptService._validate_sub_agent(
            request.prompt_handle, request.sub_agent, request.environment,
        )
        if not valid:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error_payload)

    result = PromptService.read_prompt(
        request.prompt_handle, request.environment, request.version, request.sub_agent,
        user_email=None,  # read is unauthenticated; audit still records the handle+env
    )

    if not result:
        detail: Dict[str, Any] = {
            "message": (
                f"Prompt handle '{request.prompt_handle}' not found in {request.environment}"
            ),
        }
        available_handles = PromptService.get_available_prompt_handles(
            request.environment, request.tenant_id, request.tenant_feature,
        )
        if available_handles:
            detail["available_prompt_handles"] = available_handles
            detail["hint"] = "Use one of the available prompt handles listed above."
        else:
            detail["hint"] = (
                f"No prompt handles found in '{request.environment}' "
                f"for tenant_id='{request.tenant_id}', tenant_feature='{request.tenant_feature}'."
            )
        if request.version is not None:
            all_versions = PromptService.get_all_versions(
                request.prompt_handle, request.environment, request.sub_agent,
            )
            if all_versions:
                detail["available_versions"] = [v["version"] for v in all_versions]
                detail["message"] = (
                    f"Version {request.version} not found for '{request.prompt_handle}' "
                    f"in {request.environment}. Available versions listed below."
                )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)

    if isinstance(result, list):
        return {"total_results": len(result), "prompts": result}
    return result


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@router.post("/search", response_model=SearchResponseSchema)
async def search_prompts(request: SearchPromptRequest) -> SearchResponseSchema:
    """
    Search prompts by metadata filters in an environment database.

    Mandatory: environment, tenant_id, tenant_feature, agent_name, model_provider, model_name.
    Optional: prompt_handle, label, sub_agent.
    """
    filters: Dict[str, Any] = {
        "agent_name":     request.agent_name,
        "model_provider": request.model_provider,
        "model_name":     request.model_name,
        "tenant_id":      request.tenant_id,
        "tenant_feature": request.tenant_feature,
    }
    if request.label:          filters["label"]          = request.label
    if request.sub_agent:      filters["sub_agent"]      = request.sub_agent
    if request.created_by:     filters["created_by"]     = request.created_by
    if request.version:        filters["version"]        = request.version
    if request.created_after:  filters["created_after"]  = request.created_after
    if request.created_before: filters["created_before"] = request.created_before

    prompts = PromptService.search_prompts(
        filters, request.environment,
        prompt_handle=request.prompt_handle,
        user_email=None,
    )
    return SearchResponseSchema(
        total_results=len(prompts),
        prompts=prompts,
        operation=OperationMetadataSchema(operation_type="search"),
    )


# ---------------------------------------------------------------------------
# Update (read → temp)
# ---------------------------------------------------------------------------


@router.post("/update", response_model=Dict[str, Any])
async def update_prompt(request: UpdatePromptRequest) -> Dict[str, Any]:
    """
    Read a prompt from an environment DB and save the modified version to temp.
    Use /commit afterwards to persist permanently.
    """
    updates: Dict[str, Any] = {}
    if request.prompt_data:
        updates["prompt_data"] = request.prompt_data
    if request.description:
        updates["description"] = request.description
    if request.tags:
        updates["tags"] = request.tags

    result = PromptService.update_prompt(
        prompt_handle=request.prompt_handle,
        environment=request.environment,
        tenant_id=request.tenant_id,
        tenant_feature=request.tenant_feature,
        updates=updates,
        user_email=request.user_email,
        version=request.version,
        sub_agent=request.sub_agent,
    )

    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={k: v for k, v in result.items() if k != "success"},
        )
    return result


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@router.post("/delete", response_model=DeleteResponseSchema)
async def delete_prompt(request: DeletePromptRequest) -> DeleteResponseSchema:
    """
    Delete a prompt version from an environment database (audit logged).

    Version must be provided. If wrong, available versions are returned.
    """
    result = PromptService.delete_prompt(
        prompt_handle=request.prompt_handle,
        environment=request.environment,
        tenant_id=request.tenant_id,
        tenant_feature=request.tenant_feature,
        version=request.version,
        sub_agent=request.sub_agent,
        user_email=request.user_email,
        deletion_reason=request.deletion_reason,
    )

    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={k: v for k, v in result.items() if k != "success"},
        )

    return DeleteResponseSchema(
        success=result["success"],
        message=result["message"],
        deleted_prompt_handle=result["deleted_prompt_handle"],
        deleted_version=result["deleted_version"],
        deleted_environment=result["deleted_environment"],
        deleted_sub_agent=result.get("deleted_sub_agent"),
        metadata=result["metadata"],
        operation=OperationMetadataSchema(
            operation_type="delete",
            performed_by=result["deleted_by"],
        ),
    )


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


@router.post("/versions", response_model=SearchResponseSchema)
async def get_all_versions(request: VersionsRequest) -> SearchResponseSchema:
    """
    List all versions of a prompt handle.

    Mandatory: prompt_handle, environment, tenant_id, tenant_feature.
    Optional: sub_agent.
    """
    versions = PromptService.get_all_versions(
        request.prompt_handle, request.environment,
        sub_agent=request.sub_agent,
        user_email=None,
    )
    if not versions:
        detail: Dict[str, Any] = {
            "message": (
                f"No versions found for '{request.prompt_handle}' in {request.environment}."
            ),
        }
        available_handles = PromptService.get_available_prompt_handles(
            request.environment, request.tenant_id, request.tenant_feature,
        )
        if available_handles:
            detail["available_prompt_handles"] = available_handles
            detail["hint"] = "Use one of the available prompt handles listed above."
        else:
            detail["hint"] = (
                f"No prompt handles found in '{request.environment}' "
                f"for tenant_id='{request.tenant_id}', tenant_feature='{request.tenant_feature}'."
            )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)

    return SearchResponseSchema(
        total_results=len(versions),
        prompts=versions,
        operation=OperationMetadataSchema(operation_type="versions"),
    )
