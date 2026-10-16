import hashlib
import hmac
import json
import uuid

from fastapi import APIRouter, HTTPException, Request, status

from app.ai import get_ai_provider
from app.api.dependencies import DbSession
from app.core.config import get_settings
from app.core.rate_limit import limiter
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
@limiter.limit(lambda: get_settings().public_inbound_rate_limit)
async def inbound_webhook(
    request: Request, organization_id: uuid.UUID, db: DbSession
) -> InboundProcessResponse:
    organization = db.get(Organization, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    raw_body = await request.body()
    settings = get_settings()
    requires_signature = settings.webhook_signature_required or bool(
        organization.inbound_webhook_secret
    )

    if requires_signature:
        if not organization.inbound_webhook_secret:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Webhook signature required but organization has no secret configured",
            )
        signature_header = request.headers.get("X-Missed-Lead-Signature")
        if not signature_header:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing X-Missed-Lead-Signature header",
            )
        if signature_header.startswith("sha256="):
            provided_sig = signature_header.split("sha256=", 1)[1].strip()
        else:
            provided_sig = signature_header.strip()

        expected_sig = hmac.new(
            organization.inbound_webhook_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(provided_sig, expected_sig):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature",
            )

    try:
        decoded = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else raw_body
        payload_data = json.loads(decoded)
        payload = WebsiteWebhookCreate.model_validate(payload_data)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid webhook JSON payload: {exc}",
        ) from exc

    return _process_website_payload(organization_id, payload, InboundChannel.WEBSITE_WEBHOOK, db)


@router.post(
    "/inbound/form/{organization_id}",
    response_model=InboundProcessResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(lambda: get_settings().public_inbound_rate_limit)
def inbound_form(
    request: Request,
    organization_id: uuid.UUID,
    payload: WebsiteWebhookCreate,
    db: DbSession,
) -> InboundProcessResponse:
    return _process_website_payload(organization_id, payload, InboundChannel.WEBSITE_FORM, db)


@router.post(
    "/inquiries/{organization_id}",
    response_model=PublicInquiryResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(lambda: get_settings().public_inbound_rate_limit)
def create_public_inquiry(
    request: Request,
    organization_id: uuid.UUID,
    payload: PublicInquiryCreate,
    db: DbSession,
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
