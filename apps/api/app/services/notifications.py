from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.models.lead import Lead

logger = logging.getLogger("missed_lead_rescue.notifications")


@dataclass(frozen=True)
class OwnerNotification:
    organization_id: uuid.UUID
    lead_id: uuid.UUID | None
    conversation_id: uuid.UUID | None
    type: str
    title: str
    body: str
    metadata: dict[str, Any] = field(default_factory=dict)


class OwnerNotificationProvider(ABC):
    @abstractmethod
    def send_owner_notification(self, notification: OwnerNotification) -> bool:
        """Send owner notification.

        Must return True on success or raise an Exception / return False on failure.
        """
        pass


class ConsoleOwnerNotificationProvider(OwnerNotificationProvider):
    def send_owner_notification(self, notification: OwnerNotification) -> bool:
        # Structured log safe for production (no secrets exposed)
        logger.info(
            "[OWNER_NOTIFICATION] org_id=%s lead_id=%s conv_id=%s type=%s title='%s' body='%s'",
            notification.organization_id,
            notification.lead_id,
            notification.conversation_id,
            notification.type,
            notification.title,
            notification.body.replace("\n", " | "),
        )
        return True


class NotificationService:
    def __init__(self, provider: OwnerNotificationProvider | None = None):
        self.provider = provider or ConsoleOwnerNotificationProvider()

    def send_owner_notification(self, notification: OwnerNotification) -> bool:
        return self.provider.send_owner_notification(notification)


def format_owner_reminder_content(
    lead: Lead,
    channel_name: str = "Website Form",
    elapsed_minutes: int = 60,
) -> tuple[str, str]:
    """Generate deterministic, human-readable owner reminder title and body."""
    customer_name = lead.customer_name or "New Customer"
    inquiry_snippet = lead.latest_inbound_message or lead.message or "Inquiry details"
    if len(inquiry_snippet) > 120:
        inquiry_snippet = inquiry_snippet[:117] + "..."

    if elapsed_minutes < 60:
        waiting_str = f"{elapsed_minutes} minutes"
    elif elapsed_minutes % 60 == 0:
        hours = elapsed_minutes // 60
        waiting_str = f"{hours} hour" if hours == 1 else f"{hours} hours"
    else:
        hours = elapsed_minutes // 60
        mins = elapsed_minutes % 60
        waiting_str = f"{hours}h {mins}m"

    title = f"Customer inquiry waiting for response: {customer_name}"
    body = (
        f"New customer inquiry is still waiting for a response.\n"
        f"Customer: {customer_name}\n"
        f"Channel: {channel_name}\n"
        f"Inquiry: {inquiry_snippet}\n"
        f"Waiting: {waiting_str}"
    )
    return title, body
