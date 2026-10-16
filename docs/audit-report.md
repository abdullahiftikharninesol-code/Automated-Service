# Missed Lead Rescue — Comprehensive System Audit Report

**Date:** October 15, 2026  
**Auditor Roles:** Senior Software Architect, QA Lead, Security Reviewer, Product Auditor  
**Repository:** `missed-lead-rescue`  
**Target Milestone:** Post-Phase 2 Verification & Pre-Phase 3 Readiness  

---

# 1. Executive Summary

### Overall Status: **YELLOW**

The `missed-lead-rescue` codebase possesses a clean, well-architected core. The domain boundaries between HTTP controllers, Pydantic contracts, service workflows, repositories, and SQLAlchemy models are properly separated. Multi-tenancy isolation is enforced consistently across all lead, event, message, and organization endpoints. The database migration chain runs idempotently from scratch on PostgreSQL, seed data loads without errors, and automated suites (22 backend pytest tests, 4 frontend vitest test suites with 5 tests, Ruff linting, ESLint, TypeScript typecheck, and Next.js 16 production build) pass with zero errors.

However, the system is rated **YELLOW** rather than GREEN due to several critical operational, security, and architectural gaps that must be resolved before proceeding into Phase 3 (omnichannel integrations such as WhatsApp, telephony, and bidirectional messaging):

1. **Security & Abuse Risks on Public Ingestion:** Public webhook and form endpoints (`/public/inbound/webhook/{org_id}`, `/public/inbound/form/{org_id}`, `/public/inquiries/{org_id}`) lack rate limiting, webhook secret/HMAC verification, and abuse protection. Anyone with an organization's public UUID can spam the endpoint, consuming database storage, exhausting third-party AI tokens (OpenAI), and triggering unthrottled outbound emails.
2. **Fragile Phone Deduplication:** Inbound duplicate matching uses exact string equality for phone numbers without E.164 normalization. A customer providing `+1 (555) 010-1234` on a web form and `5550101234` on a webhook fails duplicate matching, fragmenting customer inquiry history.
3. **Absence of Customer & Conversation Entities:** Customer contact details are duplicated across both `InboundMessage` and `Lead`. There is no `Customer` entity to consolidate customer history over time, and no `Conversation` entity to manage bidirectional, multi-message threads.
4. **Synchronous Email Dispatch:** The email abstraction sends outbound messages synchronously within the HTTP request cycle using Python's standard `urlopen` (with a 15-second blocking timeout). There is no transactional outbox or retry mechanism.
5. **In-Memory Dashboard Scaling Bottleneck:** The dashboard API loads all leads for an organization into application memory to calculate status counts and evaluate deadlines in Python, which will degrade severely as lead volume grows.

Addressing the targeted P0 and P1 issues will make the codebase an exceptionally resilient foundation for Phase 3.

---

# 2. What Works

The following features have been verified via direct automated testing, database inspection, and API execution:

### 2.1 Authentication & Tenancy
- **Organization & Owner Registration:** Atomic creation of `Organization` and `User` (role `OWNER`) in a single database transaction (`POST /auth/register`).
- **Password Hashing:** Passwords hashed with Argon2 via `pwdlib`. Plaintext passwords are never logged or stored.
- **JWT Issuance & Authentication:** Signed HMAC-SHA256 tokens issued on login (`POST /auth/login`), verified via HTTP Bearer scheme on protected endpoints (`GET /auth/me`).
- **Multi-Tenant Isolation:** Complete tenant scoping verified across all resources:
  - Organization A cannot read, modify, or list Organization B's leads (`404 Not Found`).
  - Organization A cannot view or update Organization B's settings or integration information (`404 Not Found`).
  - Organization A cannot view Organization B's lead events or inbound messages (`404 Not Found`).

