from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ConversationStatus, InboundChannel, WaitingOn

if TYPE_CHECKING:
    from app.models.conversation_message import ConversationMessage
    from app.models.customer import Customer
    from app.models.lead import Lead
    from app.models.organization import Organization


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_org_status", "organization_id", "status"),
        Index("ix_conversations_org_customer", "organization_id", "customer_id"),
        Index("ix_conversations_org_lead", "organization_id", "lead_id"),
        Index("ix_conversations_org_last_msg", "organization_id", "last_message_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True
    )
    channel: Mapped[InboundChannel] = mapped_column(
        Enum(InboundChannel), default=InboundChannel.WEBSITE_FORM
    )
    status: Mapped[ConversationStatus] = mapped_column(
        Enum(ConversationStatus), default=ConversationStatus.OPEN
    )
    waiting_on: Mapped[WaitingOn] = mapped_column(Enum(WaitingOn), default=WaitingOn.OWNER)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_inbound_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_outbound_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    organization: Mapped[Organization] = relationship(
        "Organization", back_populates="conversations"
    )
    customer: Mapped[Customer | None] = relationship("Customer", back_populates="conversations")
    lead: Mapped[Lead | None] = relationship(
        "Lead", back_populates="conversations", foreign_keys=[lead_id]
    )
    messages: Mapped[list[ConversationMessage]] = relationship(
        "ConversationMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.sent_at",
    )
