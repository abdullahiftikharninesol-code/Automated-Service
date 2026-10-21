import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.api.dependencies import CurrentOrganization, DbSession
from app.schemas.qualification import (
    ApplyTemplateRequest,
    QualificationFieldCreate,
    QualificationFieldListResponse,
    QualificationFieldResponse,
    QualificationFieldUpdate,
)
from app.services.qualification import QualificationService

router = APIRouter(prefix="/qualification-fields", tags=["Qualification"])


@router.get("", response_model=QualificationFieldListResponse)
def list_qualification_fields(
    db: DbSession,
    organization: CurrentOrganization,
    enabled_only: bool = Query(default=False),
) -> QualificationFieldListResponse:
    service = QualificationService(db)
    fields = service.list_fields(organization.id, enabled_only=enabled_only)
    return QualificationFieldListResponse(
        items=[QualificationFieldResponse.model_validate(f) for f in fields]
    )


@router.post(
    "",
    response_model=QualificationFieldResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_qualification_field(
    payload: QualificationFieldCreate,
    db: DbSession,
    organization: CurrentOrganization,
) -> QualificationFieldResponse:
    service = QualificationService(db)
    try:
        field = service.create_field(organization.id, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return QualificationFieldResponse.model_validate(field)


@router.patch("/{field_id}", response_model=QualificationFieldResponse)
def update_qualification_field(
    field_id: uuid.UUID,
    payload: QualificationFieldUpdate,
    db: DbSession,
    organization: CurrentOrganization,
) -> QualificationFieldResponse:
    service = QualificationService(db)
    field = service.update_field(organization.id, field_id, payload)
    if not field:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Qualification field not found",
        )
    return QualificationFieldResponse.model_validate(field)


@router.delete("/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_qualification_field(
    field_id: uuid.UUID,
    db: DbSession,
    organization: CurrentOrganization,
) -> None:
    service = QualificationService(db)
    deleted = service.delete_field(organization.id, field_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Qualification field not found",
        )


@router.post("/apply-template", response_model=QualificationFieldListResponse)
def apply_qualification_template(
    payload: ApplyTemplateRequest,
    db: DbSession,
    organization: CurrentOrganization,
) -> QualificationFieldListResponse:
    service = QualificationService(db)
    try:
        fields = service.apply_template(
            organization_id=organization.id,
            template_name=payload.template_name,
            replace_existing=payload.replace_existing,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return QualificationFieldListResponse(
        items=[QualificationFieldResponse.model_validate(f) for f in fields]
    )
