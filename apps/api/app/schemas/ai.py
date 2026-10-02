from pydantic import BaseModel, Field

from app.models.enums import Urgency


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
    additional_fields: dict[str, str | int | float | bool] = Field(default_factory=dict)
