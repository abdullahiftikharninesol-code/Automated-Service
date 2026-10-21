from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.conversation import Conversation
from app.models.enums import (
    FollowUpStatus,
    FollowUpType,
    QualificationStatus,
    WaitingOn,
)
from app.models.followup import FollowUp
from app.models.lead import Lead
from app.models.organization import Organization
from app.services.whatsapp.provider import FakeWhatsAppProvider
from tests.conftest import register
from tests.test_whatsapp import build_meta_webhook, sign_payload


def test_qualification_field_crud_and_tenant_isolation(
    client: TestClient, db: Session
) -> None:
    # 1. Register two isolated tenants
    tenant_a = register(client, "clothing-co")
    headers_a = {"Authorization": f"Bearer {tenant_a['access_token']}"}

    tenant_b = register(client, "dental-clinic")
    headers_b = {"Authorization": f"Bearer {tenant_b['access_token']}"}
    org_b_id = uuid.UUID(tenant_b["user"]["organization_id"])

    # 2. Validation: invalid field keys
    res_bad_key = client.post(
        "/qualification-fields",
        headers=headers_a,
        json={"key": "Invalid-Key!", "label": "Invalid"},
    )
    assert res_bad_key.status_code == 422 or res_bad_key.status_code == 400

    res_reserved = client.post(
        "/qualification-fields",
        headers=headers_a,
        json={"key": "lead_id", "label": "Reserved"},
    )
    assert res_reserved.status_code == 422 or res_reserved.status_code == 400

    # 3. Create valid fields for Tenant A
    res_create = client.post(
        "/qualification-fields",
        headers=headers_a,
        json={
            "key": "product",
            "label": "Product",
            "field_type": "TEXT",
            "required": True,
            "sort_order": 1,
            "question_text": "What product are you looking for?",
        },
    )
    assert res_create.status_code == 201
    field_a = res_create.json()
    field_a_id = field_a["id"]
    assert field_a["key"] == "product"
    assert field_a["required"] is True

    # 4. Duplicate key rejection for Tenant A
    res_dup = client.post(
        "/qualification-fields",
        headers=headers_a,
        json={"key": "product", "label": "Product Duplicate"},
    )
    assert res_dup.status_code == 400
    assert "already exists" in res_dup.json()["detail"]

    # 5. Tenant B can create field with same key 'product' without collision
    res_create_b = client.post(
        "/qualification-fields",
        headers=headers_b,
        json={
            "key": "product",
            "label": "Tenant B Product",
            "field_type": "TEXT",
            "required": False,
        },
    )
    assert res_create_b.status_code == 201
    field_b = res_create_b.json()
    assert field_b["organization_id"] == str(org_b_id)

    # 6. Tenant B cannot access or modify Tenant A's field
    # The endpoint is collection-based or detail-based; detail patch should 404
    res_b_patch = client.patch(
        f"/qualification-fields/{field_a_id}",
        headers=headers_b,
        json={"label": "Hacked"},
    )
    assert res_b_patch.status_code == 404

    res_b_delete = client.delete(
        f"/qualification-fields/{field_a_id}",
        headers=headers_b,
    )
    assert res_b_delete.status_code == 404

    # 7. Tenant A can list, update, and delete
    list_a = client.get("/qualification-fields", headers=headers_a)
    assert list_a.status_code == 200
    assert len(list_a.json()["items"]) == 1

    patch_a = client.patch(
        f"/qualification-fields/{field_a_id}",
        headers=headers_a,
        json={"label": "Desired Product", "required": False},
    )
    assert patch_a.status_code == 200
    assert patch_a.json()["label"] == "Desired Product"
    assert patch_a.json()["required"] is False

    del_a = client.delete(f"/qualification-fields/{field_a_id}", headers=headers_a)
    assert del_a.status_code == 204

    list_a_after = client.get("/qualification-fields", headers=headers_a)
    assert len(list_a_after.json()["items"]) == 0


