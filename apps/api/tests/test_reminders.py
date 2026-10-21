from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.jobs.scheduler import BackgroundReminderScheduler
from app.models.conversation import Conversation
from app.models.enums import (
    FollowUpChannel,
    FollowUpStatus,
    FollowUpType,
    LeadEventType,
    WaitingOn,
)
from app.models.followup import FollowUp
from app.models.lead import Lead
from app.models.lead_event import LeadEvent
from app.services.followup_processor import FollowUpProcessor
from app.services.notifications import (
    NotificationService,
    OwnerNotification,
    OwnerNotificationProvider,
)
from tests.conftest import register


class RecordingNotificationProvider(OwnerNotificationProvider):
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.sent_notifications: list[OwnerNotification] = []

    def send_owner_notification(self, notification: OwnerNotification) -> bool:
        if self.should_fail:
            raise RuntimeError("Provider connection timeout")
        self.sent_notifications.append(notification)
        return True


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def test_scheduler_config_and_lifecycle() -> None:
    settings = get_settings()
    assert settings.reminder_sweep_interval_seconds == 60
    assert settings.default_owner_reminder_delay_minutes == 60
    assert settings.default_owner_reminder_repeat_minutes == 60
    assert settings.default_owner_reminder_max_attempts == 3
    assert settings.job_max_retries == 3
    assert settings.job_processing_timeout_minutes == 10

    # Outside an active event loop, start gracefully logs warning and does not crash
    sched = BackgroundReminderScheduler(interval_seconds=1)
    assert not sched.is_running
    sched.start()
    assert not sched.is_running

    import asyncio

    async def _test_async():
        s = BackgroundReminderScheduler(interval_seconds=1)
        assert not s.is_running
        s.start()
        assert s.is_running
        # Multiple start calls are idempotent
        s.start()
        assert s.is_running
        await s.stop()
        assert not s.is_running

    asyncio.run(_test_async())


def test_scenario_a_customer_inbound_schedules_owner_reminder(
    client: TestClient, account: dict[str, object], db: Session
) -> None:
    org_id = str(account["user"]["organization_id"])
    now_before = datetime.now(UTC)

    res = client.post(
        f"/public/inbound/form/{org_id}",
        json={
            "name": "Sara Ahmed",
            "email": "sara@example.com",
            "phone": "+15125550199",
            "message": "Inquiry for black shalwar kameez, Medium",
        },
    )
    assert res.status_code == 201
    lead_id = uuid.UUID(res.json()["lead_id"])

    # Query followups for this lead
    reminders = list(
        db.scalars(
            select(FollowUp).where(
                FollowUp.lead_id == lead_id,
                FollowUp.type == FollowUpType.OWNER_RESPONSE_REMINDER,
            )
        )
    )
    assert len(reminders) == 1
    rem = reminders[0]
    assert rem.status == FollowUpStatus.PENDING
    assert rem.attempt_count == 0
    assert rem.channel == FollowUpChannel.INTERNAL
    assert rem.conversation_id is not None
    # Scheduled for ~60 minutes from now
    expected_due = now_before + timedelta(minutes=60)
    assert abs((to_utc(rem.due_at) - expected_due).total_seconds()) < 60

    # Verify audit event
    events = list(
        db.scalars(
            select(LeadEvent).where(
                LeadEvent.lead_id == lead_id,
                LeadEvent.event_type == LeadEventType.OWNER_REMINDER_SCHEDULED,
            )
        )
    )
    assert len(events) >= 1


