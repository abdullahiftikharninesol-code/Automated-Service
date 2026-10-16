from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.conversation_message import ConversationMessage
from app.models.customer import Customer
from app.models.enums import (
    ConversationStatus,
    InboundChannel,
    MessageDeliveryStatus,
    MessageDirection,
    MessageSenderType,
    WaitingOn,
)
from app.models.lead import Lead
from tests.conftest import register


def test_customer_matching_and_conflict_handling(
    client: TestClient, account: dict[str, object], auth_headers: dict[str, str], db: Session
) -> None:
    org_id = str(account["user"]["organization_id"])
    client.patch(
        f"/organizations/{org_id}", json={"default_phone_region": "US"}, headers=auth_headers
    )

    # 1. First inbound creates customer with phone and email
    r1 = client.post(
        f"/public/inbound/form/{org_id}",
        json={
            "name": "Customer One",
            "email": "customer1@example.com",
            "phone": "+1 512 555 0101",
            "message": "First inquiry",
        },
    )
    assert r1.status_code == 201

    customers = db.query(Customer).filter(Customer.organization_id == uuid.UUID(org_id)).all()
    assert len(customers) == 1
    cust1 = customers[0]
    assert cust1.name == "Customer One"
    assert cust1.email_normalized == "customer1@example.com"
    assert cust1.phone_normalized == "+15125550101"

    # 2. Second inbound with same normalized phone but formatted differently -> reuses cust1
    r2 = client.post(
        f"/public/inbound/form/{org_id}",
        json={
            "name": "Customer One Renamed",
            "phone": "(512) 555-0101",
            "message": "Second inquiry by phone",
        },
    )
    assert r2.status_code == 201
    assert db.query(Customer).filter(Customer.organization_id == uuid.UUID(org_id)).count() == 1

    # 3. Third inbound with email only -> creates new customer cust2
    r3 = client.post(
        f"/public/inbound/form/{org_id}",
        json={
            "name": "Customer Two",
            "email": "customer2@example.com",
            "message": "Email only inquiry",
        },
    )
    assert r3.status_code == 201
    assert db.query(Customer).filter(Customer.organization_id == uuid.UUID(org_id)).count() == 2

    # 4. Identity conflict: incoming message has cust1's phone AND cust2's email
    # Must NOT silently merge cust1 and cust2!
    r4 = client.post(
        f"/public/inbound/form/{org_id}",
        json={
            "name": "Conflict Person",
            "phone": "+15125550101",  # Matches cust1
            "email": "customer2@example.com",  # Matches cust2
            "message": "Conflict inquiry",
        },
    )
    assert r4.status_code == 201
    # Customer count remains 2 (no duplicate created, no merging)
    assert db.query(Customer).filter(Customer.organization_id == uuid.UUID(org_id)).count() == 2


def test_customer_cross_tenant_isolation(
    client: TestClient, account: dict[str, object], db: Session
) -> None:
    org_a_id = str(account["user"]["organization_id"])
    org_b = register(client, "org-b-cust")
    org_b_id = str(org_b["user"]["organization_id"])

    # Org A inbound
    client.post(
        f"/public/inbound/form/{org_a_id}",
        json={
            "name": "Shared Identity",
            "email": "shared@example.com",
            "phone": "+15125550200",
            "message": "Message for A",
        },
    )

    # Org B inbound with identical contact info -> Must create distinct customer
    client.post(
        f"/public/inbound/form/{org_b_id}",
        json={
            "name": "Shared Identity",
            "email": "shared@example.com",
            "phone": "+15125550200",
            "message": "Message for B",
        },
    )

    cust_a = db.query(Customer).filter(Customer.organization_id == uuid.UUID(org_a_id)).first()
    cust_b = db.query(Customer).filter(Customer.organization_id == uuid.UUID(org_b_id)).first()
    assert cust_a is not None and cust_b is not None
    assert cust_a.id != cust_b.id


def test_conversation_lifecycle_and_messages(
    client: TestClient, account: dict[str, object], auth_headers: dict[str, str], db: Session
) -> None:
    org_id = str(account["user"]["organization_id"])

    # 1. First inbound request
    res = client.post(
        f"/public/inbound/webhook/{org_id}",
        json={
            "external_message_id": "ext-lifecycle-1",
            "name": "Grace Hopper",
            "email": "grace@navy.example.com",
            "phone": "+15125550300",
            "message": "First message requesting system upgrade",
        },
    )
    assert res.status_code == 201
    lead_id = res.json()["lead_id"]

    # Verify relationships on Lead
    lead = db.get(Lead, uuid.UUID(lead_id))
    assert lead is not None
    assert lead.customer_id is not None
    assert lead.primary_conversation_id is not None

    conv = db.get(Conversation, lead.primary_conversation_id)
    assert conv is not None
    assert conv.customer_id == lead.customer_id
    assert conv.lead_id == lead.id
    assert conv.status == ConversationStatus.OPEN
    assert conv.waiting_on == WaitingOn.CUSTOMER  # Acknowledgement set waiting_on to CUSTOMER

    # Verify ConversationMessages
    messages = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == conv.id)
        .order_by(ConversationMessage.sent_at.asc())
        .all()
    )
    assert len(messages) >= 2
    # Inbound message from customer
    msg1 = messages[0]
    assert msg1.direction == MessageDirection.INBOUND
    assert msg1.sender_type == MessageSenderType.CUSTOMER
    assert msg1.external_message_id == "ext-lifecycle-1"
    assert "system upgrade" in msg1.body

    # Outbound acknowledgement
    msg2 = messages[1]
    assert msg2.direction == MessageDirection.OUTBOUND
    assert msg2.sender_type == MessageSenderType.SYSTEM
    assert msg2.channel == InboundChannel.EMAIL
    assert msg2.delivery_status == MessageDeliveryStatus.SENT

    # 2. Second message within duplicate window attaches to same conversation & lead
    res2 = client.post(
        f"/public/inbound/webhook/{org_id}",
        json={
            "external_message_id": "ext-lifecycle-2",
            "name": "Grace Hopper",
            "email": "grace@navy.example.com",
            "phone": "+15125550300",
            "message": "Follow-up note with serial number",
        },
    )
    assert res2.status_code == 201
    assert res2.json()["lead_id"] == lead_id

    messages_after = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == conv.id)
        .order_by(ConversationMessage.sent_at.asc())
        .all()
    )
    # Appended new inbound message
    inbounds = [m for m in messages_after if m.direction == MessageDirection.INBOUND]
    assert len(inbounds) == 2
    assert inbounds[1].external_message_id == "ext-lifecycle-2"


