from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.enums import FollowUpChannel, FollowUpStatus, FollowUpType, LeadEventType
from app.models.followup import FollowUp
from app.models.lead import Lead
from app.models.lead_event import LeadEvent
from app.models.organization import Organization
from app.services.followup_processor import FollowUpProcessor


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

    def schedule_owner_response_reminder(
        self,
        conversation: Conversation,
        lead: Lead,
        organization: Organization,
        now: datetime | None = None,
    ) -> FollowUp:
        """Schedule or reschedule an owner response reminder.

        Rule: Maintain at most ONE active pending OWNER_RESPONSE_REMINDER per conversation.
        If customer sends another inbound message while one is already pending,
        update/reschedule that pending reminder from the most recent inbound time.
        """
        now = now or datetime.now(UTC)
        delay_minutes = organization.owner_reminder_delay_minutes or 60
        target_due = now + timedelta(minutes=delay_minutes)

        existing = self.db.scalar(
            select(FollowUp).where(
                FollowUp.organization_id == organization.id,
                FollowUp.conversation_id == conversation.id,
                FollowUp.type == FollowUpType.OWNER_RESPONSE_REMINDER,
                FollowUp.status == FollowUpStatus.PENDING,
            )
        )

        if existing:
            existing.due_at = target_due
            existing.attempt_count = 0
            existing.message = "Customer waiting for business owner response"
            self.db.flush()
            return existing

        reminder = FollowUp(
            lead_id=lead.id,
            organization_id=organization.id,
            conversation_id=conversation.id,
            due_at=target_due,
            type=FollowUpType.OWNER_RESPONSE_REMINDER,
            status=FollowUpStatus.PENDING,
            attempt_count=0,
            channel=FollowUpChannel.INTERNAL,
            message="Customer waiting for business owner response",
        )
        self.db.add(reminder)
        self.db.add(
            LeadEvent(
                lead_id=lead.id,
                organization_id=organization.id,
                event_type=LeadEventType.OWNER_REMINDER_SCHEDULED,
                event_metadata={
                    "due_at": target_due.isoformat(),
                    "attempt": 1,
                    "conversation_id": str(conversation.id),
                },
            )
        )
        self.db.flush()
        return reminder

    def cancel_pending_owner_reminders(
        self,
        conversation_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> int:
        """Cancel pending OWNER_RESPONSE_REMINDER followups for a conversation
        when the owner replies.
        """
        pending = list(
            self.db.scalars(
                select(FollowUp).where(
                    FollowUp.organization_id == organization_id,
                    FollowUp.conversation_id == conversation_id,
                    FollowUp.type == FollowUpType.OWNER_RESPONSE_REMINDER,
                    FollowUp.status == FollowUpStatus.PENDING,
                )
            )
        )
        now = datetime.now(UTC)
        for p in pending:
            p.status = FollowUpStatus.CANCELLED
            p.processed_at = now
            p.failure_reason = "Owner replied"
            self.db.add(
                LeadEvent(
                    lead_id=p.lead_id,
                    organization_id=organization_id,
                    event_type=LeadEventType.OWNER_REMINDER_CANCELLED,
                    event_metadata={
                        "reason": "Owner replied with outbound message",
                        "reminder_id": str(p.id),
                    },
                )
            )
        self.db.flush()
        return len(pending)

    def _add_reminders(
        self,
        lead: Lead,
        reminders: list[tuple[datetime, str]],
        channel: FollowUpChannel,
    ) -> None:
        for due_at, message in reminders:
            self.db.add(
                FollowUp(
                    lead_id=lead.id,
                    organization_id=lead.organization_id,
                    due_at=due_at,
                    type=FollowUpType.LEAD_FOLLOWUP,
                    status=FollowUpStatus.PENDING,
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
        """Cancel all pending followups for a lead."""
        pending = list(
            self.db.scalars(
                select(FollowUp).where(
                    FollowUp.lead_id == lead_id,
                    FollowUp.organization_id == organization_id,
                    FollowUp.status == FollowUpStatus.PENDING,
                )
            )
        )
        now = datetime.now(UTC)
        for p in pending:
            p.status = FollowUpStatus.CANCELLED
            p.processed_at = now
            p.failure_reason = "Lead status updated or cancelled"
            if p.type == FollowUpType.OWNER_RESPONSE_REMINDER:
                self.db.add(
                    LeadEvent(
                        lead_id=lead_id,
                        organization_id=organization_id,
                        event_type=LeadEventType.OWNER_REMINDER_CANCELLED,
                        event_metadata={
                            "reason": "Lead status transition / cancelled",
                            "reminder_id": str(p.id),
                        },
                    )
                )
        self.db.flush()

    def process_due(self, organization_id: uuid.UUID, now: datetime | None = None) -> int:
        return FollowUpProcessor(self.db).process_due(organization_id=organization_id, now=now)
