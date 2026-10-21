from __future__ import annotations

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
    MessageDeliveryStatus,
    MessageSenderType,
    QualificationStatus,
    WaitingOn,
)
from app.models.followup import FollowUp
from app.models.lead import Lead
from app.models.organization import Organization
from app.services.whatsapp.provider import FakeWhatsAppProvider
from tests.conftest import register
from tests.test_whatsapp import build_meta_webhook, sign_payload


def setup_generic_demo_org(
    client: TestClient, db: Session, phone_id: str, app_secret: str
) -> dict:
    tenant = register(client, f"demo-biz-{uuid.uuid4().hex[:6]}")
    headers = {"Authorization": f"Bearer {tenant['access_token']}"}
    org_id = uuid.UUID(tenant["user"]["organization_id"])

    # Configure WhatsApp on org
    org = db.get(Organization, org_id)
    assert org is not None
    org.name = "Demo Business"
    org.whatsapp_enabled = True
    org.whatsapp_phone_number_id = phone_id
    org.whatsapp_business_account_id = "waba_demo_123"
    org.whatsapp_display_phone_number = "+15551234567"
    org.settings = {"owner_reminder_delay_minutes": 2}
    db.commit()

    # Configure generic qualification fields: customer_need, preferred_date, location
    fields = [
        {
            "key": "customer_need",
            "label": "Customer Need",
            "required": True,
            "sort_order": 0,
            "question_text": "What do you need help with?",
        },
        {
            "key": "preferred_date",
            "label": "Preferred Date",
            "required": True,
            "sort_order": 1,
            "question_text": "What date would you prefer?",
        },
        {
            "key": "location",
            "label": "Location",
            "required": True,
            "sort_order": 2,
            "question_text": "What city or location are you in?",
        },
    ]
    for f in fields:
        res = client.post(
            "/qualification-fields",
            headers=headers,
            json={
                "key": f["key"],
                "label": f["label"],
                "field_type": "TEXT",
                "required": f["required"],
                "sort_order": f["sort_order"],
                "question_text": f["question_text"],
            },
        )
        assert res.status_code == 201

    return {
        "org_id": org_id,
        "headers": headers,
        "phone_id": phone_id,
        "app_secret": app_secret,
    }


