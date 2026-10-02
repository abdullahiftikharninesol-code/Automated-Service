from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.enums import LeadSource, LeadStatus, Urgency
from app.models.lead import Lead


class LeadRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, lead_id: uuid.UUID, organization_id: uuid.UUID) -> Lead | None:
        return self.db.scalar(
            select(Lead).where(Lead.id == lead_id, Lead.organization_id == organization_id)
        )

    def list(
        self,
        organization_id: uuid.UUID,
        *,
        search: str | None = None,
        status: LeadStatus | None = None,
        urgency: Urgency | None = None,
        source: LeadSource | None = None,
        sort: str = "newest",
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Lead], int]:
        filters = [Lead.organization_id == organization_id]
        if search:
            term = f"%{search.strip()}%"
            filters.append(
                or_(
                    Lead.customer_name.ilike(term),
                    Lead.customer_email.ilike(term),
                    Lead.customer_phone.ilike(term),
                    Lead.service_type.ilike(term),
                )
            )
        if status:
            filters.append(Lead.status == status)
        if urgency:
            filters.append(Lead.urgency == urgency)
        if source:
            filters.append(Lead.source == source)
        order = Lead.created_at.asc() if sort == "oldest" else Lead.created_at.desc()
        items = list(
            self.db.scalars(
                select(Lead).where(*filters).order_by(order).limit(limit).offset(offset)
            )
        )
        total = self.db.scalar(select(func.count(Lead.id)).where(*filters)) or 0
        return items, total

    def add(self, lead: Lead) -> Lead:
        self.db.add(lead)
        self.db.flush()
        return lead

    def pending_before(self, organization_id: uuid.UUID, now: datetime) -> list[Lead]:
        return list(
            self.db.scalars(
                select(Lead)
                .where(
                    Lead.organization_id == organization_id,
                    Lead.status.in_([LeadStatus.NEW, LeadStatus.CONTACTED]),
                    Lead.next_followup_at.is_not(None),
                    Lead.next_followup_at <= now,
                )
                .order_by(Lead.next_followup_at.asc())
            )
        )
