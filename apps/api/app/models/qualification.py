import uuid
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import QualificationFieldType


class QualificationField(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "qualification_fields"
    __table_args__ = (
        UniqueConstraint("organization_id", "key", name="uq_qualification_fields_org_key"),
        Index("ix_qualification_fields_org_order", "organization_id", "enabled", "sort_order"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    field_type: Mapped[QualificationFieldType] = mapped_column(
        Enum(QualificationFieldType), default=QualificationFieldType.TEXT
    )
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    question_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    options: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    example_values: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)

    organization = relationship("Organization", back_populates="qualification_fields")
