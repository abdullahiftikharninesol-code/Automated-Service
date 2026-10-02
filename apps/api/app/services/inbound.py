import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.ai.base import AIProvider
from app.models.enums import InboundChannel, LeadEventType, LeadSource, LeadStatus, Urgency
from app.models.inbound_message import InboundMessage
from app.models.lead import Lead
from app.models.lead_event import LeadEvent
from app.models.organization import Organization
from app.schemas.ai import LeadExtractionResult
from app.schemas.inbound import InboundMessageCreate
from app.services.email import EmailProvider
from app.services.followups import FollowUpService

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
    def __init__(self, db: Session, ai: AIProvider, email: EmailProvider):
        self.db = db
        self.ai = ai
        self.email = email
        self.followups = FollowUpService(db)

    def process(
        self, organization_id: uuid.UUID, payload: InboundMessageCreate
    ) -> InboundProcessingResult:
        organization = self.db.get(Organization, organization_id)
        if not organization:
            raise InboundOrganizationNotFound("Organization not found")

        existing = self._existing_external_message(organization.id, payload)
        if existing and existing.lead:
            return InboundProcessingResult(existing.lead, existing, created=False)

        email = str(payload.customer_email).lower() if payload.customer_email else None
        message = InboundMessage(
            organization_id=organization.id,
            channel=payload.channel,
            external_message_id=payload.external_message_id,
            customer_name=payload.customer_name.strip(),
            customer_email=email,
            customer_phone=payload.customer_phone.strip() if payload.customer_phone else None,
            message_text=payload.message_text.strip(),
            inbound_metadata=payload.metadata,
        )
        self.db.add(message)
        self.db.flush()

        extraction = self.ai.extract_lead_information(
            message.message_text,
            business_type=organization.business_type.value,
        )
        lead = self._find_open_lead(organization, message)
        created = lead is None
        if created:
            lead = self._create_lead(organization, message, payload, extraction)
        else:
            self._enrich_lead(lead, message, payload, extraction)

        message.lead_id = lead.id
        message.processed_at = datetime.now(UTC)
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

        self._acknowledge(organization, lead, extraction)
        self.db.commit()
        self.db.refresh(lead)
        self.db.refresh(message)
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
        if message.customer_phone:
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
        if message.customer_phone:
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
    ) -> Lead:
        category = payload.category_or_service or extraction.category_or_service
        lead = Lead(
            organization_id=organization.id,
            customer_name=message.customer_name,
            customer_email=message.customer_email,
            customer_phone=message.customer_phone,
            intent=extraction.intent,
            category_or_service=category,
            service_type=category or extraction.product_name,
            product_name=extraction.product_name,
            product_variant=extraction.product_variant,
            quantity=extraction.quantity,
            ai_additional_fields=extraction.additional_fields,
            message=message.message_text,
            location=payload.location or extraction.location,
            urgency=extraction.urgency,
            preferred_date=payload.preferred_date,
            preferred_time=payload.preferred_time,
            preferred_date_text=None if payload.preferred_date else extraction.preferred_date,
            preferred_time_text=None if payload.preferred_time else extraction.preferred_time,
            source=CHANNEL_SOURCES[payload.channel],
            ai_summary=extraction.summary,
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
    ) -> None:
        lead.customer_email = lead.customer_email or message.customer_email
        lead.customer_phone = lead.customer_phone or message.customer_phone
        lead.intent = lead.intent or extraction.intent
        lead.category_or_service = (
            lead.category_or_service
            or payload.category_or_service
            or extraction.category_or_service
        )
        lead.service_type = lead.service_type or lead.category_or_service or extraction.product_name
        lead.product_name = lead.product_name or extraction.product_name
        lead.product_variant = lead.product_variant or extraction.product_variant
        lead.quantity = lead.quantity or extraction.quantity
        lead.location = lead.location or payload.location or extraction.location
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

    def _acknowledge(
        self,
        organization: Organization,
        lead: Lead,
        extraction: LeadExtractionResult,
    ) -> None:
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
        else:
            self._event(lead, LeadEventType.ACKNOWLEDGEMENT_SENT, {"channel": "EMAIL"})

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
