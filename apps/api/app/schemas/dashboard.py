from pydantic import BaseModel

from app.schemas.lead import LeadResponse


class DashboardCounts(BaseModel):
    new: int
    needs_attention: int
    contacted: int
    booked: int
    lost: int


class DashboardResponse(BaseModel):
    counts: DashboardCounts
    needs_attention: list[LeadResponse]
    recent_leads: list[LeadResponse]
