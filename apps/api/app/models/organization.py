from sqlalchemy import Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import BusinessType


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(160))
    industry: Mapped[str] = mapped_column(String(80), default="General")
    business_type: Mapped[BusinessType] = mapped_column(
        Enum(BusinessType), default=BusinessType.GENERAL
    )
    timezone: Mapped[str] = mapped_column(String(80), default="America/New_York")
    default_phone_region: Mapped[str | None] = mapped_column(String(10), nullable=True)
    inbound_webhook_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    duplicate_window_minutes: Mapped[int] = mapped_column(Integer, default=60)
    followup_new_lead_minutes: Mapped[int] = mapped_column(Integer, default=30)
    followup_second_reminder_hours: Mapped[int] = mapped_column(Integer, default=2)
    followup_contacted_hours: Mapped[int] = mapped_column(Integer, default=24)
    followup_final_days: Mapped[int] = mapped_column(Integer, default=3)
    owner_reminder_delay_minutes: Mapped[int] = mapped_column(Integer, default=60)
    owner_reminder_repeat_minutes: Mapped[int] = mapped_column(Integer, default=60)
    owner_reminder_max_attempts: Mapped[int] = mapped_column(Integer, default=3)

    users = relationship("User", back_populates="organization", cascade="all, delete-orphan")
    leads = relationship("Lead", back_populates="organization", cascade="all, delete-orphan")
    inbound_messages = relationship(
        "InboundMessage", back_populates="organization", cascade="all, delete-orphan"
    )
    customers = relationship(
        "Customer", back_populates="organization", cascade="all, delete-orphan"
    )
    conversations = relationship(
        "Conversation", back_populates="organization", cascade="all, delete-orphan"
    )
    conversation_messages = relationship(
        "ConversationMessage", back_populates="organization", cascade="all, delete-orphan"
    )
