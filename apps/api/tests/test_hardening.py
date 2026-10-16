import hashlib
import hmac
import json
import uuid
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.phone import normalize_phone_number
from app.core.rate_limit import limiter
from app.models.enums import LeadEventType, LeadStatus
from app.models.lead import Lead
from app.models.lead_event import LeadEvent
from tests.conftest import register


def test_phone_normalization_helper() -> None:
    assert normalize_phone_number("+1 (512) 555-0100") == "+15125550100"
    assert normalize_phone_number("+1 512 555 0100") == "+15125550100"
    assert normalize_phone_number("512-555-0100", default_region="US") == "+15125550100"
    assert normalize_phone_number("(512) 555-0100", default_region="US") == "+15125550100"
    assert normalize_phone_number("03001234567", default_region="PK") == "+923001234567"
    # No region and no international prefix => return None rather than guessing
    assert normalize_phone_number("512-555-0100", default_region=None) is None
    assert normalize_phone_number("invalid-phone") is None
    assert normalize_phone_number(None) is None


def test_rate_limiting_register(client: TestClient) -> None:
    limiter.enabled = True
    limiter.reset()
    try:
        # Register limit is 5/minute
        for i in range(5):
            res = client.post(
                "/auth/register",
                json={
                    "organization_name": f"Rate Org {i}",
                    "name": f"User {i}",
                    "email": f"rateuser_{i}@example.com",
                    "password": "StrongPassword123!",
                },
            )
            assert res.status_code == 201

        # 6th attempt should be blocked
        res_blocked = client.post(
            "/auth/register",
            json={
                "organization_name": "Rate Org 6",
                "name": "User 6",
                "email": "rateuser_6@example.com",
                "password": "StrongPassword123!",
            },
        )
        assert res_blocked.status_code == 429
        assert "Rate limit exceeded" in res_blocked.json()["detail"]
    finally:
        limiter.reset()
        limiter.enabled = False


def test_rate_limiting_login(client: TestClient, account: dict[str, object]) -> None:
    limiter.enabled = True
    limiter.reset()
    try:
        # Login limit is 10/minute
        for _ in range(10):
            res = client.post(
                "/auth/login",
                json={
                    "email": "owner-one@example.com",
                    "password": "WrongPassword!",
                },
            )
            assert res.status_code == 401

        # 11th attempt returns 429
        res_blocked = client.post(
            "/auth/login",
            json={
                "email": "owner-one@example.com",
                "password": "StrongPassword123!",
            },
        )
        assert res_blocked.status_code == 429
        assert "Rate limit exceeded" in res_blocked.json()["detail"]
    finally:
        limiter.reset()
        limiter.enabled = False


def test_rate_limiting_can_be_disabled(client: TestClient) -> None:
    limiter.enabled = False
    limiter.reset()
    # When disabled, requests beyond 5 succeed
    for i in range(8):
        res = client.post(
            "/auth/register",
            json={
                "organization_name": f"Disabled Limiter Org {i}",
                "name": f"User {i}",
                "email": f"disabled_limiter_{i}@example.com",
                "password": "StrongPassword123!",
            },
        )
        assert res.status_code == 201


def test_rate_limiting_public_inbound(client: TestClient, account: dict[str, object]) -> None:
    org_id = str(account["user"]["organization_id"])
    limiter.enabled = True
    limiter.reset()
    try:
        with mock.patch("app.api.routes.public.get_settings") as mock_settings:
            settings_obj = mock.MagicMock()
            settings_obj.public_inbound_rate_limit = "3/minute"
            settings_obj.webhook_signature_required = False
            mock_settings.return_value = settings_obj

            for i in range(3):
                res = client.post(
                    f"/public/inbound/form/{org_id}",
                    json={
                        "name": f"Lead {i}",
                        "email": f"inbound_{i}@example.com",
                        "phone": f"+1512555010{i}",
                        "message": "AC quote needed",
                    },
                )
                assert res.status_code == 201

            res_blocked = client.post(
                f"/public/inbound/form/{org_id}",
                json={
                    "name": "Blocked Lead",
                    "email": "blocked@example.com",
                    "phone": "+15125550199",
                    "message": "AC quote needed",
                },
            )
            assert res_blocked.status_code == 429
            assert "Rate limit exceeded" in res_blocked.json()["detail"]
    finally:
        limiter.reset()
        limiter.enabled = False


