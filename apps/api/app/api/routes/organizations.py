import secrets
import uuid

from fastapi import APIRouter, HTTPException

from app.api.dependencies import CurrentOrganization, DbSession
from app.core.config import get_settings
from app.schemas.organization import (
    OrganizationIntegrationResponse,
    OrganizationResponse,
    OrganizationUpdate,
    WebhookSecretRotateResponse,
)
from app.services.email import email_provider_status

router = APIRouter(prefix="/organizations", tags=["Organizations"])


@router.get("/{organization_id}", response_model=OrganizationResponse)
def get_organization(
    organization_id: uuid.UUID, organization: CurrentOrganization
) -> OrganizationResponse:
    if organization_id != organization.id:
        raise HTTPException(status_code=404, detail="Organization not found")
    return OrganizationResponse.model_validate(organization)


@router.patch("/{organization_id}", response_model=OrganizationResponse)
def update_organization(
    organization_id: uuid.UUID,
    payload: OrganizationUpdate,
    db: DbSession,
    organization: CurrentOrganization,
) -> OrganizationResponse:
    if organization_id != organization.id:
        raise HTTPException(status_code=404, detail="Organization not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(organization, key, value)
    db.commit()
    db.refresh(organization)
    return OrganizationResponse.model_validate(organization)


@router.get(
    "/{organization_id}/integration-info",
    response_model=OrganizationIntegrationResponse,
)
def integration_info(
    organization_id: uuid.UUID, organization: CurrentOrganization
) -> OrganizationIntegrationResponse:
    if organization_id != organization.id:
        raise HTTPException(status_code=404, detail="Organization not found")
    settings = get_settings()
    api_url = settings.public_api_url.rstrip("/")
    web_url = settings.public_web_url.rstrip("/")
    webhook_url = f"{api_url}/public/inbound/webhook/{organization.id}"
    embed_url = f"{web_url}/embed/inquiry/{organization.id}"
    provider, configured = email_provider_status()
    return OrganizationIntegrationResponse(
        inbound_webhook_url=webhook_url,
        embed_form_url=embed_url,
        embed_code=(
            f'<iframe src="{embed_url}" title="Contact {organization.name}" '
            'width="100%" height="720" frameborder="0"></iframe>'
        ),
        email_provider=provider,
        email_configured=configured,
        webhook_secret_configured=bool(organization.inbound_webhook_secret),
        whatsapp_enabled=bool(organization.whatsapp_enabled),
        whatsapp_configured=bool(
            organization.whatsapp_enabled
            and (organization.whatsapp_phone_number_id or settings.meta_whatsapp_phone_number_id)
        ),
        whatsapp_phone_number_id=(
            organization.whatsapp_phone_number_id or settings.meta_whatsapp_phone_number_id
        ),
        whatsapp_display_phone_number=organization.whatsapp_display_phone_number,
        whatsapp_webhook_url=f"{api_url}/webhooks/whatsapp",
    )


@router.post(
    "/{organization_id}/rotate-webhook-secret",
    response_model=WebhookSecretRotateResponse,
)
def rotate_webhook_secret(
    organization_id: uuid.UUID,
    db: DbSession,
    organization: CurrentOrganization,
) -> WebhookSecretRotateResponse:
    if organization_id != organization.id:
        raise HTTPException(status_code=404, detail="Organization not found")
    new_secret = f"whsec_{secrets.token_urlsafe(32)}"
    organization.inbound_webhook_secret = new_secret
    db.commit()
    db.refresh(organization)
    return WebhookSecretRotateResponse(webhook_secret=new_secret)
