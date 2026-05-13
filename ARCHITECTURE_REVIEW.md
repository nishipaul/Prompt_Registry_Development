# Architecture Review — Prompt Management Service
> Assessed: 2026-05-13 | Reviewer: Principal Engineer perspective

---

## 1. Executive Summary

The codebase has a **solid structural foundation** — clean layering, well-typed schemas, centralised validation, and proper audit machinery. Several production-grade decisions (Pydantic v2 `Annotated` types, `OperationMetadataSchema` on every response, TTL-backed temp storage, per-environment audit logs) reflect real product thinking.

However, it is **not yet shippable to production** as-is. The gaps are not cosmetic — they are in authentication, observability, error handling, data isolation, and concurrency safety. The section below classifies every finding by priority.

---

## 2. What Is in Good Shape

| Area | Assessment |
|------|------------|
| **Schema layer** | `Annotated[str, AfterValidator(...)]` pattern centralises all validation in one place; zero duplication across request classes. Production-grade. |
| **Response envelope** | `OperationMetadataSchema` on every mutating response gives audit traceability by design. |
| **Schema organisation** | `schemas/requests/` and `schemas/responses/` split by operation, one file each. Easy to navigate and extend. |
| **Validation service** | `ValidationService.resolve_commit_data` cleanly separates business-logic resolution from Pydantic field validation. Correct separation of concerns. |
| **Temp storage design** | MongoDB TTL index approach for auto-expiry is the right tool. `_ensure_collection_ttl` + background cleanup thread covers both the index and empty-collection hygiene. |
| **Audit log on delete** | Separate `<env>_logs` database per environment is a good pattern — audit data survives the operational DB. |
| **Settings** | `pydantic-settings` `BaseSettings` with `.env` support and typed fields is production-standard config management. |
| **MongoEngine model factory** | `create_env_prompt_model` / `create_log_model` with model caching avoids re-creating classes on every call. |
| **`lifespan` hook** | Proper startup/shutdown lifecycle — connects DBs, ensures TTL indexes, starts cleanup thread, and tears everything down cleanly. |
| **Folder layout** | `api/`, `services/`, `schemas/`, `mongodb_db/`, `utils/` separation makes each layer findable. |

---

## 3. Critical Issues — Must Fix Before Production (P0)

### 3.1 No Authentication or Authorisation
**File:** `api/routers.py`

Every endpoint is open. Any caller can read, overwrite, or delete any tenant's prompts. There is no API key, JWT, OAuth2, or even a shared secret.

**Required:** Add FastAPI `Depends(verify_api_key)` or `Depends(get_current_user)` on all mutating endpoints. For internal services, a signed JWT or HMAC-signed request header is standard. At minimum, add `X-API-Key` middleware before any deployment.

---

### 3.2 Silent Exception Swallowing Everywhere
**Files:** `services/prompt.py` (11 methods), `mongodb_db/database.py`

Pattern found throughout:
```python
except Exception:
    return []   # or return None / return {}
```

This silently hides database timeouts, schema errors, query failures, and connection pool exhaustion. In production you will have incidents with no trace of the cause.

**Required:** All exceptions must be logged at `ERROR` level before being swallowed or re-raised. Temporary failures (network) should be distinguished from programming errors (wrong field names). Use structured logging (see §3.3).

---

### 3.3 No Structured Logging
**Files:** All

There is not a single `import logging` in the codebase. No request IDs are injected into log context. No DB errors are recorded. No operation timing is measured.

**Required:**
```python
import logging
logger = logging.getLogger(__name__)
```
Use `structlog` or configure `logging` with JSON formatter for production. Log at entry and exit of every service method with `prompt_handle`, `environment`, `user_email`, and `request_id` in context. Wire `OperationMetadataSchema.request_id` to a middleware that injects `X-Request-ID` per request.

---

### 3.4 `prompt_handle` Is Not Tenant-Scoped — Cross-Tenant Data Collision
**Files:** `services/prompt.py`, `mongodb_db/schemas.py`

