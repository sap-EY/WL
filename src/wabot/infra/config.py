"""Application configuration.

Single source of truth for runtime settings. Loaded from environment / .env via
pydantic-settings. The DB DSN is assembled from components so the password is
never embedded in a config string and never logged.

Phase 1 will extend this module with structured-logging hooks; the surface
defined here is final for Phase 0 and the keys map 1:1 with `.env.example`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import quote_plus

from pydantic import Field, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["local", "dev", "staging", "prod"]
SslMode = Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"]
BrokerBackend = Literal["redis_streams", "azure_servicebus"]


class _Base(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


class AppSettings(_Base):
    """Top-level runtime settings.

    Names follow the `.env.example` keys verbatim. Field aliases keep the
    Python identifiers ergonomic while preserving the env-var contract.
    """

    # --- App ----------------------------------------------------------------
    name: str = Field(default="wabot", alias="APP_NAME")
    env: AppEnv = Field(default="local", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="APP_LOG_LEVEL")
    log_json: bool = Field(default=True, alias="APP_LOG_JSON")
    http_port: int = Field(default=8000, alias="APP_HTTP_PORT")
    request_timeout_seconds: int = Field(default=30, alias="APP_REQUEST_TIMEOUT_SECONDS")
    feature_dry_run_outbound: bool = Field(default=False, alias="APP_FEATURE_FLAG_DRY_RUN_OUTBOUND")

    # --- DB (components → DSN computed below) -------------------------------
    db_host: str = Field(alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")
    db_user: str = Field(alias="DB_USER")
    db_password: SecretStr = Field(alias="DB_PASSWORD")
    db_name: str = Field(default="postgres", alias="DB_NAME")
    db_schema: str = Field(default="wabot", alias="DB_SCHEMA")
    db_ssl_mode: SslMode = Field(default="require", alias="DB_SSL_MODE")
    db_pool_size: int = Field(default=20, alias="DB_POOL_SIZE")
    db_pool_max_overflow: int = Field(default=20, alias="DB_POOL_MAX_OVERFLOW")
    db_statement_timeout_ms: int = Field(default=15_000, alias="DB_STATEMENT_TIMEOUT_MS")

    # --- Redis --------------------------------------------------------------
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    redis_lock_ttl_seconds: int = Field(default=30, alias="REDIS_LOCK_TTL_SECONDS")
    redis_dedupe_ttl_seconds: int = Field(default=600, alias="REDIS_DEDUPE_TTL_SECONDS")

    # --- Interakt -----------------------------------------------------------
    interakt_base_url: str = Field(default="https://api.interakt.ai", alias="INTERAKT_BASE_URL")
    interakt_api_key: SecretStr = Field(default=SecretStr(""), alias="INTERAKT_API_KEY")
    interakt_timeout_connect_seconds: float = Field(
        default=5.0, alias="INTERAKT_TIMEOUT_CONNECT_SECONDS"
    )
    interakt_timeout_read_seconds: float = Field(
        default=10.0, alias="INTERAKT_TIMEOUT_READ_SECONDS"
    )
    interakt_rate_limit_rps: int = Field(default=80, alias="INTERAKT_RATE_LIMIT_RPS")
    interakt_webhook_path_secret: SecretStr = Field(
        default=SecretStr("change-me"), alias="INTERAKT_WEBHOOK_PATH_SECRET"
    )
    interakt_allowed_cidrs: str = Field(default="0.0.0.0/0", alias="INTERAKT_ALLOWED_CIDRS")

    # --- Templates ----------------------------------------------------------
    template_doctor_welcome_consent: str = Field(
        default="doctor_welcome_consent_v1", alias="TEMPLATE_DOCTOR_WELCOME_CONSENT"
    )
    template_hotline: str = Field(default="hotline_v1", alias="TEMPLATE_HOTLINE")
    template_locale: str = Field(default="en", alias="TEMPLATE_LOCALE")
    support_contact_value: str = Field(default="+91-XXXXXXXXXX", alias="SUPPORT_CONTACT_VALUE")

    # --- Registration journey ----------------------------------------------
    registration_max_retries: int = Field(default=2, alias="REGISTRATION_MAX_RETRIES")

    # --- GenAI --------------------------------------------------------------
    genai_base_url: str = Field(default="", alias="GENAI_BASE_URL")
    genai_api_key: SecretStr = Field(default=SecretStr(""), alias="GENAI_API_KEY")
    genai_timeout_connect_seconds: float = Field(default=2.0, alias="GENAI_TIMEOUT_CONNECT_SECONDS")
    genai_timeout_read_seconds: float = Field(default=20.0, alias="GENAI_TIMEOUT_READ_SECONDS")
    genai_circuit_fail_threshold: int = Field(default=5, alias="GENAI_CIRCUIT_FAIL_THRESHOLD")
    genai_circuit_window_seconds: int = Field(default=60, alias="GENAI_CIRCUIT_WINDOW_SECONDS")

    # --- Broker -------------------------------------------------------------
    broker_backend: BrokerBackend = Field(default="redis_streams", alias="BROKER_BACKEND")
    broker_inbound_stream: str = Field(default="wabot.inbound", alias="BROKER_INBOUND_STREAM")
    broker_inbound_group: str = Field(default="wabot.inbound.workers", alias="BROKER_INBOUND_GROUP")
    broker_dlq_stream: str = Field(default="wabot.inbound.dlq", alias="BROKER_DLQ_STREAM")
    servicebus_connection_string: SecretStr = Field(
        default=SecretStr(""), alias="SERVICEBUS_CONNECTION_STRING"
    )
    servicebus_queue_inbound: str = Field(default="wabot-inbound", alias="SERVICEBUS_QUEUE_INBOUND")

    # --- Computed -----------------------------------------------------------
    @computed_field  # type: ignore[prop-decorator]
    @property
    def db_dsn(self) -> str:
        """SQLAlchemy + asyncpg DSN. Password is URL-encoded; SSL mode applied."""
        pwd = quote_plus(self.db_password.get_secret_value())
        user = quote_plus(self.db_user)
        return (
            f"postgresql+asyncpg://{user}:{pwd}@{self.db_host}:{self.db_port}"
            f"/{self.db_name}?ssl={self.db_ssl_mode}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def db_dsn_for_logging(self) -> str:
        """DSN with password masked, safe to log."""
        return (
            f"postgresql+asyncpg://{self.db_user}:***@{self.db_host}:{self.db_port}"
            f"/{self.db_name}?ssl={self.db_ssl_mode}"
        )


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Cached settings instance."""
    return AppSettings()
