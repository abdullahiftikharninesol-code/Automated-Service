from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.ai import get_ai_provider
from app.ai.base import AIProvider
from app.models.enums import InboundChannel
from app.schemas.inbound import InboundMessageCreate
from app.services.email import EmailProvider, get_email_provider
from app.services.inbound import InboundLeadService
from app.services.whatsapp.provider import WhatsAppProvider, get_whatsapp_provider
from app.services.whatsapp.resolver import WhatsAppOrganizationResolver
from app.services.whatsapp.status import WhatsAppStatusHandler

logger = logging.getLogger("missed_lead_rescue.whatsapp.inbound")


class WhatsAppInboundAdapter:
    """Normalizes raw Meta WhatsApp Cloud API webhooks into application domain models.

    Zero domain duplication: maps Meta payloads to standard InboundMessageCreate contracts
    and delegates to InboundLeadService, WhatsAppStatusHandler, and WhatsAppOrganizationResolver.
    """

    def __init__(
        self,
        db: Session,
        ai: AIProvider | None = None,
        email: EmailProvider | None = None,
        whatsapp: WhatsAppProvider | None = None,
    ):
        self.db = db
        self.ai = ai or get_ai_provider()
        self.email = email or get_email_provider()
        self.whatsapp = whatsapp or get_whatsapp_provider()
        self.resolver = WhatsAppOrganizationResolver(db)
        self.status_handler = WhatsAppStatusHandler(db)

    def process_webhook_payload(self, payload: dict[str, Any]) -> dict[str, int]:
        """Process incoming Meta webhook JSON payload with multi-entry/multi-change array safety."""
        entries = payload.get("entry", [])
        if not isinstance(entries, list):
            logger.warning("[WHATSAPP_INBOUND] Invalid payload format: 'entry' is not a list")
            return {"messages_processed": 0, "statuses_processed": 0}

        messages_processed = 0
        statuses_processed = 0

        for entry in entries:
            changes = entry.get("changes", [])
            if not isinstance(changes, list):
                continue

            for change in changes:
                value = change.get("value", {})
                if not isinstance(value, dict):
                    continue

                metadata = value.get("metadata", {})
                phone_number_id = metadata.get("phone_number_id")
                display_phone = metadata.get("display_phone_number")

                organization = self.resolver.resolve(phone_number_id)
                if not organization:
                    logger.warning(
                        "[WHATSAPP_INBOUND] No organization resolved for "
                        "phone_number_id=%s. Skipping change.",
                        phone_number_id,
                    )
                    continue

                logger.info(
                    "[WHATSAPP_INBOUND] Tenant resolved: org_id=%s phone_number_id=%s",
                    organization.id,
                    phone_number_id,
                )

                # 1. Process Message Statuses (Receipts)
                statuses = value.get("statuses", [])
                if isinstance(statuses, list):
                    for st in statuses:
                        wamid = st.get("id")
                        status_name = st.get("status")
                        if wamid and status_name:
                            self.status_handler.handle_status_update(
                                organization_id=organization.id,
                                wamid=wamid,
                                status_name=status_name,
                                status_payload=st,
                            )
                            statuses_processed += 1

                # 2. Process Inbound Messages
                raw_messages = value.get("messages", [])
                if isinstance(raw_messages, list):
                    # Build contacts lookup
                    contacts = value.get("contacts", [])
                    contact_names: dict[str, str] = {}
                    if isinstance(contacts, list):
                        for c in contacts:
                            wa_id = str(c.get("wa_id", "")).strip()
                            profile_name = c.get("profile", {}).get("name")
                            if wa_id and profile_name:
                                contact_names[wa_id] = profile_name

                    for msg in raw_messages:
                        wamid = msg.get("id")
                        from_phone = str(msg.get("from", "")).strip()
                        msg_type = msg.get("type", "unknown")

                        if not wamid or not from_phone:
                            logger.warning(
                                "[WHATSAPP_INBOUND] Missing id or from in message payload: %s", msg
                            )
                            continue

                        logger.info(
                            "[WHATSAPP_INBOUND] Inbound message received: "
                            "wamid=%s type=%s phone_id=%s org_id=%s",
                            wamid,
                            msg_type,
                            phone_number_id,
                            organization.id,
                        )

                        if msg_type == "text":
                            text_body = msg.get("text", {}).get("body", "").strip()
                            contact_name = contact_names.get(from_phone) or "WhatsApp Customer"
                            ts_raw = msg.get("timestamp")

                            # Meta WhatsApp numbers are digits without '+' (e.g. 923001234567).
                            # Prepend '+' so E.164 parser recognizes the country code.
                            normalized_input_phone = (
                                f"+{from_phone}"
                                if from_phone and not from_phone.startswith("+")
                                else from_phone
                            )

                            inbound_create = InboundMessageCreate(
                                channel=InboundChannel.WHATSAPP,
                                customer_name=contact_name,
                                customer_phone=normalized_input_phone,
                                message_text=text_body,
                                external_message_id=wamid,
                                metadata={
                                    "phone_number_id": phone_number_id,
                                    "display_phone_number": display_phone,
                                    "raw_from": from_phone,
                                    "raw_timestamp": ts_raw,
                                },
                            )

                            inbound_service = InboundLeadService(
                                db=self.db,
                                ai=self.ai,
                                email=self.email,
                                whatsapp=self.whatsapp,
                            )
                            res = inbound_service.process(organization.id, inbound_create)
                            logger.info(
                                "[WHATSAPP_INBOUND] Processed text msg wamid=%s "
                                "lead_id=%s created=%s",
                                wamid,
                                res.lead.id,
                                res.created,
                            )
                            messages_processed += 1
                        else:
                            # Safely handle unsupported types (audio, image, document, sticker, etc)
                            logger.warning(
                                "[WHATSAPP_INBOUND_UNSUPPORTED] Unsupported message "
                                "type '%s' from %s wamid=%s org_id=%s",
                                msg_type,
                                from_phone,
                                wamid,
                                organization.id,
                            )

        return {
            "messages_processed": messages_processed,
            "statuses_processed": statuses_processed,
        }
