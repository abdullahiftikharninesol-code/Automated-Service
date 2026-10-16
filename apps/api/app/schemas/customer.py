from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.auth import ORMModel


class CustomerResponse(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str | None = None
    email: str | None = None
    email_normalized: str | None = None
    phone: str | None = None
    phone_normalized: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="customer_metadata")
    last_contact_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CustomerListResponse(BaseModel):
    items: list[CustomerResponse]
    total: int