### 2.2 Inbound Message Pipeline
- **Channel Adapters:** Normalized ingestion for `WEBSITE_FORM`, `WEBSITE_WEBHOOK`, and `MANUAL` entry into a shared `InboundMessageCreate` schema.
- **Raw Message Persistence:** Every incoming submission is persisted in `inbound_messages` before business processing, recording channel, external ID, contact details, raw text, and arbitrary JSON metadata.
- **AI Extraction Abstraction:** Standardized `LeadExtractionResult` protocol implemented with deterministic `MockAIProvider` and `OpenAIProvider` using OpenAI Responses API (`client.responses.parse`).
- **Event Audit Trail:** Every lifecycle step generates an immutable `LeadEvent` (`INBOUND_MESSAGE_RECEIVED`, `LEAD_CREATED`, `LEAD_ENRICHED`, `AI_PROCESSED`, `ACKNOWLEDGEMENT_GENERATED`, `ACKNOWLEDGEMENT_SENT`, `ACKNOWLEDGEMENT_FAILED`, `FOLLOWUP_SCHEDULED`, `STATUS_CHANGED`, `NOTE_ADDED`).

### 2.3 Duplicate Handling & Deduplication
- **External Message ID Idempotency:** Submitting an inbound webhook with the same `(organization_id, channel, external_message_id)` returns the existing lead and preserves message history without storing duplicate records.
- **Sliding Duplicate Window:** Inbound messages matching an open lead (`NEW` or `CONTACTED`) within the organization's configurable duplicate window attach to the existing lead, enrich missing fields, update urgency if higher, and record a `LEAD_ENRICHED` event.
- **Terminal State Isolation:** When a lead is `BOOKED` or `LOST`, subsequent inquiries from the same customer cleanly generate a new `Lead`, leaving closed records untouched.
- **Cross-Tenant Customer Isolation:** The same customer submitting inquiries to two different organizations creates completely separate leads in each tenant.

### 2.4 Follow-Up Cadence & Status Engine
- **Cadence Scheduling:** Creates actionable reminders in `followups` table according to organization settings (`followup_new_lead_minutes`, `followup_second_reminder_hours`, `followup_final_days`).
- **Terminal State Cancellation:** Changing lead status to `BOOKED` or `LOST` cancels all pending reminders in the database and clears `next_followup_at`.
- **Contacted Transition:** Marking status as `CONTACTED` cancels initial intake reminders and schedules contacted-specific follow-ups.
- **Reopening:** Moving a lead from `LOST` back to `NEW` clears `lost_at` and recalculates a fresh follow-up schedule.
- **Deterministic Processor:** `FollowUpSweepJob` queries due reminders, marks them `COMPLETED`, logs timeline events, and advances `lead.next_followup_at`.

### 2.5 Email Delivery & Resilience
- **Email Abstraction:** `EmailProvider` protocol supports `ConsoleEmailProvider` (default in dev) and `ResendEmailProvider`.
- **Fault-Tolerant Acknowledgment:** When email delivery fails or provider is unconfigured, lead creation does not fail. The error is caught, logged, and recorded on the lead timeline as `ACKNOWLEDGEMENT_FAILED`.

### 2.6 Web Application
- **Next.js 16 UI:** Responsive App Router layout with dashboard metrics, attention list, lead filtering/search, lead details with timeline and message history, manual lead capture, settings, public inquiry page, and embed form.
- **Zero Compilation/Type Errors:** Vitest tests pass (5/5), ESLint passes, TypeScript passes (`tsc --noEmit`), and production build compiles cleanly.

---

# 3. What Is Partially Working

### 3.1 Generic Multi-Business Support
- **Status:** Partially implemented.
- **Details:** The data layer supports generic attributes (`intent`, `category_or_service`, `product_name`, `product_variant`, `quantity`, `business_type`). However:
  - The deterministic `MockAIProvider` relies on a Western clothing regex pattern (`dress|shirt|jacket|shoes|bag|jeans|trousers|skirt|top`), completely missing items such as `"black shalwar kameez"`.
  - The status lifecycle remains strictly hardcoded to `NEW`, `CONTACTED`, `BOOKED`, `LOST`. Non-service industries (e.g. Clothing retail: `NEW -> CONFIRMED -> DISPATCHED -> DELIVERED`) cannot customize their state pipeline without modifying core database enums and status service transition logic.