The auto-generated `prompt_handle` is `{agent_name}_{model_provider}_{model_name}`. Two different tenants with the same agent and model will write to **the same MongoDB collection**. Tenant A can read Tenant B's prompts by knowing the handle.

**Required:** Either:
- Include `tenant_id` in the collection name: `{tenant_id}_{agent_name}_{model_provider}_{model_name}`
- Or enforce strict tenant filtering on every query (query always includes `metadata__tenant_id=tenant_id`)

Currently `read_prompt` does NOT filter by `tenant_id` — it only uses `prompt_handle` and optionally `sub_agent`. Any caller who knows a handle can read across tenants.

---

### 3.5 Version Assignment Race Condition
**File:** `services/prompt.py` — `_next_version` + `commit_prompt`

```python
version = PromptService._next_version(...)   # READ max version
prompt = PromptModel(version=version, ...)
prompt.save()                                # WRITE — no atomic guarantee
```

Two concurrent commits for the same `(prompt_handle, sub_agent)` will both read the same `max_version`, both assign the same next version, and one will fail with a MongoEngine `NotUniqueError` at save time. The caller receives a raw 500 with the exception message.

**Required:** Wrap in a retry loop with `NotUniqueError` handling, or use MongoDB `findOneAndUpdate` with `$inc` on a version counter document to atomically increment the version.

---

### 3.6 Internal Error Details Exposed to Callers
**File:** `api/routers.py` — multiple endpoints

```python
raise HTTPException(
    status_code=500,
    detail=f"Error committing prompt: {e}",   # leaks stack info, query details
)
```

Exception messages leak file paths, MongoDB query strings, and internal state to API consumers.

**Required:** Log the full exception internally, return a generic message externally:
```python
logger.error("commit_prompt failed", exc_info=True, extra={"prompt_handle": ...})
raise HTTPException(status_code=500, detail="Internal error. See server logs.")
```

---

### 3.7 `save_temp_prompt` Accepts `None` for `user_id` — Guaranteed Runtime Failure
**Files:** `api/routers.py`, `services/prompt.py`

`SaveTempPromptRequest.user_email` is `OptionalValidatedEmail` — can be `None`. This flows into `PromptService.save_temp_prompt(user_email=...)` and lands at:
```python
TempModel(user_id=user_email, ...)  # user_id is StringField(required=True)
```
MongoEngine will raise `ValidationError` at save time with an opaque message.

**Required:** Either make `user_email` required on `SaveTempPromptRequest`, or set a default `"anonymous"` value before the DB call, and document the intent explicitly.

---

## 4. High Priority Issues — Fix Within First Sprint (P1)

### 4.1 No Pagination on Search and Versions
**File:** `services/prompt.py` — `search_prompts`, `get_all_versions`

Both return all matching documents with no limit. A prompt handle with 500 versions will return 500 documents in one response. Cross-collection search with many handles can return thousands.

**Required:** Add `limit: int = 50` and `offset: int = 0` (or `page`/`page_size`) to `SearchPromptRequest`, `VersionsRequest`, and the `SearchResponseSchema`. Apply `.skip(offset).limit(limit)` in the MongoEngine queries.

---

### 4.2 No Health-Check DB Ping
**File:** `api/routers.py` — `/health`

The health endpoint returns `{"status": "healthy"}` unconditionally. A load balancer or Kubernetes readiness probe relying on this endpoint will route traffic to a pod with a broken MongoDB connection.

**Required:**
```python
@router.get("/health")
async def health_check():
    try:
        # Ping any lightweight collection
        from mongoengine.connection import get_connection
        get_connection("development").server_info()
        db_status = "connected"
    except Exception:
        db_status = "unreachable"
    return {"status": "healthy" if db_status == "connected" else "degraded", "db": db_status}
```

---

### 4.4 `datetime.utcnow()` Deprecated
**Files:** `mongodb_db/schemas.py`, `services/prompt.py`

