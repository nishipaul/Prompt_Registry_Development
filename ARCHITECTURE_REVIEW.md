# Architecture Review — Prompt Management Service
> Originally assessed: 2026-05-13 | Last updated: 2026-05-18 | Reviewer: Principal Engineer perspective

---

## Changelog

| Date | What changed |
|------|--------------|
| 2026-05-13 | Initial review — baseline assessment |
| 2026-05-18 | Structured logging + central audit trail added. Enhanced validations (prompt_data, labels, handle format, version bounds). Search filtration extended. Mandatory/optional field clarity added to all schemas. `version` made required on delete and update. Router stale file removed (already done). |
| 2026-05-18 | Cross-tenant data isolation fixed — all read/version/update/delete/sub_agent queries now enforce `metadata__tenant_id` + `metadata__tenant_feature`. Version counter also scoped per tenant so two tenants sharing a handle get independent version sequences. |

---

## 1. Executive Summary

The codebase has a **solid structural foundation** — clean layering, well-typed schemas, centralised validation, and proper audit machinery. Several production-grade decisions (Pydantic v2 `Annotated` types, `OperationMetadataSchema` on every response, TTL-backed temp storage, per-environment audit logs) reflect real product thinking.

**As of the latest round of changes**, observability and data integrity are materially improved. The system now has structured logging across all service methods, a central audit trail for every CRUD operation, tighter input validation, and full mandatory/optional field documentation on every endpoint. The remaining gaps are authentication, tenant isolation, concurrency safety, and test coverage — none of which were in scope of the last sprint but remain blockers for production.

---

## 2. What Is in Good Shape

| Area | Assessment |
|------|------------|
| **Schema layer** | `Annotated[str, AfterValidator(...)]` pattern centralises all validation. Now includes `ValidatedPromptHandle`, `validate_prompt_data_value`, `validate_labels_value`. Zero duplication across request classes. |
| **Field documentation** | Every field on every request schema now carries `[REQUIRED]` or `[OPTIONAL]` with description and examples. Visible in Swagger UI at `/docs`. |
| **Structured logging** | `utils/logger.py` — `configure_logging()` wired to `lifespan`, every service method emits `op / user / handle / env` context. DELETE emits at `WARNING`; errors at `ERROR`. |
| **Central audit trail** | `mongodb_db/audit.py` — `operation_audit_log` collection per environment captures every commit, save, read, search, update, delete, and versions call with `user_email`, `duration_ms`, `status`, and `detail` payload. |
| **Input validation** | `prompt_data` must be non-empty with string keys. `labels` require ≥ 1 non-empty entry. `prompt_handle` validated against `[a-z0-9][a-z0-9_\-]{0,127}`. `version` enforced `≥ 1` on all endpoints that accept it. |
| **Search filtration** | `SearchPromptRequest` now accepts `created_after`, `created_before`, `created_by`, `version` filters — translated to MongoEngine range queries in `build_search_query`. |
| **Version required on delete/update** | `DeletePromptRequest.version` and `UpdatePromptRequest.version` are now `int` (required, `ge=1`). Foot-gun of omitting version removed at schema level. |
| **Response envelope** | `OperationMetadataSchema` on every mutating response gives audit traceability by design. |
| **Schema organisation** | `schemas/requests/` and `schemas/responses/` split by operation. Easy to navigate and extend. |
| **Validation service** | `ValidationService.resolve_commit_data` cleanly separates business-logic resolution from Pydantic field validation. |
| **Temp storage design** | MongoDB TTL index approach for auto-expiry. `_ensure_collection_ttl` + background cleanup thread covers both the index and empty-collection hygiene. |
| **Audit log on delete** | Separate `<env>_logs` database per environment. Audit data survives the operational DB. Both the legacy per-handle delete log and the new central `operation_audit_log` are written on every delete. |
| **Settings** | `pydantic-settings` `BaseSettings` with `.env` support. |
| **MongoEngine model factory** | `create_env_prompt_model` / `create_log_model` / `create_audit_log_model` with model caching. |
| **`lifespan` hook** | Connects DBs, ensures TTL indexes, starts cleanup thread, configures logging — and tears everything down cleanly. |

---

## 3. Critical Issues — Must Fix Before Production (P0)

### ✅ 3.2 Silent Exception Swallowing — PARTIALLY RESOLVED
**Files:** `services/prompt.py`

