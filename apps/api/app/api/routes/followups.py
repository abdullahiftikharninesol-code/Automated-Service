from fastapi import APIRouter
from pydantic import BaseModel

from app.api.dependencies import CurrentOrganization, DbSession
from app.jobs import FollowUpSweepJob

router = APIRouter(prefix="/followups", tags=["Follow-ups"])


class ProcessedResponse(BaseModel):
    processed: int


@router.post("/process", response_model=ProcessedResponse)
def process_followups(db: DbSession, organization: CurrentOrganization) -> ProcessedResponse:
    count = FollowUpSweepJob(db, organization.id).run()
    return ProcessedResponse(processed=count)