def test_conversation_and_customer_apis(
    client: TestClient, account: dict[str, object], auth_headers: dict[str, str]
) -> None:
    org_id = str(account["user"]["organization_id"])

    # Create inbound lead
    client.post(
        f"/public/inbound/form/{org_id}",
        json={
            "name": "Nikola Tesla",
            "email": "nikola@wardenclyffe.example.com",
            "phone": "+15125550400",
            "message": "Wireless power transmission consultation",
        },
    )

    # 1. GET /customers
    cust_res = client.get("/customers", headers=auth_headers)
    assert cust_res.status_code == 200
    cust_data = cust_res.json()
    assert cust_data["total"] >= 1
    tesla_cust = next((c for c in cust_data["items"] if c["name"] == "Nikola Tesla"), None)
    assert tesla_cust is not None
    assert tesla_cust["phone_normalized"] == "+15125550400"

    # Search customer by query
    search_res = client.get("/customers?q=Tesla", headers=auth_headers).json()
    assert len(search_res["items"]) == 1
    assert search_res["items"][0]["id"] == tesla_cust["id"]

    # 2. GET /customers/{customer_id}
    single_cust_res = client.get(f"/customers/{tesla_cust['id']}", headers=auth_headers)
    assert single_cust_res.status_code == 200
    assert single_cust_res.json()["name"] == "Nikola Tesla"

    # 3. GET /conversations
    conv_res = client.get("/conversations", headers=auth_headers)
    assert conv_res.status_code == 200
    conv_data = conv_res.json()
    assert conv_data["total"] >= 1
    tesla_conv = next((c for c in conv_data["items"] if c["customer_id"] == tesla_cust["id"]), None)
    assert tesla_conv is not None
    assert tesla_conv["status"] == "OPEN"

    # 4. GET /conversations/{conversation_id}
    conv_detail_res = client.get(f"/conversations/{tesla_conv['id']}", headers=auth_headers)
    assert conv_detail_res.status_code == 200
    conv_detail = conv_detail_res.json()
    assert conv_detail["customer"]["name"] == "Nikola Tesla"
    assert len(conv_detail["messages"]) >= 1

    # 5. GET /conversations/{conversation_id}/messages
    conv_messages_res = client.get(
        f"/conversations/{tesla_conv['id']}/messages", headers=auth_headers
    )
    assert conv_messages_res.status_code == 200
    assert len(conv_messages_res.json()) >= 1


def test_cross_tenant_api_isolation(
    client: TestClient, account: dict[str, object], auth_headers: dict[str, str], db: Session
) -> None:
    org_a_id = str(account["user"]["organization_id"])
    org_b = register(client, "org-b-api-iso")
    auth_b = {"Authorization": f"Bearer {org_b['access_token']}"}

    # Create lead in Org A
    client.post(
        f"/public/inbound/form/{org_a_id}",
        json={
            "name": "Org A VIP",
            "email": "vip-a@example.com",
            "message": "Sensitive inquiry",
        },
    )

    cust_a = db.query(Customer).filter(Customer.organization_id == uuid.UUID(org_a_id)).first()
    conv_a = (
        db.query(Conversation).filter(Conversation.organization_id == uuid.UUID(org_a_id)).first()
    )
    assert cust_a is not None and conv_a is not None

    # Org B trying to read Org A customer -> 404
    r_cust = client.get(f"/customers/{cust_a.id}", headers=auth_b)
    assert r_cust.status_code == 404

    # Org B trying to read Org A conversation -> 404
    r_conv = client.get(f"/conversations/{conv_a.id}", headers=auth_b)
    assert r_conv.status_code == 404

    # Org B trying to read Org A conversation messages -> 404
    r_msgs = client.get(f"/conversations/{conv_a.id}/messages", headers=auth_b)
    assert r_msgs.status_code == 404


def test_idempotency_conversation_message(
    client: TestClient, account: dict[str, object], db: Session
) -> None:
    org_id = str(account["user"]["organization_id"])

    payload = {
        "external_message_id": "idempotent-key-999",
        "name": "Repeat Customer",
        "email": "repeat@example.com",
        "message": "Repeat message body",
    }

    # Request 1
    r1 = client.post(f"/public/inbound/webhook/{org_id}", json=payload)
    assert r1.status_code == 201

    # Request 2 with same external_message_id
    r2 = client.post(f"/public/inbound/webhook/{org_id}", json=payload)
    assert r2.status_code == 201

    # Verify only ONE conversation message with this external_message_id exists
    count = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.external_message_id == "idempotent-key-999")
        .count()
    )
    assert count == 1
