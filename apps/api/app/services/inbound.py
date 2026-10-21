import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.ai.base import AIProvider
from app.models.conversation import Conversation
from app.models.enums import (
    InboundChannel,
    LeadEventType,
    LeadSource,
    LeadStatus,
    MessageDeliveryStatus,
    MessageSenderType,
    QualificationStatus,
    Urgency,
    WaitingOn,
)
from app.models.inbound_message import InboundMessage
from app.models.lead import Lead
from app.models.lead_event import LeadEvent
from app.models.organization import Organization
from app.schemas.ai import LeadExtractionResult
from app.schemas.inbound import InboundMessageCreate
from app.services.conversation import ConversationService
from app.services.customer import CustomerService
from app.services.email import EmailProvider
from app.services.followups import FollowUpService
from app.services.qualification import QualificationQuestionService, QualificationService
from app.services.whatsapp.provider import WhatsAppProvider, get_whatsapp_provider

logger = logging.getLogger("missed_lead_rescue.inbound")


class InboundOrganizationNotFound(ValueError):
    pass


@dataclass(frozen=True)
class InboundProcessingResult:
    lead: Lead
    message: InboundMessage
    created: bool


CHANNEL_SOURCES = {
    InboundChannel.WEBSITE_FORM: LeadSource.WEBSITE_FORM,
    InboundChannel.WEBSITE_WEBHOOK: LeadSource.WEBSITE_WEBHOOK,
    InboundChannel.EMAIL: LeadSource.EMAIL,
    InboundChannel.WHATSAPP: LeadSource.WHATSAPP,
    InboundChannel.PHONE: LeadSource.PHONE,
    InboundChannel.MANUAL: LeadSource.MANUAL,
    InboundChannel.CHAT_WIDGET: LeadSource.CHAT_WIDGET,
}

URGENCY_RANK = {
    Urgency.LOW: 0,
    Urgency.NORMAL: 1,
    Urgency.HIGH: 2,
    Urgency.EMERGENCY: 3,
}


