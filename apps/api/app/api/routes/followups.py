import uuid

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.dependencies import CurrentOrganization, DbSession
from app.jobs import FollowUpSweepJob
from app.models.enums import FollowUpStatus, FollowUpType
from app.models.followup import FollowUp
from app.schemas.followup import FollowUpListResponse, FollowUpResponse

router = APIRouter(prefix="/followups", tags=["Follow-ups"])


class ProcessedResponse(BaseModel):
    processed: int


@router.post("/process", response_model=ProcessedResponse)
def process_followups(db: DbSession, organization: CurrentOrganization) -> ProcessedResponse:
    count = FollowUpSweepJob(db, organization.id).run()
    return ProcessedResponse(processed=count)


@router.get("", response_model=FollowUpListResponse)
def list_followups(
    db: DbSession,
    organization: CurrentOrganization,
    status: FollowUpStatus | None = None,
    lead_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    type: FollowUpType | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> FollowUpListResponse:
    query = select(FollowUp).where(FollowUp.organization_id == organization.id)

    if status:
        query = query.where(FollowUp.status == status)
    if lead_id:
        query = query.where(FollowUp.lead_id == lead_id)
    if conversation_id:
        query = query.where(FollowUp.conversation_id == conversation_id)
    if type:
        query = query.where(FollowUp.type == type)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = list(
        db.scalars(
            query.order_by(FollowUp.due_at.asc(), FollowUp.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    )

    return FollowUpListResponse(
        items=[FollowUpResponse.model_validate(f) for f in items],
        total=total,
    )