### 3.2 Follow-Up Engine Triggering
- **Status:** Partially implemented.
- **Details:** The follow-up logic and sweep job exist and work deterministically. However, execution is purely on-demand via `POST /followups/process`. There is no automated background daemon, APScheduler, Celery, or cron runner. Furthermore, the endpoint is scoped exclusively to the currently authenticated user's organization; there is no system-level maintenance runner to sweep due follow-ups across all tenants.

### 3.3 Outbound Email Integration
- **Status:** Partially implemented.
- **Details:** `ResendEmailProvider` exists and constructs valid JSON payloads to `https://api.resend.com/emails`. However, it issues synchronous blocking calls using standard Python `urlopen` inside the HTTP request loop. If Resend experiences latency, client requests hang for up to 15 seconds. There is no background worker, transactional outbox, or retry mechanism for failed deliveries.

### 3.4 Search & Filtering
- **Status:** Partially implemented.
- **Details:** `LeadRepository.list` supports filtering by `status`, `urgency`, `source`, and text search. However, the search filter only inspects `customer_name`, `customer_email`, `customer_phone`, and `service_type`. It does not search `product_name`, `category_or_service`, `location`, or message content, meaning searches for products or modern generic categories fail.

---

# 4. What Is Broken

### 4.1 Phone Number Normalization in Duplicate Matching
- **Severity:** HIGH
- **Reproduction Steps:**
  1. Submit a webhook for an organization:
     `POST /public/inbound/webhook/{org_id}` with `phone: "+1 (555) 010-1234"` and `name: "Alex"`.
  2. Within 5 minutes, submit a second webhook:
     `POST /public/inbound/webhook/{org_id}` with `phone: "5550101234"` and `name: "Alex"`.
  3. Query `GET /leads`.
- **Observed Behavior:** Two separate leads are created for the same customer within the duplicate window.
- **Root Cause:** In `apps/api/app/services/inbound.py` line 157:
  `contact_filters.append(InboundMessage.customer_phone == message.customer_phone)`
  Exact string equality is evaluated against raw user input without stripping formatting characters or converting to E.164.

### 4.2 Lead Repository Search Omits Generic Fields
- **Severity:** MEDIUM
- **Reproduction Steps:**
  1. Submit a lead with product name `"black dress"` or category `"Dental Cleaning"`.
  2. Call `GET /leads?search=dress` or `GET /leads?search=Dental`.
- **Observed Behavior:** Returns 0 items, despite the lead existing in the database.
- **Root Cause:** `apps/api/app/repositories/leads.py` lines 38–44:
  ```python
  filters.append(
      or_(
          Lead.customer_name.ilike(term),
          Lead.customer_email.ilike(term),
          Lead.customer_phone.ilike(term),
          Lead.service_type.ilike(term),
      )
  )
  ```
  `Lead.product_name` and `Lead.category_or_service` are not queried.

### 4.3 In-Memory Aggregation on Dashboard
- **Severity:** MEDIUM
- **Reproduction Steps:**
  1. In an organization with 10,000 leads, load `GET /dashboard`.
- **Observed Behavior:** The endpoint loads all 10,000 lead rows into memory (`leads = list(self.db.scalars(...))`) and iterates over them in Python to calculate card counts and attention status.
- **Root Cause:** `apps/api/app/services/dashboard.py` lines 17–47 lacks SQL `COUNT()` aggregations and indexed SQL filtering.

---

# 5. What Is Missing

Comparing the current implementation to the long-term omnichannel platform vision:

