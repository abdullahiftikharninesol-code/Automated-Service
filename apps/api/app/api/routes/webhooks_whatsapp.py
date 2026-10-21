import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import PlainTextResponse

from app.api.dependencies import DbSession
from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.services.whatsapp.inbound import WhatsAppInboundAdapter

logger = logging.getLogger("missed_lead_rescue.webhooks.whatsapp")

router = APIRouter(prefix="/webhooks/whatsapp", tags=["WhatsApp Webhook"])


def verify_meta_signature(
    raw_body: bytes, signature_header: str | None, app_secret: str | None
) -> None:
    """Validate incoming X-Hub-Signature-256 header from Meta using constant-time comparison."""
    if not app_secret:
        # If no secret configured (e.g. testing or local dev without secret), skip verification
        return

    if not signature_header:
        logger.warning("[WHATSAPP_WEBHOOK] Missing X-Hub-Signature-256 header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Hub-Signature-256 header",
        )

    if not signature_header.startswith("sha256="):
        logger.warning("[WHATSAPP_WEBHOOK] Malformed X-Hub-Signature-256 header format")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed signature header; expected sha256=<hex_hash>",
        )

    provided_sig = signature_header.split("sha256=", 1)[1].strip()
    expected_sig = hmac.new(
        app_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(provided_sig, expected_sig):
        logger.warning("[WHATSAPP_WEBHOOK] Invalid X-Hub-Signature-256 signature mismatch")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook signature",
        )


@router.get("", response_class=PlainTextResponse)
def verify_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> Response:
    """Meta Webhook Verification Handshake.

    Responds to Meta's GET challenge when hub.mode='subscribe' and verify token matches.
    Returns plain text challenge.
    """
    settings = get_settings()
    expected_token = settings.meta_whatsapp_verify_token

    if not hub_mode or not hub_verify_token or not hub_challenge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required hub query parameters",
        )

    if (
        hub_mode == "subscribe"
        and expected_token
        and hmac.compare_digest(hub_verify_token, expected_token)
    ):
        logger.info("[WHATSAPP_WEBHOOK] Webhook verification handshake successful.")
        return PlainTextResponse(content=hub_challenge, status_code=status.HTTP_200_OK)

    logger.warning("[WHATSAPP_WEBHOOK] Webhook verification handshake failed: token mismatch.")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Verification token mismatch",
    )


@router.post("")
@limiter.limit(lambda: get_settings().meta_webhook_rate_limit)
async def receive_webhook(request: Request, db: DbSession) -> dict[str, str]:
    """Meta WhatsApp Cloud API Inbound Webhook.

    1. Validates X-Hub-Signature-256
    2. Parses incoming JSON payload
    3. Delegates normalization to WhatsAppInboundAdapter
    4. Quickly returns HTTP 200 OK to prevent Meta delivery retries
    """
    raw_body = await request.body()
    settings = get_settings()

    signature_header = request.headers.get("X-Hub-Signature-256")
    verify_meta_signature(raw_body, signature_header, settings.meta_app_secret)

    try:
        decoded = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else raw_body
        payload_data = json.loads(decoded)
    except Exception as exc:
        logger.warning("[WHATSAPP_WEBHOOK] Unparseable JSON payload: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid webhook JSON payload: {exc}",
        ) from exc

    logger.info("[WHATSAPP_WEBHOOK] WhatsApp webhook received")
    adapter = WhatsAppInboundAdapter(db)
    result = adapter.process_webhook_payload(payload_data)
    logger.debug("[WHATSAPP_WEBHOOK] Batch processed: %s", result)

    return {"status": "ok"}
