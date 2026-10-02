from fastapi import APIRouter

from app.api.dependencies import CurrentOrganization, DbSession
from app.schemas.dashboard import DashboardResponse
from app.services.dashboard import DashboardService

router = APIRouter(tags=["Dashboard"])


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(db: DbSession, organization: CurrentOrganization) -> DashboardResponse:
    return DashboardService(db).get(organization.id)
