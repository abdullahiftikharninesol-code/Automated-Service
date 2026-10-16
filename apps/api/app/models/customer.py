from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.conversation import Conversation
    from app.models.lead import Lead
    from app.models.organization import Organization


class Customer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (
        Index("ix_customers_org", "organization_id"),
        Index("ix_customers_org_email_norm", "organization_id", "email_normalized"),
        Index("ix_customers_org_phone_norm", "organization_id", "phone_normalized"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_normalized: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    phone_normalized: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    customer_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped[Organization] = relationship("Organization", back_populates="customers")
    conversations: Mapped[list[Conversation]] = relationship(
        "Conversation", back_populates="customer"
    )
    leads: Mapped[list[Lead]] = relationship("Lead", back_populates="customer")
