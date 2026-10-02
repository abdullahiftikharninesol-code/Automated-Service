import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDPrimaryKeyMixin, utcnow
from app.models.enums import FollowUpChannel, FollowUpStatus


class FollowUp(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "followups"
    __table_args__ = (
        Index("ix_followups_org_status_scheduled", "organization_id", "status", "scheduled_for"),
    )

    lead_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[FollowUpStatus] = mapped_column(
        Enum(FollowUpStatus), default=FollowUpStatus.PENDING
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel: Mapped[FollowUpChannel] = mapped_column(Enum(FollowUpChannel))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lead = relationship("Lead", back_populates="followups")