def test_e164_phone_duplicate_matching(
    client: TestClient, account: dict[str, object], auth_headers: dict[str, str], db: Session
) -> None:
    org_id = str(account["user"]["organization_id"])
    # Configure organization default phone region
    client.patch(
        f"/organizations/{org_id}",
        json={"default_phone_region": "US"},
        headers=auth_headers,
    )

    # First inquiry with formatted US phone (512) 555-0100
    r1 = client.post(
        f"/public/inbound/form/{org_id}",
        json={
            "name": "Jane Doe",
            "phone": "(512) 555-0100",
            "message": "Furnace maintenance quote request",
        },
    )
    assert r1.status_code == 201
    lead_id_1 = r1.json()["lead_id"]

    lead_1 = db.get(Lead, uuid.UUID(lead_id_1))
    assert lead_1 is not None
    assert lead_1.customer_phone == "(512) 555-0100"
    assert lead_1.customer_phone_normalized == "+15125550100"

    # Second inquiry with international format +1 512 555 0100
    r2 = client.post(
        f"/public/inbound/form/{org_id}",
        json={
            "name": "Jane Doe",
            "phone": "+1 512 555 0100",
            "message": "Furnace maintenance quote follow-up",
        },
    )
    assert r2.status_code == 201
    assert r2.json()["lead_id"] == lead_id_1  # Attached to existing lead!

    # Third inquiry with dashed local format 512-555-0100
    r3 = client.post(
        f"/public/inbound/form/{org_id}",
        json={
            "name": "Jane Doe",
            "phone": "512-555-0100",
            "message": "Additional notes on furnace",
        },
    )
    assert r3.status_code == 201
    assert r3.json()["lead_id"] == lead_id_1  # Also attached!


def test_duplicate_matching_isolation_and_statuses(
    client: TestClient, account: dict[str, object], auth_headers: dict[str, str], db: Session
) -> None:
    org_a_id = str(account["user"]["organization_id"])
    org_b = register(client, "org-b")
    org_b_id = str(org_b["user"]["organization_id"])

    # Submit to Org A
    r_a = client.post(
        f"/public/inbound/form/{org_a_id}",
        json={
            "name": "Customer Shared",
            "phone": "+1 512 555 0199",
            "message": "Need help in Org A",
        },
    )
    assert r_a.status_code == 201
    lead_a_id = r_a.json()["lead_id"]

    # Submit identical phone to Org B -> Must create new lead in Org B (tenant isolation)
    r_b = client.post(
        f"/public/inbound/form/{org_b_id}",
        json={
            "name": "Customer Shared",
            "phone": "+1 512 555 0199",
            "message": "Need help in Org B",
        },
    )
    assert r_b.status_code == 201
    lead_b_id = r_b.json()["lead_id"]
    assert lead_a_id != lead_b_id

    # If lead in Org A is marked BOOKED, new inquiry creates a new lead
    lead_a = db.get(Lead, uuid.UUID(lead_a_id))
    lead_a.status = LeadStatus.BOOKED
    db.commit()

    r_a2 = client.post(
        f"/public/inbound/form/{org_a_id}",
        json={
            "name": "Customer Shared",
            "phone": "+1 512 555 0199",
            "message": "Need new service after booked job",
        },
    )
    assert r_a2.status_code == 201
    assert r_a2.json()["lead_id"] != lead_a_id


def test_expanded_lead_search(
    client: TestClient, account: dict[str, object], auth_headers: dict[str, str]
) -> None:
    org_id = str(account["user"]["organization_id"])

    # Create lead with detailed service, location, and product
    r = client.post(
        f"/public/inbound/form/{org_id}",
        json={
            "name": "Marcus Aurelius",
            "email": "marcus@rome.example.com",
            "phone": "+15125550777",
            "product_or_service": "Geothermal Heat Pump",
            "location": "Downtown Austin",
            "message": "Looking to service Carrier Infinity 24 system",
        },
    )
    assert r.status_code == 201

    # Search by category_or_service
    s1 = client.get("/leads?q=Geothermal", headers=auth_headers).json()
    assert len(s1["items"]) == 1
    assert s1["items"][0]["customer_name"] == "Marcus Aurelius"

    # Search by location
    s2 = client.get("/leads?q=Downtown Austin", headers=auth_headers).json()
    assert len(s2["items"]) == 1
    assert s2["items"][0]["customer_name"] == "Marcus Aurelius"

    # Search by message text / product mention
    s3 = client.get("/leads?q=Carrier Infinity", headers=auth_headers).json()
    assert len(s3["items"]) == 1
    assert s3["items"][0]["customer_name"] == "Marcus Aurelius"

    # Search by normalized phone digits
    s4 = client.get("/leads?q=5550777", headers=auth_headers).json()
    assert len(s4["items"]) == 1
    assert s4["items"][0]["customer_name"] == "Marcus Aurelius"

    # Search by customer name
    s5 = client.get("/leads?q=Marcus", headers=auth_headers).json()
    assert len(s5["items"]) == 1

    # Verify search scoping: Org B search for "Marcus" returns nothing
    org_b = register(client, "search-b")
    auth_b = {"Authorization": f"Bearer {org_b['access_token']}"}
    s_b = client.get("/leads?q=Marcus", headers=auth_b).json()
    assert len(s_b["items"]) == 0


