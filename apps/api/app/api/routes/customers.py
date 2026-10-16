from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query

from app.api.dependencies import CurrentOrganization, DbSession
from app.schemas.customer import CustomerListResponse, CustomerResponse
from app.services.customer import CustomerService

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.get("", response_model=CustomerListResponse)
def list_customers(
    db: DbSession,
    organization: CurrentOrganization,
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> CustomerListResponse:
    service = CustomerService(db)
    items = service.list(
        organization_id=organization.id,
        q=q,
        limit=limit,
        offset=offset,
    )
    return CustomerListResponse(
        items=[CustomerResponse.model_validate(c) for c in items],
        total=len(items),
    )


@router.get("/{customer_id}", response_model=CustomerResponse)
def get_customer(
    customer_id: uuid.UUID,
    db: DbSession,
    organization: CurrentOrganization,
) -> CustomerResponse:
    service = CustomerService(db)
    customer = service.get(organization.id, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return CustomerResponse.model_validate(customer)
