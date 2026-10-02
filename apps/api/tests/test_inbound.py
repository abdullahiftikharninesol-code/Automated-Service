import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.mock import MockAIProvider
from app.models.enums import InboundChannel, LeadEventType
from app.models.inbound_message import InboundMessage
from app.models.lead import Lead
from app.models.lead_event import LeadEvent
from app.models.organization import Organization
from app.schemas.inbound import InboundMessageCreate
from app.services.inbound import InboundLeadService
from tests.conftest import register


def webhook_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Sara",
        "phone": "+923001234567",
        "message": "Do you have the black dress in medium? Can it reach Lahore by Friday?",
        "metadata": {"page_url": "https://example.com/product/black-dress"},
    }
    payload.update(overrides)
    return payload


def post_webhook(
    client: TestClient, organization_id: str, **overrides: object
) -> dict[str, object]:
    response = client.post(
        f"/public/inbound/webhook/{organization_id}",
        json=webhook_payload(**overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_website_webhook_stores_message_and_creates_generic_lead(
    client: TestClient,
    account: dict[str, object],
    auth_headers: dict[str, str],
    db: Session,
) -> None:
    organization_id = str(account["user"]["organization_id"])
    result = post_webhook(client, organization_id)

    assert result["success"] is True
    assert result["status"] == "NEW"
    inbound = db.scalar(select(InboundMessage))
    assert inbound
    assert inbound.channel == InboundChannel.WEBSITE_WEBHOOK
    assert inbound.inbound_metadata["page_url"].endswith("black-dress")

    lead_response = client.get(f"/leads/{result['lead_id']}", headers=auth_headers)
    assert lead_response.status_code == 200
    lead = lead_response.json()
    assert lead["source"] == "WEBSITE_WEBHOOK"
    assert lead["intent"] == "purchase_inquiry"
    assert lead["product_name"] == "black dress"
    assert lead["product_variant"] == "Medium"
    assert lead["location"] == "Lahore"
    assert lead["preferred_date_text"] == "Friday"


def test_hvac_webhook_example_uses_the_same_pipeline(
    client: TestClient,
    account: dict[str, object],
    auth_headers: dict[str, str],
) -> None:
    organization_id = str(account["user"]["organization_id"])
    result = post_webhook(
        client,
        organization_id,
        name="David Wilson",
        email="david@example.com",
        phone="555-123-4567",
        message="My AC stopped cooling today. Can someone come tomorrow morning?",
        metadata={"page_url": "https://example.com/contact"},
    )
    lead = client.get(f"/leads/{result['lead_id']}", headers=auth_headers).json()

    assert lead["source"] == "WEBSITE_WEBHOOK"
    assert lead["category_or_service"] == "AC Repair"
    assert lead["urgency"] == "HIGH"
    assert lead["preferred_date_text"] == "Tomorrow"
    assert lead["preferred_time_text"] == "Morning"
    assert lead["next_followup_at"] is not None


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "My AC stopped cooling. Need someone tomorrow morning.",
            {
                "intent": "service_request",
                "category_or_service": "AC Repair",
                "urgency": "HIGH",
                "preferred_date": "Tomorrow",
                "preferred_time": "Morning",
            },
        ),
        (
            "Do you have this black dress in medium and can it reach Lahore by Friday?",
            {
                "intent": "purchase_inquiry",
                "product_name": "black dress",
                "product_variant": "Medium",
                "location": "Lahore",
                "preferred_date": "Friday",
            },
        ),
        (
            "I need a cleaning appointment next week.",
            {
                "intent": "appointment_request",
                "category_or_service": "Dental Cleaning",
                "preferred_date": "Next week",
            },
        ),
    ],
)
def test_generic_mock_ai(message: str, expected: dict[str, str]) -> None:
    extracted = MockAIProvider().extract_lead_information(message)
    data = extracted.model_dump(mode="json")
    for key, value in expected.items():
        assert data[key] == value


def test_duplicate_open_inquiry_attaches_to_existing_lead(
    client: TestClient,
    account: dict[str, object],
    auth_headers: dict[str, str],
    db: Session,
) -> None:
    organization_id = str(account["user"]["organization_id"])
    first = post_webhook(client, organization_id)
    second = post_webhook(
        client,
        organization_id,
        message="Also, can the black dress arrive before Friday?",
    )

    assert second["lead_id"] == first["lead_id"]
    assert db.scalar(select(func.count(Lead.id))) == 1
    messages = client.get(f"/leads/{first['lead_id']}/messages", headers=auth_headers)
    assert messages.status_code == 200
    assert [item["message_text"] for item in messages.json()] == [
        webhook_payload()["message"],
        "Also, can the black dress arrive before Friday?",
    ]


