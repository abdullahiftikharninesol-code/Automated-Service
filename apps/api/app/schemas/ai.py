from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import Urgency


class QualificationFieldDefinition(BaseModel):
    key: str
    label: str
    field_type: str = "TEXT"
    required: bool = True
    description: str | None = None
    options: list[str] | None = None
    example_values: list[Any] | None = None


class LeadExtractionResult(BaseModel):
    intent: str | None = None
    category_or_service: str | None = None
    urgency: Urgency = Urgency.NORMAL
    location: str | None = None
    preferred_date: str | None = None
    preferred_time: str | None = None
    product_name: str | None = None
    product_variant: str | None = None
    quantity: int | None = Field(default=None, ge=1)
    summary: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0, le=1)
    additional_fields: dict[str, Any] = Field(default_factory=dict)
    # Extensible generic qualification dictionary
    extracted_qualification_fields: dict[str, Any] = Field(default_factory=dict)
    field_confidences: dict[str, float] = Field(default_factory=dict)