class InboundLeadService:
    def __init__(
        self,
        db: Session,
        ai: AIProvider,
        email: EmailProvider,
        whatsapp: WhatsAppProvider | None = None,
    ):
        self.db = db
        self.ai = ai
        self.email = email
        self.whatsapp = whatsapp or get_whatsapp_provider()
        self.followups = FollowUpService(db)
        self.customers = CustomerService(db)
        self.conversations = ConversationService(db)
        self.qualification_service = QualificationService(db)

    def process(
        self, organization_id: uuid.UUID, payload: InboundMessageCreate
    ) -> InboundProcessingResult:
        organization = self.db.get(Organization, organization_id)
        if not organization:
            raise InboundOrganizationNotFound("Organization not found")

        existing = self._existing_external_message(organization.id, payload)
        if existing and existing.lead:
            return InboundProcessingResult(existing.lead, existing, created=False)

        customer = self.customers.find_or_create(
            organization_id=organization.id,
            name=payload.customer_name,
            email=str(payload.customer_email) if payload.customer_email else None,
            phone=payload.customer_phone,
            default_region=organization.default_phone_region,
            metadata=payload.metadata,
        )

        message = InboundMessage(
            organization_id=organization.id,
            channel=payload.channel,
            external_message_id=payload.external_message_id,
            customer_name=customer.name or payload.customer_name.strip(),
            customer_email=customer.email,
            customer_phone=customer.phone,
            customer_phone_normalized=customer.phone_normalized,
            message_text=payload.message_text.strip(),
            inbound_metadata=payload.metadata,
        )
        self.db.add(message)
        self.db.flush()

        lead = self._find_open_lead(organization, message)
        created = lead is None

        # Load dynamic qualification fields and extract
        field_defs = self.qualification_service.get_field_definitions(organization.id)
        current_quals = (lead.qualifications or {}) if lead else {}
        extraction = self.ai.extract_lead_information(
            message.message_text,
            business_type=organization.business_type.value,
            qualification_fields=field_defs,
            current_qualifications=current_quals,
        )

        conversation, _ = self.conversations.get_or_create_open_conversation(
            organization_id=organization.id,
            customer_id=customer.id,
            channel=payload.channel,
            lead_id=lead.id if lead else None,
        )
        self.conversations.append_inbound_message(
            organization_id=organization.id,
            conversation_id=conversation.id,
            body=message.message_text,
            channel=payload.channel,
            external_message_id=payload.external_message_id,
            metadata=payload.metadata,
            received_at=message.received_at,
        )

        # Merge extracted qualification fields
        allowed_keys = {
            f.key for f in self.qualification_service.get_enabled_fields(organization.id)
        }
        merged_quals = self.qualification_service.merge_qualifications(
            current=current_quals,
            extracted=extraction.extracted_qualification_fields,
            confidences=extraction.field_confidences,
            allowed_keys=allowed_keys if field_defs else None,
        )

        prev_qual_status = (
            lead.qualification_status if lead else QualificationStatus.NOT_STARTED
        )

        if created:
            lead = self._create_lead(
                organization, message, payload, extraction, qualifications=merged_quals
            )
            lead.customer_id = customer.id
            lead.primary_conversation_id = conversation.id
            conversation.lead_id = lead.id
        else:
            self._enrich_lead(
                lead, message, payload, extraction, qualifications=merged_quals
            )
            lead.qualifications = merged_quals
            if not lead.customer_id:
                lead.customer_id = customer.id
            if not lead.primary_conversation_id:
                lead.primary_conversation_id = conversation.id
            conversation.lead_id = lead.id

        lead.qualifications = merged_quals

        # Evaluate qualification status
        qual_status, missing_fields = self.qualification_service.evaluate_qualification_status(
            organization.id, lead.qualifications
        )
        lead.qualification_status = qual_status

        logger.info(
            "[INBOUND_PIPELINE] Resolved lead_id=%s conv_id=%s cust_id=%s "
            "qualification_state=%s created=%s",
            lead.id,
            conversation.id,
            customer.id,
            lead.qualification_status.value,
            created,
        )

        now = datetime.now(UTC)
        if (
            qual_status == QualificationStatus.COMPLETE
            and not lead.qualification_completed_at
            and (field_defs or merged_quals)
        ):
            lead.qualification_completed_at = now
            self._event(
                lead,
                LeadEventType.QUALIFICATION_COMPLETED,
                {"qualifications": lead.qualifications},
            )
        else:
            self._event(
                lead,
                LeadEventType.QUALIFICATION_UPDATED,
                {
                    "qualifications": lead.qualifications,
                    "status": qual_status.value,
                    "missing_fields": [f.key for f in missing_fields],
                },
            )

        message.lead_id = lead.id
        message.processed_at = now
        self._event(
            lead,
            LeadEventType.INBOUND_MESSAGE_RECEIVED,
            {
                "inbound_message_id": str(message.id),
                "channel": message.channel.value,
                "duplicate_attached": not created,
            },
        )
        self._event(
            lead,
            LeadEventType.AI_PROCESSED,
            {
                "confidence": extraction.confidence,
                "provider": type(self.ai).__name__,
                "inbound_message_id": str(message.id),
            },
        )
        if created:
            self.followups.schedule_for_new_lead(lead, organization)

        # Response routing: clarification question vs standard receipt
        clarification_sent = False
        if (
            payload.channel == InboundChannel.WHATSAPP
            and qual_status == QualificationStatus.IN_PROGRESS
            and missing_fields
        ):
            meta = dict(lead.qualification_metadata or {})
            prompt_counts = dict(meta.get("prompt_counts", {}))
            eligible = [f for f in missing_fields if prompt_counts.get(f.key, 0) < 3]

            if eligible:
                question_text, keys_asked = (
                    QualificationQuestionService.generate_clarification_question(
                        eligible, max_fields=2
                    )
                )
                if question_text:
                    for k in keys_asked:
                        prompt_counts[k] = prompt_counts.get(k, 0) + 1
                    meta["prompt_counts"] = prompt_counts
                    meta["last_question_fields"] = keys_asked
                    lead.qualification_metadata = meta

                    phone = lead.customer_phone_normalized or lead.customer_phone
                    phone_number_id = organization.whatsapp_phone_number_id or "default"
                    logger.info(
                        "[WHATSAPP_OUTBOUND_ATTEMPT] type=clarification "
                        "lead_id=%s conv_id=%s fields=%s",
                        lead.id,
                        conversation.id,
                        keys_asked,
                    )
                    result = self.whatsapp.send_text_message(
                        phone_number_id=phone_number_id,
                        to_phone=phone,
                        body=question_text,
                    )
                    logger.info(
                        "[WHATSAPP_OUTBOUND_DISPATCHED] type=clarification "
                        "provider_message_id=%s success=%s",
                        result.provider_message_id,
                        result.success,
                    )
                    delivery_status = (
                        MessageDeliveryStatus.SENT
                        if result.success
                        else MessageDeliveryStatus.FAILED
                    )
                    self.conversations.append_outbound_message(
                        organization_id=organization.id,
                        conversation_id=conversation.id,
                        body=question_text,
                        channel=InboundChannel.WHATSAPP,
                        sender_type=MessageSenderType.SYSTEM,
                        delivery_status=delivery_status,
                        external_message_id=result.provider_message_id,
                        update_waiting_on=False,
                    )
                    conversation.waiting_on = WaitingOn.CUSTOMER
                    self.followups.cancel_pending_owner_reminders(
                        conversation.id, organization.id
                    )
                    clarification_sent = True
                    self._event(
                        lead,
                        LeadEventType.QUALIFICATION_QUESTION_SENT,
                        {
                            "question": question_text,
                            "keys_asked": keys_asked,
                            "provider_message_id": result.provider_message_id,
                        },
                    )

        if not clarification_sent:
            if (
                conversation
                and payload.channel != InboundChannel.MANUAL
                and conversation.waiting_on == WaitingOn.OWNER
            ):
                self.followups.schedule_owner_response_reminder(
                    conversation=conversation,
                    lead=lead,
                    organization=organization,
                    now=message.received_at,
                )

            if payload.channel == InboundChannel.WHATSAPP:
                if (
                    prev_qual_status == QualificationStatus.IN_PROGRESS
                    and qual_status == QualificationStatus.COMPLETE
                ):
                    receipt_text = (
                        "Thanks, I’ve got the details. "
                        "Someone from the team will get back to you shortly."
                    )
                else:
                    receipt_text = (
                        f"Thanks for contacting {organization.name}. We've received your "
                        "message and someone from the team will get back to you shortly."
                    )
                self._send_whatsapp_message(
                    organization=organization,
                    lead=lead,
                    conversation=conversation,
                    body=receipt_text,
                )
                conversation.waiting_on = WaitingOn.OWNER
            else:
                self._acknowledge(organization, lead, extraction, conversation=conversation)

        self.db.commit()
        self.db.refresh(lead)
        self.db.refresh(message)
        self.db.refresh(conversation)
        return InboundProcessingResult(lead, message, created=created)

    def messages(self, lead: Lead) -> list[InboundMessage]:
        return list(
            self.db.scalars(
                select(InboundMessage)
                .where(
                    InboundMessage.organization_id == lead.organization_id,
                    InboundMessage.lead_id == lead.id,
                )
                .order_by(InboundMessage.received_at.asc())
            )
        )

    def _existing_external_message(
        self, organization_id: uuid.UUID, payload: InboundMessageCreate
    ) -> InboundMessage | None:
        if not payload.external_message_id:
            return None
        return self.db.scalar(
            select(InboundMessage).where(
                InboundMessage.organization_id == organization_id,
                InboundMessage.channel == payload.channel,
                InboundMessage.external_message_id == payload.external_message_id,
            )
        )

    def _find_open_lead(self, organization: Organization, message: InboundMessage) -> Lead | None:
        cutoff = datetime.now(UTC) - timedelta(minutes=organization.duplicate_window_minutes)
        contact_filters = []
        if message.customer_email:
            contact_filters.append(
                func.lower(InboundMessage.customer_email) == message.customer_email.lower()
            )
        if message.customer_phone_normalized:
            contact_filters.append(
                InboundMessage.customer_phone_normalized == message.customer_phone_normalized
            )
        elif message.customer_phone:
            contact_filters.append(InboundMessage.customer_phone == message.customer_phone)
        if not contact_filters:
            return None

        lead = self.db.scalar(
            select(Lead)
            .join(InboundMessage, InboundMessage.lead_id == Lead.id)
            .where(
                Lead.organization_id == organization.id,
                Lead.status.in_([LeadStatus.NEW, LeadStatus.CONTACTED]),
                InboundMessage.received_at >= cutoff,
                or_(*contact_filters),
            )
            .order_by(InboundMessage.received_at.desc())
            .limit(1)
        )
        if lead:
            return lead

        legacy_filters = []
        if message.customer_email:
            legacy_filters.append(func.lower(Lead.customer_email) == message.customer_email.lower())
        if message.customer_phone_normalized:
            legacy_filters.append(
                Lead.customer_phone_normalized == message.customer_phone_normalized
            )
        elif message.customer_phone:
            legacy_filters.append(Lead.customer_phone == message.customer_phone)
        return self.db.scalar(
            select(Lead)
            .where(
                Lead.organization_id == organization.id,
                Lead.status.in_([LeadStatus.NEW, LeadStatus.CONTACTED]),
                Lead.created_at >= cutoff,
                or_(*legacy_filters),
            )
            .order_by(Lead.created_at.desc())
            .limit(1)
        )

    def _create_lead(
        self,
        organization: Organization,
        message: InboundMessage,
        payload: InboundMessageCreate,
        extraction: LeadExtractionResult,
        qualifications: dict | None = None,
    ) -> Lead:
        quals = qualifications or extraction.extracted_qualification_fields or {}
        category = (
            payload.category_or_service
            or quals.get("service")
            or quals.get("service_needed")
            or quals.get("treatment")
            or extraction.category_or_service
        )
        product_name = (
            quals.get("product")
            or quals.get("product_name")
            or quals.get("item_name")
            or extraction.product_name
        )
        product_variant = (
            quals.get("size")
            or quals.get("product_variant")
            or extraction.product_variant
        )
        quantity = quals.get("quantity") or extraction.quantity
        location = (
            payload.location
            or quals.get("delivery_city")
            or quals.get("location")
            or quals.get("address_or_zip")
            or quals.get("shipping_zip")
            or extraction.location
        )
        lead = Lead(
            organization_id=organization.id,
            customer_name=message.customer_name,
            customer_email=message.customer_email,
            customer_phone=message.customer_phone,
            customer_phone_normalized=message.customer_phone_normalized,
            intent=extraction.intent,
            category_or_service=category,
            service_type=category or product_name,
            product_name=product_name,
            product_variant=product_variant,
            quantity=quantity,
            ai_additional_fields=extraction.additional_fields,
            message=message.message_text,
            location=location,
            urgency=extraction.urgency,
            preferred_date=payload.preferred_date,
            preferred_time=payload.preferred_time,
            preferred_date_text=None if payload.preferred_date else extraction.preferred_date,
            preferred_time_text=None if payload.preferred_time else extraction.preferred_time,
            source=CHANNEL_SOURCES[payload.channel],
            ai_summary=extraction.summary,
            qualifications=quals,
        )
        self.db.add(lead)
        self.db.flush()
        self._event(lead, LeadEventType.LEAD_CREATED, {"source": lead.source.value})
        return lead

    def _enrich_lead(
        self,
        lead: Lead,
        message: InboundMessage,
        payload: InboundMessageCreate,
        extraction: LeadExtractionResult,
        qualifications: dict | None = None,
    ) -> None:
        lead.customer_email = lead.customer_email or message.customer_email
        lead.customer_phone = lead.customer_phone or message.customer_phone
        lead.customer_phone_normalized = (
            lead.customer_phone_normalized or message.customer_phone_normalized
        )
        lead.intent = lead.intent or extraction.intent
        quals = qualifications or extraction.extracted_qualification_fields or {}
        if not lead.product_name:
            lead.product_name = (
                quals.get("product")
                or quals.get("product_name")
                or quals.get("item_name")
                or extraction.product_name
            )
        if not lead.product_variant:
            lead.product_variant = (
                quals.get("size")
                or quals.get("product_variant")
                or extraction.product_variant
            )
        if not lead.quantity and (extraction.quantity or "quantity" in quals):
            lead.quantity = extraction.quantity or quals.get("quantity")
        if not lead.location:
            lead.location = (
                payload.location
                or quals.get("delivery_city")
                or quals.get("location")
                or quals.get("address_or_zip")
                or quals.get("shipping_zip")
                or extraction.location
            )
        if not lead.category_or_service:
            lead.category_or_service = (
                payload.category_or_service
                or quals.get("service")
                or quals.get("service_needed")
                or quals.get("treatment")
                or extraction.category_or_service
            )
        lead.service_type = (
            lead.service_type
            or lead.category_or_service
            or lead.product_name
            or extraction.product_name
        )
        lead.preferred_date = lead.preferred_date or payload.preferred_date
        lead.preferred_time = lead.preferred_time or payload.preferred_time
        if not lead.preferred_date and not lead.preferred_date_text:
            lead.preferred_date_text = extraction.preferred_date
        if not lead.preferred_time and not lead.preferred_time_text:
            lead.preferred_time_text = extraction.preferred_time
        if URGENCY_RANK[extraction.urgency] > URGENCY_RANK[lead.urgency]:
            lead.urgency = extraction.urgency
        lead.ai_additional_fields = {
            **(lead.ai_additional_fields or {}),
            **extraction.additional_fields,
        }
        if extraction.summary and extraction.summary not in (lead.ai_summary or ""):
            lead.ai_summary = f"{lead.ai_summary or ''} Latest: {extraction.summary}".strip()[:2000]
        self._event(
            lead,
            LeadEventType.LEAD_ENRICHED,
            {"inbound_message_id": str(message.id), "channel": message.channel.value},
        )

    def _send_whatsapp_message(
        self,
        organization: Organization,
        lead: Lead,
        conversation: Conversation,
        body: str,
    ) -> None:
        phone = lead.customer_phone_normalized or lead.customer_phone
        if not phone:
            return
        self._event(
            lead,
            LeadEventType.ACKNOWLEDGEMENT_GENERATED,
            {"message": body, "channel": "WHATSAPP"},
        )
        phone_number_id = organization.whatsapp_phone_number_id or "default"
        logger.info(
            "[WHATSAPP_OUTBOUND_ATTEMPT] type=confirmation lead_id=%s conversation_id=%s",
            lead.id,
            conversation.id,
        )
        result = self.whatsapp.send_text_message(
            phone_number_id=phone_number_id,
            to_phone=phone,
            body=body,
        )
        logger.info(
            "[WHATSAPP_OUTBOUND_DISPATCHED] type=confirmation provider_message_id=%s success=%s",
            result.provider_message_id,
            result.success,
        )
        if result.success:
            self._event(
                lead,
                LeadEventType.ACKNOWLEDGEMENT_SENT,
                {"channel": "WHATSAPP", "provider_message_id": result.provider_message_id},
            )
            self.conversations.append_outbound_message(
                organization_id=organization.id,
                conversation_id=conversation.id,
                body=body,
                channel=InboundChannel.WHATSAPP,
                sender_type=MessageSenderType.SYSTEM,
                delivery_status=MessageDeliveryStatus.SENT,
                external_message_id=result.provider_message_id,
                update_waiting_on=False,
            )
        else:
            self._event(
                lead,
                LeadEventType.ACKNOWLEDGEMENT_FAILED,
                {"channel": "WHATSAPP", "error": result.error},
            )
            self.conversations.append_outbound_message(
                organization_id=organization.id,
                conversation_id=conversation.id,
                body=body,
                channel=InboundChannel.WHATSAPP,
                sender_type=MessageSenderType.SYSTEM,
                delivery_status=MessageDeliveryStatus.FAILED,
                metadata={"error": result.error},
                update_waiting_on=False,
            )

    def _acknowledge(
        self,
        organization: Organization,
        lead: Lead,
        extraction: LeadExtractionResult,
        conversation: Conversation | None = None,
    ) -> None:
        if conversation and conversation.channel == InboundChannel.WHATSAPP:
            receipt_text = (
                f"Thanks for contacting {organization.name}. We've received your "
                "message and someone from the team will get back to you shortly."
            )
            self._send_whatsapp_message(
                organization=organization,
                lead=lead,
                conversation=conversation,
                body=receipt_text,
            )
            return

        acknowledgement = self.ai.generate_acknowledgement(
            customer_name=lead.customer_name,
            organization_name=organization.name,
            extraction=extraction,
        )
        self._event(
            lead,
            LeadEventType.ACKNOWLEDGEMENT_GENERATED,
            {"message": acknowledgement},
        )
        if not lead.customer_email:
            return
        if not getattr(self.email, "configured", True):
            logger.error("Email provider is not configured for lead %s", lead.id)
            self._event(
                lead,
                LeadEventType.ACKNOWLEDGEMENT_FAILED,
                {"channel": "EMAIL", "error_type": "EmailProviderNotConfigured"},
            )
            if conversation:
                self.conversations.append_outbound_message(
                    organization_id=organization.id,
                    conversation_id=conversation.id,
                    body=acknowledgement,
                    channel=InboundChannel.EMAIL,
                    sender_type=MessageSenderType.SYSTEM,
                    delivery_status=MessageDeliveryStatus.FAILED,
                    metadata={"error_type": "EmailProviderNotConfigured"},
                )
            return
        try:
            self.email.send(
                to=lead.customer_email,
                subject=f"We received your inquiry — {organization.name}",
                body=acknowledgement,
            )
        except Exception as exc:  # Provider failures must never discard an inquiry.
            logger.exception("Acknowledgement delivery failed for lead %s", lead.id)
            self._event(
                lead,
                LeadEventType.ACKNOWLEDGEMENT_FAILED,
                {"channel": "EMAIL", "error_type": type(exc).__name__},
            )
            if conversation:
                self.conversations.append_outbound_message(
                    organization_id=organization.id,
                    conversation_id=conversation.id,
                    body=acknowledgement,
                    channel=InboundChannel.EMAIL,
                    sender_type=MessageSenderType.SYSTEM,
                    delivery_status=MessageDeliveryStatus.FAILED,
                    metadata={"error_type": type(exc).__name__},
                )
        else:
            self._event(lead, LeadEventType.ACKNOWLEDGEMENT_SENT, {"channel": "EMAIL"})
            if conversation:
                self.conversations.append_outbound_message(
                    organization_id=organization.id,
                    conversation_id=conversation.id,
                    body=acknowledgement,
                    channel=InboundChannel.EMAIL,
                    sender_type=MessageSenderType.SYSTEM,
                    delivery_status=MessageDeliveryStatus.SENT,
                )

    def _event(
        self, lead: Lead, event_type: LeadEventType, metadata: dict[str, object]
    ) -> LeadEvent:
        event = LeadEvent(
            lead_id=lead.id,
            organization_id=lead.organization_id,
            event_type=event_type,
            event_metadata=metadata,
        )
        self.db.add(event)
        return event