def test_terminal_lead_allows_new_lead(
    client: TestClient, account: dict[str, object], auth_headers: dict[str, str]
) -> None:
    organization_id = str(account["user"]["organization_id"])
    first = post_webhook(client, organization_id)
    closed = client.post(
        f"/leads/{first['lead_id']}/status",
        headers=auth_headers,
        json={"status": "BOOKED"},
    )
    assert closed.status_code == 200
    second = post_webhook(client, organization_id, message="Is the black dress still available?")
    assert second["lead_id"] != first["lead_id"]


class FailingEmailProvider:
    @property
    def configured(self) -> bool:
        return True

    def send(self, *, to: str, subject: str, body: str) -> None:
        raise RuntimeError("provider unavailable")


class UnconfiguredEmailProvider:
    configured = False

    def send(self, *, to: str, subject: str, body: str) -> None:
        raise AssertionError("send must not be called when the provider is unconfigured")


def test_acknowledgement_failure_does_not_discard_lead(
    db: Session, account: dict[str, object]
) -> None:
    organization_id = uuid.UUID(str(account["user"]["organization_id"]))
    result = InboundLeadService(db, MockAIProvider(), FailingEmailProvider()).process(
        organization_id,
        InboundMessageCreate(
            channel=InboundChannel.WEBSITE_WEBHOOK,
            customer_name="David",
            customer_email="david@example.com",
            message_text="My AC stopped cooling today.",
        ),
    )
    assert db.get(Lead, result.lead.id)
    event_types = set(
        db.scalars(select(LeadEvent.event_type).where(LeadEvent.lead_id == result.lead.id)).all()
    )
    assert LeadEventType.ACKNOWLEDGEMENT_FAILED in event_types


def test_unconfigured_email_provider_is_non_fatal(
    db: Session, account: dict[str, object]
) -> None:
    organization_id = uuid.UUID(str(account["user"]["organization_id"]))
    result = InboundLeadService(db, MockAIProvider(), UnconfiguredEmailProvider()).process(
        organization_id,
        InboundMessageCreate(
            channel=InboundChannel.WEBSITE_FORM,
            customer_name="Amina",
            customer_email="amina@example.com",
            message_text="I need a cleaning appointment next week.",
        ),
    )
    assert db.get(Lead, result.lead.id)


def test_inbound_message_history_is_organization_scoped(
    client: TestClient, account: dict[str, object], auth_headers: dict[str, str]
) -> None:
    organization_id = str(account["user"]["organization_id"])
    result = post_webhook(client, organization_id)
    other = register(client, "inbound-other")
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}
    assert (
        client.get(f"/leads/{result['lead_id']}/messages", headers=other_headers).status_code == 404
    )
    assert (
        client.get(f"/leads/{result['lead_id']}/messages", headers=auth_headers).status_code == 200
    )


def test_public_embed_form_submission_uses_form_channel(
    client: TestClient, account: dict[str, object], db: Session
) -> None:
    organization_id = str(account["user"]["organization_id"])
    response = client.post(
        f"/public/inbound/form/{organization_id}",
        json={
            "name": "Amina",
            "phone": "+923009998888",
            "message": "I need a cleaning appointment next week.",
        },
    )
    assert response.status_code == 201, response.text
    inbound = db.scalar(
        select(InboundMessage).where(
            InboundMessage.id
            == select(InboundMessage.id)
            .where(InboundMessage.channel == InboundChannel.WEBSITE_FORM)
            .scalar_subquery()
        )
    )
    assert inbound
    assert inbound.lead_id == uuid.UUID(response.json()["lead_id"])


def test_business_type_can_be_configured(
    client: TestClient, account: dict[str, object], auth_headers: dict[str, str], db: Session
) -> None:
    organization_id = str(account["user"]["organization_id"])
    response = client.patch(
        f"/organizations/{organization_id}",
        headers=auth_headers,
        json={"business_type": "CLOTHING", "duplicate_window_minutes": 90},
    )
    assert response.status_code == 200, response.text
    assert response.json()["business_type"] == "CLOTHING"
    assert db.get(Organization, uuid.UUID(organization_id)).duplicate_window_minutes == 90
