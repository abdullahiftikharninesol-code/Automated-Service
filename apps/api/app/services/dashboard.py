import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import LeadStatus, Urgency
from app.models.lead import Lead
from app.schemas.dashboard import DashboardCounts, DashboardResponse


class DashboardService:
    def __init__(self, db: Session):
        self.db = db

    def get(self, organization_id: uuid.UUID) -> DashboardResponse:
        leads = list(
            self.db.scalars(
                select(Lead)
                .where(Lead.organization_id == organization_id)
                .order_by(Lead.created_at.desc())
            )
        )
        now = datetime.now(UTC)

        def needs_attention(lead: Lead) -> bool:
            if lead.status == LeadStatus.NEW and lead.urgency in {
                Urgency.HIGH,
                Urgency.EMERGENCY,
            }:
                return True
            due = lead.next_followup_at
            if due and due.tzinfo is None:
                due = due.replace(tzinfo=UTC)
            return lead.status in {LeadStatus.NEW, LeadStatus.CONTACTED} and bool(
                due and due <= now
            )

        attention = [lead for lead in leads if needs_attention(lead)]
        return DashboardResponse(
            counts=DashboardCounts(
                new=sum(lead.status == LeadStatus.NEW for lead in leads),
                needs_attention=len(attention),
                contacted=sum(lead.status == LeadStatus.CONTACTED for lead in leads),
                booked=sum(lead.status == LeadStatus.BOOKED for lead in leads),
                lost=sum(lead.status == LeadStatus.LOST for lead in leads),
            ),
            needs_attention=attention[:10],
            recent_leads=leads[:10],
        )