def test_scenario_b_processor_due_notification_and_recurring(
    client: TestClient, account: dict[str, object], db: Session
) -> None:
    org_id = str(account["user"]["organization_id"])

    client.post(
        f"/public/inbound/form/{org_id}",
        json={
            "name": "Sara Ahmed",
            "email": "sara.b@example.com",
            "phone": "+15125550198",
            "message": "Black shalwar kameez, Medium",
        },
    )

    rem = db.scalar(
        select(FollowUp).where(
            FollowUp.organization_id == uuid.UUID(org_id),
            FollowUp.type == FollowUpType.OWNER_RESPONSE_REMINDER,
            FollowUp.status == FollowUpStatus.PENDING,
        )
    )
    assert rem is not None

    # Advance time: set reminder to be due 5 minutes in the past
    now = datetime.now(UTC)
    rem.due_at = now - timedelta(minutes=5)
    db.commit()

    provider = RecordingNotificationProvider()
    notif_service = NotificationService(provider=provider)
    processor = FollowUpProcessor(db, notifications=notif_service)

    processed_count = processor.process_due(now=now)
    # At least our owner reminder is processed
    assert processed_count >= 1
    assert len(provider.sent_notifications) == 1

    notification = provider.sent_notifications[0]
    assert notification.organization_id == uuid.UUID(org_id)
    assert "Sara Ahmed" in notification.title
    assert "Sara Ahmed" in notification.body
    assert "Black shalwar kameez" in notification.body

    # Verify original reminder is COMPLETED
    db.refresh(rem)
    assert rem.status == FollowUpStatus.COMPLETED
    assert rem.processed_at is not None

    # Verify OWNER_REMINDER_SENT event recorded
    sent_event = db.scalar(
        select(LeadEvent).where(
            LeadEvent.lead_id == rem.lead_id,
            LeadEvent.event_type == LeadEventType.OWNER_REMINDER_SENT,
        )
    )
    assert sent_event is not None

    # Verify recurring reminder #2 was scheduled (attempt 1 < max 3)
    pending_reminders = list(
        db.scalars(
            select(FollowUp).where(
                FollowUp.lead_id == rem.lead_id,
                FollowUp.type == FollowUpType.OWNER_RESPONSE_REMINDER,
                FollowUp.status == FollowUpStatus.PENDING,
            )
        )
    )
    assert len(pending_reminders) == 1
    recurring_rem = pending_reminders[0]
    assert recurring_rem.attempt_count == 1
    assert to_utc(recurring_rem.due_at) >= now + timedelta(minutes=59)


def test_scenario_c_owner_responds_cancels_reminder(
    client: TestClient, account: dict[str, object], auth_headers: dict[str, str], db: Session
) -> None:
    org_id = str(account["user"]["organization_id"])

    res = client.post(
        f"/public/inbound/form/{org_id}",
        json={
            "name": "Bilal Khan",
            "email": "bilal@example.com",
            "message": "Wedding booking inquiry",
        },
    )
    lead_id = uuid.UUID(res.json()["lead_id"])
    lead = db.get(Lead, lead_id)
    assert lead is not None and lead.primary_conversation_id is not None

    # Owner responds via authenticated message endpoint
    reply_res = client.post(
        f"/conversations/{lead.primary_conversation_id}/messages",
        headers=auth_headers,
        json={"body": "Hello Bilal, I am reviewing your request right now!"},
    )
    assert reply_res.status_code == 201

    # Verify reminder is CANCELLED
    rem = db.scalar(
        select(FollowUp).where(
            FollowUp.lead_id == lead_id,
            FollowUp.type == FollowUpType.OWNER_RESPONSE_REMINDER,
        )
    )
    assert rem is not None
    assert rem.status == FollowUpStatus.CANCELLED
    assert rem.failure_reason == "Owner replied"

    # Verify conversation waiting_on changed to CUSTOMER
    conv = db.get(Conversation, lead.primary_conversation_id)
    assert conv is not None
    assert conv.waiting_on == WaitingOn.CUSTOMER

    # Running processor generates NO notification
    provider = RecordingNotificationProvider()
    processor = FollowUpProcessor(db, notifications=NotificationService(provider=provider))
    processor.process_due(now=datetime.now(UTC) + timedelta(hours=2))
    assert len(provider.sent_notifications) == 0


def test_scenario_d_lead_booked_cancels_reminder(
    client: TestClient, account: dict[str, object], auth_headers: dict[str, str], db: Session
) -> None:
    org_id = str(account["user"]["organization_id"])
    res = client.post(
        f"/public/inbound/form/{org_id}",
        json={"name": "Booked Customer", "email": "booked@example.com", "message": "Ready to book"},
    )
    lead_id = res.json()["lead_id"]

    # Change status to BOOKED
    status_res = client.post(
        f"/leads/{lead_id}/status",
        headers=auth_headers,
        json={"status": "BOOKED"},
    )
    assert status_res.status_code == 200

    # Verify all pending followups cancelled
    pending = list(
        db.scalars(
            select(FollowUp).where(
                FollowUp.lead_id == uuid.UUID(lead_id),
                FollowUp.status == FollowUpStatus.PENDING,
            )
        )
    )
    assert len(pending) == 0


