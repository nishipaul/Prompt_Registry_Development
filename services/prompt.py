from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from pymongo import MongoClient

from mongodb_db.database import DatabaseConfig
from mongodb_db.schemas import (
    PromptMetadata,
    create_env_prompt_model,
    create_log_model,
    create_user_temp_prompt_model,
    get_user_temp_collection_name,
)
from mongodb_db.settings import settings
from utils import build_search_query, format_prompt_response, generate_prompt_handle


class PromptService:
    _ttl_ensured: set = set()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def build_metadata(meta: Dict[str, Any]) -> PromptMetadata:
        """Construct a PromptMetadata document from a plain metadata dict."""
        return PromptMetadata(
            tenant_id=meta["tenant_id"],
            tenant_feature=meta["tenant_feature"],
            model_name=meta["model_name"],
            model_provider=meta["model_provider"],
            label=meta["label"],
            agent_name=meta["agent_name"],
            framework=meta.get("framework"),
            additional_metadata=meta.get("additional_metadata", {}),
        )

    @staticmethod
    def _get_env_collections(environment: str) -> List[str]:
        """Return all non-system collection names in an environment DB."""
        try:
            client = MongoClient(host=DatabaseConfig.MONGODB_HOST, port=DatabaseConfig.MONGODB_PORT)
            collections = [
                c for c in client[DatabaseConfig.get_db_name(environment)].list_collection_names()
                if not c.startswith("system.")
            ]
            client.close()
            return collections
        except Exception:
            return []

    @staticmethod
    def _ensure_collection_ttl(collection_name: str) -> None:
        if collection_name in PromptService._ttl_ensured:
            return
        try:
            client = MongoClient(host=DatabaseConfig.MONGODB_HOST, port=DatabaseConfig.MONGODB_PORT)
            coll = client[DatabaseConfig.DB_USER_TEMP][collection_name]
            has_ttl = any(
                v.get("expireAfterSeconds") is not None
                for v in coll.index_information().values()
            )
            if not has_ttl:
                coll.create_index("expires_at", expireAfterSeconds=0)
            client.close()
            PromptService._ttl_ensured.add(collection_name)
        except Exception:
            return

    @staticmethod
    def _not_found_detail(
        prompt_handle: str, environment: str, tenant_id: str, tenant_feature: str,
    ) -> Dict[str, Any]:
        """Standardised 'prompt handle not found' error response."""
        detail: Dict[str, Any] = {
            "success": False,
            "message": f"Prompt handle '{prompt_handle}' not found in {environment}.",
        }
        available = PromptService.get_available_prompt_handles(environment, tenant_id, tenant_feature)
        if available:
            detail["available_prompt_handles"] = available
            detail["hint"] = "Use one of the available prompt handles listed above."
        else:
            detail["hint"] = (
                f"No prompt handles found in '{environment}' for "
                f"tenant_id='{tenant_id}', tenant_feature='{tenant_feature}'."
            )
        return detail

    # ------------------------------------------------------------------
    # Sub-agent helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_existing_sub_agents(prompt_handle: str, environment: str) -> List[Dict[str, Any]]:
        """Return each distinct sub_agent with its latest version number."""
        PromptModel = create_env_prompt_model(prompt_handle, environment)
        pipeline = [
            {"$match": {"prompt_handle": prompt_handle}},
            {"$sort": {"version": -1}},
            {
                "$group": {
                    "_id": "$sub_agent",
                    "latest_version": {"$first": "$version"},
                    "prompt_data_preview": {"$first": "$prompt_data"},
                    "created_by": {"$first": "$created_by"},
                    "created_at": {"$first": "$created_at"},
                }
            },
            {"$sort": {"_id": 1}},
        ]
        try:
            return [
                {
                    "sub_agent": r["_id"],
                    "latest_version": r["latest_version"],
                    "prompt_data_preview": r.get("prompt_data_preview", {}),
                    "created_by": r.get("created_by"),
                    "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                }
                for r in PromptModel.objects.aggregate(pipeline)
            ]
        except Exception:
            return []

    @staticmethod
    def _validate_sub_agent(
        prompt_handle: str, sub_agent: str, environment: str,
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Return (True, None) if sub_agent exists or the collection is empty."""
        PromptModel = create_env_prompt_model(prompt_handle, environment)
        if PromptModel.objects(prompt_handle=prompt_handle, sub_agent=sub_agent).first():
            return True, None
        existing = PromptService._get_existing_sub_agents(prompt_handle, environment)
        if not existing:
            return True, None
        return False, {
            "message": f"sub_agent '{sub_agent}' not found in '{prompt_handle}' ({environment}).",
            "existing_sub_agents": existing,
            "hint": (
                "Fix the sub_agent name to match an existing one (version auto-increments), "
                "or supply a new name to create a new sub_agent."
            ),
        }

    # ------------------------------------------------------------------
    # Version helper
    # ------------------------------------------------------------------

    @staticmethod
    def _next_version(
        prompt_handle: str, environment: str, sub_agent: Optional[str] = None
    ) -> int:
        """Auto-increment version for a (prompt_handle, sub_agent) pair."""
        PromptModel = create_env_prompt_model(prompt_handle, environment)
        latest = (
            PromptModel.objects(prompt_handle=prompt_handle, sub_agent=sub_agent)
            .order_by("-version")
            .only("version")
            .first()
        )
        return (latest.version + 1) if latest else 1

    # ------------------------------------------------------------------
    # Commit (permanent)
    # ------------------------------------------------------------------

    @staticmethod
    def check_existing_prompt(
        prompt_handle: str, environment: str, sub_agent: Optional[str] = None,
    ) -> Tuple[bool, Optional[Dict]]:
        PromptModel = create_env_prompt_model(prompt_handle, environment)
        try:
            query: Dict[str, Any] = {"prompt_handle": prompt_handle}
            if sub_agent is not None:
                query["sub_agent"] = sub_agent
            existing = PromptModel.objects(**query).order_by("-version").first()
            return (True, format_prompt_response(existing)) if existing else (False, None)
        except Exception:
            return False, None

    @staticmethod
    def commit_prompt(validated_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Permanently commit a prompt to an environment DB.
        DB = environment name, Collection = prompt_handle. Version is always auto-incremented.
        """
        environment = validated_data["environment"]
        prompt_handle = validated_data["prompt_handle"]
        sub_agent = validated_data.get("sub_agent")
        PromptModel = create_env_prompt_model(prompt_handle, environment)

        is_new_sub_agent = bool(
            sub_agent
            and not PromptModel.objects(prompt_handle=prompt_handle, sub_agent=sub_agent).first()
        )
        version = PromptService._next_version(prompt_handle, environment, sub_agent)

        prompt = PromptModel(
            prompt_handle=prompt_handle,
            version=version,
            sub_agent=sub_agent,
            metadata=PromptService.build_metadata(validated_data["metadata"]),
            environment=environment,
            prompt_data=validated_data["prompt_data"],
            created_by=validated_data["user_email"],
            created_at=datetime.utcnow(),
            description=validated_data.get("description"),
            tags=validated_data.get("tags", {}),
        )
        prompt.save()

        return {
            "success": True,
            "message": f"Prompt committed successfully to {environment}",
            "prompt_handle": prompt_handle,
            "version": version,
            "sub_agent": sub_agent,
            "is_new_sub_agent": is_new_sub_agent,
            "environment": environment,
            "created_at": prompt.created_at,
            "committed_by": validated_data["user_email"],
        }

    # ------------------------------------------------------------------
    # Read / Search
    # ------------------------------------------------------------------

    @staticmethod
    def _format_temp_response(doc: Any) -> Dict[str, Any]:
        """Serialize a temp-collection document into the same shape as format_prompt_response."""
        meta = doc.metadata
        return {
            "prompt_handle": doc.prompt_handle,
            "version": doc.original_version,
            "sub_agent": None,
            "environment": "user_temp",
            "info": (
                f"Temp draft — expires {doc.expires_at.isoformat()}" if doc.expires_at else "Temp draft"
            ),
            "metadata": {
                "tenant_id": meta.tenant_id,
                "tenant_feature": meta.tenant_feature,
                "model_name": meta.model_name,
                "model_provider": meta.model_provider,
                "label": list(meta.label) if meta.label else [],
                "agent_name": meta.agent_name,
                "framework": meta.framework,
                "additional_metadata": meta.additional_metadata or {},
            },
            "prompt_data": doc.prompt_data,
            "labels": list(meta.label) if meta.label else [],
            "description": getattr(doc, "description", None),
            "tags": {},
            "created_by": doc.user_id,
            "created_at": doc.created_at,
            "updated_by": None,
            "updated_at": None,
        }

    @staticmethod
    def read_prompt(
        prompt_handle: str,
        environment: str,
        version: Optional[int] = None,
        sub_agent: Optional[str] = None,
    ) -> Optional[Any]:
        """Return one prompt dict (specific version) or a list (all versions). None if not found."""
        if environment == "user_temp":
            TempModel = create_user_temp_prompt_model(prompt_handle)
            try:
                docs = list(TempModel.objects(prompt_handle=prompt_handle).order_by("-created_at"))
                if not docs:
                    return None
                results = [PromptService._format_temp_response(d) for d in docs]
                if version is not None:
                    results = [r for r in results if r.get("version") == version]
                if not results:
                    return None
                return results[0] if len(results) == 1 else results
            except Exception:
                return None

        PromptModel = create_env_prompt_model(prompt_handle, environment)
        try:
            query: Dict[str, Any] = {"prompt_handle": prompt_handle}
            if sub_agent is not None:
                query["sub_agent"] = sub_agent
            if version is not None:
                query["version"] = version
                prompt = PromptModel.objects(**query).first()
                return format_prompt_response(prompt) if prompt else None
            prompts = PromptModel.objects(**query).order_by("-version")
            return [format_prompt_response(p) for p in prompts] or None
        except Exception:
            return None

    @staticmethod
    def get_available_prompt_handles(
        environment: str, tenant_id: str, tenant_feature: str,
    ) -> List[str]:
        """List prompt_handles in an environment matching the given tenant."""
        matching: List[str] = []
        for coll_name in PromptService._get_env_collections(environment):
            Model = create_env_prompt_model(coll_name, environment)
            try:
                if Model.objects(
                    metadata__tenant_id=tenant_id,
                    metadata__tenant_feature=tenant_feature,
                ).first():
                    matching.append(coll_name)
            except Exception:
                continue
        return matching

    @staticmethod
    def search_prompts(
        filters: Dict[str, Any], environment: str, prompt_handle: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search prompts in one collection (if prompt_handle given) or across all."""
        if prompt_handle:
            PromptModel = create_env_prompt_model(prompt_handle, environment)
            try:
                return [
                    format_prompt_response(p)
                    for p in PromptModel.objects(**build_search_query(filters)).order_by("-created_at")
                ]
            except Exception:
                return []

        query = build_search_query(filters)
        results: List[Dict[str, Any]] = []
        for coll_name in PromptService._get_env_collections(environment):
            Model = create_env_prompt_model(coll_name, environment)
            try:
                results.extend(
                    format_prompt_response(p)
                    for p in Model.objects(**query).order_by("-created_at")
                )
            except Exception:
                continue
        return results

    @staticmethod
    def get_all_versions(
        prompt_handle: str, environment: str, sub_agent: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        PromptModel = create_env_prompt_model(prompt_handle, environment)
        try:
            query: Dict[str, Any] = {"prompt_handle": prompt_handle}
            if sub_agent is not None:
                query["sub_agent"] = sub_agent
            return [
                format_prompt_response(p)
                for p in PromptModel.objects(**query).order_by("-version")
            ]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Save (temporary)
    # ------------------------------------------------------------------

    @staticmethod
    def save_temp_prompt(
        user_email: str,
        metadata: PromptMetadata,
        prompt_data: Dict[str, Any],
        prompt_handle: Optional[str] = None,
        original_environment: Optional[str] = None,
        original_version: Optional[int] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Upsert a prompt into the user's temporary collection.
        MongoDB TTL index on expires_at handles auto-expiry.
        """
        try:
            if not prompt_handle:
                prompt_handle = generate_prompt_handle(
                    metadata.agent_name, metadata.model_provider, metadata.model_name
                )

            TempModel = create_user_temp_prompt_model(prompt_handle)
            collection_name = get_user_temp_collection_name(prompt_handle)
            PromptService._ensure_collection_ttl(collection_name)

            retention_minutes = settings.TEMP_PROMPT_RETENTION_MINUTES
            created_at = datetime.utcnow()
            expires_at = created_at + timedelta(minutes=retention_minutes)

            existing = TempModel.objects(user_id=user_email, prompt_handle=prompt_handle).first()
            if existing:
                existing.prompt_data = prompt_data
                existing.metadata = metadata
                existing.description = description
                existing.expires_at = expires_at
                existing.save()
                action = "updated"
            else:
                TempModel(
                    user_id=user_email,
                    prompt_handle=prompt_handle,
                    metadata=metadata,
                    prompt_data=prompt_data,
                    original_environment=original_environment,
                    original_version=original_version,
                    description=description,
                    created_at=created_at,
                    expires_at=expires_at,
                ).save()
                action = "created"

            if retention_minutes >= 1440:
                retention_display = f"{retention_minutes / 1440:.1f} days"
            elif retention_minutes >= 60:
                retention_display = f"{retention_minutes / 60:.1f} hours"
            else:
                retention_display = f"{retention_minutes} minutes"

            return {
                "success": True,
                "message": f"Temporary prompt {action} in collection '{collection_name}'",
                "prompt_created": action == "created",
                "user_email": user_email,
                "prompt_handle": prompt_handle,
                "collection_name": collection_name,
                "prompt_data_saved": prompt_data,
                "description": description,
                "created_at": created_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "will_be_deleted_after": retention_display,
                "retention_minutes": retention_minutes,
                "note": (
                    "Temporary storage only. MongoDB TTL auto-deletes after expiry. "
                    "Use /commit to persist permanently."
                ),
            }
        except Exception as e:
            return {"success": False, "message": f"Error saving temporary prompt: {e}"}

    # ------------------------------------------------------------------
    # Update (read from env → save to temp)
    # ------------------------------------------------------------------

    @staticmethod
    def update_prompt(
        prompt_handle: str,
        environment: str,
        tenant_id: str,
        tenant_feature: str,
        updates: Dict[str, Any],
        user_email: Optional[str] = None,
        version: Optional[int] = None,
        sub_agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Read a prompt from an environment DB and save the modified version to temp."""
        PromptModel = create_env_prompt_model(prompt_handle, environment)
        try:
            query: Dict[str, Any] = {"prompt_handle": prompt_handle}
            if sub_agent is not None:
                query["sub_agent"] = sub_agent
            all_docs = list(PromptModel.objects(**query).order_by("-version"))

            if not all_docs:
                return PromptService._not_found_detail(
                    prompt_handle, environment, tenant_id, tenant_feature
                )

            available_versions = [d.version for d in all_docs]

            if version is None:
                return {
                    "success": False,
                    "message": "Version is required for update.",
                    "available_versions": available_versions,
                    "hint": "Provide a valid version number to update.",
                }

            existing = next((d for d in all_docs if d.version == version), None)
            if not existing:
                return {
                    "success": False,
                    "message": f"Version {version} not found for '{prompt_handle}' in {environment}.",
                    "available_versions": available_versions,
                    "hint": "Provide one of the available versions listed above.",
                }

            result = PromptService.save_temp_prompt(
                user_email=user_email or "unknown",
                metadata=existing.metadata,
                prompt_data=updates.get("prompt_data", existing.prompt_data),
                prompt_handle=prompt_handle,
                original_environment=environment,
                original_version=existing.version,
                description=updates.get("description", existing.description),
            )

            if result["success"]:
                result["message"] = (
                    f"Prompt read from {environment} (v{existing.version}) and saved to "
                    "temporary collection. Use /commit to save permanently."
                )
                result["original_version"] = existing.version
                result["original_environment"] = environment

            return result
        except Exception as e:
            return {"success": False, "message": f"Error updating prompt: {e}"}

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    @staticmethod
    def delete_prompt(
        prompt_handle: str,
        environment: str,
        tenant_id: str,
        tenant_feature: str,
        version: Optional[int] = None,
        sub_agent: Optional[str] = None,
        user_email: Optional[str] = None,
        deletion_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Delete a prompt version and write an audit log entry."""
        PromptModel = create_env_prompt_model(prompt_handle, environment)
        try:
            query: Dict[str, Any] = {"prompt_handle": prompt_handle}
            if sub_agent is not None:
                query["sub_agent"] = sub_agent
            all_docs = list(PromptModel.objects(**query).order_by("-version"))

            if not all_docs:
                return PromptService._not_found_detail(
                    prompt_handle, environment, tenant_id, tenant_feature
                )

            available_versions = [d.version for d in all_docs]

            if version is None:
                return {
                    "success": False,
                    "message": "Version is required for delete.",
                    "available_versions": available_versions,
                    "hint": "Provide a valid version number to delete.",
                }

            prompt_to_delete = next((d for d in all_docs if d.version == version), None)
            if not prompt_to_delete:
                return {
                    "success": False,
                    "message": f"Version {version} not found for '{prompt_handle}' in {environment}.",
                    "available_versions": available_versions,
                    "hint": "Provide one of the available versions listed above.",
                }

            deleted_by = user_email or "unknown"
            create_log_model(prompt_handle, environment)(
                prompt_handle=prompt_to_delete.prompt_handle,
                version=prompt_to_delete.version,
                sub_agent=prompt_to_delete.sub_agent,
                environment=environment,
                metadata=prompt_to_delete.metadata,
                prompt_data=prompt_to_delete.prompt_data,
                original_created_by=prompt_to_delete.created_by,
                original_created_at=prompt_to_delete.created_at,
                deleted_by=deleted_by,
                deleted_at=datetime.utcnow(),
                deletion_reason=deletion_reason,
                additional_data={
                    "description": prompt_to_delete.description,
                    "tags": prompt_to_delete.tags,
                },
            ).save()

            deleted_version = prompt_to_delete.version
            deleted_sub_agent = prompt_to_delete.sub_agent
            prompt_to_delete.delete()

            return {
                "success": True,
                "message": f"Prompt deleted from {environment} and logged",
                "deleted_prompt_handle": prompt_handle,
                "deleted_version": deleted_version,
                "deleted_environment": environment,
                "deleted_sub_agent": deleted_sub_agent,
                "deleted_by": deleted_by,
                "logged_at": datetime.utcnow(),
                "metadata": {
                    "tenant_id": prompt_to_delete.metadata.tenant_id,
                    "tenant_feature": prompt_to_delete.metadata.tenant_feature,
                    "model_name": prompt_to_delete.metadata.model_name,
                    "model_provider": prompt_to_delete.metadata.model_provider,
                    "label": list(prompt_to_delete.metadata.label),
                    "agent_name": prompt_to_delete.metadata.agent_name,
                    "framework": prompt_to_delete.metadata.framework,
                    "additional_metadata": prompt_to_delete.metadata.additional_metadata or {},
                },
            }
        except Exception as e:
            return {"success": False, "message": f"Error deleting prompt: {e}"}
