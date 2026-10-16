import uuid
from datetime import date, datetime, time
from typing import Self

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.models.enums import LeadEventType, LeadSource, LeadStatus, Urgency
from app.schemas.common import ORMModel


class LeadCreate(BaseModel):
    customer_name: str = Field(min_length=1, max_length=160)
    customer_email: EmailStr | None = None
    customer_phone: str | None = Field(default=None, max_length=60)
    service_type: str | None = Field(default=None, max_length=160)
    message: str = Field(min_length=2, max_length=5000)
    location: str | None = Field(default=None, max_length=255)
    preferred_date: date | None = None
    preferred_time: time | None = None
    source: LeadSource = LeadSource.MANUAL

    @model_validator(mode="after")
    def require_contact_method(self) -> Self:
        if not self.customer_email and not self.customer_phone:
            raise ValueError("Provide at least an email address or phone number")
        return self


class PublicInquiryCreate(BaseModel):
    customer_name: str = Field(min_length=1, max_length=160)
    customer_email: EmailStr
    customer_phone: str | None = Field(default=None, max_length=60)
    service_type: str | None = Field(default=None, max_length=160)
    location: str | None = Field(default=None, max_length=255)
    preferred_date: date | None = None
    preferred_time: time | None = None
    message: str = Field(min_length=2, max_length=5000)


class LeadUpdate(BaseModel):
    customer_name: str | None = Field(default=None, min_length=1, max_length=160)
    customer_email: EmailStr | None = None
    customer_phone: str | None = Field(default=None, max_length=60)
    category_or_service: str | None = Field(default=None, max_length=160)
    service_type: str | None = Field(default=None, max_length=160)
    product_name: str | None = Field(default=None, max_length=160)
    product_variant: str | None = Field(default=None, max_length=160)
    message: str | None = Field(default=None, min_length=2, max_length=5000)
    location: str | None = Field(default=None, max_length=255)
    urgency: Urgency | None = None
    preferred_date: date | None = None
    preferred_time: time | None = None


class LeadStatusUpdate(BaseModel):
    status: LeadStatus


class NoteCreate(BaseModel):
    note: str = Field(min_length=1, max_length=3000)


class LeadResponse(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    customer_name: str
    customer_email: EmailStr | None
    customer_phone: str | None
    customer_phone_normalized: str | None = None
    intent: str | None
    category_or_service: str | None
    service_type: str | None
    product_name: str | None
    product_variant: str | None
    quantity: int | None
    ai_additional_fields: dict[str, object]
    message: str
    location: str | None
    urgency: Urgency
    preferred_date: date | None
    preferred_time: time | None
    preferred_date_text: str | None
    preferred_time_text: str | None
    source: LeadSource
    status: LeadStatus
    ai_summary: str | None
    latest_inbound_message: str
    created_at: datetime
    updated_at: datetime
    last_contacted_at: datetime | None
    next_followup_at: datetime | None
    booked_at: datetime | None
    lost_at: datetime | None
    customer_id: uuid.UUID | None = None
    primary_conversation_id: uuid.UUID | None = None


class LeadListResponse(BaseModel):
    items: list[LeadResponse]
    total: int


class LeadEventResponse(ORMModel):
    id: uuid.UUID
    lead_id: uuid.UUID
    organization_id: uuid.UUID
    event_type: LeadEventType
    metadata: dict[str, object] = Field(validation_alias="event_metadata")
    created_at: datetime


class FollowUpDraftResponse(BaseModel):
    message: str


class PublicInquiryResponse(BaseModel):
    id: uuid.UUID
    message: str = "Thanks — your request was received."
