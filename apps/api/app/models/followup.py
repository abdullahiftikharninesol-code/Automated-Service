import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDPrimaryKeyMixin, utcnow
from app.models.enums import FollowUpChannel, FollowUpStatus, FollowUpType


class FollowUp(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "followups"
    __table_args__ = (
        Index("ix_followups_org_status_due", "organization_id", "status", "due_at"),
        Index("ix_followups_status_due", "status", "due_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    type: Mapped[FollowUpType] = mapped_column(
        Enum(FollowUpType), default=FollowUpType.LEAD_FOLLOWUP
    )
    status: Mapped[FollowUpStatus] = mapped_column(
        Enum(FollowUpStatus), default=FollowUpStatus.PENDING
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel: Mapped[FollowUpChannel] = mapped_column(
        Enum(FollowUpChannel), default=FollowUpChannel.INTERNAL
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    lead = relationship("Lead", back_populates="followups")
    conversation = relationship("Conversation")
    organization = relationship("Organization")

    @property
    def scheduled_for(self) -> datetime:
        return self.due_at

    @scheduled_for.setter
    def scheduled_for(self, value: datetime) -> None:
        self.due_at = value

    @property
    def completed_at(self) -> datetime | None:
        return self.processed_at

    @completed_at.setter
    def completed_at(self, value: datetime | None) -> None:
        self.processed_at = value
