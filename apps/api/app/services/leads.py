import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.base import AIProvider
from app.models.enums import InboundChannel, LeadEventType, LeadSource, LeadStatus
from app.models.lead import Lead
from app.models.lead_event import LeadEvent
from app.models.organization import Organization
from app.repositories.leads import LeadRepository
from app.schemas.inbound import InboundMessageCreate
from app.schemas.lead import LeadCreate, LeadUpdate
from app.services.email import EmailProvider
from app.services.followups import FollowUpService
from app.services.inbound import InboundLeadService


class LeadService:
    def __init__(self, db: Session, ai: AIProvider, email: EmailProvider):
        self.db = db
        self.ai = ai
        self.email = email
        self.repository = LeadRepository(db)
        self.followups = FollowUpService(db)

    def create(self, organization: Organization, payload: LeadCreate) -> Lead:
        channels = {
            LeadSource.WEBSITE: InboundChannel.WEBSITE_FORM,
            LeadSource.WEBSITE_FORM: InboundChannel.WEBSITE_FORM,
            LeadSource.WEBSITE_WEBHOOK: InboundChannel.WEBSITE_WEBHOOK,
            LeadSource.EMAIL: InboundChannel.EMAIL,
            LeadSource.WHATSAPP: InboundChannel.WHATSAPP,
            LeadSource.PHONE: InboundChannel.PHONE,
            LeadSource.MANUAL: InboundChannel.MANUAL,
            LeadSource.CHAT_WIDGET: InboundChannel.CHAT_WIDGET,
        }
        result = InboundLeadService(self.db, self.ai, self.email).process(
            organization.id,
            InboundMessageCreate(
                channel=channels[payload.source],
                customer_name=payload.customer_name,
                customer_email=payload.customer_email,
                customer_phone=payload.customer_phone,
                message_text=payload.message,
                category_or_service=payload.service_type,
                location=payload.location,
                preferred_date=payload.preferred_date,
                preferred_time=payload.preferred_time,
            ),
        )
        return result.lead

    def update(self, lead: Lead, payload: LeadUpdate) -> Lead:
        changes = payload.model_dump(exclude_unset=True)
        if "category_or_service" in changes and "service_type" not in changes:
            changes["service_type"] = changes["category_or_service"]
        elif "service_type" in changes and "category_or_service" not in changes:
            changes["category_or_service"] = changes["service_type"]
        for key, value in changes.items():
            setattr(lead, key, value)
        self.db.commit()
        self.db.refresh(lead)
        return lead

    def change_status(self, lead: Lead, organization: Organization, status: LeadStatus) -> Lead:
        previous = lead.status
        if previous == status:
            return lead
        now = datetime.now(UTC)
        lead.status = status
        if status == LeadStatus.CONTACTED:
            lead.last_contacted_at = now
            lead.booked_at = None
            lead.lost_at = None
            self.followups.schedule_for_contacted(lead, organization)
        elif status == LeadStatus.BOOKED:
            lead.booked_at = now
            lead.lost_at = None
            lead.next_followup_at = None
            self.followups.cancel_pending(lead.id, organization.id)
        elif status == LeadStatus.LOST:
            lead.lost_at = now
            lead.booked_at = None
            lead.next_followup_at = None
            self.followups.cancel_pending(lead.id, organization.id)
        elif status == LeadStatus.NEW:
            lead.booked_at = None
            lead.lost_at = None
            self.followups.cancel_pending(lead.id, organization.id)
            self.followups.schedule_for_new_lead(lead, organization)
        self._event(
            lead,
            LeadEventType.STATUS_CHANGED,
            {"from": previous.value, "to": status.value},
        )
        self.db.commit()
        self.db.refresh(lead)
        return lead

    def add_note(self, lead: Lead, note: str, author_id: uuid.UUID) -> LeadEvent:
        event = self._event(
            lead,
            LeadEventType.NOTE_ADDED,
            {"note": note, "author_id": str(author_id)},
        )
        self.db.commit()
        self.db.refresh(event)
        return event

    def generate_followup(self, lead: Lead) -> str:
        preferred = lead.preferred_time_text
        if not preferred and lead.preferred_time:
            preferred = lead.preferred_time.strftime("%H:%M")
        message = self.ai.generate_followup_message(
            customer_name=lead.customer_name,
            service_type=lead.product_name or lead.category_or_service or lead.service_type,
            preferred_time=preferred,
        )
        self._event(lead, LeadEventType.FOLLOWUP_GENERATED, {"message": message, "sent": False})
        self.db.commit()
        return message

    def events(self, lead: Lead) -> list[LeadEvent]:
        return list(
            self.db.scalars(
                select(LeadEvent)
                .where(
                    LeadEvent.lead_id == lead.id,
                    LeadEvent.organization_id == lead.organization_id,
                )
                .order_by(LeadEvent.created_at.desc())
            )
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