| Feature / Capability | Status in Codebase | Description & Impact |
| :--- | :--- | :--- |
| **Customer Entity** | **MISSING** | No `customers` table. Name, phone, and email are stored ephemerally on leads and messages. Historical customer lifetime value and cross-inquiry context are impossible. |
| **Conversation Entity** | **MISSING** | No `conversations` or `messages` thread model. `InboundMessage` is strictly one-way and linked to leads. Outbound messages cannot be represented as chat messages. |
| **Outbound Two-Way Messaging** | **MISSING** | Dashboard allows generating AI follow-up drafts, but has no "Send" action, no SMS sending, no email reply sending, and no chat interface. |
| **Real-Time Owner Alerts** | **MISSING** | When a high-urgency or emergency lead arrives, the owner is not notified via SMS, push notification, email, or webhook. Alerts only appear if the owner manually loads the dashboard. |
| **Automated Missing-Info Collection** | **MISSING** | The AI identifies missing fields, but cannot automatically message the customer to request missing details (e.g. "What size do you need?" or "What is your address?"). |
| **Status-Driven Customer Notifications** | **MISSING** | Lead status changes trigger internal follow-up cancellations, but never send status updates to customers (e.g. appointment confirmed, order dispatched). |
| **Omnichannel Connectors** | **MISSING** | WhatsApp Cloud API, Twilio Voice/SMS, Inbound Email Parser (SendGrid/Postmark/Resend), and Instagram/Facebook Graph APIs do not exist. Only enum placeholders exist. |
| **Background Scheduler / Daemon** | **MISSING** | No scheduled cron runner for follow-up sweep jobs. Follow-ups only advance when an authenticated client manually triggers `POST /followups/process`. |
| **Transactional Outbox for Email** | **MISSING** | Email sending is executed directly within the HTTP request. If email fails or DB commit fails, inconsistency occurs. |

---

# 6. Architecture Review

### Current Architecture Summary

The repository follows a clean layered design:
```text
Customer / Channel Adapter
         │
         ▼
apps/api/app/api/routes/public.py
         │
         ▼
apps/api/app/services/inbound.py  ──►  apps/api/app/ai/ (Mock / OpenAI)
         │                         ──►  apps/api/app/services/email.py (Console / Resend)
         │                         ──►  apps/api/app/services/followups.py
         ▼
PostgreSQL (SQLAlchemy 2.x ORM / Alembic)
         ▲
         │
apps/api/app/api/routes/ (auth, dashboard, leads, organizations, followups)
         ▲
         │
apps/web (Next.js 16 App Router UI)
```

### Architectural Strengths
1. **Strict Tenant Separation:** Tenant isolation is enforced at the database query level via `LeadRepository.get(lead_id, organization_id)` and dependency injection `CurrentOrganization`. No cross-tenant data leaks were identified.
2. **Normalized Inbound Ingestion:** All channels (form, webhook, manual) normalize into a single internal contract (`InboundMessageCreate`) before processing.
3. **Resilient Failure Boundaries:** Inbound message capture and lead creation are decoupled from third-party email provider health.
4. **Strong Typing & Contracts:** Pydantic schemas validate all API inputs and outputs; TypeScript types in the frontend mirror backend responses accurately.

### Architectural Risks & Limitations Before Extension
- **Extending Without `Customer` & `Conversation` Models Will Create Technical Debt:** If Phase 3 attempts to attach WhatsApp or SMS directly to `Lead`, the platform will become permanently trapped in a lead-centric model rather than an omnichannel customer-conversation model.
- **Synchronous External Calls:** External HTTP calls (OpenAI, Resend) are made synchronously inside request handlers, making the API vulnerable to worker exhaustion under load.

---

# 7. Security Findings

