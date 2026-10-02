import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import FollowUpStatus
from app.models.followup import FollowUp
from tests.conftest import register


def create_manual(client: TestClient, headers: dict[str, str], name: str = "David") -> dict:
    phone_suffix = sum(ord(character) for character in name) % 10000
    response = client.post(
        "/leads",
        headers=headers,
        json={
            "customer_name": name,
            "customer_email": f"{name.lower()}@example.com",
            "customer_phone": f"555-123-{phone_suffix:04d}",
            "message": "My AC has stopped cooling. Can someone come tomorrow morning?",
            "source": "MANUAL",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_manual_lead_uses_mock_ai_and_schedules_followups(
    client: TestClient, auth_headers: dict[str, str], db: Session
) -> None:
    lead = create_manual(client, auth_headers)
    assert lead["service_type"] == "AC Repair"
    assert lead["urgency"] == "HIGH"
    assert lead["preferred_date_text"] == "Tomorrow"
    assert lead["preferred_time_text"] == "Morning"
    assert lead["next_followup_at"] is not None
    assert len(db.scalars(select(FollowUp)).all()) == 3
    events = client.get(f"/leads/{lead['id']}/events", headers=auth_headers)
    event_types = {event["event_type"] for event in events.json()}
    assert {"LEAD_CREATED", "AI_PROCESSED", "ACKNOWLEDGEMENT_SENT"} <= event_types


def test_status_transitions_and_terminal_states_cancel_followups(
    client: TestClient, auth_headers: dict[str, str], db: Session
) -> None:
    lead = create_manual(client, auth_headers, "Jordan")
    contacted = client.post(
        f"/leads/{lead['id']}/status",
        headers=auth_headers,
        json={"status": "CONTACTED"},
    )
    assert contacted.status_code == 200
    assert contacted.json()["last_contacted_at"] is not None
    assert contacted.json()["next_followup_at"] is not None

    booked = client.post(
        f"/leads/{lead['id']}/status",
        headers=auth_headers,
        json={"status": "BOOKED"},
    )
    assert booked.status_code == 200
    assert booked.json()["booked_at"] is not None
    assert booked.json()["next_followup_at"] is None
    pending = db.scalars(
        select(FollowUp).where(
            FollowUp.lead_id == uuid.UUID(lead["id"]), FollowUp.status == FollowUpStatus.PENDING
        )
    ).all()
    assert pending == []


def test_lost_cancels_followups(
    client: TestClient, auth_headers: dict[str, str], db: Session
) -> None:
    lead = create_manual(client, auth_headers, "Casey")
    response = client.post(
        f"/leads/{lead['id']}/status", headers=auth_headers, json={"status": "LOST"}
    )
    assert response.status_code == 200
    assert response.json()["lost_at"] is not None
    assert not db.scalars(
        select(FollowUp).where(
            FollowUp.lead_id == uuid.UUID(lead["id"]), FollowUp.status == FollowUpStatus.PENDING
        )
    ).first()


def test_tenant_isolation(client: TestClient) -> None:
    first = register(client, "tenant-a")
    first_headers = {"Authorization": f"Bearer {first['access_token']}"}
    lead = create_manual(client, first_headers, "Private")
    second = register(client, "tenant-b")
    second_headers = {"Authorization": f"Bearer {second['access_token']}"}
    assert client.get(f"/leads/{lead['id']}", headers=second_headers).status_code == 404
    assert client.get("/leads", headers=second_headers).json()["items"] == []
    assert (
        client.get(
            f"/organizations/{first['user']['organization_id']}", headers=second_headers
        ).status_code
        == 404
    )
