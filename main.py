from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

_parent_dir = str(Path(__file__).parent)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from mongodb_db import init_all_connections, stop_cleanup_thread, DatabaseConfig
from mongodb_db.settings import settings
from api.routers import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_all_connections()
    yield
    stop_cleanup_thread()
    DatabaseConfig.disconnect_all()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Prompt Management System\n\n"
        "- **/save**: Temporary storage (auto-deleted by MongoDB TTL)\n"
        "- **/commit**: Permanent storage in environment databases\n"
        "- **/read** / **/search**: Query environment databases\n"
        "- **/update**: Read → modify → save to temp\n"
        "- **/delete**: Remove from environment (audit logged)\n"
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
async def root():
    return {
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": "/api/v1/prompts/health",
    }


if __name__ == "__main__":
    import os
    import uvicorn

    module_path = (
        "main:app"
        if os.path.basename(os.getcwd()) == "prompt_management"
        else "prompt_management.main:app"
    )
    uvicorn.run(module_path, host="0.0.0.0", port=8000, reload=settings.DEBUG)
