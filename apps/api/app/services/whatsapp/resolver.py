from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.organization import Organization

logger = logging.getLogger("missed_lead_rescue.whatsapp.resolver")


class WhatsAppOrganizationResolver:
    """Resolves Meta WhatsApp phone_number_id to the owning Organization.

    Strict tenant boundary: incoming webhooks identify the destination by the
    provider's receiving phone_number_id, NEVER from client-supplied payload parameters.
    """

    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()

    def resolve(self, phone_number_id: str | None) -> Organization | None:
        if not phone_number_id:
            logger.warning("[WHATSAPP_RESOLVER] Empty phone_number_id in webhook payload")
            return None

        # 1. Primary lookup: Match organization by registered phone_number_id
        org = self.db.scalar(
            select(Organization).where(
                Organization.whatsapp_phone_number_id == phone_number_id,
                Organization.whatsapp_enabled.is_(True),
            )
        )
        if org:
            return org

        # 2. Also check if configured even if whatsapp_enabled was not explicitly set
        org = self.db.scalar(
            select(Organization).where(
                Organization.whatsapp_phone_number_id == phone_number_id,
            )
        )
        if org:
            return org

        # 3. Development / single-tenant fallback: Check if phone_number_id matches global config
        env_phone_id = self.settings.meta_whatsapp_phone_number_id
        if env_phone_id and phone_number_id == env_phone_id:
            # Fall back to first organization in database for local test harness
            fallback_org = self.db.scalar(
                select(Organization).order_by(Organization.created_at.asc()).limit(1)
            )
            if fallback_org:
                logger.info(
                    "[WHATSAPP_RESOLVER] Resolved phone_number_id=%s "
                    "via env config fallback to org=%s",
                    phone_number_id,
                    fallback_org.id,
                )
                return fallback_org

        logger.warning(
            "[WHATSAPP_RESOLVER] No organization found for receiving WhatsApp phone_number_id=%s",
            phone_number_id,
        )
        return None