| Severity | Issue | Location | Impact | Recommended Fix |
| :--- | :--- | :--- | :--- | :--- |
| **HIGH** | **Unauthenticated Public Inbound Abuse & Token Exhaustion** | `apps/api/app/api/routes/public.py` | Anyone possessing an organization UUID can flood `/public/inbound/webhook/{org_id}` and `/public/inbound/form/{org_id}`, creating massive DB rows, exhausting OpenAI API credits, and sending spam emails. | Implement rate limiting (e.g. `slowapi` or Redis token bucket) and support optional webhook HMAC secret keys (`X-Signature` or `?token=`). |
| **HIGH** | **No Rate Limiting on Authentication Endpoints** | `apps/api/app/api/routes/auth.py` | `/auth/login` and `/auth/register` are unprotected against credential stuffing, brute force, and automated tenant creation. | Add IP-based and username-based rate limiting on all auth routes. |
| **MEDIUM** | **Tokens Stored in `localStorage`** | `apps/web/lib/api.ts` | JWT bearer token is stored in browser `localStorage`, exposing session tokens to cross-site scripting (XSS). | Migrate to `HttpOnly`, `SameSite=Lax`, `Secure` cookies with Next.js middleware / BFF pattern. |
| **MEDIUM** | **Synchronous Blocking Network Call in Request Loop** | `apps/api/app/services/email.py` (`ResendEmailProvider`) | `urllib.request.urlopen` blocks the FastAPI worker thread for up to 15 seconds per inquiry with an email. | Use asynchronous HTTP (`httpx.AsyncClient`) or dispatch email delivery to a background queue / outbox. |
| **MEDIUM** | **Global Unique Email Constraint on Users** | `apps/api/app/models/user.py` (`ix_users_email`) | A single user email cannot belong to or manage multiple organizations. | If multi-business ownership is required, index `(organization_id, email)` as unique or separate authentication accounts from tenant memberships. |
| **LOW** | **No Token Invalidation / Revocation** | `apps/api/app/core/security.py` | JWT tokens remain valid for 480 minutes even if user changes password or is deactivated. | Introduce token versioning, revocation blocklist, or shorter token lifespans with refresh rotation. |
| **LOW** | **CORS Configuration With Credentials** | `apps/api/app/main.py` | `allow_credentials=True` combined with configurable `cors_origins`. Safe with explicit origins, but risky if misconfigured to wildcards. | Enforce strict origin validation in production configuration. |

---

# 8. Backend Verification

### 8.1 Test Suite
- **Command:** `pytest` (executed via Python 3.12 with site-packages)
- **Result:** **22 passed, 0 failed** in 4.86s
- **Breakdown:**
  - `tests/test_auth.py`: 2 passed (registration, login, invalid password, `/auth/me`).
  - `tests/test_leads.py`: 4 passed (manual lead creation, mock AI parsing, follow-up scheduling, status transitions, terminal cancellations, multi-tenant isolation).
  - `tests/test_workflows.py`: 4 passed (public inquiry, dashboard attention counts, follow-up processing, lead reopening).
  - `tests/test_inbound.py`: 12 passed (webhook ingestion, generic lead creation, HVAC pipeline, 3x mock AI extraction parameterized cases, duplicate open lead attachment, terminal lead separation, email failure resilience, unconfigured email handling, organization scoping of message history, embed form channel tagging, business type updating).

### 8.2 Code Linting
- **Command:** `ruff check apps/api`
- **Result:** **All checks passed! (0 errors, 0 warnings)**

### 8.3 Database Migrations & Integrity
- **Current Head:** `20261002_0002 (head)`
- **Migration Zero Verification:** Created clean PostgreSQL database `test_migration_zero`, executed `alembic upgrade head`, ran `alembic downgrade base`, and re-ran `alembic upgrade head`. **All migration steps passed with zero errors.**
- **PostgreSQL Inspection:** Verified constraints, foreign keys (`ON DELETE CASCADE`), indexes (`ix_leads_org_followup`, `ix_leads_org_status_created`, `ix_inbound_messages_org_received`), and unique constraint `uq_inbound_messages_external` on `(organization_id, channel, external_message_id)`.

### 8.4 Seed Data
- **Command:** `python seed.py`
- **Result:** Idempotent seed passed. Seeded demo organization `ComfortAir HVAC`, user `owner@example.com`, and initial representative leads.

---

# 9. Frontend Verification

