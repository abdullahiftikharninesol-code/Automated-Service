import uuid
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import LeadSource, LeadStatus, Urgency


class Lead(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_leads_org_status_created", "organization_id", "status", "created_at"),
        Index("ix_leads_org_followup", "organization_id", "next_followup_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    customer_name: Mapped[str] = mapped_column(String(160))
    customer_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    customer_phone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    intent: Mapped[str | None] = mapped_column(String(80), nullable=True)
    category_or_service: Mapped[str | None] = mapped_column(String(160), nullable=True)
    service_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    product_variant: Mapped[str | None] = mapped_column(String(160), nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_additional_fields: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    message: Mapped[str] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    urgency: Mapped[Urgency] = mapped_column(Enum(Urgency), default=Urgency.NORMAL)
    preferred_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    preferred_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    preferred_date_text: Mapped[str | None] = mapped_column(String(80), nullable=True)
    preferred_time_text: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source: Mapped[LeadSource] = mapped_column(Enum(LeadSource), default=LeadSource.MANUAL)
    status: Mapped[LeadStatus] = mapped_column(Enum(LeadStatus), default=LeadStatus.NEW)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    booked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lost_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organization = relationship("Organization", back_populates="leads")
    events = relationship("LeadEvent", back_populates="lead", cascade="all, delete-orphan")
    followups = relationship("FollowUp", back_populates="lead", cascade="all, delete-orphan")
    inbound_messages = relationship(
        "InboundMessage",
        back_populates="lead",
        cascade="all, delete-orphan",
        order_by="InboundMessage.received_at",
    )

    @property
    def latest_inbound_message(self) -> str:
        if self.inbound_messages:
            return self.inbound_messages[-1].message_text
        return self.message