def test_scenario_1_complete_first_message(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenario 1: Complete First Message.

    Customer sends all required details at once.
    Qualification becomes COMPLETE immediately.
    Confirmation sent, waiting_on=OWNER, reminder scheduled.
    """
    phone_id = "phone_demo_scen1"
    app_secret = "meta-secret-32-chars-scen1-demo!!"
    monkeypatch.setattr(get_settings(), "meta_app_secret", app_secret)

    fake_wa = FakeWhatsAppProvider()
    monkeypatch.setattr(
        "app.services.whatsapp.inbound.get_whatsapp_provider", lambda: fake_wa
    )
    monkeypatch.setattr(
        "app.services.inbound.get_whatsapp_provider", lambda: fake_wa
    )

    demo = setup_generic_demo_org(client, db, phone_id, app_secret)
    org_id = demo["org_id"]

    customer_phone = "+15125550301"
    payload = build_meta_webhook(
        phone_number_id=phone_id,
        from_phone=customer_phone,
        message_id="wamid_scen1_msg1",
        text="Hi, I need help with a consultation this Friday in Islamabad.",
        contact_name="Tariq Mansoor",
    )
    raw = json.dumps(payload).encode("utf-8")
    sig = sign_payload(raw, app_secret)

    res = client.post(
        "/webhooks/whatsapp",
        content=raw,
        headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
    )
    assert res.status_code == 200

    # 1. Customer created
    cust = db.scalar(
        select(Customer).where(
            Customer.organization_id == org_id,
            Customer.phone_normalized == customer_phone,
        )
    )
    assert cust is not None
    assert cust.name == "Tariq Mansoor"

    # 2. Conversation created with channel WHATSAPP
    conv = db.scalar(
        select(Conversation).where(
            Conversation.organization_id == org_id,
            Conversation.customer_id == cust.id,
            Conversation.channel == InboundChannel.WHATSAPP,
        )
    )
    assert conv is not None

    # 3. ConversationMessage inbound exists
    inbound_msg = db.scalar(
        select(ConversationMessage).where(
            ConversationMessage.conversation_id == conv.id,
            ConversationMessage.external_message_id == "wamid_scen1_msg1",
        )
    )
    assert inbound_msg is not None
    assert inbound_msg.sender_type == MessageSenderType.CUSTOMER

    # 4. Lead exists with COMPLETE qualification
    lead = db.scalar(
        select(Lead).where(Lead.organization_id == org_id, Lead.customer_id == cust.id)
    )
    assert lead is not None
    assert lead.qualification_status == QualificationStatus.COMPLETE
    assert lead.qualifications.get("customer_need") is not None
    assert lead.qualifications.get("preferred_date") is not None
    assert lead.qualifications.get("location") is not None

    # 5. Confirmation sent via WhatsApp
    assert len(fake_wa.sent_messages) == 1
    confirmation = fake_wa.sent_messages[0]
    confirm_body = confirmation["body"].lower()
    assert "received your message" in confirm_body or "got the details" in confirm_body

    # 6. Conversation state is OWNER
    db.refresh(conv)
    assert conv.waiting_on == WaitingOn.OWNER

    # 7. Owner response reminder scheduled
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


def test_scenario_2_multi_turn_and_scenario_3_owner_reply(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenario 2 & 3: Multi-turn qualification flow followed by owner reply.

    Turn 1: Incomplete message -> Clarification question sent, waiting_on=CUSTOMER.
    Turn 2: Partial details -> Next clarification question sent.
    Turn 3: Complete details -> Confirmation sent, waiting_on=OWNER, reminder scheduled.
    Scenario 3: Owner replies via API -> Sent to WhatsApp, waiting_on=CUSTOMER, reminder cancelled.
    """
    phone_id = "phone_demo_scen2"
    app_secret = "meta-secret-32-chars-scen2-demo!!"
    monkeypatch.setattr(get_settings(), "meta_app_secret", app_secret)

    fake_wa = FakeWhatsAppProvider()
    monkeypatch.setattr(
        "app.services.whatsapp.inbound.get_whatsapp_provider", lambda: fake_wa
    )
    monkeypatch.setattr(
        "app.services.inbound.get_whatsapp_provider", lambda: fake_wa
    )
    monkeypatch.setattr(
        "app.services.outbound_messaging.get_whatsapp_provider", lambda: fake_wa
    )

    demo = setup_generic_demo_org(client, db, phone_id, app_secret)
    org_id = demo["org_id"]
    headers = demo["headers"]

    customer_phone = "+15125550302"

    # --- TURN 1 ---
    payload_1 = build_meta_webhook(
        phone_number_id=phone_id,
        from_phone=customer_phone,
        message_id="wamid_scen2_turn1",
        text="Hi, I need help.",
        contact_name="Sara Ahmed",
    )
    raw_1 = json.dumps(payload_1).encode("utf-8")
    sig_1 = sign_payload(raw_1, app_secret)
    res_1 = client.post(
        "/webhooks/whatsapp",
        content=raw_1,
        headers={"X-Hub-Signature-256": sig_1, "Content-Type": "application/json"},
    )
    assert res_1.status_code == 200

    lead = db.scalar(select(Lead).where(Lead.organization_id == org_id))
    assert lead is not None
    assert lead.qualification_status == QualificationStatus.IN_PROGRESS

    conv = db.get(Conversation, lead.primary_conversation_id)
    assert conv is not None
    # Waiting on customer for clarification!
    assert conv.waiting_on == WaitingOn.CUSTOMER

    # Clarification question was sent
    assert len(fake_wa.sent_messages) == 1
    clarif_body = fake_wa.sent_messages[0]["body"]
    assert "?" in clarif_body

    # No owner reminder while waiting on customer
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
    assert len(reminders) == 0

    # --- TURN 2 (Partial answer: provides date and location, customer_need still missing) ---
    payload_2 = build_meta_webhook(
        phone_number_id=phone_id,
        from_phone=customer_phone,
        message_id="wamid_scen2_turn2",
        text="Friday in Islamabad.",
        contact_name="Sara Ahmed",
    )
    raw_2 = json.dumps(payload_2).encode("utf-8")
    sig_2 = sign_payload(raw_2, app_secret)
    res_2 = client.post(
        "/webhooks/whatsapp",
        content=raw_2,
        headers={"X-Hub-Signature-256": sig_2, "Content-Type": "application/json"},
    )
    assert res_2.status_code == 200

    db.refresh(lead)
    db.refresh(conv)

    # Lead should merge date and location, but customer_need is still required
    assert lead.qualifications.get("preferred_date") is not None
    assert lead.qualifications.get("location") is not None
    assert lead.qualification_status == QualificationStatus.IN_PROGRESS
    assert conv.waiting_on == WaitingOn.CUSTOMER

    # Next clarification question asked for remaining customer_need
    assert len(fake_wa.sent_messages) == 2
    next_question = fake_wa.sent_messages[1]["body"]
    assert "help" in next_question.lower() or "need" in next_question.lower()

    # --- TURN 3 (Customer answers customer_need: "A consultation service") ---
    payload_3 = build_meta_webhook(
        phone_number_id=phone_id,
        from_phone=customer_phone,
        message_id="wamid_scen2_turn3",
        text="I need a consultation service.",
        contact_name="Sara Ahmed",
    )
    raw_3 = json.dumps(payload_3).encode("utf-8")
    sig_3 = sign_payload(raw_3, app_secret)
    res_3 = client.post(
        "/webhooks/whatsapp",
        content=raw_3,
        headers={"X-Hub-Signature-256": sig_3, "Content-Type": "application/json"},
    )
    assert res_3.status_code == 200

    db.refresh(lead)
    db.refresh(conv)

    # No duplicate leads created across turns
    leads_count = len(list(db.scalars(select(Lead).where(Lead.organization_id == org_id))))
    assert leads_count == 1
    assert lead.qualification_status == QualificationStatus.COMPLETE
    assert lead.qualifications.get("customer_need") is not None
    assert conv.waiting_on == WaitingOn.OWNER

    # Confirmation message sent (message 3)
    assert len(fake_wa.sent_messages) == 3
    confirm_msg = fake_wa.sent_messages[2]["body"]
    assert "got the details" in confirm_msg.lower() or "received" in confirm_msg.lower()

    # Exactly 1 pending owner reminder scheduled
    reminders_turn3 = list(
        db.scalars(
            select(FollowUp).where(
                FollowUp.organization_id == org_id,
                FollowUp.conversation_id == conv.id,
                FollowUp.type == FollowUpType.OWNER_RESPONSE_REMINDER,
                FollowUp.status == FollowUpStatus.PENDING,
            )
        )
    )
    assert len(reminders_turn3) == 1

    # --- SCENARIO 3: OWNER REPLY ---
    res_reply = client.post(
        f"/conversations/{conv.id}/reply",
        headers=headers,
        json={"body": "Hello Sara! We can gladly assist you this Friday in Islamabad."},
    )
    assert res_reply.status_code == 201
    reply_data = res_reply.json()
    assert reply_data["sender_type"] == "OWNER"
    assert reply_data["delivery_status"] == "SENT"
    assert reply_data["external_message_id"] is not None

    db.refresh(conv)
    assert conv.waiting_on == WaitingOn.CUSTOMER

    # Pending owner reminder must be CANCELLED!
    cancelled_reminders = list(
        db.scalars(
            select(FollowUp).where(
                FollowUp.organization_id == org_id,
                FollowUp.conversation_id == conv.id,
                FollowUp.type == FollowUpType.OWNER_RESPONSE_REMINDER,
                FollowUp.status == FollowUpStatus.CANCELLED,
            )
        )
    )
    assert len(cancelled_reminders) == 1


def test_scenario_4_delivery_status_monotonic(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenario 4: Delivery status callbacks SENT -> DELIVERED -> READ."""
    phone_id = "phone_demo_scen4"
    app_secret = "meta-secret-32-chars-scen4-demo!!"
    monkeypatch.setattr(get_settings(), "meta_app_secret", app_secret)

    demo = setup_generic_demo_org(client, db, phone_id, app_secret)
    org_id = demo["org_id"]

    # Pre-create outbound message in SENT state
    wamid = "wamid.HBgLMTIzNDU2Nzg5MBUCABEYEk"
    msg = ConversationMessage(
        organization_id=org_id,
        conversation_id=uuid.uuid4(),
        direction="OUTBOUND",
        channel=InboundChannel.WHATSAPP,
        sender_type=MessageSenderType.OWNER,
        body="Status test message",
        delivery_status=MessageDeliveryStatus.SENT,
        external_message_id=wamid,
        sent_at=datetime.now(UTC),
    )
    # Ensure conversation exists
    conv = Conversation(
        id=msg.conversation_id,
        organization_id=org_id,
        channel=InboundChannel.WHATSAPP,
        status="OPEN",
        waiting_on=WaitingOn.CUSTOMER,
    )
    db.add(conv)
    db.add(msg)
    db.commit()

    # 1. DELIVERED callback
    payload_del = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba_demo_123",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": phone_id},
                            "statuses": [
                                {
                                    "id": wamid,
                                    "status": "delivered",
                                    "timestamp": "1710000010",
                                    "recipient_id": "15125550304",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    raw_del = json.dumps(payload_del).encode("utf-8")
    sig_del = sign_payload(raw_del, app_secret)
    res_del = client.post(
        "/webhooks/whatsapp",
        content=raw_del,
        headers={"X-Hub-Signature-256": sig_del, "Content-Type": "application/json"},
    )
    assert res_del.status_code == 200

    db.refresh(msg)
    assert msg.delivery_status == MessageDeliveryStatus.DELIVERED

    # 2. READ callback
    payload_read = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba_demo_123",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": phone_id},
                            "statuses": [
                                {
                                    "id": wamid,
                                    "status": "read",
                                    "timestamp": "1710000020",
                                    "recipient_id": "15125550304",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    raw_read = json.dumps(payload_read).encode("utf-8")
    sig_read = sign_payload(raw_read, app_secret)
    res_read = client.post(
        "/webhooks/whatsapp",
        content=raw_read,
        headers={"X-Hub-Signature-256": sig_read, "Content-Type": "application/json"},
    )
    assert res_read.status_code == 200

    db.refresh(msg)
    assert msg.delivery_status == MessageDeliveryStatus.READ

    # 3. Monotonic check: late DELIVERED callback must NOT regress status from READ
    res_regress = client.post(
        "/webhooks/whatsapp",
        content=raw_del,
        headers={"X-Hub-Signature-256": sig_del, "Content-Type": "application/json"},
    )
    assert res_regress.status_code == 200
    db.refresh(msg)
    assert msg.delivery_status == MessageDeliveryStatus.READ


def test_scenario_5_duplicate_webhook_idempotency(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenario 5: Duplicate webhook replay must produce zero duplicate side effects."""
    phone_id = "phone_demo_scen5"
    app_secret = "meta-secret-32-chars-scen5-demo!!"
    monkeypatch.setattr(get_settings(), "meta_app_secret", app_secret)

    fake_wa = FakeWhatsAppProvider()
    monkeypatch.setattr(
        "app.services.whatsapp.inbound.get_whatsapp_provider", lambda: fake_wa
    )
    monkeypatch.setattr(
        "app.services.inbound.get_whatsapp_provider", lambda: fake_wa
    )

    demo = setup_generic_demo_org(client, db, phone_id, app_secret)
    org_id = demo["org_id"]

    payload = build_meta_webhook(
        phone_number_id=phone_id,
        from_phone="+15125550305",
        message_id="wamid_scen5_duplicate_test",
        text="Hi, I need help with a consultation this Friday in Islamabad.",
        contact_name="Duplicate Tester",
    )
    raw = json.dumps(payload).encode("utf-8")
    sig = sign_payload(raw, app_secret)

    # First send
    res1 = client.post(
        "/webhooks/whatsapp",
        content=raw,
        headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
    )
    assert res1.status_code == 200

    leads1 = list(db.scalars(select(Lead).where(Lead.organization_id == org_id)))
    msgs1 = list(
        db.scalars(
            select(ConversationMessage).where(ConversationMessage.organization_id == org_id)
        )
    )
    reminders1 = list(db.scalars(select(FollowUp).where(FollowUp.organization_id == org_id)))
    sent1 = len(fake_wa.sent_messages)

    assert len(leads1) == 1
    assert sent1 == 1

    # Second send (Replay of exact same webhook)
    res2 = client.post(
        "/webhooks/whatsapp",
        content=raw,
        headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
    )
    assert res2.status_code == 200

    leads2 = list(db.scalars(select(Lead).where(Lead.organization_id == org_id)))
    msgs2 = list(
        db.scalars(
            select(ConversationMessage).where(ConversationMessage.organization_id == org_id)
        )
    )
    reminders2 = list(db.scalars(select(FollowUp).where(FollowUp.organization_id == org_id)))
    sent2 = len(fake_wa.sent_messages)

    assert len(leads2) == len(leads1)
    assert len(msgs2) == len(msgs1)
    assert len(reminders2) == len(reminders1)
    assert sent2 == sent1


def test_scenario_14_reminder_sweep_short_delay(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenario 14: Automated reminder sweep fires when owner does not respond."""
    phone_id = "phone_demo_scen14"
    app_secret = "meta-secret-32-chars-scen14-demo!"
    monkeypatch.setattr(get_settings(), "meta_app_secret", app_secret)

    fake_wa = FakeWhatsAppProvider()
    monkeypatch.setattr(
        "app.services.whatsapp.inbound.get_whatsapp_provider", lambda: fake_wa
    )
    monkeypatch.setattr(
        "app.services.inbound.get_whatsapp_provider", lambda: fake_wa
    )

    demo = setup_generic_demo_org(client, db, phone_id, app_secret)
    org_id = demo["org_id"]

    # Inbound message that completes qualification
    payload = build_meta_webhook(
        phone_number_id=phone_id,
        from_phone="+15125550314",
        message_id="wamid_scen14_msg",
        text="Hi, I need help with a consultation this Friday in Islamabad.",
        contact_name="Reminder Test",
    )
    raw = json.dumps(payload).encode("utf-8")
    sig = sign_payload(raw, app_secret)
    client.post(
        "/webhooks/whatsapp",
        content=raw,
        headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
    )

    conv = db.scalar(select(Conversation).where(Conversation.organization_id == org_id))
    assert conv is not None
    assert conv.waiting_on == WaitingOn.OWNER

    reminder = db.scalar(
        select(FollowUp).where(
            FollowUp.organization_id == org_id,
            FollowUp.conversation_id == conv.id,
            FollowUp.type == FollowUpType.OWNER_RESPONSE_REMINDER,
            FollowUp.status == FollowUpStatus.PENDING,
        )
    )
    assert reminder is not None

    # Advance time past the 2-minute short delay
    from app.services.followup_processor import FollowUpProcessor

    future_time = reminder.due_at + timedelta(minutes=1)
    processor = FollowUpProcessor(db)
    completed_count = processor.process_due(organization_id=org_id, now=future_time)
    assert completed_count >= 1

    db.refresh(reminder)
    # Reminder should be marked COMPLETED
    assert reminder.status == FollowUpStatus.COMPLETED


def test_scenario_16_failure_resilience(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenario 16: Failure resilience tests.

    - Invalid Meta signature -> 403
    - Unknown phone_number_id -> safely skipped
    - Unsupported media event -> safely skipped, no crash
    - Bad outbound provider response -> recorded as FAILED, no customer data lost
    """
    phone_id = "phone_demo_scen16"
    app_secret = "meta-secret-32-chars-scen16-demo!"
    monkeypatch.setattr(get_settings(), "meta_app_secret", app_secret)

    demo = setup_generic_demo_org(client, db, phone_id, app_secret)
    org_id = demo["org_id"]

    # 1. Invalid signature
    res_bad_sig = client.post(
        "/webhooks/whatsapp",
        content=b"{}",
        headers={"X-Hub-Signature-256": "sha256=bad_hex_signature"},
    )
    assert res_bad_sig.status_code == 403

    # 2. Unknown phone_number_id
    payload_unknown_phone = build_meta_webhook(
        phone_number_id="unknown_phone_999999",
        from_phone="+15125550316",
        message_id="wamid_unknown_phone",
        text="Hello to unknown phone",
    )
    raw_unknown = json.dumps(payload_unknown_phone).encode("utf-8")
    sig_unknown = sign_payload(raw_unknown, app_secret)
    res_unknown = client.post(
        "/webhooks/whatsapp",
        content=raw_unknown,
        headers={"X-Hub-Signature-256": sig_unknown, "Content-Type": "application/json"},
    )
    assert res_unknown.status_code == 200  # Return 200 so Meta does not retry indefinitely

    # 3. Unsupported media type (e.g. image)
    payload_image = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba_demo_123",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": phone_id},
                            "messages": [
                                {
                                    "id": "wamid_image_123",
                                    "from": "15125550316",
                                    "timestamp": "1710000000",
                                    "type": "image",
                                    "image": {"id": "media_id_123", "mime_type": "image/jpeg"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    raw_img = json.dumps(payload_image).encode("utf-8")
    sig_img = sign_payload(raw_img, app_secret)
    res_img = client.post(
        "/webhooks/whatsapp",
        content=raw_img,
        headers={"X-Hub-Signature-256": sig_img, "Content-Type": "application/json"},
    )
    assert res_img.status_code == 200

    # 4. Outbound provider failure resilience
    failing_wa = FakeWhatsAppProvider(should_fail=True, fail_reason="Simulated Meta API 500 error")
    monkeypatch.setattr(
        "app.services.whatsapp.inbound.get_whatsapp_provider", lambda: failing_wa
    )
    monkeypatch.setattr(
        "app.services.inbound.get_whatsapp_provider", lambda: failing_wa
    )

    payload_fail = build_meta_webhook(
        phone_number_id=phone_id,
        from_phone="+15125550317",
        message_id="wamid_provider_fail_test",
        text="Hi, I need help with a consultation this Friday in Islamabad.",
        contact_name="Failure Tester",
    )
    raw_fail = json.dumps(payload_fail).encode("utf-8")
    sig_fail = sign_payload(raw_fail, app_secret)
    res_fail = client.post(
        "/webhooks/whatsapp",
        content=raw_fail,
        headers={"X-Hub-Signature-256": sig_fail, "Content-Type": "application/json"},
    )
    assert res_fail.status_code == 200

    # Customer and lead MUST still be saved even if outbound WhatsApp fails!
    lead_saved = db.scalar(
        select(Lead).where(
            Lead.organization_id == org_id,
            Lead.customer_phone == "+15125550317",
        )
    )
    assert lead_saved is not None
    assert lead_saved.qualification_status == QualificationStatus.COMPLETE

    # Outbound message recorded as FAILED
    failed_msg = db.scalar(
        select(ConversationMessage).where(
            ConversationMessage.organization_id == org_id,
            ConversationMessage.delivery_status == MessageDeliveryStatus.FAILED,
        )
    )
    assert failed_msg is not None