def test_starter_templates_application(client: TestClient, db: Session) -> None:
    tenant = register(client, "starter-brand")
    headers = {"Authorization": f"Bearer {tenant['access_token']}"}

    # 1. Invalid template name -> 400
    res_invalid = client.post(
        "/qualification-fields/apply-template",
        headers=headers,
        json={"template_name": "NON_EXISTENT_TEMPLATE"},
    )
    assert res_invalid.status_code == 400
    assert "Unknown template" in res_invalid.json()["detail"]

    # 2. Apply CLOTHING template
    res_clothing = client.post(
        "/qualification-fields/apply-template",
        headers=headers,
        json={"template_name": "CLOTHING"},
    )
    assert res_clothing.status_code == 200
    clothing_fields = res_clothing.json()["items"]
    clothing_keys = [f["key"] for f in clothing_fields]
    assert "product" in clothing_keys
    assert "size" in clothing_keys
    assert "quantity" in clothing_keys
    assert "delivery_city" in clothing_keys

    # 3. Apply DENTAL template with replace_existing=True
    res_dental = client.post(
        "/qualification-fields/apply-template",
        headers=headers,
        json={"template_name": "DENTAL", "replace_existing": True},
    )
    assert res_dental.status_code == 200
    dental_fields = res_dental.json()["items"]
    dental_keys = [f["key"] for f in dental_fields]
    assert "service" in dental_keys
    assert "preferred_date" in dental_keys
    assert "preferred_time" in dental_keys
    # Previous clothing fields were replaced
    assert "delivery_city" not in dental_keys