**What was done:** All `except Exception` blocks in the service layer now call `log_op(logger, logging.ERROR, ...)` before returning a fallback value. Errors are no longer silently dropped — they surface in the structured log output.

**Remaining gap:** The helper methods `_get_env_collections`, `_ensure_collection_ttl`, and `_validate_sub_agent` still swallow exceptions silently without logging. These are lower-risk paths but should be brought in line.

---

### ✅ 3.3 No Structured Logging — RESOLVED
**Files:** `utils/logger.py` (new), `services/prompt.py`, `main.py`

**What was done:**
- Created `utils/logger.py` with `configure_logging()`, `get_logger()`, and `log_op()`.
- `configure_logging(debug=settings.DEBUG)` is called in the FastAPI `lifespan` hook at startup.
- Every service method — `commit_prompt`, `save_temp_prompt`, `read_prompt`, `search_prompts`, `get_all_versions`, `update_prompt`, `delete_prompt` — emits a structured start and completion log line with `op`, `user`, `handle`, and `env` context.
- DELETE operations log at `WARNING` level to make them immediately visible in any log aggregator.
- Every log line includes operation timing (`duration_ms`).

Sample output:
```
2026-05-18T10:22:01Z | INFO     | pm.service.prompt | op=commit     user=dev@co.com  handle=my-prompt env=development | Committing prompt — sub_agent=None
2026-05-18T10:22:01Z | INFO     | pm.service.prompt | op=commit     user=dev@co.com  handle=my-prompt env=development | Committed v4 successfully (14 ms)
2026-05-18T10:22:05Z | WARNING  | pm.service.prompt | op=delete     user=admin@co.com handle=my-prompt env=production  | DELETE requested — version=2 reason='outdated'
```

---

### ⏳ 3.1 No Authentication or Authorisation — OPEN
**File:** `api/routers.py`

Every endpoint is open. Any caller can read, overwrite, or delete any tenant's prompts. There is no API key, JWT, OAuth2, or even a shared secret.

**Required:** Add FastAPI `Depends(verify_api_key)` or `Depends(get_current_user)` on all mutating endpoints. For internal services, a signed JWT or HMAC-signed request header is standard. At minimum, add `X-API-Key` middleware before any deployment.

---

### ✅ 3.4 `prompt_handle` Is Not Tenant-Scoped — Cross-Tenant Data Collision — RESOLVED
**Files:** `services/prompt.py`, `api/routers.py`

**What was done:** Query-level tenant scoping applied across the entire service layer. Every read, version list, update, and delete query now enforces both `metadata__tenant_id` and `metadata__tenant_feature` so a tenant can only see and touch their own prompts — even when two tenants share the same collection (same prompt_handle, same environment).

The fix was applied consistently to 8 methods:
- `_get_existing_sub_agents` — `$match` stage in aggregation pipeline now filters by tenant
- `_validate_sub_agent` — sub-agent existence check scoped to tenant
- `_next_version` — version counter scoped per tenant, so each tenant gets an independent sequence starting at v1
- `check_existing_prompt` — existence check scoped to tenant
- `read_prompt` — query always includes `metadata__tenant_id` + `metadata__tenant_feature`
- `get_all_versions` — version list scoped to tenant
- `update_prompt` — source document lookup scoped to tenant
- `delete_prompt` — document lookup before deletion scoped to tenant

The router passes `request.tenant_id` and `request.tenant_feature` through to all service calls. Collection names were intentionally kept as-is (no tenant prefix in name) to preserve backward compatibility with existing data; isolation is enforced at query level rather than storage level.

**Residual note:** The `user_temp` path in `read_prompt` is scoped by `user_email` (stored as `user_id`) which is already user-specific, so tenant leakage via the temp collection is not possible.

---

### ⏳ 3.5 Version Assignment Race Condition — OPEN
**File:** `services/prompt.py` — `_next_version` + `commit_prompt`

```python
version = PromptService._next_version(...)   # READ max version
prompt = PromptModel(version=version, ...)
prompt.save()                                # WRITE — no atomic guarantee
```

Two concurrent commits for the same `(prompt_handle, sub_agent)` will both read the same `max_version`, both assign the same next version, and one will fail with a MongoEngine `NotUniqueError` at save time. The caller receives a raw 500 with the exception message.

