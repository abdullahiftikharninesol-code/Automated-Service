from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import FollowUpChannel, FollowUpStatus, FollowUpType
from app.schemas.common import ORMModel


class FollowUpResponse(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    lead_id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    due_at: datetime
    type: FollowUpType
    status: FollowUpStatus
    attempt_count: int
    last_attempt_at: datetime | None = None
    processed_at: datetime | None = None
    failure_reason: str | None = None
    message: str | None = None
    channel: FollowUpChannel
    created_at: datetime
    updated_at: datetime


class FollowUpListResponse(BaseModel):
    items: list[FollowUpResponse]
    total: int
