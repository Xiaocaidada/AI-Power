from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "dev"
    database_url: str = "sqlite+aiosqlite:///./ai_power.db"
    jwt_secret: str = "dev-only-insecure-secret-change-me-0123456789"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 1440
    password_min_length: int = 8

    @model_validator(mode="after")
    def _forbid_dev_secret_outside_dev(self) -> "Settings":
        if self.app_env != "dev" and self.jwt_secret.startswith("dev-"):
            raise ValueError("JWT_SECRET must be set to a generated value outside dev")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