def test_scenario_e_lead_lost_cancels_reminder(
    client: TestClient, account: dict[str, object], auth_headers: dict[str, str], db: Session
) -> None:
    org_id = str(account["user"]["organization_id"])
    res = client.post(
        f"/public/inbound/form/{org_id}",
        json={"name": "Lost Customer", "email": "lost@example.com", "message": "Nevermind"},
    )
    lead_id = res.json()["lead_id"]

    # Change status to LOST
    status_res = client.post(
        f"/leads/{lead_id}/status",
        headers=auth_headers,
        json={"status": "LOST"},
    )
    assert status_res.status_code == 200

    pending = list(
        db.scalars(
            select(FollowUp).where(
                FollowUp.lead_id == uuid.UUID(lead_id),
                FollowUp.status == FollowUpStatus.PENDING,
            )
        )
    )
    assert len(pending) == 0


def test_scenario_f_customer_second_inbound_reschedules_single_reminder(
    client: TestClient, account: dict[str, object], db: Session
) -> None:
    org_id = str(account["user"]["organization_id"])
    phone = "+15125550777"

    # Message 1
    r1 = client.post(
        f"/public/inbound/form/{org_id}",
        json={"name": "Ali", "phone": phone, "message": "First message"},
    )
    assert r1.status_code == 201

    reminders_1 = list(
        db.scalars(
            select(FollowUp).where(
                FollowUp.organization_id == uuid.UUID(org_id),
                FollowUp.type == FollowUpType.OWNER_RESPONSE_REMINDER,
                FollowUp.status == FollowUpStatus.PENDING,
            )
        )
    )
    assert len(reminders_1) == 1
    rem1_id = reminders_1[0].id
    rem1_due = reminders_1[0].due_at

    # Message 2 from same customer within duplicate window
    r2 = client.post(
        f"/public/inbound/form/{org_id}",
        json={"name": "Ali", "phone": phone, "message": "Second message adding details"},
    )
    assert r2.status_code == 201

    # Must still have at most ONE pending OWNER_RESPONSE_REMINDER
    reminders_2 = list(
        db.scalars(
            select(FollowUp).where(
                FollowUp.organization_id == uuid.UUID(org_id),
                FollowUp.type == FollowUpType.OWNER_RESPONSE_REMINDER,
                FollowUp.status == FollowUpStatus.PENDING,
            )
        )
    )
    assert len(reminders_2) == 1
    assert reminders_2[0].id == rem1_id
    # Due date was refreshed/rescheduled
    assert to_utc(reminders_2[0].due_at) >= to_utc(rem1_due)


def test_scenario_g_notification_failure_triggers_retry(
    client: TestClient, account: dict[str, object], db: Session
) -> None:
    org_id = str(account["user"]["organization_id"])

    client.post(
        f"/public/inbound/form/{org_id}",
        json={"name": "Tariq", "email": "tariq@example.com", "message": "Need AC urgent"},
    )

    rem = db.scalar(
        select(FollowUp).where(
            FollowUp.organization_id == uuid.UUID(org_id),
            FollowUp.type == FollowUpType.OWNER_RESPONSE_REMINDER,
            FollowUp.status == FollowUpStatus.PENDING,
        )
    )
    assert rem is not None
    rem.due_at = datetime.now(UTC) - timedelta(minutes=5)
    db.commit()

    failing_provider = RecordingNotificationProvider(should_fail=True)
    processor = FollowUpProcessor(db, notifications=NotificationService(provider=failing_provider))
    processor.process_due(now=datetime.now(UTC))

    db.refresh(rem)
    # Reminder is reset to PENDING with retry delay
    assert rem.status == FollowUpStatus.PENDING
    assert rem.attempt_count == 1
    assert "Provider connection timeout" in (rem.failure_reason or "")
    assert to_utc(rem.due_at) > datetime.now(UTC)


