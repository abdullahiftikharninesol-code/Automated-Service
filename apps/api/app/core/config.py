from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Missed Lead Rescue API"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/missed_lead_rescue"
    jwt_secret: str = "development-only-change-this-secret"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480
    cors_origins: list[str] = ["http://localhost:3000"]
    ai_provider: str = "mock"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    email_provider: str = "console"
    resend_api_key: str | None = None
    email_from: str | None = None
    public_api_url: str = "http://localhost:8000"
    public_web_url: str = "http://localhost:3000"
    followup_new_lead_minutes: int = Field(default=30, ge=1)
    followup_second_reminder_hours: int = Field(default=2, ge=1)
    followup_contacted_hours: int = Field(default=24, ge=1)
    followup_final_days: int = Field(default=3, ge=1)
    rate_limit_enabled: bool = True
    auth_login_rate_limit: str = "10/minute"
    auth_register_rate_limit: str = "5/minute"
    public_inbound_rate_limit: str = "30/minute"
    webhook_signature_required: bool = False
    email_timeout_seconds: float = 5.0
    background_jobs_enabled: bool = True
    reminder_sweep_interval_seconds: int = Field(default=60, ge=1)
    default_owner_reminder_delay_minutes: int = Field(default=60, ge=1)
    default_owner_reminder_repeat_minutes: int = Field(default=60, ge=1)
    default_owner_reminder_max_attempts: int = Field(default=3, ge=1)
    job_max_retries: int = Field(default=3, ge=1)
    job_retry_delay_seconds: int = Field(default=300, ge=1)
    job_processing_timeout_minutes: int = Field(default=10, ge=1)

    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
