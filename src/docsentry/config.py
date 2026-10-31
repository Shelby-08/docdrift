from typing import Literal

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(Exception):
    """Raised when environment configuration is invalid."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    github_app_id: str = Field(..., min_length=1)
    github_private_key: SecretStr
    github_webhook_secret: SecretStr
    port: int = Field(default=3000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    max_file_bytes: int = Field(default=1_000_000, ge=1, le=100_000_000)
    max_snapshot_files: int = Field(default=200, ge=1, le=50_000)
    max_total_snapshot_bytes: int = Field(default=10_000_000, ge=1, le=500_000_000)
    max_tree_requests: int = Field(default=200, ge=1, le=5000)
    github_api_timeout_seconds: int = Field(default=15, ge=1, le=300)
    max_job_attempts: int = Field(default=3, ge=1, le=10)
    max_concurrent_jobs: int = Field(default=1, ge=1, le=10)

    @field_validator("github_private_key", mode="before")
    @classmethod
    def decode_private_key(cls, v: object) -> object:
        """Convert escaped newlines in the env file to actual newlines."""
        if isinstance(v, str):
            return v.replace("\\n", "\n")
        return v

    @model_validator(mode="after")
    def check_secrets(self) -> "Settings":
        """Ensure secrets are not empty or whitespace-only."""
        if not self.github_app_id.strip():
            raise ValueError("github_app_id cannot be empty")
        if not self.github_private_key.get_secret_value().strip():
            raise ValueError("github_private_key cannot be empty")
        if not self.github_webhook_secret.get_secret_value().strip():
            raise ValueError("github_webhook_secret cannot be empty")
        return self


def load_settings(env_file: str | None = ".env") -> Settings:
    """Load settings from the given env file."""
    try:
        return Settings(_env_file=env_file)
    except ValidationError as e:
        # Build a clean error message with only field names (never the values).
        msg = "Invalid configuration:"
        for err in e.errors():
            field = str(err["loc"][0]) if err["loc"] else "settings"
            msg += f" Field '{field}': {err['msg']}"
        raise ConfigError(msg) from None