def test_scenario_h_max_retries_reached_marks_failed(
    client: TestClient, account: dict[str, object], db: Session
) -> None:
    org_id = str(account["user"]["organization_id"])

    client.post(
        f"/public/inbound/form/{org_id}",
        json={"name": "Hamza", "email": "hamza@example.com", "message": "Inquiry"},
    )

    rem = db.scalar(
        select(FollowUp).where(
            FollowUp.organization_id == uuid.UUID(org_id),
            FollowUp.type == FollowUpType.OWNER_RESPONSE_REMINDER,
            FollowUp.status == FollowUpStatus.PENDING,
        )
    )
    assert rem is not None
    # Simulate already at attempt 2 (next claim will make it 3 = max retries)
    rem.attempt_count = 2
    rem.due_at = datetime.now(UTC) - timedelta(minutes=5)
    db.commit()

    failing_provider = RecordingNotificationProvider(should_fail=True)
    processor = FollowUpProcessor(db, notifications=NotificationService(provider=failing_provider))
    processor.process_due(now=datetime.now(UTC))

    db.refresh(rem)
    assert rem.status == FollowUpStatus.FAILED
    assert rem.attempt_count == 3
    assert "Provider connection timeout" in (rem.failure_reason or "")

    failed_event = db.scalar(
        select(LeadEvent).where(
            LeadEvent.lead_id == rem.lead_id,
            LeadEvent.event_type == LeadEventType.OWNER_REMINDER_FAILED,
        )
    )
    assert failed_event is not None


def test_scenario_i_idempotency_processor_called_twice(
    client: TestClient, account: dict[str, object], db: Session
) -> None:
    org_id = str(account["user"]["organization_id"])

    client.post(
        f"/public/inbound/form/{org_id}",
        json={
            "name": "Idempotent User",
            "email": "idem@example.com",
            "message": "Check idempotent",
        },
    )

    rem = db.scalar(
        select(FollowUp).where(
            FollowUp.organization_id == uuid.UUID(org_id),
            FollowUp.type == FollowUpType.OWNER_RESPONSE_REMINDER,
            FollowUp.status == FollowUpStatus.PENDING,
        )
    )
    assert rem is not None
    rem.due_at = datetime.now(UTC) - timedelta(minutes=5)
    db.commit()

    provider = RecordingNotificationProvider()
    processor = FollowUpProcessor(db, notifications=NotificationService(provider=provider))

    # First execution
    c1 = processor.process_due(now=datetime.now(UTC))
    assert c1 >= 1
    assert len(provider.sent_notifications) == 1

    # Second execution immediately
    c2 = processor.process_due(now=datetime.now(UTC))
    assert c2 == 0
    # Still only 1 notification sent!
    assert len(provider.sent_notifications) == 1


def test_scenario_j_two_organizations_no_cross_tenant_effects(
    client: TestClient, account: dict[str, object], db: Session
) -> None:
    org_a_id = str(account["user"]["organization_id"])
    org_b = register(client, "org-b-tenant")
    org_b_id = str(org_b["user"]["organization_id"])

    # Inbound for A
    client.post(
        f"/public/inbound/form/{org_a_id}",
        json={"name": "Customer A", "email": "a@example.com", "message": "Inquiry A"},
    )
    # Inbound for B
    client.post(
        f"/public/inbound/form/{org_b_id}",
        json={"name": "Customer B", "email": "b@example.com", "message": "Inquiry B"},
    )

    # Make both due
    now = datetime.now(UTC)
    for rem in db.scalars(select(FollowUp)).all():
        rem.due_at = now - timedelta(minutes=10)
    db.commit()

    provider = RecordingNotificationProvider()
    processor = FollowUpProcessor(db, notifications=NotificationService(provider=provider))

    # Process ONLY Org A
    count_a = processor.process_due(organization_id=uuid.UUID(org_a_id), now=now)
    assert count_a >= 1

    # All sent notifications are for Org A
    for notif in provider.sent_notifications:
        assert str(notif.organization_id) == org_a_id

    # Org B reminder is untouched and still PENDING
    rem_b = db.scalar(
        select(FollowUp).where(
            FollowUp.organization_id == uuid.UUID(org_b_id),
            FollowUp.type == FollowUpType.OWNER_RESPONSE_REMINDER,
        )
    )
    assert rem_b is not None
    assert rem_b.status == FollowUpStatus.PENDING


