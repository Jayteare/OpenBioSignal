from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import os

from dotenv import load_dotenv
from pydantic import BaseModel


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Settings(BaseModel):
    """Application settings loaded from environment variables."""

    app_name: str = "OpenBioSignal"
    app_env: str = "development"
    database_url: str = "sqlite:///./openbiosignal.db"
    z_ai_api_key: str | None = None
    z_ai_model: str = "glm-5"
    z_ai_base_url: str = "https://api.z.ai/api/paas/v4/"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings with safe defaults."""

    return Settings(
        app_name=os.getenv("APP_NAME", "OpenBioSignal"),
        app_env=os.getenv("APP_ENV", "development"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./openbiosignal.db"),
        z_ai_api_key=os.getenv("ZAI_API_KEY"),
        z_ai_model=os.getenv("ZAI_MODEL", "glm-5"),
        z_ai_base_url=os.getenv("ZAI_BASE_URL", "https://api.z.ai/api/paas/v4/"),
    )
