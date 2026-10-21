import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import QualificationFieldType, QualificationStatus

KEY_REGEX = re.compile(r"^[a-z0-9_]{2,64}$")
RESERVED_KEYS = {
    "id",
    "organization_id",
    "created_at",
    "updated_at",
    "status",
    "lead_id",
    "conversation_id",
}


class QualificationFieldBase(BaseModel):
    label: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1000)
    field_type: QualificationFieldType = QualificationFieldType.TEXT
    required: bool = True
    enabled: bool = True
    sort_order: int = Field(default=0, ge=0, le=1000)
    question_text: str | None = Field(default=None, max_length=500)
    options: list[str] | None = None
    example_values: list[Any] | None = None


class QualificationFieldCreate(QualificationFieldBase):
    key: str = Field(min_length=2, max_length=64)

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not KEY_REGEX.match(cleaned):
            raise ValueError(
                "Key must contain only lowercase alphanumeric characters "
                "and underscores, length 2-64"
            )
        if cleaned in RESERVED_KEYS:
            raise ValueError(
                f"Key '{cleaned}' is reserved and cannot be used as a qualification field"
            )
        return cleaned


class QualificationFieldUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1000)
    field_type: QualificationFieldType | None = None
    required: bool | None = None
    enabled: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=1000)
    question_text: str | None = Field(default=None, max_length=500)
    options: list[str] | None = None
    example_values: list[Any] | None = None


class QualificationFieldResponse(QualificationFieldBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    key: str
    created_at: datetime
    updated_at: datetime


class QualificationFieldListResponse(BaseModel):
    items: list[QualificationFieldResponse]


class ApplyTemplateRequest(BaseModel):
    template_name: str
    replace_existing: bool = False


class QualificationStateResponse(BaseModel):
    status: QualificationStatus
    qualifications: dict[str, Any]
    missing_required_keys: list[str]
    missing_required_labels: list[str]
    completed_at: datetime | None = None