def test_clothing_business_multi_turn_whatsapp_qualification(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_secret = "test-meta-app-secret-32-chars-long!"
    phone_number_id = "phone_clothing_101"
    monkeypatch.setattr(get_settings(), "meta_app_secret", app_secret)

    fake_whatsapp = FakeWhatsAppProvider()
    monkeypatch.setattr(
        "app.services.whatsapp.inbound.get_whatsapp_provider", lambda: fake_whatsapp
    )
    monkeypatch.setattr(
        "app.services.inbound.get_whatsapp_provider", lambda: fake_whatsapp
    )

    # 1. Register organization and configure WhatsApp
    account = register(client, "zara-clothing")
    headers = {"Authorization": f"Bearer {account['access_token']}"}
    org_id = uuid.UUID(account["user"]["organization_id"])

    org = db.get(Organization, org_id)
    assert org is not None
    org.whatsapp_phone_number_id = phone_number_id
    db.commit()

    # 2. Apply CLOTHING template
    client.post(
        "/qualification-fields/apply-template",
        headers=headers,
        json={"template_name": "CLOTHING"},
    )

    customer_phone = "+15125550201"

    # Turn 1: Inbound message with missing fields:
    # "Do you have the black dress in medium?"
    # Extracts: product="black dress", size="medium", quantity=missing, delivery_city=missing
    payload_1 = build_meta_webhook(
        phone_number_id=phone_number_id,
        from_phone=customer_phone,
        message_id="wamid_clothing_turn1",
        text="Do you have the black dress in medium?",
        contact_name="Amina Khan",
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
    assert lead.qualifications.get("product") == "black dress"
    assert lead.qualifications.get("size").lower() == "medium"
    assert lead.qualification_status == QualificationStatus.IN_PROGRESS

    conv = db.get(Conversation, lead.primary_conversation_id)
    assert conv is not None
    # Crucial: waiting_on must be CUSTOMER because clarification question was sent!
    assert conv.waiting_on == WaitingOn.CUSTOMER

    # Crucial: NO OWNER_RESPONSE_REMINDER scheduled while waiting on customer!
    owner_reminders = list(
        db.scalars(
            select(FollowUp).where(
                FollowUp.organization_id == org_id,
                FollowUp.conversation_id == conv.id,
                FollowUp.type == FollowUpType.OWNER_RESPONSE_REMINDER,
                FollowUp.status == FollowUpStatus.PENDING,
            )
        )
    )
    assert len(owner_reminders) == 0

    # Verify clarification question was sent asking for missing fields (quantity, delivery city)
    assert len(fake_whatsapp.sent_messages) == 1
    sent_1 = fake_whatsapp.sent_messages[0]
    assert "quantity" in sent_1["body"].lower() or "how many" in sent_1["body"].lower()
    assert "city" in sent_1["body"].lower() or "delivery" in sent_1["body"].lower()

    # Turn 2: Customer replies providing missing details:
    # "One piece, Lahore."
    payload_2 = build_meta_webhook(
        phone_number_id=phone_number_id,
        from_phone=customer_phone,
        message_id="wamid_clothing_turn2",
        text="One piece, Lahore.",
        contact_name="Amina Khan",
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

    # Lead qualifications should now be complete
    assert lead.qualifications.get("quantity") == 1
    assert lead.qualifications.get("delivery_city") == "Lahore"
    assert lead.qualification_status == QualificationStatus.COMPLETE
    assert lead.qualification_completed_at is not None

    # Crucial: waiting_on transitions to OWNER and owner reminder is scheduled!
    assert conv.waiting_on == WaitingOn.OWNER

    # Exactly ONE owner response reminder scheduled
    reminders_after = list(
        db.scalars(
            select(FollowUp).where(
                FollowUp.organization_id == org_id,
                FollowUp.conversation_id == conv.id,
                FollowUp.type == FollowUpType.OWNER_RESPONSE_REMINDER,
                FollowUp.status == FollowUpStatus.PENDING,
            )
        )
    )
    assert len(reminders_after) == 1

    # Confirmation receipt sent to customer
    assert len(fake_whatsapp.sent_messages) == 2
    sent_2 = fake_whatsapp.sent_messages[1]
    assert "got the details" in sent_2["body"].lower()


def test_dental_clinic_qualification_genericity(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_secret = "test-meta-app-secret-32-chars-long!"
    phone_number_id = "phone_dental_202"
    monkeypatch.setattr(get_settings(), "meta_app_secret", app_secret)

    fake_whatsapp = FakeWhatsAppProvider()
    monkeypatch.setattr(
        "app.services.whatsapp.inbound.get_whatsapp_provider", lambda: fake_whatsapp
    )
    monkeypatch.setattr(
        "app.services.inbound.get_whatsapp_provider", lambda: fake_whatsapp
    )

    account = register(client, "smile-dental")
    headers = {"Authorization": f"Bearer {account['access_token']}"}
    org_id = uuid.UUID(account["user"]["organization_id"])

    org = db.get(Organization, org_id)
    assert org is not None
    org.whatsapp_phone_number_id = phone_number_id
    db.commit()

    # Apply DENTAL template (service, preferred_date, preferred_time)
    client.post(
        "/qualification-fields/apply-template",
        headers=headers,
        json={"template_name": "DENTAL"},
    )

    payload = build_meta_webhook(
        phone_number_id=phone_number_id,
        from_phone="+15125550202",
        message_id="wamid_dental_1",
        text="I need a dental cleaning next Tuesday.",
        contact_name="Farhan Ali",
    )
    raw = json.dumps(payload).encode("utf-8")
    sig = sign_payload(raw, app_secret)

    res = client.post(
        "/webhooks/whatsapp",
        content=raw,
        headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
    )
    assert res.status_code == 200

    lead = db.scalar(select(Lead).where(Lead.organization_id == org_id))
    assert lead is not None
    assert lead.qualification_status == QualificationStatus.IN_PROGRESS
    assert lead.qualifications.get("service") is not None
    assert lead.qualifications.get("preferred_date") is not None
    assert lead.qualifications.get("preferred_time") is None

    # Asks for missing preferred time
    assert len(fake_whatsapp.sent_messages) == 1
    sent = fake_whatsapp.sent_messages[0]
    assert "time" in sent["body"].lower()


def test_real_estate_qualification_genericity(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_secret = "test-meta-app-secret-32-chars-long!"
    phone_number_id = "phone_real_estate_303"
    monkeypatch.setattr(get_settings(), "meta_app_secret", app_secret)

    fake_whatsapp = FakeWhatsAppProvider()
    monkeypatch.setattr(
        "app.services.whatsapp.inbound.get_whatsapp_provider", lambda: fake_whatsapp
    )
    monkeypatch.setattr(
        "app.services.inbound.get_whatsapp_provider", lambda: fake_whatsapp
    )

    account = register(client, "premier-re")
    headers = {"Authorization": f"Bearer {account['access_token']}"}
    org_id = uuid.UUID(account["user"]["organization_id"])

    org = db.get(Organization, org_id)
    assert org is not None
    org.whatsapp_phone_number_id = phone_number_id
    db.commit()

    # Apply REAL_ESTATE template (intent, property_type, location, budget)
    client.post(
        "/qualification-fields/apply-template",
        headers=headers,
        json={"template_name": "REAL_ESTATE"},
    )

    payload = build_meta_webhook(
        phone_number_id=phone_number_id,
        from_phone="+15125550203",
        message_id="wamid_re_1",
        text="I want to rent an apartment in Islamabad.",
        contact_name="Bilal Shah",
    )
    raw = json.dumps(payload).encode("utf-8")
    sig = sign_payload(raw, app_secret)

    res = client.post(
        "/webhooks/whatsapp",
        content=raw,
        headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
    )
    assert res.status_code == 200

    lead = db.scalar(select(Lead).where(Lead.organization_id == org_id))
    assert lead is not None
    assert lead.qualification_status == QualificationStatus.IN_PROGRESS
    assert lead.qualifications.get("intent") == "rent"
    assert lead.qualifications.get("property_type") == "Apartment"
    assert lead.qualifications.get("location") == "Islamabad"
    assert lead.qualifications.get("budget") is None

    # Asks for missing budget
    assert len(fake_whatsapp.sent_messages) == 1
    sent = fake_whatsapp.sent_messages[0]
    assert "budget" in sent["body"].lower()


def test_complete_qualification_in_first_message(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_secret = "test-meta-app-secret-32-chars-long!"
    phone_number_id = "phone_complete_404"
    monkeypatch.setattr(get_settings(), "meta_app_secret", app_secret)

    fake_whatsapp = FakeWhatsAppProvider()
    monkeypatch.setattr(
        "app.services.whatsapp.inbound.get_whatsapp_provider", lambda: fake_whatsapp
    )
    monkeypatch.setattr(
        "app.services.inbound.get_whatsapp_provider", lambda: fake_whatsapp
    )

    account = register(client, "quick-buy")
    headers = {"Authorization": f"Bearer {account['access_token']}"}
    org_id = uuid.UUID(account["user"]["organization_id"])

    org = db.get(Organization, org_id)
    assert org is not None
    org.whatsapp_phone_number_id = phone_number_id
    db.commit()

    # Apply CLOTHING template
    client.post(
        "/qualification-fields/apply-template",
        headers=headers,
        json={"template_name": "CLOTHING"},
    )

    # Customer provides ALL required information in first message
    payload = build_meta_webhook(
        phone_number_id=phone_number_id,
        from_phone="+15125550204",
        message_id="wamid_complete_1",
        text="I need 1 black dress in medium delivered to Lahore.",
        contact_name="Tariq Aziz",
    )
    raw = json.dumps(payload).encode("utf-8")
    sig = sign_payload(raw, app_secret)

    res = client.post(
        "/webhooks/whatsapp",
        content=raw,
        headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
    )
    assert res.status_code == 200

    lead = db.scalar(select(Lead).where(Lead.organization_id == org_id))
    assert lead is not None
    assert lead.qualification_status == QualificationStatus.COMPLETE

    conv = db.get(Conversation, lead.primary_conversation_id)
    assert conv is not None
    assert conv.waiting_on == WaitingOn.OWNER

    # Standard acknowledgement receipt sent
    assert len(fake_whatsapp.sent_messages) == 1
    assert f"Thanks for contacting {org.name}" in fake_whatsapp.sent_messages[0]["body"]

    # Owner reminder scheduled immediately
    reminders = list(
        db.scalars(
            select(FollowUp).where(
                FollowUp.organization_id == org_id,
                FollowUp.conversation_id == conv.id,
                FollowUp.type == FollowUpType.OWNER_RESPONSE_REMINDER,
            )
        )
    )
    assert len(reminders) == 1


def test_duplicate_webhook_does_not_repeat_qualification_actions(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_secret = "test-meta-app-secret-32-chars-long!"
    phone_number_id = "phone_idemp_505"
    monkeypatch.setattr(get_settings(), "meta_app_secret", app_secret)

    fake_whatsapp = FakeWhatsAppProvider()
    monkeypatch.setattr(
        "app.services.whatsapp.inbound.get_whatsapp_provider", lambda: fake_whatsapp
    )
    monkeypatch.setattr(
        "app.services.inbound.get_whatsapp_provider", lambda: fake_whatsapp
    )

    account = register(client, "idemp-store")
    headers = {"Authorization": f"Bearer {account['access_token']}"}
    org_id = uuid.UUID(account["user"]["organization_id"])

    org = db.get(Organization, org_id)
    assert org is not None
    org.whatsapp_phone_number_id = phone_number_id
    db.commit()

    client.post(
        "/qualification-fields/apply-template",
        headers=headers,
        json={"template_name": "CLOTHING"},
    )

    payload = build_meta_webhook(
        phone_number_id=phone_number_id,
        from_phone="+15125550205",
        message_id="wamid_dup_1",
        text="Do you have black dress in medium?",
        contact_name="Duplicate Tester",
    )
    raw = json.dumps(payload).encode("utf-8")
    sig = sign_payload(raw, app_secret)

    # First delivery
    res_1 = client.post(
        "/webhooks/whatsapp",
        content=raw,
        headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
    )
    assert res_1.status_code == 200
    assert len(fake_whatsapp.sent_messages) == 1

    # Second delivery with identical wamid
    res_2 = client.post(
        "/webhooks/whatsapp",
        content=raw,
        headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
    )
    assert res_2.status_code == 200

    # No duplicate message sent
    assert len(fake_whatsapp.sent_messages) == 1


def test_owner_reply_during_in_progress_qualification(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_secret = "test-meta-app-secret-32-chars-long!"
    phone_number_id = "phone_owner_reply_606"
    monkeypatch.setattr(get_settings(), "meta_app_secret", app_secret)

    fake_whatsapp = FakeWhatsAppProvider()
    monkeypatch.setattr(
        "app.services.whatsapp.inbound.get_whatsapp_provider", lambda: fake_whatsapp
    )
    monkeypatch.setattr(
        "app.services.inbound.get_whatsapp_provider", lambda: fake_whatsapp
    )

    account = register(client, "manual-store")
    headers = {"Authorization": f"Bearer {account['access_token']}"}
    org_id = uuid.UUID(account["user"]["organization_id"])

    org = db.get(Organization, org_id)
    assert org is not None
    org.whatsapp_phone_number_id = phone_number_id
    db.commit()

    client.post(
        "/qualification-fields/apply-template",
        headers=headers,
        json={"template_name": "CLOTHING"},
    )

    # Inbound: qualification incomplete
    payload = build_meta_webhook(
        phone_number_id=phone_number_id,
        from_phone="+15125550206",
        message_id="wamid_owner_test_1",
        text="Do you have black dress in medium?",
        contact_name="Sara",
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
    assert conv.waiting_on == WaitingOn.CUSTOMER

    # Owner sends manual reply via conversation messages endpoint
    res_reply = client.post(
        f"/conversations/{conv.id}/messages",
        headers=headers,
        json={"body": "Hello Sara, we have it in stock and can deliver tomorrow!"},
    )
    assert res_reply.status_code == 201

    db.refresh(conv)
    assert conv.waiting_on == WaitingOn.CUSTOMER
