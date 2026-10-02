import uuid
from datetime import date, datetime, time
from typing import Any, Self

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.models.enums import InboundChannel, LeadStatus
from app.schemas.common import ORMModel


class InboundMessageCreate(BaseModel):
    channel: InboundChannel
    external_message_id: str | None = Field(default=None, max_length=255)
    customer_name: str = Field(min_length=1, max_length=160)
    customer_email: EmailStr | None = None
    customer_phone: str | None = Field(default=None, max_length=60)
    message_text: str = Field(min_length=2, max_length=5000)
    category_or_service: str | None = Field(default=None, max_length=160)
    location: str | None = Field(default=None, max_length=255)
    preferred_date: date | None = None
    preferred_time: time | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_contact_method(self) -> Self:
        if not self.customer_email and not self.customer_phone:
            raise ValueError("Provide at least an email address or phone number")
        return self


class WebsiteWebhookCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=60)
    message: str = Field(min_length=2, max_length=5000)
    product_or_service: str | None = Field(default=None, max_length=160)
    location: str | None = Field(default=None, max_length=255)
    preferred_date: date | None = None
    preferred_time: time | None = None
    external_message_id: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_contact_method(self) -> Self:
        if not self.email and not self.phone:
            raise ValueError("Provide at least an email address or phone number")
        return self


class InboundProcessResponse(BaseModel):
    success: bool = True
    lead_id: uuid.UUID
    status: LeadStatus


class InboundMessageResponse(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    lead_id: uuid.UUID | None
    channel: InboundChannel
    external_message_id: str | None
    customer_name: str
    customer_email: EmailStr | None
    customer_phone: str | None
    message_text: str
    metadata: dict[str, Any] = Field(validation_alias="inbound_metadata")
    received_at: datetime
    processed_at: datetime | None
    created_at: datetime
