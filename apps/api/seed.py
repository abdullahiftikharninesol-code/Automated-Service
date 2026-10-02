"""Idempotent demo seed. Run after `alembic upgrade head`."""

from sqlalchemy import select

from app.ai.mock import MockAIProvider
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.enums import BusinessType, LeadSource, LeadStatus, UserRole
from app.models.organization import Organization
from app.models.user import User
from app.schemas.lead import LeadCreate
from app.services.email import ConsoleEmailProvider
from app.services.leads import LeadService

DEMO_EMAIL = "owner@example.com"
DEMO_PASSWORD = "DemoPassword123!"


def seed() -> None:
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.email == DEMO_EMAIL))
        if existing:
            print(f"Demo data already exists for {DEMO_EMAIL}")
            return

        organization = Organization(
            name="ComfortAir HVAC",
            industry="HVAC",
            business_type=BusinessType.HVAC,
            timezone="America/Chicago",
        )
        db.add(organization)
        db.flush()
        db.add(
            User(
                organization_id=organization.id,
                name="Alex Morgan",
                email=DEMO_EMAIL,
                password_hash=hash_password(DEMO_PASSWORD),
                role=UserRole.OWNER,
            )
        )
        service = LeadService(db, MockAIProvider(), ConsoleEmailProvider())
        john = service.create(
            organization,
            LeadCreate(
                customer_name="John Carter",
                customer_email="john@example.com",
                customer_phone="555-0101",
                message="My AC stopped cooling this morning. Need someone today.",
                source=LeadSource.WEBSITE,
            ),
        )
        sarah = service.create(
            organization,
            LeadCreate(
                customer_name="Sarah Miller",
                customer_email="sarah@example.com",
                customer_phone="555-0102",
                message="Looking for pricing for a new AC installation.",
                source=LeadSource.MANUAL,
            ),
        )
        service.change_status(sarah, organization, LeadStatus.CONTACTED)
        michael = service.create(
            organization,
            LeadCreate(
                customer_name="Michael Brown",
                customer_email="michael@example.com",
                customer_phone="555-0103",
                message="Furnace making a strange noise.",
                source=LeadSource.PHONE,
            ),
        )
        service.change_status(michael, organization, LeadStatus.BOOKED)
        db.commit()
        print(f"Seeded {organization.name} ({organization.id})")
        print(f"Login: {DEMO_EMAIL} / {DEMO_PASSWORD}")
        print(f"Public form: http://localhost:3000/inquiry/{organization.id}")
        print(f"Embed form: http://localhost:3000/embed/inquiry/{organization.id}")
        print(f"Webhook: http://localhost:8000/public/inbound/webhook/{organization.id}")
        print(f"New lead: {john.customer_name}")


if __name__ == "__main__":
    seed()
