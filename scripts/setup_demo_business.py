#!/usr/bin/env python3
"""Setup Generic Demo Business for Live WhatsApp Validation & Pilot Readiness.

Creates or updates a generic pilot organization:
- Name: Demo Business
- Business Type: GENERAL
- Configures generic qualification fields:
    * customer_need ("What do you need help with?")
    * preferred_date ("What date would you prefer?")
    * location ("What city or location are you in?")
- Binds WhatsApp configuration (whatsapp_phone_number_id, whatsapp_business_account_id)
- Creates an owner login for manual dashboard QA
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure apps/api is importable
repo_root = Path(__file__).resolve().parent.parent
api_dir = repo_root / "apps" / "api"
if str(api_dir) not in sys.path:
    sys.path.insert(0, str(api_dir))

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.enums import BusinessType, QualificationFieldType, UserRole
from app.models.organization import Organization
from app.models.qualification import QualificationField
from app.models.user import User


GENERIC_FIELDS = [
    {
        "key": "customer_need",
        "label": "Customer Need",
        "description": "What assistance or service the customer is asking for",
        "field_type": QualificationFieldType.TEXT,
        "required": True,
        "sort_order": 0,
        "question_text": "What do you need help with?",
    },
    {
        "key": "preferred_date",
        "label": "Preferred Date",
        "description": "Preferred date or timeline for the request",
        "field_type": QualificationFieldType.TEXT,
        "required": True,
        "sort_order": 1,
        "question_text": "What date would you prefer?",
    },
    {
        "key": "location",
        "label": "Location",
        "description": "Customer city, area, or service address",
        "field_type": QualificationFieldType.TEXT,
        "required": True,
        "sort_order": 2,
        "question_text": "What city or location are you in?",
    },
]


def setup_demo_business(
    phone_number_id: str | None = None,
    waba_id: str | None = None,
    display_phone: str | None = "+15551234567",
    owner_email: str = "demo@example.com",
    owner_password: str = "DemoPassword123!",
    short_reminder_minutes: int | None = None,
) -> Organization:
    settings = get_settings()
    target_phone_id = (
        phone_number_id
        or settings.meta_whatsapp_phone_number_id
        or "105554443332221"
    )
    target_waba_id = (
        waba_id
        or settings.meta_whatsapp_business_account_id
        or "109998887776665"
    )

    db: Session = SessionLocal()
    try:
        # 1. Find or create Organization
        org = db.scalar(select(Organization).where(Organization.name == "Demo Business"))
        if not org:
            org = Organization(
                name="Demo Business",
                business_type=BusinessType.GENERAL,
                default_phone_region="US",
            )
            db.add(org)
            db.flush()
            print(f"[SETUP] Created organization '{org.name}' (ID: {org.id})")
        else:
            print(f"[SETUP] Updating existing organization '{org.name}' (ID: {org.id})")

        org.business_type = BusinessType.GENERAL
        org.whatsapp_enabled = True
        org.whatsapp_phone_number_id = target_phone_id
        org.whatsapp_business_account_id = target_waba_id
        if display_phone:
            org.whatsapp_display_phone_number = display_phone

        # Optional testing reminder delay
        if short_reminder_minutes is not None:
            settings_dict = dict(org.settings or {})
            settings_dict["owner_reminder_delay_minutes"] = short_reminder_minutes
            org.settings = settings_dict
            print(f"[SETUP] Set temporary reminder delay to {short_reminder_minutes} minutes")

        db.flush()

        # 2. Find or create Demo Owner User
        user = db.scalar(select(User).where(User.email == owner_email))
        if not user:
            user = User(
                organization_id=org.id,
                email=owner_email,
                password_hash=hash_password(owner_password),
                name="Demo Business Owner",
                role=UserRole.OWNER,
            )
            db.add(user)
            db.flush()
            print(f"[SETUP] Created demo owner user '{owner_email}'")
        else:
            user.organization_id = org.id
            user.password_hash = hash_password(owner_password)
            user.role = UserRole.OWNER
            db.flush()
            print(f"[SETUP] Updated demo owner user '{owner_email}'")

        # 3. Configure Generic Qualification Fields
        for f_data in GENERIC_FIELDS:
            qf = db.scalar(
                select(QualificationField).where(
                    QualificationField.organization_id == org.id,
                    QualificationField.key == f_data["key"],
                )
            )
            if not qf:
                qf = QualificationField(
                    organization_id=org.id,
                    key=f_data["key"],
                    label=f_data["label"],
                    description=f_data["description"],
                    field_type=f_data["field_type"],
                    required=f_data["required"],
                    sort_order=f_data["sort_order"],
                    question_text=f_data["question_text"],
                    enabled=True,
                )
                db.add(qf)
                print(f"[SETUP] Added qualification field: '{f_data['key']}'")
            else:
                qf.label = f_data["label"]
                qf.description = f_data["description"]
                qf.required = f_data["required"]
                qf.sort_order = f_data["sort_order"]
                qf.question_text = f_data["question_text"]
                qf.enabled = True
                print(f"[SETUP] Updated qualification field: '{f_data['key']}'")

        db.commit()
        db.refresh(org)

        print("\n" + "=" * 60)
        print(" DEMO BUSINESS SETUP COMPLETE")
        print("=" * 60)
        print(f" Organization ID:     {org.id}")
        print(f" Organization Name:   {org.name}")
        print(f" Business Type:       {org.business_type.value}")
        print(f" WhatsApp Enabled:    {org.whatsapp_enabled}")
        print(f" WhatsApp Phone ID:   {org.whatsapp_phone_number_id}")
        print(f" WhatsApp WABA ID:    {org.whatsapp_business_account_id}")
        print(f" Owner Login Email:   {owner_email}")
        print(f" Configured Fields:   {', '.join(f['key'] for f in GENERIC_FIELDS)}")
        print("=" * 60 + "\n")
        return org

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed generic Demo Business for pilot testing.")
    parser.add_argument("--phone-id", help="Meta receiving WhatsApp phone number ID")
    parser.add_argument("--waba-id", help="Meta WhatsApp Business Account ID")
    parser.add_argument("--display-phone", default="+15551234567", help="Display phone number")
    parser.add_argument("--email", default="demo@example.com", help="Owner login email")
    parser.add_argument("--password", default="DemoPassword123!", help="Owner login password")
    parser.add_argument("--reminder-minutes", type=int, default=None, help="Temporary short reminder delay in minutes")
    args = parser.parse_args()

    setup_demo_business(
        phone_number_id=args.phone_id,
        waba_id=args.waba_id,
        display_phone=args.display_phone,
        owner_email=args.email,
        owner_password=args.password,
        short_reminder_minutes=args.reminder_minutes,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
