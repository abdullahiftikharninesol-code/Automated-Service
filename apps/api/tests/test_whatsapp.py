from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.conversation import Conversation
from app.models.conversation_message import ConversationMessage
from app.models.customer import Customer
from app.models.enums import (
    FollowUpStatus,
    FollowUpType,
    InboundChannel,
    LeadEventType,
    MessageDeliveryStatus,
    MessageDirection,
    MessageSenderType,
    WaitingOn,
)
from app.models.followup import FollowUp
from app.models.lead import Lead
from app.models.lead_event import LeadEvent
from app.models.organization import Organization
from app.services.followup_processor import FollowUpProcessor
from app.services.notifications import NotificationService
from app.services.whatsapp.provider import FakeWhatsAppProvider
from tests.conftest import register
from tests.test_reminders import RecordingNotificationProvider, to_utc


def sign_payload(payload_bytes: bytes, app_secret: str) -> str:
    digest = hmac.new(app_secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def build_meta_webhook(
    phone_number_id: str,
    from_phone: str,
    message_id: str,
    text: str | None = None,
    msg_type: str = "text",
    contact_name: str = "Sara Ahmed",
    timestamp: int | None = None,
    statuses: list[dict] | None = None,
) -> dict:
    ts = timestamp or int(datetime.now(UTC).timestamp())
    value: dict = {
        "messaging_product": "whatsapp",
        "metadata": {
            "display_phone_number": "+15550555555",
            "phone_number_id": phone_number_id,
        },
    }

    if statuses:
        value["statuses"] = statuses
    else:
        value["contacts"] = [{"profile": {"name": contact_name}, "wa_id": from_phone.lstrip("+")}]
        msg_obj: dict = {
            "from": from_phone.lstrip("+"),
            "id": message_id,
            "timestamp": str(ts),
            "type": msg_type,
        }
        if msg_type == "text" and text is not None:
            msg_obj["text"] = {"body": text}
        elif msg_type == "image":
            msg_obj["image"] = {"id": "media_999", "mime_type": "image/jpeg"}
        value["messages"] = [msg_obj]

    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA_TEST_123",
                "changes": [
                    {
                        "field": "messages",
                        "value": value,
                    }
                ],
            }
        ],
    }


def test_whatsapp_webhook_verification_handshake(client: TestClient) -> None:
    settings = get_settings()
    token = settings.meta_whatsapp_verify_token

    # 1. Valid handshake
    res = client.get(
        f"/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token={token}&hub.challenge=1158201444"
    )
    assert res.status_code == 200
    assert res.text == "1158201444"
    assert "text/plain" in res.headers["content-type"]

    # 2. Token mismatch
    res_bad = client.get(
        "/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=wrong-token&hub.challenge=1158201444"
    )
    assert res_bad.status_code == 403
    assert "mismatch" in res_bad.text

    # 3. Missing query params
    res_missing = client.get("/webhooks/whatsapp")
    assert res_missing.status_code == 400


