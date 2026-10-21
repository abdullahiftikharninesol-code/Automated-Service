from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.conversation import Conversation
from app.models.conversation_message import ConversationMessage
from app.models.enums import (
    InboundChannel,
    MessageDeliveryStatus,
    MessageDirection,
    MessageSenderType,
    WaitingOn,
)
from app.models.organization import Organization
from app.services.whatsapp.provider import WhatsAppProvider, get_whatsapp_provider

logger = logging.getLogger("missed_lead_rescue.outbound_messaging")


class OutboundChannelService:
    """Channel-agnostic service for sending manual outbound replies to customers."""

    def __init__(self, db: Session, whatsapp: WhatsAppProvider | None = None):
        self.db = db
        self.whatsapp = whatsapp or get_whatsapp_provider()
        self.settings = get_settings()

    def send_owner_reply(
        self,
        organization: Organization,
        conversation: Conversation,
        body: str,
    ) -> ConversationMessage:
        """Send an authenticated owner reply on the conversation's active channel."""
        if conversation.organization_id != organization.id:
            raise ValueError("Conversation does not belong to organization")

        # Phase 3A: WhatsApp support
        if conversation.channel == InboundChannel.WHATSAPP:
            return self._send_whatsapp_reply(organization, conversation, body)
        else:
            raise ValueError(
                f"Outbound messaging is not supported for channel {conversation.channel.value}"
            )

    def _send_whatsapp_reply(
        self,
        organization: Organization,
        conversation: Conversation,
        body: str,
    ) -> ConversationMessage:
        # Determine recipient phone number
        recipient_phone = None
        if conversation.customer:
            recipient_phone = conversation.customer.phone_normalized or conversation.customer.phone
        if not recipient_phone and conversation.lead:
            recipient_phone = (
                conversation.lead.customer_phone_normalized or conversation.lead.customer_phone
            )

        if not recipient_phone:
            raise ValueError("Customer phone number is missing; cannot send WhatsApp reply.")

        phone_number_id = (
            organization.whatsapp_phone_number_id
            or self.settings.meta_whatsapp_phone_number_id
            or "default"
        )

        now = datetime.now(UTC)

        # 1. Pre-create outbound message in PENDING status
        msg = ConversationMessage(
            organization_id=organization.id,
            conversation_id=conversation.id,
            direction=MessageDirection.OUTBOUND,
            channel=InboundChannel.WHATSAPP,
            sender_type=MessageSenderType.OWNER,
            body=body,
            delivery_status=MessageDeliveryStatus.PENDING,
            sent_at=now,
            created_at=now,
        )
        self.db.add(msg)
        self.db.flush()

        # 2. Dispatch via WhatsAppProvider
        logger.info(
            "[WHATSAPP_OUTBOUND_ATTEMPT] type=owner_reply org_id=%s conversation_id=%s to=%s",
            organization.id,
            conversation.id,
            recipient_phone,
        )
        result = self.whatsapp.send_text_message(
            phone_number_id=phone_number_id,
            to_phone=recipient_phone,
            body=body,
        )

        if result.success:
            msg.delivery_status = MessageDeliveryStatus.SENT
            msg.external_message_id = result.provider_message_id
            conversation.last_message_at = now
            conversation.last_outbound_at = now
            conversation.waiting_on = WaitingOn.CUSTOMER

            # 3. Cancel pending owner response reminders
            from app.services.followups import FollowUpService

            FollowUpService(self.db).cancel_pending_owner_reminders(
                conversation_id=conversation.id,
                organization_id=organization.id,
            )

            self.db.commit()
            self.db.refresh(msg)
            logger.info(
                "[WHATSAPP_OUTBOUND_DISPATCHED] type=owner_reply "
                "provider_message_id=%s org_id=%s conv_id=%s",
                result.provider_message_id,
                organization.id,
                conversation.id,
            )
            return msg
        else:
            msg.delivery_status = MessageDeliveryStatus.FAILED
            msg.message_metadata = {"error": result.error}
            self.db.commit()
            self.db.refresh(msg)
            logger.error(
                "[OWNER_REPLY_FAILED] Failed to send WhatsApp message: org=%s conv=%s err=%s",
                organization.id,
                conversation.id,
                result.error,
            )
            raise RuntimeError(f"WhatsApp provider failed to deliver message: {result.error}")
