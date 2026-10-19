# Phase 2.5C — Background Jobs + Reminder Engine Foundation

**Date:** October 19, 2026  
**Status:** Complete  
**Objective:** Establish a resilient, database-backed background job claiming and reminder execution engine without manual API triggers, setting the foundation for omnichannel notifications in Phase 3.

---

## 1. Inspection of Existing Reminder Implementation

### 1.1 Existing Architecture
- **Model (`FollowUp`):**
  - Columns: `id`, `lead_id`, `organization_id`, `scheduled_for`, `status` (`PENDING`, `COMPLETED`, `CANCELLED`), `message`, `channel` (`EMAIL`, `INTERNAL`), `created_at`, `completed_at`.
  - Missing fields required for reliable job execution: `attempt_count`, `last_attempt_at`, `processed_at`, `failure_reason`, `conversation_id`, `type`, `updated_at`.
  - Enum lacks operational failure states: only `PENDING`, `COMPLETED`, `CANCELLED` (no `PROCESSING` or `FAILED`).
- **Follow-up Service (`FollowUpService`):**
  - Manages scheduling fixed intervals when leads are created (`followup_new_lead_minutes`, `followup_second_reminder_hours`, `followup_final_days`) or marked `CONTACTED`.
  - `process_due(organization_id, now)` queried `FollowUp.scheduled_for <= now` using simple uncommitted queries without row-level locking (`FOR UPDATE SKIP LOCKED`).
  - No cross-tenant batch sweep: `process_due` required an explicit `organization_id`.
- **Manual Dependency:**
  - Background jobs were never run automatically. They relied entirely on manual invocation of `POST /followups/process` per tenant or manual execution of `FollowUpSweepJob`.
- **Lead Events & Lifecycle:**
  - `LeadEvent` tracked `FOLLOWUP_SCHEDULED` and `FOLLOWUP_GENERATED`.
  - Missing explicit events for owner reminder lifecycle: `OWNER_REMINDER_SCHEDULED`, `OWNER_REMINDER_SENT`, `OWNER_REMINDER_CANCELLED`, `OWNER_REMINDER_FAILED`.
- **Conversations & Message Flow:**
  - Phase 2.5B introduced `Conversation` (`waiting_on`: `OWNER`, `CUSTOMER`, `SYSTEM`, `NONE`) and `ConversationMessage`.
  - However, inbound lead creation automatically generated a system email acknowledgement which set `waiting_on = WaitingOn.CUSTOMER` unconditionally, conflating automated system replies with actual owner responses.
  - No connection existed between conversation message exchange and reminder cancellation.

---

## 2. Selected Scheduler Approach

### 2.1 Technology Evaluation
- **APScheduler vs In-Process Asyncio Loop:**
  - APScheduler introduces external dependencies and thread-pool complexity that can interact unpredictably with asyncio and SQLite in-memory test harnesses.
  - A dedicated, lightweight in-process scheduler (`BackgroundReminderScheduler`) utilizing `asyncio.create_task` and the FastAPI `lifespan` context manager provides:
    - Zero additional external dependencies.
    - Deterministic startup and shutdown lifecycle hooks.
    - Clean test isolation (disabled via `BACKGROUND_JOBS_ENABLED=false`).
    - Configurable sweep intervals via `REMINDER_SWEEP_INTERVAL_SECONDS`.
    - Safe delegation of database operations to worker threads via `anyio.to_thread.run_sync`.

### 2.2 Core Architectural Principle: DB as Source of Truth
- The scheduler determines **WHEN** to sweep.
- PostgreSQL determines **WHAT** is due.
- No job state is kept in Python memory. If the server process crashes and restarts, due jobs remain intact in PostgreSQL.

---

## 3. Concurrency & Claiming Strategy

### 3.1 Two-Phase Transactional Claiming
To prevent duplicate execution and race conditions across multiple application instances or concurrent sweeps:
1. **Phase 1: Claiming Transaction (Short-lived)**
   - Query due reminders with row-level locks:
     ```sql
     SELECT * FROM followups
     WHERE (status = 'PENDING' AND due_at <= :now)
        OR (status = 'PROCESSING' AND last_attempt_at <= :stale_cutoff)
     ORDER BY due_at ASC
     LIMIT :batch_size
     FOR UPDATE SKIP LOCKED;
     ```
     *(In SQLite test environments, the query falls back to transactional status update without FOR UPDATE).*
   - Mark claimed rows as `status = 'PROCESSING'`, increment `attempt_count += 1`, and update `last_attempt_at = :now`.
   - Commit the claiming transaction immediately. Database locks are released before any notification or network I/O begins.

2. **Phase 2: Execution & Outcome Transaction**
   - For each claimed row:
     - Validate organization existence, lead state, and conversation state.
     - If lead is `BOOKED` or `LOST`, or conversation is closed: mark `CANCELLED`.
     - Perform notification action via `NotificationService`.
     - On success: mark `COMPLETED`, record `processed_at`, emit `OWNER_REMINDER_SENT`. If recurring owner reminder and `attempt_count < max_attempts`, schedule next reminder.
     - On failure: if `attempt_count < max_retries`, mark `PENDING` with retry delay (`now + retry_delay_seconds`); if max attempts exceeded, mark `FAILED` and emit `OWNER_REMINDER_FAILED`.

