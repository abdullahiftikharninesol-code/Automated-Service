import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import LeadStatus
from app.models.lead import Lead
from tests.test_leads import create_manual


def test_public_inquiry_and_dashboard(
    client: TestClient, account: dict[str, object], auth_headers: dict[str, str]
) -> None:
    organization_id = account["user"]["organization_id"]
    response = client.post(
        f"/public/inquiries/{organization_id}",
        json={
            "customer_name": "David Wilson",
            "customer_email": "david@example.com",
            "customer_phone": "555-123-4567",
            "message": (
                "My AC has stopped cooling and it is extremely hot in the house. "
                "Can someone come tomorrow morning?"
            ),
        },
    )
    assert response.status_code == 201, response.text
    dashboard = client.get("/dashboard", headers=auth_headers)
    assert dashboard.status_code == 200
    data = dashboard.json()
    assert data["counts"]["new"] == 1
    assert data["counts"]["needs_attention"] == 1
    assert data["needs_attention"][0]["customer_name"] == "David Wilson"


def test_due_followup_processor(
    client: TestClient, auth_headers: dict[str, str], db: Session
) -> None:
    created = create_manual(client, auth_headers, "Due")
    lead = db.get(Lead, uuid.UUID(created["id"]))
    assert lead
    lead.next_followup_at = datetime.now(UTC) - timedelta(minutes=1)
    for reminder in lead.followups:
        reminder.scheduled_for = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    result = client.post("/followups/process", headers=auth_headers)
    assert result.status_code == 200
    assert result.json()["processed"] == 3


def test_dashboard_counts_statuses(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    first = create_manual(client, auth_headers, "One")
    second = create_manual(client, auth_headers, "Two")
    client.post(
        f"/leads/{first['id']}/status", headers=auth_headers, json={"status": "BOOKED"}
    )
    client.post(
        f"/leads/{second['id']}/status", headers=auth_headers, json={"status": "CONTACTED"}
    )
    counts = client.get("/dashboard", headers=auth_headers).json()["counts"]
    assert counts == {"new": 0, "needs_attention": 0, "contacted": 1, "booked": 1, "lost": 0}


def test_reopen_terminal_lead(client: TestClient, auth_headers: dict[str, str]) -> None:
    lead = create_manual(client, auth_headers, "Reopen")
    client.post(
        f"/leads/{lead['id']}/status", headers=auth_headers, json={"status": LeadStatus.LOST}
    )
    reopened = client.post(
        f"/leads/{lead['id']}/status", headers=auth_headers, json={"status": LeadStatus.NEW}
    )
    assert reopened.json()["status"] == "NEW"
    assert reopened.json()["lost_at"] is None
    assert reopened.json()["next_followup_at"] is not None