**Required:** Wrap in a retry loop with `NotUniqueError` handling, or use MongoDB `findOneAndUpdate` with `$inc` on a version counter document to atomically increment the version.

---

### ⏳ 3.6 Internal Error Details Exposed to Callers — OPEN
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

### ⏳ 3.7 `save_temp_prompt` Accepts `None` for `user_id` — OPEN
**Files:** `api/routers.py`, `services/prompt.py`

`SaveTempPromptRequest.user_email` is `OptionalValidatedEmail` — can be `None`. This flows into `PromptService.save_temp_prompt(user_email=...)` and lands at:
```python
TempModel(user_id=user_email, ...)  # user_id is StringField(required=True)
```
MongoEngine will raise `ValidationError` at save time with an opaque message.

**Required:** Either make `user_email` required on `SaveTempPromptRequest`, or set a default `"anonymous"` value before the DB call, and document the intent explicitly.

---

## 4. High Priority Issues — Fix Within First Sprint (P1)

### ✅ 4.3 Stale `router.py` File — RESOLVED
The old `router.py` was already replaced by `api/routers.py` in a prior session. Removed.

---

### ✅ 4.8 Delete and Update Accept Missing Version — RESOLVED
**Files:** `schemas/requests/delete.py`, `schemas/requests/update.py`

**What was done:** `DeletePromptRequest.version` and `UpdatePromptRequest.version` are now `int` (required, `ge=1`). The footgun of passing a request with no version is rejected at Pydantic validation before it reaches the service layer.

---

### ⏳ 4.1 No Pagination on Search and Versions — OPEN
**File:** `services/prompt.py` — `search_prompts`, `get_all_versions`

Both return all matching documents with no limit. A prompt handle with 500 versions will return 500 documents in one response.

**Required:** Add `limit: int = 50` and `offset: int = 0` (or `page`/`page_size`) to `SearchPromptRequest`, `VersionsRequest`, and the `SearchResponseSchema`. Apply `.skip(offset).limit(limit)` in the MongoEngine queries.

---

### ⏳ 4.2 No Health-Check DB Ping — OPEN
**File:** `api/routers.py` — `/health`

The health endpoint returns `{"status": "healthy"}` unconditionally. A load balancer or Kubernetes readiness probe relying on this will route traffic to a pod with a broken MongoDB connection.

**Required:**
```python
@router.get("/health")
async def health_check():
    try:
        from mongoengine.connection import get_connection
        get_connection("development").server_info()
        db_status = "connected"
    except Exception:
        db_status = "unreachable"
    return {"status": "healthy" if db_status == "connected" else "degraded", "db": db_status}
```

---

### ⏳ 4.4 `datetime.utcnow()` Deprecated — OPEN
**Files:** `mongodb_db/schemas.py`, `services/prompt.py`

`datetime.utcnow()` has been deprecated since Python 3.12. It returns a naïve datetime with no timezone info, which causes ambiguity in any multi-timezone deployment.

**Required:** Replace with `datetime.now(timezone.utc)` everywhere. Also update `DateTimeField` defaults in MongoEngine schemas to use `lambda: datetime.now(timezone.utc)`.

---

### ⏳ 4.5 `CommitPromptRequest` Has Redundant `labels` Field — OPEN
**File:** `schemas/requests/commit.py`

`CommitPromptRequest` has both `labels: List[str]` at the top level AND `metadata: PromptMetadataSchema` which contains `label: List[str]`. `ValidationService.resolve_commit_data` uses `request.metadata.model_dump()` which carries `label`. The top-level `labels` field is validated but not used in persistence.

**Note:** A validator was added on `labels` to enforce non-empty values, which is good. But the canonical storage path still uses `metadata.label`. The two fields can diverge silently.

**Required:** Remove `labels` from `CommitPromptRequest` and enforce the non-empty rule on `metadata.label` directly. The canonical source should be one field only.

---

### ⏳ 4.6 `_get_env_collections` Opens a New `MongoClient` on Every Call — OPEN
**File:** `services/prompt.py`

`_get_env_collections` and `_ensure_collection_ttl` each create a raw `MongoClient` independently of the MongoEngine connection pool. Every cross-collection search opens a new TCP connection.

**Required:** Cache the `MongoClient` or use `from mongoengine.connection import get_db`.

---