def test_whatsapp_signature_validation(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    app_secret = "test-meta-app-secret-32-chars-long!"
    monkeypatch.setattr(get_settings(), "meta_app_secret", app_secret)

    payload = {"object": "whatsapp_business_account", "entry": []}
    raw_body = json.dumps(payload).encode("utf-8")

    # 1. Missing header -> 401
    res_missing = client.post("/webhooks/whatsapp", content=raw_body)
    assert res_missing.status_code == 401
    assert "Missing" in res_missing.text

    # 2. Malformed header (no sha256= prefix) -> 401
    res_malformed = client.post(
        "/webhooks/whatsapp",
        content=raw_body,
        headers={"X-Hub-Signature-256": "invalid_digest"},
    )
    assert res_malformed.status_code == 401
    assert "Malformed" in res_malformed.text

    # 3. Invalid signature hash -> 403
    res_invalid = client.post(
        "/webhooks/whatsapp",
        content=raw_body,
        headers={
            "X-Hub-Signature-256": (
                "sha256=0000000000000000000000000000000000000000000000000000000000000000"
            )
        },
    )
    assert res_invalid.status_code == 403
    assert "Invalid" in res_invalid.text

    # 4. Valid signature -> 200
    valid_sig = sign_payload(raw_body, app_secret)
    res_valid = client.post(
        "/webhooks/whatsapp",
        content=raw_body,
        headers={"X-Hub-Signature-256": valid_sig, "Content-Type": "application/json"},
    )
    assert res_valid.status_code == 200
    assert res_valid.json() == {"status": "ok"}


def test_whatsapp_inbound_end_to_end_flow(
    client: TestClient,
    account: dict[str, object],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = uuid.UUID(str(account["user"]["organization_id"]))
    org = db.get(Organization, org_id)
    assert org is not None

    phone_number_id = "phone_id_org_e2e"
    org.whatsapp_phone_number_id = phone_number_id
    org.whatsapp_enabled = True
    db.commit()

    fake_whatsapp = FakeWhatsAppProvider()
    monkeypatch.setattr(
        "app.services.whatsapp.inbound.get_whatsapp_provider", lambda: fake_whatsapp
    )
    monkeypatch.setattr("app.services.inbound.get_whatsapp_provider", lambda: fake_whatsapp)

    customer_phone = "+923001234567"
    message_text = (
        "Do you have the black shalwar kameez in medium? Can you deliver to Islamabad by Friday?"
    )
    wamid = "wamid.inbound_e2e_001"

    webhook_payload = build_meta_webhook(
        phone_number_id=phone_number_id,
        from_phone=customer_phone,
        message_id=wamid,
        text=message_text,
        contact_name="Sara Ahmed",
    )

    # 1. Send webhook
    res = client.post("/webhooks/whatsapp", json=webhook_payload)
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}

    # 2. Verify Customer created with normalized E.164 phone
    customer = db.scalar(
        select(Customer).where(
            Customer.organization_id == org_id,
            Customer.phone_normalized == customer_phone,
        )
    )
    assert customer is not None
    assert customer.name == "Sara Ahmed"

    # 3. Verify Conversation created on WHATSAPP channel
    conv = db.scalar(
        select(Conversation).where(
            Conversation.organization_id == org_id,
            Conversation.customer_id == customer.id,
            Conversation.channel == InboundChannel.WHATSAPP,
        )
    )
    assert conv is not None
    # Crucial: Conversation remains waiting on OWNER despite automated receipt
    assert conv.waiting_on == WaitingOn.OWNER

    # 4. Verify Inbound ConversationMessage saved with wamid
    inbound_msg = db.scalar(
        select(ConversationMessage).where(
            ConversationMessage.conversation_id == conv.id,
            ConversationMessage.direction == MessageDirection.INBOUND,
            ConversationMessage.external_message_id == wamid,
        )
    )
    assert inbound_msg is not None
    assert inbound_msg.body == message_text
    assert inbound_msg.sender_type == MessageSenderType.CUSTOMER
    assert inbound_msg.channel == InboundChannel.WHATSAPP

    # 5. Verify Lead created with AI extraction
    lead = db.scalar(
        select(Lead).where(
            Lead.organization_id == org_id,
            Lead.customer_id == customer.id,
        )
    )
    assert lead is not None
    assert lead.primary_conversation_id == conv.id
    assert lead.category_or_service is not None or lead.intent is not None

    # 6. Verify automated WhatsApp acknowledgement sent via provider
    assert len(fake_whatsapp.sent_messages) == 1
    sent_record = fake_whatsapp.sent_messages[0]
    assert sent_record["to_phone"] == customer_phone.lstrip("+")
    assert f"Thanks for contacting {org.name}" in sent_record["body"]

    # 7. Verify outbound SYSTEM ConversationMessage recorded
    outbound_ack = db.scalar(
        select(ConversationMessage).where(
            ConversationMessage.conversation_id == conv.id,
            ConversationMessage.direction == MessageDirection.OUTBOUND,
            ConversationMessage.sender_type == MessageSenderType.SYSTEM,
        )
    )
    assert outbound_ack is not None
    assert outbound_ack.delivery_status == MessageDeliveryStatus.SENT
    assert outbound_ack.external_message_id == sent_record["id"]
    assert outbound_ack.channel == InboundChannel.WHATSAPP

    # 8. Verify exactly ONE OWNER_RESPONSE_REMINDER scheduled
    reminders = list(
        db.scalars(
            select(FollowUp).where(
                FollowUp.organization_id == org_id,
                FollowUp.conversation_id == conv.id,
                FollowUp.type == FollowUpType.OWNER_RESPONSE_REMINDER,
                FollowUp.status == FollowUpStatus.PENDING,
            )
        )
    )
    assert len(reminders) == 1
    rem = reminders[0]
    assert to_utc(rem.due_at) > datetime.now(UTC) + timedelta(minutes=50)

    # 9. Verify LeadEvent audit trail
    events = list(
        db.scalars(
            select(LeadEvent).where(
                LeadEvent.lead_id == lead.id,
                LeadEvent.organization_id == org_id,
            )
        )
    )
    event_types = [e.event_type for e in events]
    assert LeadEventType.INBOUND_MESSAGE_RECEIVED in event_types
    assert LeadEventType.ACKNOWLEDGEMENT_GENERATED in event_types
    assert LeadEventType.ACKNOWLEDGEMENT_SENT in event_types
    assert LeadEventType.OWNER_REMINDER_SCHEDULED in event_types


def test_whatsapp_duplicate_webhook_is_idempotent(
    client: TestClient,
    account: dict[str, object],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = uuid.UUID(str(account["user"]["organization_id"]))
    org = db.get(Organization, org_id)
    assert org is not None
    org.whatsapp_phone_number_id = "phone_id_idempotent"
    org.whatsapp_enabled = True
    db.commit()

    fake_whatsapp = FakeWhatsAppProvider()
    monkeypatch.setattr(
        "app.services.whatsapp.inbound.get_whatsapp_provider", lambda: fake_whatsapp
    )
    monkeypatch.setattr("app.services.inbound.get_whatsapp_provider", lambda: fake_whatsapp)

    wamid = "wamid.idempotency_duplicate_test"
    payload = build_meta_webhook(
        phone_number_id="phone_id_idempotent",
        from_phone="+923005556677",
        message_id=wamid,
        text="Testing duplicate delivery",
    )

    # First delivery
    res1 = client.post("/webhooks/whatsapp", json=payload)
    assert res1.status_code == 200
    assert len(fake_whatsapp.sent_messages) == 1

    # Second delivery with identical wamid
    res2 = client.post("/webhooks/whatsapp", json=payload)
    assert res2.status_code == 200

    # No duplicate messages, leads, or acknowledgements
    assert len(fake_whatsapp.sent_messages) == 1

    messages = list(
        db.scalars(
            select(ConversationMessage).where(
                ConversationMessage.external_message_id == wamid,
            )
        )
    )
    assert len(messages) == 1

    reminders = list(
        db.scalars(
            select(FollowUp).where(
                FollowUp.organization_id == org_id,
                FollowUp.type == FollowUpType.OWNER_RESPONSE_REMINDER,
                FollowUp.status == FollowUpStatus.PENDING,
            )
        )
    )
    assert len(reminders) == 1


def test_customer_identity_reused_across_website_and_whatsapp(
    client: TestClient,
    account: dict[str, object],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = uuid.UUID(str(account["user"]["organization_id"]))
    org = db.get(Organization, org_id)
    assert org is not None
    org.whatsapp_phone_number_id = "phone_id_identity_test"
    org.whatsapp_enabled = True
    db.commit()

    phone_raw = "+15125550188"

    # 1. Customer first submits website form
    form_res = client.post(
        f"/public/inbound/form/{org_id}",
        json={
            "name": "Alex Taylor",
            "email": "alex@example.com",
            "phone": phone_raw,
            "message": "Inquiry on website form",
        },
    )
    assert form_res.status_code == 201

    customer_initial = db.scalar(
        select(Customer).where(
            Customer.organization_id == org_id,
            Customer.phone_normalized == phone_raw,
        )
    )
    assert customer_initial is not None
    initial_customer_id = customer_initial.id

    # 2. Same customer later messages via WhatsApp with same phone
    payload = build_meta_webhook(
        phone_number_id="phone_id_identity_test",
        from_phone=phone_raw,
        message_id="wamid.identity_test_001",
        text="Following up on my web form via WhatsApp",
    )
    res_wa = client.post("/webhooks/whatsapp", json=payload)
    assert res_wa.status_code == 200

    # Verify same Customer record is reused
    matching_customers = list(
        db.scalars(
            select(Customer).where(
                Customer.organization_id == org_id,
                Customer.phone_normalized == phone_raw,
            )
        )
    )
    assert len(matching_customers) == 1
    assert matching_customers[0].id == initial_customer_id


def test_whatsapp_acknowledgement_failure_resilience(
    client: TestClient,
    account: dict[str, object],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = uuid.UUID(str(account["user"]["organization_id"]))
    org = db.get(Organization, org_id)
    assert org is not None
    org.whatsapp_phone_number_id = "phone_id_fail_test"
    org.whatsapp_enabled = True
    db.commit()

    failing_whatsapp = FakeWhatsAppProvider(
        should_fail=True, fail_reason="Simulated WhatsApp timeout"
    )
    monkeypatch.setattr(
        "app.services.whatsapp.inbound.get_whatsapp_provider", lambda: failing_whatsapp
    )
    monkeypatch.setattr("app.services.inbound.get_whatsapp_provider", lambda: failing_whatsapp)

    payload = build_meta_webhook(
        phone_number_id="phone_id_fail_test",
        from_phone="+923009998877",
        message_id="wamid.fail_test_001",
        text="Inquiry where acknowledgement fails",
    )

    # Webhook still succeeds and returns 200 to Meta
    res = client.post("/webhooks/whatsapp", json=payload)
    assert res.status_code == 200

    # Customer and lead remain persisted
    customer = db.scalar(
        select(Customer).where(
            Customer.organization_id == org_id,
            Customer.phone_normalized == "+923009998877",
        )
    )
    assert customer is not None

    conv = db.scalar(
        select(Conversation).where(
            Conversation.organization_id == org_id,
            Conversation.customer_id == customer.id,
        )
    )
    assert conv is not None

    # Outbound acknowledgment message exists with FAILED status
    failed_msg = db.scalar(
        select(ConversationMessage).where(
            ConversationMessage.conversation_id == conv.id,
            ConversationMessage.direction == MessageDirection.OUTBOUND,
            ConversationMessage.sender_type == MessageSenderType.SYSTEM,
        )
    )
    assert failed_msg is not None
    assert failed_msg.delivery_status == MessageDeliveryStatus.FAILED
    assert "Simulated WhatsApp timeout" in str(failed_msg.message_metadata)

    # Owner reminder remains active!
    rem = db.scalar(
        select(FollowUp).where(
            FollowUp.organization_id == org_id,
            FollowUp.conversation_id == conv.id,
            FollowUp.type == FollowUpType.OWNER_RESPONSE_REMINDER,
            FollowUp.status == FollowUpStatus.PENDING,
        )
    )
    assert rem is not None


def test_whatsapp_delivery_status_callbacks_and_progression(
    client: TestClient,
    account: dict[str, object],
    db: Session,
) -> None:
    org_id = uuid.UUID(str(account["user"]["organization_id"]))
    org = db.get(Organization, org_id)
    assert org is not None
    phone_id = "phone_id_status_test"
    org.whatsapp_phone_number_id = phone_id
    org.whatsapp_enabled = True
    db.commit()

    # Pre-create Conversation & outbound message with a known wamid
    conv = Conversation(
        organization_id=org_id,
        channel=InboundChannel.WHATSAPP,
        waiting_on=WaitingOn.CUSTOMER,
    )
    db.add(conv)
    db.flush()

    wamid = "wamid.status_lifecycle_test"
    now = datetime.now(UTC)
    outbound_msg = ConversationMessage(
        organization_id=org_id,
        conversation_id=conv.id,
        direction=MessageDirection.OUTBOUND,
        channel=InboundChannel.WHATSAPP,
        sender_type=MessageSenderType.OWNER,
        body="Hello from business",
        external_message_id=wamid,
        delivery_status=MessageDeliveryStatus.SENT,
        sent_at=now,
        created_at=now,
    )
    db.add(outbound_msg)
    db.commit()

    # 1. 'delivered' webhook callback
    payload_delivered = build_meta_webhook(
        phone_number_id=phone_id,
        from_phone="12345",
        message_id="dummy",
        statuses=[{"id": wamid, "status": "delivered", "timestamp": str(int(now.timestamp()))}],
    )
    res_del = client.post("/webhooks/whatsapp", json=payload_delivered)
    assert res_del.status_code == 200

    db.refresh(outbound_msg)
    assert outbound_msg.delivery_status == MessageDeliveryStatus.DELIVERED

    # 2. 'read' webhook callback
    payload_read = build_meta_webhook(
        phone_number_id=phone_id,
        from_phone="12345",
        message_id="dummy",
        statuses=[{"id": wamid, "status": "read", "timestamp": str(int(now.timestamp()) + 10)}],
    )
    res_read = client.post("/webhooks/whatsapp", json=payload_read)
    assert res_read.status_code == 200

    db.refresh(outbound_msg)
    assert outbound_msg.delivery_status == MessageDeliveryStatus.READ

    # 3. Delayed 'delivered' callback must NOT regress status backwards from READ
    res_regress = client.post("/webhooks/whatsapp", json=payload_delivered)
    assert res_regress.status_code == 200

    db.refresh(outbound_msg)
    assert outbound_msg.delivery_status == MessageDeliveryStatus.READ


def test_whatsapp_status_failed_callback_records_error(
    client: TestClient,
    account: dict[str, object],
    db: Session,
) -> None:
    org_id = uuid.UUID(str(account["user"]["organization_id"]))
    org = db.get(Organization, org_id)
    assert org is not None
    phone_id = "phone_id_status_fail"
    org.whatsapp_phone_number_id = phone_id
    org.whatsapp_enabled = True
    db.commit()

    conv = Conversation(
        organization_id=org_id,
        channel=InboundChannel.WHATSAPP,
        waiting_on=WaitingOn.CUSTOMER,
    )
    db.add(conv)
    db.flush()

    wamid = "wamid.status_fail_record_test"
    msg = ConversationMessage(
        organization_id=org_id,
        conversation_id=conv.id,
        direction=MessageDirection.OUTBOUND,
        channel=InboundChannel.WHATSAPP,
        sender_type=MessageSenderType.OWNER,
        body="Attempting outbound message",
        external_message_id=wamid,
        delivery_status=MessageDeliveryStatus.SENT,
        sent_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    db.add(msg)
    db.commit()

    # Post failure status update with error code 131047 (service window expired)
    payload_failed = build_meta_webhook(
        phone_number_id=phone_id,
        from_phone="12345",
        message_id="dummy",
        statuses=[
            {
                "id": wamid,
                "status": "failed",
                "timestamp": str(int(datetime.now(UTC).timestamp())),
                "errors": [
                    {
                        "code": 131047,
                        "title": "Re-engagement message",
                        "message": "Message failed because more than 24 hours have passed",
                    }
                ],
            }
        ],
    )
    res = client.post("/webhooks/whatsapp", json=payload_failed)
    assert res.status_code == 200

    db.refresh(msg)
    assert msg.delivery_status == MessageDeliveryStatus.FAILED
    assert "delivery_error" in msg.message_metadata
    assert msg.message_metadata["delivery_error"]["errors"][0]["code"] == 131047


def test_unsupported_media_message_type_handled_safely(
    client: TestClient,
    account: dict[str, object],
    db: Session,
) -> None:
    org_id = uuid.UUID(str(account["user"]["organization_id"]))
    org = db.get(Organization, org_id)
    assert org is not None
    phone_id = "phone_id_media_test"
    org.whatsapp_phone_number_id = phone_id
    org.whatsapp_enabled = True
    db.commit()

    # Image payload
    payload = build_meta_webhook(
        phone_number_id=phone_id,
        from_phone="+923001122334",
        message_id="wamid.image_test_001",
        msg_type="image",
    )

    # Must return HTTP 200 without crashing
    res = client.post("/webhooks/whatsapp", json=payload)
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_owner_reply_via_api_and_reminder_cancellation(
    client: TestClient,
    account: dict[str, object],
    auth_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = uuid.UUID(str(account["user"]["organization_id"]))
    org = db.get(Organization, org_id)
    assert org is not None
    phone_id = "phone_id_owner_reply"
    org.whatsapp_phone_number_id = phone_id
    org.whatsapp_enabled = True
    db.commit()

    fake_whatsapp = FakeWhatsAppProvider()
    monkeypatch.setattr(
        "app.services.outbound_messaging.get_whatsapp_provider", lambda: fake_whatsapp
    )

    # 1. Customer initiates WhatsApp conversation
    customer = Customer(
        organization_id=org_id,
        name="Usman",
        phone="+923007788990",
        phone_normalized="+923007788990",
    )
    db.add(customer)
    db.flush()

    conv = Conversation(
        organization_id=org_id,
        customer_id=customer.id,
        channel=InboundChannel.WHATSAPP,
        waiting_on=WaitingOn.OWNER,
    )
    db.add(conv)
    db.flush()

    lead = Lead(
        organization_id=org_id,
        customer_id=customer.id,
        primary_conversation_id=conv.id,
        customer_name="Usman",
        customer_phone="+923007788990",
        customer_phone_normalized="+923007788990",
        message="Need AC checkup",
        source="WHATSAPP",
    )
    db.add(lead)
    db.flush()
    conv.lead_id = lead.id

    # Active pending owner reminder
    rem = FollowUp(
        organization_id=org_id,
        lead_id=lead.id,
        conversation_id=conv.id,
        due_at=datetime.now(UTC) + timedelta(minutes=45),
        type=FollowUpType.OWNER_RESPONSE_REMINDER,
        status=FollowUpStatus.PENDING,
    )
    db.add(rem)
    db.commit()

    # 2. Owner replies via POST /conversations/{conversation_id}/reply
    reply_body = "Hello Usman! We have an HVAC technician available tomorrow at 10 AM."
    reply_res = client.post(
        f"/conversations/{conv.id}/reply",
        headers=auth_headers,
        json={"body": reply_body},
    )
    assert reply_res.status_code == 201
    reply_data = reply_res.json()
    assert reply_data["sender_type"] == "OWNER"
    assert reply_data["delivery_status"] == "SENT"
    assert reply_data["external_message_id"] is not None

    # Verify provider was called
    assert len(fake_whatsapp.sent_messages) == 1
    assert fake_whatsapp.sent_messages[0]["body"] == reply_body

    # Verify conversation waiting_on changed to CUSTOMER
    db.refresh(conv)
    assert conv.waiting_on == WaitingOn.CUSTOMER

    # Verify pending owner response reminder is CANCELLED
    db.refresh(rem)
    assert rem.status == FollowUpStatus.CANCELLED
    assert rem.failure_reason == "Owner replied"

    # Sweep generates no notification
    provider = RecordingNotificationProvider()
    processor = FollowUpProcessor(db, notifications=NotificationService(provider=provider))
    processor.process_due(now=datetime.now(UTC) + timedelta(hours=2))
    assert len(provider.sent_notifications) == 0


def test_multi_tenancy_phone_number_routing_and_tenant_isolation(
    client: TestClient,
    account: dict[str, object],
    auth_headers: dict[str, str],
    db: Session,
) -> None:
    # Org A (from account fixture)
    org_a_id = uuid.UUID(str(account["user"]["organization_id"]))
    org_a = db.get(Organization, org_a_id)
    assert org_a is not None
    org_a.whatsapp_phone_number_id = "phone_org_aaa"
    org_a.whatsapp_enabled = True

    # Register Org B
    account_b = register(client, suffix="multi_tenancy_b")
    org_b_id = uuid.UUID(str(account_b["user"]["organization_id"]))
    auth_headers_b = {"Authorization": f"Bearer {account_b['access_token']}"}
    org_b = db.get(Organization, org_b_id)
    assert org_b is not None
    org_b.whatsapp_phone_number_id = "phone_org_bbb"
    org_b.whatsapp_enabled = True
    db.commit()

    # Send webhook to Org A's phone number
    payload_a = build_meta_webhook(
        phone_number_id="phone_org_aaa",
        from_phone="+923000000001",
        message_id="wamid.tenant_a_msg",
        text="Inquiry strictly for Org A",
    )
    res_a = client.post("/webhooks/whatsapp", json=payload_a)
    assert res_a.status_code == 200

    # Verify data created in Org A
    lead_a = db.scalar(
        select(Lead).where(
            Lead.organization_id == org_a_id,
            Lead.customer_phone_normalized == "+923000000001",
        )
    )
    assert lead_a is not None
    conv_a_id = lead_a.primary_conversation_id

    # Verify zero data leaked into Org B
    lead_b = db.scalar(
        select(Lead).where(
            Lead.organization_id == org_b_id,
            Lead.customer_phone_normalized == "+923000000001",
        )
    )
    assert lead_b is None

    # Org B user cannot view or reply to Org A's conversation
    cross_reply = client.post(
        f"/conversations/{conv_a_id}/reply",
        headers=auth_headers_b,
        json={"body": "Malicious attempt from Org B"},
    )
    assert cross_reply.status_code == 404

    cross_get = client.get(
        f"/conversations/{conv_a_id}",
        headers=auth_headers_b,
    )
    assert cross_get.status_code == 404
