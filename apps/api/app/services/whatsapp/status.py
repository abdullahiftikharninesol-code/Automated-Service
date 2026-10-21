from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.conversation_message import ConversationMessage
from app.models.enums import InboundChannel, MessageDeliveryStatus

logger = logging.getLogger("missed_lead_rescue.whatsapp.status")

# Numeric rank for forward-only delivery progression
STATUS_PROGRESSION_RANK: dict[MessageDeliveryStatus, int] = {
    MessageDeliveryStatus.PENDING: 0,
    MessageDeliveryStatus.SENT: 1,
    MessageDeliveryStatus.DELIVERED: 2,
    MessageDeliveryStatus.READ: 3,
}

META_STATUS_MAP: dict[str, MessageDeliveryStatus] = {
    "sent": MessageDeliveryStatus.SENT,
    "delivered": MessageDeliveryStatus.DELIVERED,
    "read": MessageDeliveryStatus.READ,
    "failed": MessageDeliveryStatus.FAILED,
}


class WhatsAppStatusHandler:
    def __init__(self, db: Session):
        self.db = db

    def handle_status_update(
        self,
        organization_id: uuid.UUID,
        wamid: str,
        status_name: str,
        status_payload: dict[str, Any],
    ) -> bool:
        """Process Meta delivery status callbacks (sent, delivered, read, failed).

        Guarantees:
        - Strict idempotency (repeated callbacks do not cause errors)
        - Forward-only status progression (no regression from READ to DELIVERED)
        - Safe error recording on failure
        """
        new_status = META_STATUS_MAP.get(status_name.lower())
        if not new_status:
            logger.info(
                "[WHATSAPP_STATUS] Ignoring unknown status '%s' for wamid=%s", status_name, wamid
            )
            return False

        msg = self.db.scalar(
            select(ConversationMessage).where(
                ConversationMessage.organization_id == organization_id,
                ConversationMessage.channel == InboundChannel.WHATSAPP,
                ConversationMessage.external_message_id == wamid,
            )
        )
        if not msg:
            logger.info(
                "[WHATSAPP_STATUS] No ConversationMessage found for org=%s wamid=%s "
                "(may be non-system message)",
                organization_id,
                wamid,
            )
            return False

        current_status = msg.delivery_status or MessageDeliveryStatus.PENDING

        # Check for failure
        if new_status == MessageDeliveryStatus.FAILED:
            msg.delivery_status = MessageDeliveryStatus.FAILED
            errors = status_payload.get("errors", [])
            meta = dict(msg.message_metadata or {})
            meta["delivery_error"] = {
                "errors": errors,
                "timestamp": status_payload.get("timestamp"),
            }
            msg.message_metadata = meta
            self.db.commit()
            logger.warning("[WHATSAPP_STATUS] Message %s marked FAILED: %s", wamid, errors)
            return True

        # Forward-only status progression check
        current_rank = STATUS_PROGRESSION_RANK.get(current_status, 0)
        new_rank = STATUS_PROGRESSION_RANK.get(new_status, 0)

        if new_rank > current_rank:
            msg.delivery_status = new_status
            meta = dict(msg.message_metadata or {})
            meta[f"status_{new_status.value.lower()}_at"] = status_payload.get("timestamp")
            msg.message_metadata = meta
            self.db.commit()
            logger.info(
                "[WHATSAPP_STATUS] Updated message %s status from %s to %s",
                wamid,
                current_status.value,
                new_status.value,
            )
            return True
        else:
            logger.debug(
                "[WHATSAPP_STATUS] Ignored redundant or regressional status '%s' "
                "(current: '%s') for wamid=%s",
                new_status.value,
                current_status.value,
                wamid,
            )
            return False
