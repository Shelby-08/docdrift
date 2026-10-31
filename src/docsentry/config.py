from typing import Literal

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from docsentry.ai_review.urlcheck import UnsafeOllamaUrl, validate_ollama_base_url


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

    # Stage 3 Intelligence Limits
    analysis_max_source_files: int = Field(default=500, ge=1, le=5000)
    analysis_max_doc_files: int = Field(default=200, ge=1, le=2000)
    analysis_max_unchanged_source_files: int = Field(default=50, ge=0, le=500)
    analysis_time_budget_seconds: int = Field(default=60, ge=1, le=600)
    analysis_max_graph_depth: int = Field(default=3, ge=1, le=10)
    analysis_max_graph_nodes: int = Field(default=2000, ge=10, le=20000)
    analysis_max_candidates_per_claim: int = Field(default=5, ge=1, le=50)
    analysis_include_full_entities: bool = Field(default=False)
    ai_review_max_items: int = Field(default=50, ge=1, le=500)

    # Stage 4: Check Run reporting (single process / single Uvicorn worker only)
    docsentry_check_name: str = Field(default="DocSentry", min_length=1, max_length=60)
    docsentry_max_annotations: int = Field(default=25, ge=1, le=100)
    docsentry_max_summary_findings: int = Field(default=30, ge=1, le=100)
    docsentry_publish_enabled: bool = Field(default=True)

    # Stage 4: optional local advisory AI (Ollama on loopback only)
    ai_review_enabled: bool = Field(default=False)
    ollama_base_url: str = Field(default="http://127.0.0.1:11434")
    ai_backend: Literal["ollama", "llama_cpp"] = "ollama"
    ollama_model: str = Field(default="", max_length=200)
    ollama_timeout_seconds: int = Field(default=120, ge=1, le=300)
    ollama_num_ctx: int = Field(default=8192, ge=1, le=16384)
    ai_review_total_budget_seconds: int = Field(default=180, ge=1, le=600)
    ai_review_max_batch_items: int = Field(default=5, ge=1, le=10)
    ai_review_max_batch_chars: int = Field(default=12000, ge=1, le=30000)
    ai_review_max_output_tokens: int = Field(default=1200, ge=1, le=4000)
    ai_review_max_retries: int = Field(default=0, ge=0, le=1)

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
        try:
            validate_ollama_base_url(self.ollama_base_url)
        except UnsafeOllamaUrl:
            raise ValueError("ollama_base_url must be a loopback http URL") from None
        return self

    @property
    def ai_effective(self) -> bool:
        """AI runs only when enabled AND a model tag is configured (fail closed)."""
        if self.ai_backend == "llama_cpp":
            return self.ai_review_enabled  # llama.cpp serves one model; the tag is optional
        return self.ai_review_enabled and bool(self.ollama_model.strip())


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
