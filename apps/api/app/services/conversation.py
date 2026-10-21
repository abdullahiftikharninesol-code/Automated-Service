from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.conversation_message import ConversationMessage
from app.models.enums import (
    ConversationStatus,
    InboundChannel,
    MessageDeliveryStatus,
    MessageDirection,
    MessageSenderType,
    WaitingOn,
)

logger = logging.getLogger("missed_lead_rescue.conversation")


class ConversationService:
    def __init__(self, db: Session):
        self.db = db

    def get_or_create_open_conversation(
        self,
        organization_id: uuid.UUID,
        customer_id: uuid.UUID | None,
        channel: InboundChannel,
        lead_id: uuid.UUID | None = None,
    ) -> tuple[Conversation, bool]:
        # 1. If lead_id is provided, check if open conversation exists for that lead
        if lead_id:
            conv = self.db.scalar(
                select(Conversation).where(
                    Conversation.organization_id == organization_id,
                    Conversation.lead_id == lead_id,
                    Conversation.status == ConversationStatus.OPEN,
                )
            )
            if conv:
                return conv, False

        # 2. Check for an open conversation with this customer on the same channel
        if customer_id:
            conv = self.db.scalar(
                select(Conversation)
                .where(
                    Conversation.organization_id == organization_id,
                    Conversation.customer_id == customer_id,
                    Conversation.channel == channel,
                    Conversation.status == ConversationStatus.OPEN,
                )
                .order_by(Conversation.last_message_at.desc())
            )
            if conv:
                if lead_id and not conv.lead_id:
                    conv.lead_id = lead_id
                    self.db.flush()
                return conv, False

        # 3. Create new conversation
        conv = Conversation(
            organization_id=organization_id,
            customer_id=customer_id,
            lead_id=lead_id,
            channel=channel,
            status=ConversationStatus.OPEN,
            waiting_on=WaitingOn.OWNER,
        )
        self.db.add(conv)
        self.db.flush()
        return conv, True

    def append_inbound_message(
        self,
        organization_id: uuid.UUID,
        conversation_id: uuid.UUID,
        body: str,
        channel: InboundChannel,
        external_message_id: str | None = None,
        metadata: dict | None = None,
        received_at: datetime | None = None,
    ) -> tuple[ConversationMessage, bool]:
        # Idempotency check
        if external_message_id:
            existing = self.db.scalar(
                select(ConversationMessage).where(
                    ConversationMessage.organization_id == organization_id,
                    ConversationMessage.channel == channel,
                    ConversationMessage.external_message_id == external_message_id,
                )
            )
            if existing:
                return existing, False

        conv = self.db.scalar(
            select(Conversation).where(
                Conversation.organization_id == organization_id,
                Conversation.id == conversation_id,
            )
        )
        if not conv:
            raise ValueError(f"Conversation {conversation_id} not found in org {organization_id}")

        now = received_at or datetime.now(UTC)
        msg = ConversationMessage(
            organization_id=organization_id,
            conversation_id=conversation_id,
            direction=MessageDirection.INBOUND,
            channel=channel,
            sender_type=MessageSenderType.CUSTOMER,
            body=body,
            external_message_id=external_message_id,
            delivery_status=MessageDeliveryStatus.DELIVERED,
            message_metadata=metadata or {},
            sent_at=now,
            created_at=now,
        )
        self.db.add(msg)

        conv.last_message_at = now
        conv.last_inbound_at = now
        conv.waiting_on = WaitingOn.OWNER
        self.db.flush()
        return msg, True

    def append_outbound_message(
        self,
        organization_id: uuid.UUID,
        conversation_id: uuid.UUID,
        body: str,
        channel: InboundChannel,
        sender_type: MessageSenderType = MessageSenderType.SYSTEM,
        delivery_status: MessageDeliveryStatus = MessageDeliveryStatus.SENT,
        external_message_id: str | None = None,
        metadata: dict | None = None,
        update_waiting_on: bool | None = None,
    ) -> ConversationMessage:
        conv = self.db.scalar(
            select(Conversation).where(
                Conversation.organization_id == organization_id,
                Conversation.id == conversation_id,
            )
        )
        if not conv:
            raise ValueError(f"Conversation {conversation_id} not found in org {organization_id}")

        now = datetime.now(UTC)
        msg = ConversationMessage(
            organization_id=organization_id,
            conversation_id=conversation_id,
            direction=MessageDirection.OUTBOUND,
            channel=channel,
            sender_type=sender_type,
            body=body,
            external_message_id=external_message_id,
            delivery_status=delivery_status,
            message_metadata=metadata or {},
            sent_at=now,
            created_at=now,
        )
        self.db.add(msg)

        conv.last_message_at = now
        conv.last_outbound_at = now

        # Update waiting_on status
        if update_waiting_on is False:
            pass  # Leave waiting_on unchanged
        elif update_waiting_on is True or sender_type == MessageSenderType.OWNER:
            conv.waiting_on = WaitingOn.CUSTOMER
        elif channel == InboundChannel.WHATSAPP and sender_type == MessageSenderType.SYSTEM:
            # WhatsApp automated SYSTEM receipts leave conversation waiting on OWNER
            pass
        else:
            conv.waiting_on = WaitingOn.CUSTOMER

        self.db.flush()

        if sender_type == MessageSenderType.OWNER:
            from app.services.followups import FollowUpService

            FollowUpService(self.db).cancel_pending_owner_reminders(
                conversation_id=conversation_id,
                organization_id=organization_id,
            )

        return msg

    def get(self, organization_id: uuid.UUID, conversation_id: uuid.UUID) -> Conversation | None:
        return self.db.scalar(
            select(Conversation).where(
                Conversation.organization_id == organization_id,
                Conversation.id == conversation_id,
            )
        )

    def list(
        self,
        organization_id: uuid.UUID,
        status: ConversationStatus | None = None,
        channel: InboundChannel | None = None,
        waiting_on: WaitingOn | None = None,
        lead_id: uuid.UUID | None = None,
        customer_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Conversation]:
        query = (
            select(Conversation)
            .where(Conversation.organization_id == organization_id)
            .order_by(
                Conversation.last_message_at.desc().nulls_last(),
                Conversation.created_at.desc(),
            )
        )
        if status:
            query = query.where(Conversation.status == status)
        if channel:
            query = query.where(Conversation.channel == channel)
        if waiting_on:
            query = query.where(Conversation.waiting_on == waiting_on)
        if lead_id:
            query = query.where(Conversation.lead_id == lead_id)
        if customer_id:
            query = query.where(Conversation.customer_id == customer_id)

        return list(self.db.scalars(query.offset(offset).limit(limit)))

    def messages(
        self, organization_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> list[ConversationMessage]:
        return list(
            self.db.scalars(
                select(ConversationMessage)
                .where(
                    ConversationMessage.organization_id == organization_id,
                    ConversationMessage.conversation_id == conversation_id,
                )
                .order_by(ConversationMessage.sent_at.asc())
            )
        )
