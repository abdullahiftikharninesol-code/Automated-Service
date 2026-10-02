import logging
from json import dumps
from typing import Protocol
from urllib.request import Request, urlopen

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

    def __init__(self, api_key: str | None, email_from: str | None):
        self.api_key = api_key
        self.email_from = email_from

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.email_from)

    def send(self, *, to: str, subject: str, body: str) -> None:
        if not self.configured:
            raise RuntimeError("Resend requires RESEND_API_KEY and EMAIL_FROM")
        request = Request(
            self.endpoint,
            data=dumps(
                {
                    "from": self.email_from,
                    "to": [to],
                    "subject": subject,
                    "text": body,
                }
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=15) as response:  # noqa: S310
            if response.status >= 300:
                raise RuntimeError(f"Resend returned HTTP {response.status}")


def get_email_provider() -> EmailProvider:
    settings = get_settings()
    provider = settings.email_provider.lower()
    if provider == "console":
        return ConsoleEmailProvider()
    if provider == "resend":
        return ResendEmailProvider(settings.resend_api_key, settings.email_from)
    raise RuntimeError(f"Unsupported EMAIL_PROVIDER: {provider}")


def email_provider_status() -> tuple[str, bool]:
    settings = get_settings()
    provider = settings.email_provider.lower()
    if provider == "console":
        return provider, True
    if provider == "resend":
        return provider, bool(settings.resend_api_key and settings.email_from)
    return provider, False
