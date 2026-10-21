from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import get_settings
from app.models.enums import MessageDeliveryStatus

logger = logging.getLogger("missed_lead_rescue.whatsapp.provider")


@dataclass(frozen=True)
class WhatsAppSendResult:
    success: bool
    provider_message_id: str | None = None
    status: MessageDeliveryStatus = MessageDeliveryStatus.SENT
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class WhatsAppProvider(ABC):
    @abstractmethod
    def send_text_message(
        self,
        phone_number_id: str,
        to_phone: str,
        body: str,
        access_token: str | None = None,
    ) -> WhatsAppSendResult:
        """Send an outbound WhatsApp text message to a customer."""
        pass


class MetaWhatsAppCloudProvider(WhatsAppProvider):
    def __init__(self, timeout: float | None = None):
        self.settings = get_settings()
        self.timeout = timeout or self.settings.whatsapp_http_timeout_seconds

    def send_text_message(
        self,
        phone_number_id: str,
        to_phone: str,
        body: str,
        access_token: str | None = None,
    ) -> WhatsAppSendResult:
        token = access_token or self.settings.meta_whatsapp_access_token
        if not token:
            logger.error("Meta WhatsApp access token not configured.")
            return WhatsAppSendResult(
                success=False,
                status=MessageDeliveryStatus.FAILED,
                error="Meta WhatsApp access token not configured",
            )

        # Normalize phone: Meta expects digits without leading '+' or symbols
        normalized_to = to_phone.lstrip("+").strip()
        version = self.settings.meta_graph_api_version or "v22.0"
        url = f"https://graph.facebook.com/{version}/{phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": normalized_to,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": body,
            },
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, json=payload, headers=headers)

            if response.is_success:
                data = response.json()
                messages = data.get("messages", [])
                provider_msg_id = messages[0].get("id") if messages else None
                logger.info(
                    "WhatsApp message sent successfully: recipient=%s wamid=%s",
                    normalized_to,
                    provider_msg_id,
                )
                return WhatsAppSendResult(
                    success=True,
                    provider_message_id=provider_msg_id,
                    status=MessageDeliveryStatus.SENT,
                    metadata={"response": data},
                )
            else:
                error_body = response.text
                try:
                    error_json = response.json().get("error", {})
                    error_message = error_json.get("message") or error_body
                    error_code = error_json.get("code")
                except Exception:
                    error_message = error_body
                    error_code = None

                logger.error(
                    "Meta WhatsApp API error (HTTP %d, code=%s): %s",
                    response.status_code,
                    error_code,
                    error_message,
                )
                return WhatsAppSendResult(
                    success=False,
                    status=MessageDeliveryStatus.FAILED,
                    error=f"HTTP {response.status_code}: {error_message}",
                    metadata={"status_code": response.status_code, "error_code": error_code},
                )
        except Exception as exc:
            logger.exception("Network/connection failure when sending WhatsApp message: %s", exc)
            return WhatsAppSendResult(
                success=False,
                status=MessageDeliveryStatus.FAILED,
                error=f"Connection failure: {str(exc)}",
            )


class FakeWhatsAppProvider(WhatsAppProvider):
    def __init__(self, should_fail: bool = False, fail_reason: str = "Simulated delivery failure"):
        self.should_fail = should_fail
        self.fail_reason = fail_reason
        self.sent_messages: list[dict[str, Any]] = []

    def send_text_message(
        self,
        phone_number_id: str,
        to_phone: str,
        body: str,
        access_token: str | None = None,
    ) -> WhatsAppSendResult:
        normalized_to = to_phone.lstrip("+").strip()
        record = {
            "phone_number_id": phone_number_id,
            "to_phone": normalized_to,
            "body": body,
            "access_token_provided": bool(access_token),
        }

        if self.should_fail:
            record["failed"] = True
            record["error"] = self.fail_reason
            self.sent_messages.append(record)
            logger.warning("FakeWhatsAppProvider simulated failure: to=%s", normalized_to)
            return WhatsAppSendResult(
                success=False,
                status=MessageDeliveryStatus.FAILED,
                error=self.fail_reason,
            )

        msg_id = f"wamid.mock_{uuid.uuid4().hex[:16]}"
        record["id"] = msg_id
        record["failed"] = False
        self.sent_messages.append(record)
        logger.info("FakeWhatsAppProvider sent message: to=%s wamid=%s", normalized_to, msg_id)
        return WhatsAppSendResult(
            success=True,
            provider_message_id=msg_id,
            status=MessageDeliveryStatus.SENT,
            metadata={"mock": True},
        )


_default_fake_provider = FakeWhatsAppProvider()


def get_whatsapp_provider() -> WhatsAppProvider:
    settings = get_settings()
    if settings.whatsapp_provider.lower() == "meta":
        return MetaWhatsAppCloudProvider()
    return _default_fake_provider
