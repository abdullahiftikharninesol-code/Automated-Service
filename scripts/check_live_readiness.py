#!/usr/bin/env python3
"""Live WhatsApp Validation & Pilot Readiness Checker.

Safely audits live environment configuration, database state,
Alembic migration version, Meta WhatsApp settings, organization
mappings, and AI setup without exposing secrets.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure apps/api is importable
repo_root = Path(__file__).resolve().parent.parent
api_dir = repo_root / "apps" / "api"
if str(api_dir) not in sys.path:
    sys.path.insert(0, str(api_dir))

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.organization import Organization
from app.models.qualification import QualificationField


def mask_status(val: str | None, required_len: int = 1) -> str:
    if not val or len(val.strip()) < required_len:
        return "MISSING"
    return "CONFIGURED"


def main() -> int:
    settings = get_settings()
    issues: list[str] = []

    print("\n" + "=" * 60)
    print(" MISSED LEAD RESCUE — LIVE WHATSAPP READINESS CHECKER")
    print("=" * 60)

    # 1. Database Reachability
    db_ok = False
    try:
        engine = create_engine(settings.database_url, connect_args={"connect_timeout": 5})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
        print(f"{'Database connection':.<35} PASS")
    except Exception as exc:
        print(f"{'Database connection':.<35} FAIL ({exc.__class__.__name__})")
        issues.append("Database is not reachable. Ensure PostgreSQL is running on port 5432.")

    # 2. Alembic Migration Version
    migration_ok = False
    current_version = None
    if db_ok:
        try:
            with engine.connect() as conn:
                res = conn.execute(text("SELECT version_num FROM alembic_version"))
                row = res.first()
                if row:
                    current_version = row[0]
            expected_head = "20261020_0007"
            if current_version == expected_head:
                migration_ok = True
                print(f"{'Database migration head':.<35} PASS ({current_version})")
            else:
                print(f"{'Database migration head':.<35} FAIL (current: {current_version})")
                issues.append(f"Database migration not at head. Run 'alembic upgrade head' (expected {expected_head}).")
        except Exception:
            print(f"{'Database migration head':.<35} FAIL (table alembic_version missing)")
            issues.append("alembic_version table not found. Run 'alembic upgrade head'.")

    # 3. WhatsApp Enabled
    if settings.whatsapp_enabled:
        print(f"{'WhatsApp integration enabled':.<35} PASS (true)")
    else:
        print(f"{'WhatsApp integration enabled':.<35} BLOCKED (WHATSAPP_ENABLED=false)")
        issues.append("Set WHATSAPP_ENABLED=true in .env to accept live Meta webhooks.")

    # 4. WhatsApp Provider
    if settings.whatsapp_provider == "meta":
        print(f"{'WhatsApp provider mode':.<35} PASS (meta)")
    else:
        print(f"{'WhatsApp provider mode':.<35} WARNING ({settings.whatsapp_provider})")
        if settings.whatsapp_enabled:
            issues.append("Set WHATSAPP_PROVIDER=meta in .env for live Meta Cloud API delivery (currently mock).")

    # 5. Meta Credentials Audit (Safe masking)
    access_token_status = mask_status(settings.meta_whatsapp_access_token, required_len=10)
    print(f"{'Meta access token':.<35} {access_token_status}")
    if access_token_status == "MISSING":
        issues.append("Set META_WHATSAPP_ACCESS_TOKEN in .env (System User or Temporary Access Token).")

    app_secret_status = mask_status(settings.meta_app_secret, required_len=8)
    print(f"{'Meta app secret':.<35} {app_secret_status}")
    if app_secret_status == "MISSING":
        issues.append("Set META_APP_SECRET in .env for X-Hub-Signature-256 webhook validation.")

    verify_token_status = mask_status(settings.meta_whatsapp_verify_token, required_len=3)
    print(f"{'Meta webhook verify token':.<35} {verify_token_status}")
    if verify_token_status == "MISSING":
        issues.append("Set META_WHATSAPP_VERIFY_TOKEN in .env for GET /webhooks/whatsapp handshake.")

    phone_id_status = mask_status(settings.meta_whatsapp_phone_number_id, required_len=3)
    print(f"{'Meta phone number ID':.<35} {phone_id_status}")
    if phone_id_status == "MISSING":
        issues.append("Set META_WHATSAPP_PHONE_NUMBER_ID in .env.")

    waba_id_status = mask_status(settings.meta_whatsapp_business_account_id, required_len=3)
    print(f"{'Meta business account ID':.<35} {waba_id_status}")
    if waba_id_status == "MISSING":
        issues.append("Set META_WHATSAPP_BUSINESS_ACCOUNT_ID in .env.")

    print(f"{'Meta Graph API version':.<35} PASS ({settings.meta_graph_api_version})")

    # 6. Organization Mapping in Database
    org_mapped = False
    org_with_quals = False
    if db_ok:
        try:
            with Session(engine) as session:
                target_phone_id = settings.meta_whatsapp_phone_number_id
                stmt = select(Organization)
                if target_phone_id:
                    stmt = stmt.where(Organization.whatsapp_phone_number_id == target_phone_id)
                else:
                    stmt = stmt.where(Organization.whatsapp_phone_number_id.is_not(None))
                orgs = list(session.scalars(stmt))

                if orgs:
                    org = orgs[0]
                    if not org.whatsapp_enabled:
                        print(f"{'Organization WhatsApp mapping':.<35} FAIL ({org.name} whatsapp_enabled=false)")
                        issues.append(f"Organization '{org.name}' has whatsapp_enabled=false. Must be true for webhook routing.")
                    else:
                        org_mapped = True
                        print(f"{'Organization WhatsApp mapping':.<35} PASS ({org.name})")

                    # Check qualification fields for mapped organization
                    quals = list(
                        session.scalars(
                            select(QualificationField).where(
                                QualificationField.organization_id == org.id,
                                QualificationField.enabled.is_(True),
                            )
                        )
                    )
                    if quals:
                        org_with_quals = True
                        req_keys = [q.key for q in quals if q.required]
                        print(f"{'Qualification fields configured':.<35} PASS ({len(quals)} fields, {len(req_keys)} required)")
                    else:
                        print(f"{'Qualification fields configured':.<35} WARNING (0 fields)")
                        issues.append(f"Organization '{org.name}' has no enabled qualification fields configured.")
                else:
                    print(f"{'Organization WhatsApp mapping':.<35} MISSING")
                    issues.append("No Organization in database is linked to the configured META_WHATSAPP_PHONE_NUMBER_ID.")
        except Exception as exc:
            print(f"{'Organization mapping check':.<35} FAIL ({exc.__class__.__name__})")

    # 7. Background Jobs Scheduler
    if settings.background_jobs_enabled:
        print(f"{'Background scheduler enabled':.<35} PASS")
    else:
        print(f"{'Background scheduler enabled':.<35} WARNING (disabled)")
        issues.append("Enable BACKGROUND_JOBS_ENABLED=true for automated owner response reminder sweeps.")

    # 8. AI Provider
    if settings.ai_provider == "openai":
        openai_status = mask_status(settings.openai_api_key, required_len=15)
        print(f"{'AI provider mode':.<35} openai ({openai_status})")
        if openai_status == "MISSING":
            issues.append("AI_PROVIDER=openai requires OPENAI_API_KEY to be set in .env.")
    else:
        print(f"{'AI provider mode':.<35} PASS ({settings.ai_provider} - deterministic)")

    # 9. Public URLs
    print(f"{'Backend public URL':.<35} {settings.public_api_url}")
    print(f"{'Frontend public URL':.<35} {settings.public_web_url}")

    print("=" * 60)
    if not issues:
        print(" LIVE READINESS STATUS: READY")
        print(" All prerequisites for live Meta WhatsApp communication are satisfied.")
        print("=" * 60 + "\n")
        return 0
    else:
        print(" LIVE READINESS STATUS: BLOCKED")
        print(f" {len(issues)} corrective action(s) required:")
        for idx, item in enumerate(issues, 1):
            print(f"   {idx}. {item}")
        print("=" * 60 + "\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
