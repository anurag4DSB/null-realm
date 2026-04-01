"""Application configuration via Pydantic Settings.

Loads from environment variables (or .env file when present).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the Null Realm platform."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM API Keys ---
    google_api_key: str = ""
    anthropic_api_key: str = ""

    # --- Database ---
    database_url: str = "postgresql+asyncpg://nullrealm:nullrealm@localhost:5432/nullrealm"

    # --- NATS ---
    nats_url: str = "nats://localhost:4222"

    # --- Langfuse (LLM observability) ---
    langfuse_secret_key: str = ""
    langfuse_public_key: str = ""
    langfuse_host: str = "http://localhost:3001"

    # --- Jaeger (distributed tracing) ---
    jaeger_endpoint: str = "http://localhost:4318"

    # --- Service settings ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    environment: str = "local"
    log_level: str = "info"


settings = Settings()