def test_crash_recovery_stale_processing_reclaimed(
    client: TestClient, account: dict[str, object], db: Session
) -> None:
    org_id = str(account["user"]["organization_id"])

    client.post(
        f"/public/inbound/form/{org_id}",
        json={"name": "Crash Recovery", "email": "crash@example.com", "message": "Crash test"},
    )

    rem = db.scalar(
        select(FollowUp).where(
            FollowUp.organization_id == uuid.UUID(org_id),
            FollowUp.type == FollowUpType.OWNER_RESPONSE_REMINDER,
        )
    )
    assert rem is not None
    now = datetime.now(UTC)
    # Simulate crashed job stuck in PROCESSING from 15 minutes ago
    rem.status = FollowUpStatus.PROCESSING
    rem.last_attempt_at = now - timedelta(minutes=15)
    rem.attempt_count = 1
    db.commit()

    provider = RecordingNotificationProvider()
    processor = FollowUpProcessor(db, notifications=NotificationService(provider=provider))
    processed = processor.process_due(now=now)
    assert processed >= 1
    assert len(provider.sent_notifications) == 1

    db.refresh(rem)
    assert rem.status == FollowUpStatus.COMPLETED


def test_conversation_waiting_on_and_system_acknowledgement(
    client: TestClient, account: dict[str, object], auth_headers: dict[str, str], db: Session
) -> None:
    org_id = str(account["user"]["organization_id"])

    # 1. Customer inbound message -> waiting_on = OWNER
    res = client.post(
        f"/public/inbound/form/{org_id}",
        json={
            "name": "Zainab",
            "email": "zainab@example.com",
            "message": "Custom tailoring price quote",
        },
    )
    assert res.status_code == 201
    lead_id = uuid.UUID(res.json()["lead_id"])
    lead = db.get(Lead, lead_id)
    assert lead is not None
    conv = db.get(Conversation, lead.primary_conversation_id)
    assert conv is not None

    # Owner reminder must remain active after system email acknowledgement
    rem = db.scalar(
        select(FollowUp).where(
            FollowUp.lead_id == lead_id,
            FollowUp.type == FollowUpType.OWNER_RESPONSE_REMINDER,
        )
    )
    assert rem is not None
    assert rem.status == FollowUpStatus.PENDING

    # 2. Owner outbound message -> waiting_on = CUSTOMER and reminder cancelled
    client.post(
        f"/conversations/{conv.id}/messages",
        headers=auth_headers,
        json={"body": "Hello Zainab, the custom tailoring price is $150."},
    )

    db.refresh(conv)
    assert conv.waiting_on == WaitingOn.CUSTOMER
    db.refresh(rem)
    assert rem.status == FollowUpStatus.CANCELLED


def test_followups_api_visibility_and_manual_process(
    client: TestClient, account: dict[str, object], auth_headers: dict[str, str], db: Session
) -> None:
    org_id = str(account["user"]["organization_id"])

    # Create inbound lead
    client.post(
        f"/public/inbound/form/{org_id}",
        json={"name": "Visibility User", "email": "vis@example.com", "message": "Check api list"},
    )

    # 1. GET /followups
    list_res = client.get("/followups", headers=auth_headers)
    assert list_res.status_code == 200
    data = list_res.json()
    assert data["total"] >= 1
    assert any(item["type"] == "OWNER_RESPONSE_REMINDER" for item in data["items"])

    # Filter by type
    filter_type_res = client.get("/followups?type=OWNER_RESPONSE_REMINDER", headers=auth_headers)
    assert filter_type_res.status_code == 200
    items = filter_type_res.json()["items"]
    assert all(item["type"] == "OWNER_RESPONSE_REMINDER" for item in items)

    # Filter by status
    filter_status_res = client.get("/followups?status=PENDING", headers=auth_headers)
    assert filter_status_res.status_code == 200
    assert all(item["status"] == "PENDING" for item in filter_status_res.json()["items"])

    # 2. POST /followups/process (manual endpoint)
    process_res = client.post("/followups/process", headers=auth_headers)
    assert process_res.status_code == 200
    assert "processed" in process_res.json()
