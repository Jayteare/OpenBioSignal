from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.db import models  # noqa: F401
from app.db.session import initialize_database
from app.routes.api import router as api_router
from app.routes.ui import router as ui_router

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Create local database tables during app startup."""

    initialize_database()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)


app.include_router(ui_router)
app.include_router(api_router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str | bool]:
    """Basic application health check."""

    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
        "z_ai_api_key_configured": bool(settings.z_ai_api_key),
    }