### 9.1 Test Suite
- **Command:** `npm test` (Vitest v3.2.7)
- **Result:** **4 test files passed, 5 tests passed** in 4.45s
- **Breakdown:**
  - `__tests__/status-badge.test.tsx`: 2 tests passed (renders status and urgency styles).
  - `__tests__/lead-table.test.tsx`: 1 test passed (renders table rows and customer details).
  - `__tests__/settings-integration.test.tsx`: 1 test passed (renders webhook URL, embed code, email provider status).
  - `__tests__/inquiry-form.test.tsx`: 1 test passed (form submission against shared endpoint).

### 9.2 Linting & Typechecking
- **Command:** `npm run lint` (ESLint 9)
  - **Result:** **0 errors, 0 warnings**
- **Command:** `npm run typecheck` (`tsc --noEmit`)
  - **Result:** **0 errors**

### 9.3 Production Build
- **Command:** `npm run build` (Next.js 16.3.7 with Turbopack)
- **Result:** **Successfully compiled production build in 1224ms.** All 10 routes compiled and validated:
  - `○ /` (Dashboard)
  - `○ /_not-found`
  - `ƒ /embed/inquiry/[organizationId]` (Dynamic Embed Form)
  - `ƒ /inquiry/[organizationId]` (Dynamic Public Form)
  - `○ /leads` (Leads List & Filters)
  - `ƒ /leads/[id]` (Lead Details & Timeline)
  - `○ /leads/new` (Manual Lead Capture)
  - `○ /login` (Login)
  - `○ /register` (Workspace Registration)
  - `○ /settings` (Organization & Cadence Settings)

---

# 10. End-to-End Workflow Results

| Workflow | Path / Endpoint | Verification Performed | Result |
| :--- | :--- | :--- | :--- |
| **Manual Lead Capture** | `POST /leads` | Submitted name, email, phone, message via manual form. | **PASS:** Inbound message saved (`MANUAL`), AI extracted details, lead created, initial follow-ups scheduled, acknowledgement sent. |
| **Website Embed Form** | `POST /public/inbound/form/{id}` | Submitted embed form payload without authentication. | **PASS:** Returned `201 Created`, created lead with `source=WEBSITE_FORM`, attached message history, displayed on dashboard. |
| **Website Webhook** | `POST /public/inbound/webhook/{id}` | Submitted webhook payload with metadata. | **PASS:** Returned `201 Created`, created lead with `source=WEBSITE_WEBHOOK`, preserved custom JSON metadata in message history. |
| **Duplicate Inquiry** | `POST /public/inbound/webhook/{id}` | Sent second inquiry with same customer email within duplicate window. | **PASS:** Identified open lead, attached new message to message history, emitted `LEAD_ENRICHED` event, did not duplicate lead. |
| **Terminal Lead Inquiry** | `POST /public/inbound/webhook/{id}` | Marked lead `BOOKED`, then sent another inquiry from same customer. | **PASS:** Allowed new lead creation without altering closed booking. |
| **Lead Status Lifecycle** | `POST /leads/{id}/status` | Cycled lead through `NEW` -> `CONTACTED` -> `BOOKED`. | **PASS:** Cancelled old reminders, scheduled contacted reminders, cancelled all reminders upon booking. |
| **AI Follow-up Draft** | `POST /leads/{id}/generate-followup` | Generated follow-up text for existing lead. | **PASS:** Returned draft text referencing service and customer name, logged `FOLLOWUP_GENERATED` event. |
| **Follow-up Processing** | `POST /followups/process` | Set scheduled reminder timestamp to past, executed sweep. | **PASS:** Completed due reminders, generated audit event, advanced `next_followup_at`. |

---

# 11. Multi-Business Readiness

We tested three distinct industry scenarios against the system:

### 11.1 HVAC
- **Input:** *"My AC stopped cooling today. Can someone come tomorrow morning?"*
- **Extraction Result:**
  - Intent: `service_request`
  - Category / Service: `AC Repair`
  - Urgency: `HIGH`
  - Preferred Date: `Tomorrow`
  - Preferred Time: `Morning`
