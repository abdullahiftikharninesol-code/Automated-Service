from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDPrimaryKeyMixin, utcnow
from app.models.enums import (
    InboundChannel,
    MessageDeliveryStatus,
    MessageDirection,
    MessageSenderType,
)

if TYPE_CHECKING:
    from app.models.conversation import Conversation
    from app.models.organization import Organization


class ConversationMessage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        Index("ix_conv_messages_org_conv", "organization_id", "conversation_id"),
        Index("ix_conv_messages_sent", "conversation_id", "sent_at"),
        UniqueConstraint(
            "organization_id",
            "channel",
            "external_message_id",
            name="uq_conv_messages_external",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    direction: Mapped[MessageDirection] = mapped_column(Enum(MessageDirection))
    channel: Mapped[InboundChannel] = mapped_column(Enum(InboundChannel))
    sender_type: Mapped[MessageSenderType] = mapped_column(Enum(MessageSenderType))
    body: Mapped[str] = mapped_column(Text)
    external_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delivery_status: Mapped[MessageDeliveryStatus | None] = mapped_column(
        Enum(MessageDeliveryStatus), nullable=True
    )
    message_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    organization: Mapped[Organization] = relationship(
        "Organization", back_populates="conversation_messages"
    )
    conversation: Mapped[Conversation] = relationship("Conversation", back_populates="messages")