`datetime.utcnow()` has been deprecated since Python 3.12. It returns a naïve datetime with no timezone info, which causes ambiguity in any multi-timezone deployment.

**Required:** Replace with `datetime.now(timezone.utc)` everywhere. Also update `DateTimeField` defaults in MongoEngine schemas to use `lambda: datetime.now(timezone.utc)`.

---

### 4.5 `CommitPromptRequest` Has Redundant `labels` Field
**File:** `schemas/requests/commit.py`

`CommitPromptRequest` has both `labels: List[str]` at the top level AND `metadata: PromptMetadataSchema` which contains `label: List[str]`. It is unclear which one is the source of truth. `ValidationService.resolve_commit_data` uses `request.metadata.model_dump()` which carries `label`, not `labels`. The top-level `labels` field is never used.

**Required:** Remove `labels` from `CommitPromptRequest`. The canonical source is `metadata.label`.

---

### 4.6 `_get_env_collections` Opens a New `MongoClient` on Every Call
**File:** `services/prompt.py`

`_get_env_collections` and `_ensure_collection_ttl` each create a raw `MongoClient` independently of the MongoEngine connection pool. Every search across collections (the default code path when `prompt_handle` is not provided) opens a new TCP connection.

**Required:** Cache the `MongoClient` or use the MongoEngine connection: `from mongoengine.connection import get_db`. This also applies to the DB-level client in `DatabaseConfig`.

---

### 4.7 `read_prompt` Doesn't Filter by Tenant
**File:** `services/prompt.py`

`read_prompt` queries only by `prompt_handle`, `sub_agent`, and `version`. `tenant_id` and `tenant_feature` from `ReadPromptRequest` are not used in the query — only in the error fallback. A caller can read any prompt in any collection by knowing the handle.

**Required:** Add `metadata__tenant_id=tenant_id, metadata__tenant_feature=tenant_feature` to the query, or document explicitly that this is a trusted-caller-only API.

---

### 4.8 Delete Does Not Require Version — Can Be Called Without It
**File:** `services/prompt.py` — `delete_prompt`

`DeletePromptRequest.version` is `Optional[int]`. The service returns a soft error if missing. But the endpoint signature accepts a request with no version, which is a dangerous footgun. In production, an accidental delete request with no version should be rejected at input validation, not returned as a soft-failure dict.

**Required:** Make `version: int` required on `DeletePromptRequest`, or change `delete_prompt` to delete all versions when none is provided but add an explicit `delete_all: bool = False` guard field.

---

## 5. Medium Priority Issues — Address Within a Cycle (P2)

### 5.1 No Tests

Zero test files exist. No unit tests, no integration tests, no contract tests. With dynamic MongoEngine models, cache state, and complex version logic, regressions are nearly impossible to detect without tests.

**Required:** At minimum:
- Unit tests for `utils/helpers.py` (pure functions, trivial to test)
- Unit tests for `schemas/validators.py`
- Integration tests for `PromptService` against a real MongoDB (use `mongomock` or a Docker test container)
- HTTP-level tests with FastAPI `TestClient`

---

### 5.2 Static Methods — No Dependency Injection
**File:** `services/prompt.py`

`PromptService` consists entirely of `@staticmethod` methods. This makes it impossible to:
- Mock the service in tests without monkeypatching
- Inject different DB connections per request (e.g., tenant-specific connection strings)
- Profile or trace individual service calls via middleware

**Required:** Convert to a class with `__init__` or use FastAPI `Depends()` with a factory function. This doesn't need to be complex — a simple `get_prompt_service()` dependency is enough.

---

### 5.3 Dynamic Model Cache Has No Eviction
**File:** `mongodb_db/schemas.py`

`_ENV_MODEL_CACHE`, `_TEMP_MODEL_CACHE`, and `_LOG_MODEL_CACHE` grow indefinitely. In a long-running process with many unique `(prompt_handle, environment)` pairs, this is a memory leak.

