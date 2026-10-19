from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import (
    ConversationStatus,
    InboundChannel,
    MessageDeliveryStatus,
    MessageDirection,
    MessageSenderType,
    WaitingOn,
)
from app.schemas.auth import ORMModel
from app.schemas.customer import CustomerResponse


class ConversationMessageCreate(BaseModel):
    body: str = Field(min_length=1)
    channel: InboundChannel | None = None


class ConversationMessageResponse(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    conversation_id: uuid.UUID
    direction: MessageDirection
    channel: InboundChannel
    sender_type: MessageSenderType
    body: str
    external_message_id: str | None = None
    delivery_status: MessageDeliveryStatus | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="message_metadata")
    sent_at: datetime
    created_at: datetime


class ConversationResponse(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    customer_id: uuid.UUID | None = None
    lead_id: uuid.UUID | None = None
    channel: InboundChannel
    status: ConversationStatus
    waiting_on: WaitingOn
    subject: str | None = None
    external_thread_id: str | None = None
    last_message_at: datetime | None = None
    last_inbound_at: datetime | None = None
    last_outbound_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ConversationDetailResponse(ConversationResponse):
    customer: CustomerResponse | None = None
    messages: list[ConversationMessageResponse] = Field(default_factory=list)


class ConversationListResponse(BaseModel):
    items: list[ConversationResponse]
    total: int
