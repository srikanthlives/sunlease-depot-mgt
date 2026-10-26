import os
from typing import ClassVar

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "Sunlease Depot Management"
    SECRET_KEY: str = os.environ.get("DEPOT_SECRET_KEY", "dev-secret-change-in-production-please")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 12
    DATABASE_URL: str = os.environ.get("DEPOT_DATABASE_URL", "sqlite:///../data/depot.db")
    DEFAULT_TIMEZONE: str = "Asia/Kolkata"

    # HRMS employee sync (read-only pull). Both must be set to enable it.
    HRMS_SYNC_URL: str = os.environ.get("DEPOT_HRMS_SYNC_URL", "")
    HRMS_SYNC_TOKEN: str = os.environ.get("DEPOT_HRMS_SYNC_TOKEN", "")

    _cors_origins = os.environ.get("DEPOT_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    CORS_ORIGINS: ClassVar[list] = [o.strip() for o in _cors_origins.split(",")]

    class Config:
        env_prefix = "DEPOT_"


settings = Settings()