- **Assessment:** **EXCELLENT.** The deterministic mock and OpenAI prompts handle this case completely.

### 11.2 Clothing / Retail
- **Input:** *"Do you have the black shalwar kameez in medium? Can you deliver to Islamabad by Friday?"*
- **Extraction Result:**
  - Intent: `purchase_inquiry`
  - Category / Service: `None`
  - Product Name: `None` (Mock regex failed to match "shalwar kameez")
  - Variant: `Medium`
  - Location: `Islamabad`
  - Preferred Date: `Friday`
  - Urgency: `NORMAL`
- **Assessment:** **PARTIALLY WORKING.**
  - The generic schema stores product details, location, and variant.
  - The LLM provider (OpenAI) extracts `"black shalwar kameez"`, but the local deterministic `MockAIProvider` fails because its pattern is hardcoded to Western garments (`dress|shirt|jacket|shoes|bag|jeans...`).
  - The status workflow cannot track retail orders (`CONFIRMED`, `DISPATCHED`, `DELIVERED`).

### 11.3 Dental / Healthcare
- **Input:** *"I need a dental cleaning appointment next week."*
- **Extraction Result:**
  - Intent: `appointment_request`
  - Category / Service: `Dental Cleaning`
  - Preferred Date: `Next week`
  - Urgency: `NORMAL`
- **Assessment:** **GOOD.**
  - Intent and service correctly identified.
  - Lifecycle statuses (`NEW`, `CONTACTED`, `BOOKED`) map reasonably well to appointments, though healthcare-specific appointment reminders and calendar scheduling are not yet present.

### Remaining HVAC-Specific Assumptions in the Codebase
1. `apps/api/app/main.py:16`: `description="Simple, tenant-safe lead follow-up for small HVAC businesses."`
2. `apps/web/app/layout.tsx:6`: `description: "Simple lead follow-up for HVAC teams"`
3. `apps/web/app/register/page.tsx:23`: `subtitle="Start rescuing missed HVAC opportunities."`
4. `apps/web/components/auth-frame.tsx:3`: `<p className="text-xs text-slate-500">For HVAC teams</p>`
5. `apps/api/app/ai/mock.py:12-17`: Category patterns overwhelmingly weight HVAC terms (`AC Installation`, `Heating Repair`, `Thermostat Service`, `Duct Service`, `HVAC Maintenance`, `AC Repair`).

---

# 12. Phase 3 Readiness

| Capability | Readiness | Gap Description |
| :--- | :--- | :--- |
| **Conversation Model** | **NOT READY** | Currently, messages are tied directly to leads. There is no `Conversation` entity, thread ID, or concept of outbound replies. Multi-turn dialogue cannot be modeled. |
| **Customer Model** | **NOT READY** | Customer records do not exist independently of individual leads. Returning customers cannot be tracked across multiple visits or conversations. |
| **WhatsApp Ingestion** | **NOT READY** | Only enum value `WHATSAPP` exists. No webhook verification handshake, signature validation, or Meta Cloud API integration. |
| **Inbound Email Processing** | **NOT READY** | Outbound email exists, but there is no inbound webhook/parser (SendGrid Inbound Parse, Postmark, or Resend Inbound). |
| **Owner Notifications** | **NOT READY** | Only in-app dashboard display exists. No SMS, push, or email notification triggers when a lead needs attention. |
| **Hourly / Recurring Reminders** | **PARTIALLY READY** | Reminders can be persisted, but they require an external automated scheduler or background worker to process them. |
| **Customer Status Notifications** | **NOT READY** | No automated outbound messaging to customers when lead status changes. |
| **Two-Way Communication** | **NOT READY** | The UI only allows copying AI drafts to the clipboard; it cannot transmit messages back to customers over email, SMS, or WhatsApp. |

---

# 13. Technical Debt

