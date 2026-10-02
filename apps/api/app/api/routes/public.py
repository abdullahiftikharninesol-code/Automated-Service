import uuid

from fastapi import APIRouter, HTTPException, status

from app.ai import get_ai_provider
from app.api.dependencies import DbSession
from app.models.enums import InboundChannel
from app.models.organization import Organization
from app.schemas.inbound import (
    InboundMessageCreate,
    InboundProcessResponse,
    WebsiteWebhookCreate,
)
from app.schemas.lead import PublicInquiryCreate, PublicInquiryResponse
from app.services.email import get_email_provider
from app.services.inbound import InboundLeadService, InboundOrganizationNotFound

router = APIRouter(prefix="/public", tags=["Public inquiries"])


@router.get("/organizations/{organization_id}")
def public_organization(organization_id: uuid.UUID, db: DbSession) -> dict[str, str]:
    organization = db.get(Organization, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    return {
        "id": str(organization.id),
        "name": organization.name,
        "industry": organization.industry,
        "business_type": organization.business_type.value,
    }


@router.post(
    "/inbound/webhook/{organization_id}",
    response_model=InboundProcessResponse,
    status_code=status.HTTP_201_CREATED,
)
def inbound_webhook(
    organization_id: uuid.UUID, payload: WebsiteWebhookCreate, db: DbSession
) -> InboundProcessResponse:
    return _process_website_payload(organization_id, payload, InboundChannel.WEBSITE_WEBHOOK, db)


@router.post(
    "/inbound/form/{organization_id}",
    response_model=InboundProcessResponse,
    status_code=status.HTTP_201_CREATED,
)
def inbound_form(
    organization_id: uuid.UUID, payload: WebsiteWebhookCreate, db: DbSession
) -> InboundProcessResponse:
    return _process_website_payload(organization_id, payload, InboundChannel.WEBSITE_FORM, db)


@router.post(
    "/inquiries/{organization_id}",
    response_model=PublicInquiryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_public_inquiry(
    organization_id: uuid.UUID, payload: PublicInquiryCreate, db: DbSession
) -> PublicInquiryResponse:
    result = _process(
        organization_id,
        InboundMessageCreate(
            channel=InboundChannel.WEBSITE_FORM,
            customer_name=payload.customer_name,
            customer_email=payload.customer_email,
            customer_phone=payload.customer_phone,
            message_text=payload.message,
            category_or_service=payload.service_type,
            location=payload.location,
            preferred_date=payload.preferred_date,
            preferred_time=payload.preferred_time,
        ),
        db,
    )
    return PublicInquiryResponse(id=result.lead_id)


def _process_website_payload(
    organization_id: uuid.UUID,
    payload: WebsiteWebhookCreate,
    channel: InboundChannel,
    db: DbSession,
) -> InboundProcessResponse:
    return _process(
        organization_id,
        InboundMessageCreate(
            channel=channel,
            external_message_id=payload.external_message_id,
            customer_name=payload.name,
            customer_email=payload.email,
            customer_phone=payload.phone,
            message_text=payload.message,
            category_or_service=payload.product_or_service,
            location=payload.location,
            preferred_date=payload.preferred_date,
            preferred_time=payload.preferred_time,
            metadata=payload.metadata,
        ),
        db,
    )


def _process(
    organization_id: uuid.UUID, payload: InboundMessageCreate, db: DbSession
) -> InboundProcessResponse:
    try:
        result = InboundLeadService(db, get_ai_provider(), get_email_provider()).process(
            organization_id, payload
        )
    except InboundOrganizationNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return InboundProcessResponse(lead_id=result.lead.id, status=result.lead.status)
