"""Application configuration.

Every setting is read from environment variables (or a .env file) and validated
by Pydantic when the app starts. A missing or malformed value stops the app
immediately with a clear error instead of failing later inside a request.

Usage:
    from app.core.config import settings
    settings.database_url
"""

from decimal import Decimal
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Look for .env in the repo root (when run from backend/) and in the current folder.
        # Real environment variables always override values from these files.
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",  # ignore unrelated variables (e.g. the frontend's VITE_* vars)
    )

    # --- Application ---
    APP_NAME: str = "InvoiceIQ"
    ENVIRONMENT: Literal["local", "test", "production"] = "local"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Comma-separated in .env, e.g. CORS_ORIGINS=http://localhost:5173,http://localhost:3000
    # NoDecode stops pydantic-settings from expecting JSON, so our validator can split the string.
    CORS_ORIGINS: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    # --- PostgreSQL ---
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "invoiceiq"
    POSTGRES_PASSWORD: SecretStr = SecretStr("invoiceiq")
    POSTGRES_DB: str = "invoiceiq"

    # --- Redis / Celery ---
    # Separate Redis logical databases keep cache keys and the Celery queue apart.
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # --- Auth (JWT) ---
    # No default: the app must not start without a secret.
    JWT_SECRET_KEY: SecretStr
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # --- Rate limits (SlowAPI syntax) ---
    RATE_LIMIT_ENABLED: bool = True
    LOGIN_RATE_LIMIT: str = "5/minute"
    UPLOAD_RATE_LIMIT: str = "30/minute"

    # --- File storage ---
    STORAGE_BACKEND: Literal["s3", "azure"] = "s3"  # s3 = any S3-compatible service
    S3_ENDPOINT_URL: str = "http://localhost:8333"
    # Presigned URLs are opened by the browser, which cannot resolve Docker-internal
    # hostnames like "seaweedfs:8333". This is the address the browser should use.
    S3_PUBLIC_ENDPOINT_URL: str = "http://localhost:8333"
    S3_ACCESS_KEY: str = "invoiceiq"
    S3_SECRET_KEY: SecretStr = SecretStr("invoiceiq-dev-secret")
    S3_BUCKET: str = "invoices"
    S3_REGION: str = "us-east-1"
    PRESIGNED_URL_EXPIRE_SECONDS: int = 900
    MAX_UPLOAD_SIZE_MB: int = Field(default=10, gt=0)

    # --- OCR ---
    OCR_PROVIDER: Literal["tesseract"] = "tesseract"
    TESSERACT_CMD: str | None = None  # full path to tesseract.exe on Windows if not on PATH
    POPPLER_PATH: str | None = None  # folder containing pdftoppm, needed by pdf2image on Windows

    # --- LLM ---
    LLM_PROVIDER: Literal["gemini", "openai"] = "gemini"
    LLM_API_KEY: SecretStr | None = None
    LLM_MODEL: str = "gemini-2.5-flash"
    LLM_TIMEOUT_SECONDS: int = 60

    # --- Processing pipeline ---
    AUTO_APPROVE_CONFIDENCE_THRESHOLD: float = Field(default=0.90, ge=0.0, le=1.0)
    # Allowed rounding difference (in rupees) when checking that totals add up
    AMOUNT_TOLERANCE: Decimal = Decimal("1.00")
    MAX_TASK_RETRIES: int = 3

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------
    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def split_cors_origins(cls, value: object) -> object:
        """Turn 'a,b,c' into ['a', 'b', 'c']; leave real lists unchanged."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def check_production_safety(self) -> "Settings":
        """Refuse to start in production with insecure settings."""
        if self.ENVIRONMENT == "production":
            if len(self.JWT_SECRET_KEY.get_secret_value()) < 32:
                raise ValueError("JWT_SECRET_KEY must be at least 32 characters in production")
            if self.DEBUG:
                raise ValueError("DEBUG must be false in production")
        return self

    # ------------------------------------------------------------------
    # Derived values
    # ------------------------------------------------------------------
    # A plain @property (not @computed_field) so the URL, which contains the password,
    # never appears in model_dump() output or logs.
    @property
    def database_url(self) -> str:
        """Async SQLAlchemy URL built from the individual POSTGRES_* parts."""
        password = self.POSTGRES_PASSWORD.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{password}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def max_upload_size_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Build Settings once and reuse it (reading env files on every call would be wasteful).

    Tests can call get_settings.cache_clear() after changing environment variables.
    """
    return Settings()


settings = get_settings()