**Required:** Use `functools.lru_cache` with a `maxsize` or a bounded LRU dict. A reasonable upper bound is 512 entries.

---

### 5.4 `sys.path` Manipulation in `main.py`
**File:** `main.py`

```python
_parent_dir = str(Path(__file__).parent)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)
```

This is a development workaround that indicates the package is not installed properly. In production Docker images, the working directory is set and the package is installed via `pip install -e .` or similar.

**Required:** Add a `pyproject.toml` (or `setup.py`) and install the package. Remove the `sys.path` manipulation.

---

### 5.5 `SearchPromptRequest.label` Is `Optional[str]` but Schema Stores `List[str]`
**File:** `schemas/requests/search.py`

The `label` filter accepts a single string but `PromptMetadataSchema.label` is a `List[str]`. Searching for a label stored as `["billing", "v2"]` with a single string `"billing"` uses MongoEngine's exact match, which won't work for list fields. This likely silently returns 0 results instead of failing visibly.

**Required:** Change `label` in `SearchPromptRequest` to `Optional[List[str]]` and use MongoEngine's `in` operator (`metadata__label__in=label`) for the query.

---

### 5.6 `commit_prompt` Leaks `is_new_sub_agent` Flag in the Response
**File:** `api/routers.py`, `schemas/responses/commit.py`

`CommitResponseSchema.is_new_sub_agent` is internal implementation state that the caller doesn't need for correct usage. Exposing it creates a contract where callers may start depending on it.

**Suggestion:** Move this info into `CommitResponseSchema.info` as a human-readable string. Or keep it as `Optional[bool]` but document it as advisory.

---

### 5.7 Audit Log Write Is Not Transactional With Delete
**File:** `services/prompt.py` — `delete_prompt`

```python
create_log_model(...)(...).save()   # Write audit log
prompt_to_delete.delete()           # Delete the prompt
```

If the audit log write fails, the prompt is not deleted (good). But if the log write succeeds and the delete fails, the audit log contains a phantom deletion. If the delete succeeds and the log write had an exception that was swallowed (§3.2), there is no audit trail for the deletion.

**Required:** Wrap in a try/except that rolls back or re-raises. MongoDB 4.0+ supports multi-document transactions — consider using them here.

---

### 5.8 `format_prompt_response` Does Not Include `description` and `tags`
**File:** `utils/helpers.py`, `schemas/responses/create.py`

`format_prompt_response` returns `description` and `tags` fields, but `CreateResponseSchema` does not declare them. They will be silently stripped by FastAPI's response serialization when the response model is applied. This loses data the caller might need.

**Required:** Add `description: Optional[str]` and `tags: Optional[Dict[str, Any]]` to `CreateResponseSchema`, or remove them from `format_prompt_response`.

---

## 6. Architecture Improvements for Future Cycles

### 6.1 Async DB Operations
MongoEngine is synchronous. In a high-traffic FastAPI service, sync DB calls block the event loop. Consider:
- **Short term:** Run blocking calls in a thread pool via `asyncio.run_in_executor`
- **Long term:** Migrate to `motor` (the async MongoDB driver) with Beanie ODM or raw `motor` collections

### 6.2 Event-Driven Promotion Flow
The current `save → commit` flow is entirely pull-based (caller invokes `/commit` explicitly). For a production prompt management workflow, consider an event on commit (e.g., publish to a message queue) so downstream systems (CI pipelines, model deployments, canary testers) can react to new prompt versions without polling.

### 6.3 Diff and Rollback
There is no way to compare two versions of a prompt or roll back to a previous version without manually re-committing it. Version management in prompt engineering contexts requires:
- `GET /diff?handle=X&v1=1&v2=3` — structured diff of `prompt_data`
- `POST /rollback` — commit a copy of a historical version as the new latest

