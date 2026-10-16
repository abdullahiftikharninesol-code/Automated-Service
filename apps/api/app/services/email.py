import logging
from typing import Protocol

import httpx

from app.core.config import get_settings

logger = logging.getLogger("missed_lead_rescue.email")


class EmailProvider(Protocol):
    @property
    def configured(self) -> bool: ...

    def send(self, *, to: str, subject: str, body: str) -> None: ...


class ConsoleEmailProvider:
    @property
    def configured(self) -> bool:
        return True

    def send(self, *, to: str, subject: str, body: str) -> None:
        logger.info("Development email to=%s subject=%s body=%s", to, subject, body)


class ResendEmailProvider:
    endpoint = "https://api.resend.com/emails"

    def __init__(
        self,
        api_key: str | None,
        email_from: str | None,
        timeout: float = 5.0,
    ):
        self.api_key = api_key
        self.email_from = email_from
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.email_from)

    def send(self, *, to: str, subject: str, body: str) -> None:
        if not self.configured:
            raise RuntimeError("Resend requires RESEND_API_KEY and EMAIL_FROM")
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    self.endpoint,
                    json={
                        "from": self.email_from,
                        "to": [to],
                        "subject": subject,
                        "text": body,
                    },
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )
                if response.status_code >= 300:
                    raise RuntimeError(f"Resend returned HTTP {response.status_code}")
        except httpx.RequestError as exc:
            logger.error("Resend HTTP request failed: %s", type(exc).__name__)
            raise RuntimeError(f"Resend connection failed: {type(exc).__name__}") from exc


def get_email_provider() -> EmailProvider:
    settings = get_settings()
    provider = settings.email_provider.lower()
    if provider == "console":
        return ConsoleEmailProvider()
    if provider == "resend":
        return ResendEmailProvider(
            settings.resend_api_key,
            settings.email_from,
            timeout=settings.email_timeout_seconds,
        )
    raise RuntimeError(f"Unsupported EMAIL_PROVIDER: {provider}")


def email_provider_status() -> tuple[str, bool]:
    settings = get_settings()
    provider = settings.email_provider.lower()
    if provider == "console":
        return provider, True
    if provider == "resend":
        return provider, bool(settings.resend_api_key and settings.email_from)
    return provider, False
