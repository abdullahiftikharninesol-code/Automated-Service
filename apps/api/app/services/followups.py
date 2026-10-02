import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.enums import FollowUpChannel, FollowUpStatus, LeadEventType
from app.models.followup import FollowUp
from app.models.lead import Lead
from app.models.lead_event import LeadEvent
from app.models.organization import Organization


class FollowUpService:
    def __init__(self, db: Session):
        self.db = db

    def schedule_for_new_lead(self, lead: Lead, organization: Organization) -> None:
        now = lead.created_at or datetime.now(UTC)
        reminders = [
            (
                now + timedelta(minutes=organization.followup_new_lead_minutes),
                "New lead needs attention",
            ),
            (
                now + timedelta(hours=organization.followup_second_reminder_hours),
                "New lead is still waiting for contact",
            ),
            (
                now + timedelta(days=organization.followup_final_days),
                "Lead remains unresolved",
            ),
        ]
        self._add_reminders(lead, reminders, FollowUpChannel.INTERNAL)

    def schedule_for_contacted(self, lead: Lead, organization: Organization) -> None:
        self.cancel_pending(lead.id, lead.organization_id)
        now = datetime.now(UTC)
        reminders = [
            (
                now + timedelta(hours=organization.followup_contacted_hours),
                "Generate a customer follow-up suggestion",
            ),
            (
                now + timedelta(days=organization.followup_final_days),
                "Contacted lead remains unresolved",
            ),
        ]
        self._add_reminders(lead, reminders, FollowUpChannel.EMAIL)

    def _add_reminders(
        self,
        lead: Lead,
        reminders: list[tuple[datetime, str]],
        channel: FollowUpChannel,
    ) -> None:
        for scheduled_for, message in reminders:
            self.db.add(
                FollowUp(
                    lead_id=lead.id,
                    organization_id=lead.organization_id,
                    scheduled_for=scheduled_for,
                    message=message,
                    channel=channel,
                )
            )
        lead.next_followup_at = min(item[0] for item in reminders)
        self.db.add(
            LeadEvent(
                lead_id=lead.id,
                organization_id=lead.organization_id,
                event_type=LeadEventType.FOLLOWUP_SCHEDULED,
                event_metadata={"next_followup_at": lead.next_followup_at.isoformat()},
            )
        )

    def cancel_pending(self, lead_id: uuid.UUID, organization_id: uuid.UUID) -> None:
        self.db.execute(
            update(FollowUp)
            .where(
                FollowUp.lead_id == lead_id,
                FollowUp.organization_id == organization_id,
                FollowUp.status == FollowUpStatus.PENDING,
            )
            .values(status=FollowUpStatus.CANCELLED, completed_at=datetime.now(UTC))
        )

    def process_due(self, organization_id: uuid.UUID, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        due = list(
            self.db.scalars(
                select(FollowUp).where(
                    FollowUp.organization_id == organization_id,
                    FollowUp.status == FollowUpStatus.PENDING,
                    FollowUp.scheduled_for <= now,
                )
            )
        )
        affected_leads: set[uuid.UUID] = set()
        for reminder in due:
            reminder.status = FollowUpStatus.COMPLETED
            reminder.completed_at = now
            affected_leads.add(reminder.lead_id)
            self.db.add(
                LeadEvent(
                    lead_id=reminder.lead_id,
                    organization_id=organization_id,
                    event_type=LeadEventType.FOLLOWUP_GENERATED,
                    event_metadata={"message": reminder.message or "Follow-up reminder due"},
                )
            )
        for lead_id in affected_leads:
            lead = self.db.get(Lead, lead_id)
            next_due = self.db.scalar(
                select(FollowUp.scheduled_for)
                .where(
                    FollowUp.lead_id == lead_id,
                    FollowUp.organization_id == organization_id,
                    FollowUp.status == FollowUpStatus.PENDING,
                )
                .order_by(FollowUp.scheduled_for.asc())
                .limit(1)
            )
            if lead:
                lead.next_followup_at = next_due
        self.db.flush()
        return len(due)