### ⏳ 4.7 `read_prompt` Doesn't Filter by Tenant — OPEN
**File:** `services/prompt.py`

`read_prompt` queries only by `prompt_handle`, `sub_agent`, and `version`. `tenant_id` and `tenant_feature` from `ReadPromptRequest` are only used in the error fallback. Any caller can read any prompt in any collection by knowing the handle.

**Required:** Add `metadata__tenant_id=tenant_id, metadata__tenant_feature=tenant_feature` to the query, or document explicitly that this is a trusted-caller-only internal API.

---

## 5. Medium Priority Issues — Address Within a Cycle (P2)

### ✅ 5.7 Audit Log Write Coverage — PARTIALLY IMPROVED
**File:** `services/prompt.py`, `mongodb_db/audit.py`

**What was done:** A new `create_audit_log_model` creates a central `operation_audit_log` collection per environment. Every operation — commit, save, read, search, update, delete, versions — now writes one audit entry with `operation`, `user_email`, `prompt_handle`, `environment`, `version`, `status`, `duration_ms`, `detail`, and `error`. Audit failures are caught and logged at `WARNING` level so they never crash the main operation.

**Remaining gap:** The delete operation is still non-transactional — the legacy deletion log is written before the document is deleted. If the delete fails after the log write, the audit log contains a phantom deletion. Full transactional safety requires MongoDB 4.0+ multi-document transactions.

---

### ⏳ 5.1 No Tests — OPEN

Zero test files exist. No unit tests, no integration tests, no contract tests.

**Required:** At minimum:
- Unit tests for `utils/helpers.py` and `schemas/validators.py` (pure functions, no DB needed)
- Integration tests for `PromptService` against a real MongoDB (use `mongomock` or a Docker test container)
- HTTP-level tests with FastAPI `TestClient`
- Edge cases to cover: empty `prompt_data`, duplicate version race, unknown `prompt_handle`, cross-tenant reads, temp expiry, delete without version (now caught at schema), valid vs. invalid `prompt_handle` format

---

### ⏳ 5.2 Static Methods — No Dependency Injection — OPEN
**File:** `services/prompt.py`

`PromptService` consists entirely of `@staticmethod` methods. This makes it impossible to mock the service in tests without monkeypatching, inject different DB connections per request, or trace individual service calls via middleware.

**Required:** Convert to a class with `__init__` or use FastAPI `Depends()` with a factory function.

---

### ⏳ 5.3 Dynamic Model Cache Has No Eviction — OPEN
**File:** `mongodb_db/schemas.py`

`_ENV_MODEL_CACHE`, `_TEMP_MODEL_CACHE`, `_LOG_MODEL_CACHE`, and `_AUDIT_CACHE` (new) all grow indefinitely. In a long-running process with many unique `(prompt_handle, environment)` pairs, this is a memory leak.

**Required:** Use `functools.lru_cache` with a `maxsize` or a bounded LRU dict. A reasonable upper bound is 512 entries.

---

### ⏳ 5.4 `sys.path` Manipulation in `main.py` — OPEN
**File:** `main.py`

```python
_parent_dir = str(Path(__file__).parent)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)
```

This is a development workaround that indicates the package is not installed properly. In production Docker images, the working directory is set and the package is installed via `pip install -e .`.

**Required:** Add a `pyproject.toml` and install the package. Remove the `sys.path` manipulation.

---

### ⏳ 5.5 `SearchPromptRequest.label` Is `Optional[str]` but Schema Stores `List[str]` — OPEN
**File:** `schemas/requests/search.py`

The `label` filter accepts a single string but `PromptMetadataSchema.label` is a `List[str]`. Searching for `"billing"` in a stored list `["billing", "v2"]` uses exact match, which silently returns 0 results.

**Required:** Change `label` in `SearchPromptRequest` to `Optional[List[str]]` and use MongoEngine's `in` operator (`metadata__label__in=label`).

---

### ⏳ 5.6 `description` and `tags` Missing from Response Schema — OPEN
**File:** `schemas/responses/create.py`

`format_prompt_response` returns `description` and `tags` but `CreateResponseSchema` doesn't declare them. FastAPI strips them during response serialization.

**Required:** Add `description: Optional[str]` and `tags: Optional[Dict[str, Any]]` to `CreateResponseSchema`.

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

