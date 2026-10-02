import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.ai import get_ai_provider
from app.api.dependencies import CurrentOrganization, CurrentUser, DbSession
from app.models.enums import LeadSource, LeadStatus, Urgency
from app.models.lead import Lead
from app.repositories.leads import LeadRepository
from app.schemas.inbound import InboundMessageResponse
from app.schemas.lead import (
    FollowUpDraftResponse,
    LeadCreate,
    LeadEventResponse,
    LeadListResponse,
    LeadResponse,
    LeadStatusUpdate,
    LeadUpdate,
    NoteCreate,
)
from app.services.email import get_email_provider
from app.services.inbound import InboundLeadService
from app.services.leads import LeadService

router = APIRouter(prefix="/leads", tags=["Leads"])


def scoped_lead(db: DbSession, organization_id: uuid.UUID, lead_id: uuid.UUID) -> Lead:
    lead = LeadRepository(db).get(lead_id, organization_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.get("", response_model=LeadListResponse)
def list_leads(
    db: DbSession,
    organization: CurrentOrganization,
    search: str | None = None,
    lead_status: Annotated[LeadStatus | None, Query(alias="status")] = None,
    urgency: Urgency | None = None,
    source: LeadSource | None = None,
    sort: str = Query(default="newest", pattern="^(newest|oldest)$"),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> LeadListResponse:
    items, total = LeadRepository(db).list(
        organization.id,
        search=search,
        status=lead_status,
        urgency=urgency,
        source=source,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return LeadListResponse(items=items, total=total)


@router.post("", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
def create_lead(
    payload: LeadCreate, db: DbSession, organization: CurrentOrganization
) -> LeadResponse:
    service = LeadService(db, get_ai_provider(), get_email_provider())
    return LeadResponse.model_validate(service.create(organization, payload))


@router.get("/{lead_id}", response_model=LeadResponse)
def get_lead(lead_id: uuid.UUID, db: DbSession, organization: CurrentOrganization) -> Lead:
    return scoped_lead(db, organization.id, lead_id)


@router.patch("/{lead_id}", response_model=LeadResponse)
def update_lead(
    lead_id: uuid.UUID,
    payload: LeadUpdate,
    db: DbSession,
    organization: CurrentOrganization,
) -> Lead:
    lead = scoped_lead(db, organization.id, lead_id)
    return LeadService(db, get_ai_provider(), get_email_provider()).update(lead, payload)


@router.post("/{lead_id}/status", response_model=LeadResponse)
def update_status(
    lead_id: uuid.UUID,
    payload: LeadStatusUpdate,
    db: DbSession,
    organization: CurrentOrganization,
) -> Lead:
    lead = scoped_lead(db, organization.id, lead_id)
    return LeadService(db, get_ai_provider(), get_email_provider()).change_status(
        lead, organization, payload.status
    )


@router.post("/{lead_id}/notes", response_model=LeadEventResponse)
def add_note(
    lead_id: uuid.UUID,
    payload: NoteCreate,
    db: DbSession,
    user: CurrentUser,
    organization: CurrentOrganization,
) -> LeadEventResponse:
    lead = scoped_lead(db, organization.id, lead_id)
    event = LeadService(db, get_ai_provider(), get_email_provider()).add_note(
        lead, payload.note, user.id
    )
    return LeadEventResponse.model_validate(event)


@router.post("/{lead_id}/generate-followup", response_model=FollowUpDraftResponse)
def generate_followup(
    lead_id: uuid.UUID, db: DbSession, organization: CurrentOrganization
) -> FollowUpDraftResponse:
    lead = scoped_lead(db, organization.id, lead_id)
    message = LeadService(db, get_ai_provider(), get_email_provider()).generate_followup(lead)
    return FollowUpDraftResponse(message=message)


@router.get("/{lead_id}/events", response_model=list[LeadEventResponse])
def lead_events(
    lead_id: uuid.UUID, db: DbSession, organization: CurrentOrganization
) -> list[LeadEventResponse]:
    lead = scoped_lead(db, organization.id, lead_id)
    events = LeadService(db, get_ai_provider(), get_email_provider()).events(lead)
    return [LeadEventResponse.model_validate(event) for event in events]


@router.get("/{lead_id}/messages", response_model=list[InboundMessageResponse])
def lead_messages(
    lead_id: uuid.UUID, db: DbSession, organization: CurrentOrganization
) -> list[InboundMessageResponse]:
    lead = scoped_lead(db, organization.id, lead_id)
    service = InboundLeadService(db, get_ai_provider(), get_email_provider())
    return [InboundMessageResponse.model_validate(item) for item in service.messages(lead)]
