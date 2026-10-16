from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.phone import normalize_phone_number
from app.models.customer import Customer

logger = logging.getLogger("missed_lead_rescue.customer")


class CustomerService:
    def __init__(self, db: Session):
        self.db = db

    def find_or_create(
        self,
        organization_id: uuid.UUID,
        name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        default_region: str | None = None,
        metadata: dict | None = None,
    ) -> Customer:
        phone_clean = phone.strip() if phone and phone.strip() else None
        phone_normalized = normalize_phone_number(phone_clean, default_region=default_region)

        email_clean = email.strip() if email and email.strip() else None
        email_normalized = email_clean.lower() if email_clean else None

        name_clean = name.strip() if name and name.strip() else None
        now = datetime.now(UTC)

        # 1. Match by normalized phone
        customer_by_phone: Customer | None = None
        if phone_normalized:
            customer_by_phone = self.db.scalar(
                select(Customer).where(
                    Customer.organization_id == organization_id,
                    Customer.phone_normalized == phone_normalized,
                )
            )

        # 2. Match by normalized email
        customer_by_email: Customer | None = None
        if email_normalized:
            customer_by_email = self.db.scalar(
                select(Customer).where(
                    Customer.organization_id == organization_id,
                    Customer.email_normalized == email_normalized,
                )
            )

        # Deterministic conflict resolution
        customer: Customer | None = None
        if customer_by_phone and customer_by_email:
            if customer_by_phone.id == customer_by_email.id:
                customer = customer_by_phone
            else:
                logger.warning(
                    "Identity conflict in org %s: phone matches customer %s but email matches %s. "
                    "Prioritizing phone match without merging.",
                    organization_id,
                    customer_by_phone.id,
                    customer_by_email.id,
                )
                customer = customer_by_phone
        elif customer_by_phone:
            customer = customer_by_phone
        elif customer_by_email:
            customer = customer_by_email

        if customer:
            # Enrich missing fields on existing customer
            if not customer.name and name_clean:
                customer.name = name_clean
            if not customer.email and email_clean:
                customer.email = email_clean
                customer.email_normalized = email_normalized
            if not customer.phone and phone_clean:
                customer.phone = phone_clean
                customer.phone_normalized = phone_normalized
            customer.last_contact_at = now
            self.db.flush()
            return customer

        # 3. Create new customer
        customer = Customer(
            organization_id=organization_id,
            name=name_clean,
            email=email_clean,
            email_normalized=email_normalized,
            phone=phone_clean,
            phone_normalized=phone_normalized,
            customer_metadata=metadata or {},
            last_contact_at=now,
        )
        self.db.add(customer)
        self.db.flush()
        return customer

    def get(self, organization_id: uuid.UUID, customer_id: uuid.UUID) -> Customer | None:
        return self.db.scalar(
            select(Customer).where(
                Customer.organization_id == organization_id,
                Customer.id == customer_id,
            )
        )

    def list(
        self,
        organization_id: uuid.UUID,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Customer]:
        query = (
            select(Customer)
            .where(Customer.organization_id == organization_id)
            .order_by(Customer.created_at.desc())
        )
        if q and q.strip():
            term = f"%{q.strip().lower()}%"
            query = query.where(
                or_(
                    func.lower(Customer.name).ilike(term),
                    func.lower(Customer.email).ilike(term),
                    Customer.phone.ilike(term),
                    Customer.phone_normalized.ilike(term),
                )
            )
        return list(self.db.scalars(query.offset(offset).limit(limit)))
