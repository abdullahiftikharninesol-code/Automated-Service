import uuid
from datetime import datetime

from pydantic import Field

from app.models.enums import BusinessType
from app.schemas.common import ORMModel


class OrganizationResponse(ORMModel):
    id: uuid.UUID
    name: str
    industry: str
    business_type: BusinessType
    timezone: str
    duplicate_window_minutes: int
    default_phone_region: str | None = None
    followup_new_lead_minutes: int
    followup_second_reminder_hours: int
    followup_contacted_hours: int
    followup_final_days: int
    owner_reminder_delay_minutes: int = 60
    owner_reminder_repeat_minutes: int = 60
    owner_reminder_max_attempts: int = 3
    created_at: datetime
    updated_at: datetime


class OrganizationUpdate(ORMModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    industry: str | None = Field(default=None, min_length=2, max_length=80)
    business_type: BusinessType | None = None
    timezone: str | None = Field(default=None, min_length=3, max_length=80)
    default_phone_region: str | None = Field(default=None, max_length=10)
    duplicate_window_minutes: int | None = Field(default=None, ge=1, le=10080)
    followup_new_lead_minutes: int | None = Field(default=None, ge=1, le=1440)
    followup_second_reminder_hours: int | None = Field(default=None, ge=1, le=168)
    followup_contacted_hours: int | None = Field(default=None, ge=1, le=720)
    followup_final_days: int | None = Field(default=None, ge=1, le=90)
    owner_reminder_delay_minutes: int | None = Field(default=None, ge=1, le=10080)
    owner_reminder_repeat_minutes: int | None = Field(default=None, ge=1, le=10080)
    owner_reminder_max_attempts: int | None = Field(default=None, ge=1, le=50)


class OrganizationIntegrationResponse(ORMModel):
    inbound_webhook_url: str
    embed_form_url: str
    embed_code: str
    email_provider: str
    email_configured: bool
    webhook_secret_configured: bool = False


class WebhookSecretRotateResponse(ORMModel):
    webhook_secret: str
