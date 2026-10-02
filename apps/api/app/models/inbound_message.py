import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDPrimaryKeyMixin, utcnow
from app.models.enums import InboundChannel


class InboundMessage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "inbound_messages"
    __table_args__ = (
        Index("ix_inbound_messages_org_received", "organization_id", "received_at"),
        Index("ix_inbound_messages_org_lead", "organization_id", "lead_id"),
        UniqueConstraint(
            "organization_id",
            "channel",
            "external_message_id",
            name="uq_inbound_messages_external",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=True, index=True
    )
    channel: Mapped[InboundChannel] = mapped_column(Enum(InboundChannel))
    external_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_name: Mapped[str] = mapped_column(String(160))
    customer_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    customer_phone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    message_text: Mapped[str] = mapped_column(Text)
    inbound_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    organization = relationship("Organization", back_populates="inbound_messages")
    lead = relationship("Lead", back_populates="inbound_messages")
