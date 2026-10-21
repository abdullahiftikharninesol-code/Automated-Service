from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.conversation import Conversation
from app.models.enums import (
    ConversationStatus,
    FollowUpChannel,
    FollowUpStatus,
    FollowUpType,
    LeadEventType,
    LeadStatus,
)
from app.models.followup import FollowUp
from app.models.lead import Lead
from app.models.lead_event import LeadEvent
from app.models.organization import Organization
from app.services.notifications import (
    NotificationService,
    OwnerNotification,
    format_owner_reminder_content,
)

logger = logging.getLogger("missed_lead_rescue.followup_processor")


def ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class FollowUpProcessor:
    def __init__(
        self,
        db: Session,
        notifications: NotificationService | None = None,
    ):
        self.db = db
        self.notifications = notifications or NotificationService()
        self.settings = get_settings()

    def claim_due(
        self,
        organization_id: uuid.UUID | None = None,
        now: datetime | None = None,
        batch_size: int = 50,
    ) -> list[uuid.UUID]:
        """Claim due PENDING and stale PROCESSING followups in a dedicated, short-lived transaction.

        Uses SELECT ... FOR UPDATE SKIP LOCKED on PostgreSQL to allow multiple concurrent workers
        to claim distinct due rows without colliding.
        """
        now = now or datetime.now(UTC)
        stale_cutoff = now - timedelta(minutes=self.settings.job_processing_timeout_minutes)

        query = select(FollowUp).where(
            or_(
                and_(
                    FollowUp.status == FollowUpStatus.PENDING,
                    FollowUp.due_at <= now,
                ),
                and_(
                    FollowUp.status == FollowUpStatus.PROCESSING,
                    FollowUp.last_attempt_at <= stale_cutoff,
                ),
            )
        )
        if organization_id:
            query = query.where(FollowUp.organization_id == organization_id)

        query = query.order_by(FollowUp.due_at.asc()).limit(batch_size)

        bind = self.db.get_bind()
        if bind and bind.dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)

        due_rows = list(self.db.scalars(query))
        claimed_ids: list[uuid.UUID] = []

        for row in due_rows:
            row.status = FollowUpStatus.PROCESSING
            row.attempt_count += 1
            row.last_attempt_at = now
            claimed_ids.append(row.id)

        if claimed_ids:
            self.db.commit()
            logger.info("Claimed %d due followup jobs (ids=%s)", len(claimed_ids), claimed_ids)
        else:
            self.db.rollback()

        return claimed_ids

    def process_due(
        self,
        organization_id: uuid.UUID | None = None,
        now: datetime | None = None,
        batch_size: int = 50,
    ) -> int:
        """Process all due followups across all organizations (or for a specific organization).

        Safe claiming occurs first; then each claimed row is processed individually
        in its own transaction.
        """
        now = now or datetime.now(UTC)
        claimed_ids = self.claim_due(
            organization_id=organization_id, now=now, batch_size=batch_size
        )
        if not claimed_ids:
            return 0

        completed_count = 0
        for reminder_id in claimed_ids:
            if self._process_single_claimed(reminder_id, now):
                completed_count += 1

        return completed_count

    def _process_single_claimed(self, reminder_id: uuid.UUID, now: datetime) -> bool:
        reminder = self.db.get(FollowUp, reminder_id)
        if not reminder:
            return False

        # Reminder must still be in PROCESSING status
        if reminder.status != FollowUpStatus.PROCESSING:
            return False

        org = self.db.get(Organization, reminder.organization_id)
        lead = self.db.get(Lead, reminder.lead_id)

        # 1. Validation: Organization and Lead existence
        if not org or not lead:
            reminder.status = FollowUpStatus.CANCELLED
            reminder.failure_reason = "Organization or Lead no longer exists"
            reminder.processed_at = now
            self.db.commit()
            return False

        # 2. Validation: Lead is still actionable (NOT BOOKED or LOST)
        if lead.status in (LeadStatus.BOOKED, LeadStatus.LOST):
            reminder.status = FollowUpStatus.CANCELLED
            reminder.failure_reason = f"Lead is no longer actionable (status: {lead.status.value})"
            reminder.processed_at = now
            self.db.add(
                LeadEvent(
                    lead_id=lead.id,
                    organization_id=org.id,
                    event_type=LeadEventType.OWNER_REMINDER_CANCELLED
                    if reminder.type == FollowUpType.OWNER_RESPONSE_REMINDER
                    else LeadEventType.STATUS_CHANGED,
                    event_metadata={
                        "reason": f"Lead is {lead.status.value}",
                        "followup_id": str(reminder.id),
                    },
                )
            )
            self.db.commit()
            return False

        # 3. Validation: Linked Conversation
        conv: Conversation | None = None
        if reminder.conversation_id:
            conv = self.db.get(Conversation, reminder.conversation_id)
            if conv and conv.status in (ConversationStatus.CLOSED, ConversationStatus.ARCHIVED):
                reminder.status = FollowUpStatus.CANCELLED
                reminder.failure_reason = f"Conversation is {conv.status.value}"
                reminder.processed_at = now
                self.db.commit()
                return False

        # 4. Action execution based on type
        if reminder.type == FollowUpType.OWNER_RESPONSE_REMINDER:
            return self._execute_owner_reminder(reminder, org, lead, conv, now)
        else:
            return self._execute_lead_followup(reminder, org, lead, now)

    def _execute_owner_reminder(
        self,
        reminder: FollowUp,
        org: Organization,
        lead: Lead,
        conv: Conversation | None,
        now: datetime,
    ) -> bool:
        now = ensure_utc(now) or datetime.now(UTC)
        channel_name = conv.channel.value.replace("_", " ").title() if conv else "Website Form"
        created_ref = ensure_utc(lead.created_at) or ensure_utc(reminder.created_at) or now
        elapsed_minutes = max(1, int((now - created_ref).total_seconds() / 60))

        title, body = format_owner_reminder_content(
            lead=lead,
            channel_name=channel_name,
            elapsed_minutes=elapsed_minutes,
        )

        notification = OwnerNotification(
            organization_id=org.id,
            lead_id=lead.id,
            conversation_id=reminder.conversation_id,
            type="OWNER_RESPONSE_REMINDER",
            title=title,
            body=body,
            metadata={
                "attempt_count": reminder.attempt_count,
                "lead_id": str(lead.id),
                "conversation_id": (
                    str(reminder.conversation_id) if reminder.conversation_id else None
                ),
            },
        )

        try:
            success = self.notifications.send_owner_notification(notification)
            if not success:
                raise RuntimeError("Notification provider indicated failure to deliver.")
        except Exception as exc:
            logger.exception("Owner notification failed for reminder %s: %s", reminder.id, exc)
            self._handle_reminder_failure(reminder, lead, org, exc, now)
            return False

        # Mark COMPLETED
        reminder.status = FollowUpStatus.COMPLETED
        reminder.processed_at = now
        reminder.failure_reason = None

        self.db.add(
            LeadEvent(
                lead_id=lead.id,
                organization_id=org.id,
                event_type=LeadEventType.OWNER_REMINDER_SENT,
                event_metadata={
                    "attempt_count": reminder.attempt_count,
                    "title": title,
                    "body": body,
                    "reminder_id": str(reminder.id),
                },
            )
        )

        # Recurring reminder scheduling if attempts remain
        max_attempts = org.owner_reminder_max_attempts
        if reminder.attempt_count < max_attempts:
            repeat_minutes = org.owner_reminder_repeat_minutes
            next_due = now + timedelta(minutes=repeat_minutes)
            next_reminder = FollowUp(
                organization_id=org.id,
                lead_id=lead.id,
                conversation_id=reminder.conversation_id,
                type=FollowUpType.OWNER_RESPONSE_REMINDER,
                due_at=next_due,
                status=FollowUpStatus.PENDING,
                attempt_count=reminder.attempt_count,
                channel=FollowUpChannel.INTERNAL,
                message=reminder.message,
            )
            self.db.add(next_reminder)
            self.db.add(
                LeadEvent(
                    lead_id=lead.id,
                    organization_id=org.id,
                    event_type=LeadEventType.OWNER_REMINDER_SCHEDULED,
                    event_metadata={
                        "due_at": next_due.isoformat(),
                        "attempt": reminder.attempt_count + 1,
                        "reminder_id": str(next_reminder.id),
                    },
                )
            )

        self.db.commit()
        return True

    def _execute_lead_followup(
        self,
        reminder: FollowUp,
        org: Organization,
        lead: Lead,
        now: datetime,
    ) -> bool:
        reminder.status = FollowUpStatus.COMPLETED
        reminder.processed_at = now
        reminder.failure_reason = None

        self.db.add(
            LeadEvent(
                lead_id=lead.id,
                organization_id=org.id,
                event_type=LeadEventType.FOLLOWUP_GENERATED,
                event_metadata={"message": reminder.message or "Follow-up reminder due"},
            )
        )

        # Update lead next_followup_at
        next_due = self.db.scalar(
            select(FollowUp.due_at)
            .where(
                FollowUp.lead_id == lead.id,
                FollowUp.organization_id == org.id,
                FollowUp.status == FollowUpStatus.PENDING,
            )
            .order_by(FollowUp.due_at.asc())
            .limit(1)
        )
        lead.next_followup_at = next_due
        self.db.commit()
        return True

    def _handle_reminder_failure(
        self,
        reminder: FollowUp,
        lead: Lead,
        org: Organization,
        exc: Exception,
        now: datetime,
    ) -> None:
        self.db.rollback()
        # Reload reminder in fresh transaction
        rem = self.db.get(FollowUp, reminder.id)
        if not rem:
            return

        if rem.attempt_count < self.settings.job_max_retries:
            rem.status = FollowUpStatus.PENDING
            rem.due_at = now + timedelta(seconds=self.settings.job_retry_delay_seconds)
            rem.failure_reason = str(exc)
            logger.warning(
                "Reminder %s retry scheduled at %s (attempt %d/%d)",
                rem.id,
                rem.due_at,
                rem.attempt_count,
                self.settings.job_max_retries,
            )
        else:
            rem.status = FollowUpStatus.FAILED
            rem.failure_reason = str(exc)
            rem.processed_at = now
            self.db.add(
                LeadEvent(
                    lead_id=lead.id,
                    organization_id=org.id,
                    event_type=LeadEventType.OWNER_REMINDER_FAILED,
                    event_metadata={
                        "attempt_count": rem.attempt_count,
                        "error": str(exc),
                        "reminder_id": str(rem.id),
                    },
                )
            )
            logger.error("Reminder %s reached MAX retries and marked FAILED: %s", rem.id, exc)

        self.db.commit()
