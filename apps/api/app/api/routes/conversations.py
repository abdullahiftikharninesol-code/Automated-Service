from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query

from app.api.dependencies import CurrentOrganization, DbSession
from app.models.enums import ConversationStatus, InboundChannel, MessageSenderType, WaitingOn
from app.schemas.conversation import (
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationMessageCreate,
    ConversationMessageResponse,
    ConversationResponse,
)
from app.schemas.customer import CustomerResponse
from app.services.conversation import ConversationService

router = APIRouter(prefix="/conversations", tags=["Conversations"])


@router.get("", response_model=ConversationListResponse)
def list_conversations(
    db: DbSession,
    organization: CurrentOrganization,
    status: ConversationStatus | None = None,
    channel: InboundChannel | None = None,
    waiting_on: WaitingOn | None = None,
    lead_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ConversationListResponse:
    service = ConversationService(db)
    items = service.list(
        organization_id=organization.id,
        status=status,
        channel=channel,
        waiting_on=waiting_on,
        lead_id=lead_id,
        customer_id=customer_id,
        limit=limit,
        offset=offset,
    )
    return ConversationListResponse(
        items=[ConversationResponse.model_validate(c) for c in items],
        total=len(items),
    )


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation(
    conversation_id: uuid.UUID,
    db: DbSession,
    organization: CurrentOrganization,
) -> ConversationDetailResponse:
    service = ConversationService(db)
    conv = service.get(organization.id, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = service.messages(organization.id, conversation_id)
    customer_resp = CustomerResponse.model_validate(conv.customer) if conv.customer else None
    return ConversationDetailResponse(
        id=conv.id,
        organization_id=conv.organization_id,
        customer_id=conv.customer_id,
        lead_id=conv.lead_id,
        channel=conv.channel,
        status=conv.status,
        waiting_on=conv.waiting_on,
        subject=conv.subject,
        external_thread_id=conv.external_thread_id,
        last_message_at=conv.last_message_at,
        last_inbound_at=conv.last_inbound_at,
        last_outbound_at=conv.last_outbound_at,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        customer=customer_resp,
        messages=[ConversationMessageResponse.model_validate(m) for m in messages],
    )


@router.get("/{conversation_id}/messages", response_model=list[ConversationMessageResponse])
def get_conversation_messages(
    conversation_id: uuid.UUID,
    db: DbSession,
    organization: CurrentOrganization,
) -> list[ConversationMessageResponse]:
    service = ConversationService(db)
    conv = service.get(organization.id, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = service.messages(organization.id, conversation_id)
    return [ConversationMessageResponse.model_validate(m) for m in messages]


@router.post(
    "/{conversation_id}/messages",
    response_model=ConversationMessageResponse,
    status_code=201,
)
def send_conversation_message(
    conversation_id: uuid.UUID,
    payload: ConversationMessageCreate,
    db: DbSession,
    organization: CurrentOrganization,
) -> ConversationMessageResponse:
    service = ConversationService(db)
    conv = service.get(organization.id, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msg = service.append_outbound_message(
        organization_id=organization.id,
        conversation_id=conversation_id,
        body=payload.body,
        channel=payload.channel or conv.channel,
        sender_type=MessageSenderType.OWNER,
    )
    db.commit()
    db.refresh(msg)
    return ConversationMessageResponse.model_validate(msg)