1. **Dashboard In-Memory Computation:** `DashboardService.get()` pulls all leads into memory to compute status counts and filter attention leads. Must be replaced with SQL aggregation (`SELECT status, count(*) FROM leads GROUP BY status`).
2. **Missing E.164 Phone Normalization:** Phone numbers stored in raw format, leading to duplicate customer fragmentation.
3. **Lead Search Field Gaps:** `LeadRepository.list` does not search `product_name` or `category_or_service`.
4. **Organization PATCH Route Business Logic:** `PATCH /organizations/{id}` sets model attributes directly in the route handler rather than delegating to an organization service method.
5. **UI Copy Residuals:** Several UI components and metadata strings still state "For HVAC teams".
6. **Frontend Test Coverage Gaps:** Core views (Dashboard, Lead Details, Settings, Login, Register) lack automated component test coverage.

---

# 14. Priority Fixes Before Phase 3

### **P0 — Must Fix Immediately**
- [ ] **P0.1 Rate Limiting on Public Endpoints:** Add rate limiting to `/public/inbound/*`, `/public/inquiries/*`, `/auth/login`, and `/auth/register` to prevent API token exhaustion and spam.
- [ ] **P0.2 Phone Number Normalization:** Normalize phone numbers to E.164 (or stripped digits) during inbound ingestion and duplicate matching.
- [ ] **P0.3 Fix Lead Search Query:** Include `product_name` and `category_or_service` in `LeadRepository.list` search filter.

### **P1 — Should Fix Before Phase 3**
- [ ] **P1.1 Webhook Authentication / Secret:** Add support for webhook secret tokens / HMAC signatures to verify incoming webhooks.
- [ ] **P1.2 Asynchronous Email Dispatch / Outbox:** Convert Resend email provider to non-blocking async (`httpx`) or background queue to prevent 15-second worker blocking.
- [ ] **P1.3 SQL Aggregation on Dashboard:** Replace in-memory lead counting with SQL group-by aggregations.
- [ ] **P1.4 Remove Residual HVAC Copy:** Clean up HVAC-specific descriptions in `main.py`, `layout.tsx`, `register/page.tsx`, and `auth-frame.tsx`.

### **P2 — Can Wait Until Phase 3 Stabilization**
- [ ] **P2.1 Expand Deterministic Mock Patterns:** Add broader international and multi-industry patterns to `MockAIProvider`.
- [ ] **P2.2 Cookie-Based Session Storage:** Migrate JWT storage from `localStorage` to `HttpOnly` cookies.
- [ ] **P2.3 Service Layer Refactoring for Organization:** Move attribute updates from `organizations.py` route handler into `OrganizationService`.

---

# 15. Final Recommendation

### A. Is the current MVP stable enough to continue development?
**Yes.** The system architecture is clean, migrations and seed scripts are robust, multi-tenant isolation is strictly enforced, and the existing test suites pass completely.

### B. Should we fix anything before Phase 3?
**Yes.** The three **P0** items must be fixed before writing Phase 3 features:
1. Rate limiting on public and auth endpoints.
2. E.164 phone normalization in duplicate matching.
3. Search filtering for `product_name` and `category_or_service`.

### C. Can the existing architecture support the intended omnichannel product without a rewrite?
**Yes, but an entity schema evolution is mandatory.**
A rewrite is NOT required. However, developers must not force multi-channel conversations onto the `Lead` model. Instead, introducing two new core entities:
- `Customer` (owning contact details, organization scoping, and lifetime history)
- `Conversation` (owning channel threads, inbound messages, and outbound replies)
linked to `Lead` will naturally evolve the system into the intended omnichannel platform without disrupting existing lead workflows.

### D. What should be the exact next development phase?
**Phase 2.5: Foundation Hardening & Channel Core**
1. Resolve P0 fixes (rate limiting, phone normalization, search query fix).
2. Introduce `Customer` and `Conversation` models in Alembic migration `0003`.
3. Introduce an asynchronous background worker (e.g. lightweight APScheduler or Redis queue) for automated follow-up sweeps and non-blocking email delivery.
4. Proceed to **Phase 3: Real Omnichannel Ingestion** (WhatsApp Cloud API & Inbound Email webhook).