### 6.4 Prompt Rendering / Template Expansion
`prompt_data` is stored as a raw `DictField`. There is no concept of template variables, rendering, or validation that the stored data is a valid prompt for the target model. A production prompt store should have:
- A schema for `prompt_data` per model provider (e.g., OpenAI chat format vs. Anthropic messages format)
- Optional server-side rendering with variable substitution

### 6.5 Environment Promotion API
A common need is to promote a prompt from `development → test → uat → production` with an approval gate. Currently the caller must read from dev and commit to prod manually. A `POST /promote` endpoint that copies a version across environments (with optional approval state) would cover a major production use case.

### 6.6 Multi-Tenancy Isolation at Connection Level
Today all tenants share the same MongoDB instance and the same databases. A large enterprise deployment would require:
- Separate collections per tenant (include `tenant_id` in collection name) — already flagged in §3.4
- Or separate database per tenant
- Or separate MongoDB cluster per tier (SaaS vs. enterprise on-prem)

### 6.7 Rate Limiting and Quotas
No rate limiting on any endpoint. A runaway client can exhaust the thread pool and starve other tenants. Add `slowapi` or an API Gateway rate limit rule with per-tenant quotas.

---

## 7. Summary Priority Table

| ID | Area | Severity | Effort |
|----|------|----------|--------|
| 3.1 | Authentication / Authorisation | P0 | Medium |
| 3.2 | Silent exception swallowing | P0 | Low |
| 3.3 | No structured logging | P0 | Low |
| 3.4 | Cross-tenant data collision | P0 | Medium |
| 3.5 | Version assignment race condition | P0 | Medium |
| 3.6 | Error details leaked to callers | P0 | Low |
| 3.7 | `save` accepts `None` user_id | P0 | Low |
| 4.1 | No pagination | P1 | Low |
| 4.2 | Health check doesn't ping DB | P1 | Low |
| 4.3 | Stale `router.py` file | P1 | Trivial |
| 4.4 | `datetime.utcnow()` deprecated | P1 | Low |
| 4.5 | Redundant `labels` on CommitRequest | P1 | Low |
| 4.6 | MongoClient opened per call | P1 | Low |
| 4.7 | `read_prompt` not tenant-scoped | P1 | Low |
| 4.8 | Delete accepts missing version | P1 | Low |
| 5.1 | No tests | P2 | High |
| 5.2 | Static methods / no DI | P2 | Medium |
| 5.3 | Unbounded model cache | P2 | Low |
| 5.4 | `sys.path` manipulation | P2 | Low |
| 5.5 | `label` search type mismatch | P2 | Low |
| 5.6 | `description`/`tags` not in response schema | P2 | Low |
| 5.7 | Non-transactional audit log + delete | P2 | Medium |
| F.1 | Async DB (motor/beanie) | Future | High |
| F.2 | Event on commit | Future | High |
| F.3 | Diff + rollback endpoints | Future | Medium |
| F.4 | Prompt template schema validation | Future | High |
| F.5 | Environment promotion API | Future | Medium |
| F.6 | Per-tenant collection isolation | Future | High |
| F.7 | Rate limiting + quotas | Future | Low |

---

## 8. Recommended Next Steps (Ordered)

1. **Add authentication** (P0) — no code is worth shipping without this.
2. **Add structured logging + fix silent exceptions** (P0 combo) — log every caught exception at `ERROR` level.
3. **Fix tenant data isolation** (P0) — scope collection names and queries by `tenant_id`.
4. **Fix version race condition** (P0) — use atomic MongoDB counter or retry on `NotUniqueError`.
5. **Add pagination** (P1) — `limit`/`offset` on search and versions.
6. **Delete stale `router.py`** (P1 trivial).
7. **Fix `datetime.utcnow()`** (P1 low effort).
8. **Fix `label` search type + add `description`/`tags` to response schema** (P2 low effort, group together).
9. **Write integration tests** (P2) — establish a baseline before further refactoring.
10. **Replace static methods with DI** (P2) — makes testing tractable.