---

## 4. Failure & Crash Recovery Strategy

### 4.1 Bounded Retries
- Configurable settings:
  - `JOB_MAX_RETRIES`: Default 3.
  - `JOB_RETRY_DELAY_SECONDS`: Default 300 (5 minutes).
- Failures do not drop jobs silently. Transient errors reschedule the job for retry. Permanent exhaustion marks the job `FAILED` and records an auditable `LeadEvent`.

### 4.2 Crash & Stale Processing Recovery
- If a server worker crashes while a reminder is in `PROCESSING` state:
  - `JOB_PROCESSING_TIMEOUT_MINUTES`: Default 10.
  - The sweep query automatically reclaims any job that has remained in `PROCESSING` state for longer than the timeout window.

---

## 5. Domain & Reminder Model Enhancements

### 5.1 FollowUp Schema (Migration `20261016_0005`)
- Add `conversation_id`: Foreign key to `conversations.id` (nullable, ondelete `SET NULL`, indexed).
- Rename `scheduled_for` to `due_at` (with backward compatibility property).
- Add `type`: `FollowUpType` (`OWNER_RESPONSE_REMINDER`, `LEAD_FOLLOWUP`).
- Extend `FollowUpStatus` enum: `PENDING`, `PROCESSING`, `COMPLETED`, `CANCELLED`, `FAILED`.
- Add `attempt_count` (int, default 0).
- Add `last_attempt_at` (datetime, nullable).
- Add `processed_at` (datetime, nullable).
- Add `failure_reason` (text, nullable).
- Add `updated_at` (datetime, default utcnow).

### 5.2 Organization Settings
- `owner_reminder_delay_minutes`: Default 60.
- `owner_reminder_repeat_minutes`: Default 60.
- `owner_reminder_max_attempts`: Default 3.

---

## 6. Notification Abstraction Foundation

### 6.1 Domain Separation
- Reminder engine does not know about WhatsApp, Twilio, Meta, or SMS.
- `OwnerNotification` value object:
  - `organization_id`, `lead_id`, `conversation_id`, `type`, `title`, `body`, `metadata`.
- `OwnerNotificationProvider` interface:
  - Method: `send_owner_notification(notification: OwnerNotification) -> bool`.
- Initial provider:
  - `ConsoleOwnerNotificationProvider`: Logs structured notifications cleanly without leaking sensitive credentials.
- Future Phase 3 providers:
  - `WhatsAppOwnerNotificationProvider`, `EmailOwnerNotificationProvider`, `PushOwnerNotificationProvider` can be plugged in without changing reminder engine logic.

---

## 7. Future Scaling Strategy (Beyond Single-Process MVP)

For local development and single-instance deployment, the in-process FastAPI lifespan scheduler is simple and self-contained.

When the application scales horizontally to multiple API replicas:
```text
┌──────────────┐    ┌──────────────┐
│  API Node 1  │    │  API Node 2  │
└──────┬───────┘    └──────┬───────┘
       │                   │
       ▼                   ▼
┌──────────────────────────────────┐
│      PostgreSQL (Job Queue)      │
│     FOR UPDATE SKIP LOCKED       │
└────────────────┬─────────────────┘
                 ▲
       ┌─────────┴─────────┐
       │ Dedicated Worker  │
       │   Scheduler Pod   │
       └───────────────────┘
```
1. **Dedicated Worker / Scheduler Process:**
   - In production, set `BACKGROUND_JOBS_ENABLED=false` on API web workers.
   - Run a standalone worker process or cron container that executes sweeps.
2. **SKIP LOCKED Scalability:**
   - Because row claiming uses PostgreSQL `FOR UPDATE SKIP LOCKED`, multiple worker pods can query the same database concurrently without collision or double-processing.
3. **Optional Redis Queue:**
   - If sub-second execution latency or high-volume instant dispatch is required in later phases, an external queue (e.g. Celery / ARQ / Redis Streams) can be layered on top, while PostgreSQL retains business state.

---

## 8. Verification Results

- **Alembic Migrations:**
  - Forward migration `20261016_0004` -> `20261016_0005 (head)` applied cleanly.
  - Rollback `20261016_0005` -> `20261016_0004` downgraded cleanly.
  - Fresh base -> head: downgraded to base and re-applied all 5 migrations cleanly to head.
- **Backend Tests:**
  - 52/52 tests passed (`pytest`).
  - Baseline 38 Phase 2/2.5 tests passed with zero regressions.
  - Added 14 new comprehensive tests in `test_reminders.py` covering Scenarios A through J, crash recovery, conversation waiting_on, and API visibility.
- **Backend Linting:**
  - `ruff check .` passed with 0 errors.
- **Frontend Verification:**
  - `vitest`: 5/5 tests passed across 4 test suites.
  - `tsc --noEmit`: Clean, 0 type errors.
  - `eslint .`: Clean, 0 warnings/errors.
  - `next build`: Optimized production bundle built successfully.