| ID | Area | Status | Severity | Effort |
|----|------|--------|----------|--------|
| 3.1 | Authentication / Authorisation | ⏳ Open | P0 | Medium |
| 3.2 | Silent exception swallowing | ✅ Partial — errors now logged | P0 | Low |
| 3.3 | No structured logging | ✅ Done — `utils/logger.py` + audit trail | P0 | Low |
| 3.4 | Cross-tenant data collision | ✅ Done — query-level tenant scoping on all reads/writes | P0 | Medium |
| 3.5 | Version assignment race condition | ⏳ Open | P0 | Medium |
| 3.6 | Error details leaked to callers | ⏳ Open | P0 | Low |
| 3.7 | `save` accepts `None` user_id | ⏳ Open | P0 | Low |
| 4.1 | No pagination | ⏳ Open | P1 | Low |
| 4.2 | Health check doesn't ping DB | ⏳ Open | P1 | Low |
| 4.3 | Stale `router.py` file | ✅ Done — removed in prior session | P1 | Trivial |
| 4.4 | `datetime.utcnow()` deprecated | ⏳ Open | P1 | Low |
| 4.5 | Redundant `labels` on CommitRequest | ⏳ Open | P1 | Low |
| 4.6 | MongoClient opened per call | ⏳ Open | P1 | Low |
| 4.7 | `read_prompt` not tenant-scoped | ⏳ Open | P1 | Low |
| 4.8 | Delete/update accept missing version | ✅ Done — `version: int ge=1` required | P1 | Low |
| 5.1 | No tests | ⏳ Open | P2 | High |
| 5.2 | Static methods / no DI | ⏳ Open | P2 | Medium |
| 5.3 | Unbounded model cache | ⏳ Open | P2 | Low |
| 5.4 | `sys.path` manipulation | ⏳ Open | P2 | Low |
| 5.5 | `label` search type mismatch | ⏳ Open | P2 | Low |
| 5.6 | `description`/`tags` not in response schema | ⏳ Open | P2 | Low |
| 5.7 | Non-transactional audit log + delete | ✅ Partial — central audit log added | P2 | Medium |
| F.1 | Async DB (motor/beanie) | ⏳ Future | Future | High |
| F.2 | Event on commit | ⏳ Future | Future | High |
| F.3 | Diff + rollback endpoints | ⏳ Future | Future | Medium |
| F.4 | Prompt template schema validation | ⏳ Future | Future | High |
| F.5 | Environment promotion API | ⏳ Future | Future | Medium |
| F.6 | Per-tenant collection isolation | ⏳ Future | Future | High |
| F.7 | Rate limiting + quotas | ⏳ Future | Future | Low |

---

## 8. Recommended Next Steps (Ordered)

Steps already completed are struck through. Remaining work is ordered by risk reduction per unit of effort.

1. ~~**Add structured logging + fix silent exceptions** (P0 combo)~~ — ✅ Done
2. ~~**Delete stale `router.py`** (P1 trivial)~~ — ✅ Done
3. ~~**Make version required on delete/update** (P1 low effort)~~ — ✅ Done
4. **Fix `None` user_id on save** (P0 low effort) — make `user_email` required on `SaveTempPromptRequest` or default to `"anonymous"`.
5. **Sanitise error messages returned to callers** (P0 low effort) — catch exceptions in router, log internally, return `"Internal error. See server logs."`.
6. **Fix remaining silent swallows in helpers** (P0 low effort) — add `log_op(logger, logging.ERROR, ...)` in `_get_env_collections`, `_ensure_collection_ttl`, `_validate_sub_agent`.
7. **Add authentication** (P0 medium effort) — no code is worth shipping without this.
8. **Add pagination** (P1 low effort) — `limit`/`offset` on search and versions before data grows.
9. **Fix `datetime.utcnow()`** (P1 low effort) — quick sweepable change.
10. **Fix `label` search type + add `description`/`tags` to response schema** (P2 low effort) — group together, 30 minutes of work.
11. ~~**Fix tenant data isolation** (P0 medium effort)~~ — ✅ Done
12. **Fix version race condition** (P0 medium effort) — atomic MongoDB counter or retry on `NotUniqueError`.
13. **Write integration tests** (P2) — establish a baseline before further refactoring.
14. **Replace static methods with DI** (P2) — makes testing tractable.
