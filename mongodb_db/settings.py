from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    APP_NAME: str = "Prompt Management System"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    # MongoDB connection
    MONGODB_HOST: str = "localhost"
    MONGODB_PORT: int = 27017

    # Retention policy
    LOG_RETENTION_DAYS: int = 365
    TEMP_PROMPT_RETENTION_MINUTES: int = 20

    # CORS
    CORS_ORIGINS: List[str] = ["*"]

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