def test_webhook_hmac_lifecycle(
    client: TestClient, account: dict[str, object], auth_headers: dict[str, str]
) -> None:
    org_id = str(account["user"]["organization_id"])

    payload = {
        "external_message_id": "ext-msg-101",
        "name": "Webhook Lead",
        "email": "webhook_lead@example.com",
        "phone": "+15125550888",
        "message": "Emergency AC fix",
    }
    raw_payload = json.dumps(payload).encode("utf-8")

    # 1. Unsigned request accepted when no secret is configured
    res_unsigned = client.post(
        f"/public/inbound/webhook/{org_id}",
        content=raw_payload,
        headers={"Content-Type": "application/json"},
    )
    assert res_unsigned.status_code == 201
    lead_id_1 = res_unsigned.json()["lead_id"]

    # 2. Rotate secret
    rot_res = client.post(
        f"/organizations/{org_id}/rotate-webhook-secret", headers=auth_headers
    )
    assert rot_res.status_code == 200
    secret = rot_res.json()["webhook_secret"]
    assert secret.startswith("whsec_")

    # Verify integration-info reflects secret configured
    info_res = client.get(f"/organizations/{org_id}/integration-info", headers=auth_headers)
    assert info_res.status_code == 200
    assert info_res.json()["webhook_secret_configured"] is True

    # 3. Missing signature rejected with 401
    res_missing_sig = client.post(
        f"/public/inbound/webhook/{org_id}",
        content=raw_payload,
        headers={"Content-Type": "application/json"},
    )
    assert res_missing_sig.status_code == 401
    assert "Missing X-Missed-Lead-Signature" in res_missing_sig.json()["detail"]

    # 4. Invalid signature rejected with 401
    res_bad_sig = client.post(
        f"/public/inbound/webhook/{org_id}",
        content=raw_payload,
        headers={
            "Content-Type": "application/json",
            "X-Missed-Lead-Signature": "sha256=0123456789abcdef",
        },
    )
    assert res_bad_sig.status_code == 401
    assert "Invalid webhook signature" in res_bad_sig.json()["detail"]

    # 5. Valid signature accepted with 201
    valid_sig = hmac.new(secret.encode("utf-8"), raw_payload, hashlib.sha256).hexdigest()
    res_valid = client.post(
        f"/public/inbound/webhook/{org_id}",
        content=raw_payload,
        headers={
            "Content-Type": "application/json",
            "X-Missed-Lead-Signature": f"sha256={valid_sig}",
        },
    )
    assert res_valid.status_code == 201
    # Idempotency: external_message_id attaches to lead_id_1
    assert res_valid.json()["lead_id"] == lead_id_1

    # 6. Verify embed form (/public/inbound/form) still succeeds without any signature
    res_form = client.post(
        f"/public/inbound/form/{org_id}",
        json={
            "name": "Public Form Lead",
            "email": "form_lead@example.com",
            "message": "Form inquiry",
        },
    )
    assert res_form.status_code == 201


def test_email_failure_does_not_abort_lead_creation(
    client: TestClient, account: dict[str, object], db: Session
) -> None:
    org_id = str(account["user"]["organization_id"])

    # Simulate email provider timeout or network crash
    with mock.patch("app.api.routes.public.get_email_provider") as mock_get_email:
        from app.services.email import ResendEmailProvider

        mock_provider = ResendEmailProvider(
            api_key="resend-secret-key",
            email_from="noreply@example.com",
            timeout=1.0,
        )
        mock_provider.send = mock.MagicMock(
            side_effect=RuntimeError("Resend HTTP 504 Gateway Timeout")
        )
        mock_get_email.return_value = mock_provider

        res = client.post(
            f"/public/inbound/form/{org_id}",
            json={
                "name": "Sarah Connor",
                "email": "sarah@cyberdyne.example.com",
                "phone": "+15125550999",
                "message": "AC replacement estimate",
            },
        )
        # HTTP request succeeds with 201
        assert res.status_code == 201
        lead_id = res.json()["lead_id"]

        # Lead was committed safely to database
        lead = db.get(Lead, uuid.UUID(lead_id))
        assert lead is not None
        assert lead.customer_name == "Sarah Connor"
        assert lead.customer_phone_normalized == "+15125550999"

        # ACKNOWLEDGEMENT_FAILED was recorded as an audit event
        events = db.query(LeadEvent).filter(LeadEvent.lead_id == lead.id).all()
        failure_event = next(
            (e for e in events if e.event_type == LeadEventType.ACKNOWLEDGEMENT_FAILED), None
        )
        assert failure_event is not None
        assert failure_event.event_metadata["channel"] == "EMAIL"
        assert failure_event.event_metadata["error_type"] == "RuntimeError"
