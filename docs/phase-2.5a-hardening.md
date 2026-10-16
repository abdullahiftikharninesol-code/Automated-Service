# Phase 2.5A — Foundation Hardening Plan

**Date:** October 16, 2026  
**Status:** Complete  
**Objective:** Harden existing foundation against identified P0 and P1 audit findings without scope creep.

---

## 1. Issues & Scope

### P0 Issues
1. **Rate Limiting on Public & Auth Endpoints:** Prevent automated abuse, credential stuffing, and AI/email resource exhaustion on `/auth/login`, `/auth/register`, `/public/inbound/webhook/{org_id}`, `/public/inbound/form/{org_id}`, and `/public/inquiries/{org_id}`.
2. **E.164 Phone Normalization:** Standardize incoming phone numbers using `phonenumbers` to prevent duplicate customer fragmentation across different input formats (e.g. `+1 512 555 0100` vs `(512) 555-0100`).
3. **Lead Search Coverage:** Extend `LeadRepository.list` search filter to cover `category_or_service`, `product_name`, `product_variant`, `location`, `message`, and `customer_phone_normalized`.

### P1 Issues
4. **Webhook HMAC / Secret Verification:** Optional organization-level webhook signature validation (`X-Missed-Lead-Signature: sha256=<hex>`) on `POST /public/inbound/webhook/{org_id}` while keeping public embed forms open and unauthenticated.
5. **Non-Blocking Email Request Path:** Replace synchronous blocking `urllib.request.urlopen` in `ResendEmailProvider` with non-blocking HTTP (`httpx`) and background execution to ensure lead creation is never delayed by provider latency.

---

## 2. Intended Fixes & Architecture

### 2.1 Rate Limiting
- Use `slowapi` with in-memory storage (keyed by client IP `get_remote_address`).
- Configurable via `Settings`:
  - `RATE_LIMIT_ENABLED` (default `True` in production, toggleable for tests)
  - `AUTH_LOGIN_RATE_LIMIT="10/minute"`
  - `AUTH_REGISTER_RATE_LIMIT="5/minute"`
  - `PUBLIC_INBOUND_RATE_LIMIT="30/minute"`
- Returns HTTP 429 with `{ "detail": "Rate limit exceeded: ..." }`.
- `/health` and internal protected workspace routes remain unthrottled.

### 2.2 Phone Normalization & Database Schema
- Implement `apps/api/app/core/phone.py` with `normalize_phone_number(raw_phone, default_region=None)`.
- If phone includes international country code (`+...`), normalize directly to E.164.
- If phone is national format, use organization's `default_phone_region` (e.g. `US`, `PK`, `GB`). If unparseable or ambiguous without region, return `None` (preserve raw phone without guessing).
- Database migration `20261015_0003_hardening`:
  - Add `customer_phone_normalized` (String(60), nullable, indexed) to `leads` and `inbound_messages`.
  - Add compound indexes: `ix_leads_org_phone_norm` on `(organization_id, customer_phone_normalized)` and `ix_inbound_messages_org_phone_norm` on `(organization_id, customer_phone_normalized)`.
  - Add `default_phone_region` (String(10), nullable) to `organizations`.
  - Add `inbound_webhook_secret` (String(255), nullable) to `organizations`.

### 2.3 Duplicate Matching Update
- In `InboundLeadService._find_open_lead`:
  - If `message.customer_phone_normalized` is present, match against `customer_phone_normalized`.
  - Fall back to raw `customer_phone` string matching if normalized is not available.
  - Retain existing email matching (`func.lower(...)`).
  - Retain duplicate window check and open status (`NEW`, `CONTACTED`) requirement.

### 2.4 Lead Search Query
- Update `LeadRepository.list` to include:
  - `Lead.customer_name`
  - `Lead.customer_email`
  - `Lead.customer_phone`
  - `Lead.customer_phone_normalized`
  - `Lead.service_type`
  - `Lead.category_or_service`
  - `Lead.product_name`
  - `Lead.product_variant`
  - `Lead.location`
  - `Lead.message`

### 2.5 Webhook HMAC Verification
- Add `POST /organizations/{org_id}/rotate-webhook-secret` to generate a secure random secret token (`whsec_...`).
- When `WEBHOOK_SIGNATURE_REQUIRED=True` or organization has a configured secret:
  - Verify header `X-Missed-Lead-Signature: sha256=<hex digest>`.
  - Compute `hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()`.
  - Compare using constant-time `hmac.compare_digest`.
  - Reject missing or mismatched signatures with HTTP 401.

### 2.6 Email Request-Path Hardening
- Refactor `ResendEmailProvider` to use `httpx.Client` with explicit timeout (5s) instead of `urllib.request.urlopen`.
- Dispatch acknowledgement email via FastAPI `BackgroundTasks` so the HTTP response is returned to the user immediately upon DB commit.
- Record `ACKNOWLEDGEMENT_SENT` or `ACKNOWLEDGEMENT_FAILED` reliably.

---

## 3. Files Likely Affected

1. `apps/api/requirements.txt` (add `phonenumbers`, `slowapi`)
2. `apps/api/app/core/config.py` (add rate limit & webhook settings)
3. `apps/api/app/core/phone.py` (new phone normalization utility)
4. `apps/api/app/core/rate_limit.py` (new rate limiting initialization & handler)
5. `apps/api/app/models/organization.py` (add `default_phone_region`, `inbound_webhook_secret`)
6. `apps/api/app/models/lead.py` (add `customer_phone_normalized`)
7. `apps/api/app/models/inbound_message.py` (add `customer_phone_normalized`)
8. `apps/api/alembic/versions/20261015_0003_hardening.py` (migration for new columns & indexes)
9. `apps/api/app/schemas/organization.py` (expose `default_phone_region`, `webhook_secret_configured`)
10. `apps/api/app/schemas/lead.py` & `schemas/inbound.py` (add `customer_phone_normalized` to responses)
11. `apps/api/app/services/inbound.py` (update phone normalization & duplicate query)
12. `apps/api/app/services/email.py` (httpx-based email provider)
13. `apps/api/app/repositories/leads.py` (expanded search filter)
14. `apps/api/app/api/routes/auth.py` (apply login/register rate limits)
15. `apps/api/app/api/routes/public.py` (apply inbound rate limits & HMAC verification)
16. `apps/api/app/api/routes/organizations.py` (add secret rotation endpoint)
17. `apps/api/app/main.py` (register rate limiter & exception handler)
18. `.env.example` (document new environment variables)
19. `apps/api/tests/` (add tests for rate limiting, phone normalization, search, webhook HMAC, async email)

---

## 4. Tests Required

- **Rate Limiting Tests:**
  - `POST /auth/login` exceeds threshold -> 429
  - `POST /auth/register` exceeds threshold -> 429
  - `POST /public/inbound/webhook/{id}` exceeds threshold -> 429
  - `POST /public/inbound/form/{id}` exceeds threshold -> 429
  - Health check remains unthrottled
  - Disabled limiter allows requests
- **Phone Normalization & Duplicates:**
  - E.164 normalization for `+1 512 555 0100`, `(512) 555-0100`, `5125550100` with US default region.
  - Matching across differently formatted phones.
  - Invalid phone handling (no crash, stored as raw with normalized=None).
  - Cross-tenant phone duplicate isolation.
- **Search Query Tests:**
  - Search by product name (`black dress`), category (`Dental Cleaning`), location (`Islamabad`), and normalized phone.
  - Ensure cross-tenant isolation in search.
- **Webhook HMAC Tests:**
  - Valid signature accepted.
  - Missing signature rejected (401) when secret is set.
  - Invalid signature rejected (401).
  - Unsigned accepted when secret is not configured.
- **Email Resilience Tests:**
  - Request returns successfully before/without provider latency.
  - Error logs event without failing lead creation.

---

## 5. Compatibility & Regression Risks

- Public embed forms must NOT require HMAC signatures.
- Existing tests in `test_inbound.py`, `test_leads.py`, `test_workflows.py`, `test_auth.py` must continue to pass.
- In-memory rate limiting must be disabled by default during standard test fixtures to prevent cross-test interference.

---

## 6. Verification Results

### Backend Tests
- **Total Tests:** 32 passed (22 existing + 10 new hardening tests)
- **Suite:**
  - `tests/test_hardening.py` (Rate limiting, E.164 normalization, search expansion, webhook HMAC lifecycle, email resilience)
  - `tests/test_auth.py` (Auth token generation and user retrieval)
  - `tests/test_inbound.py` (Inbound webhook, embed form, duplicate attachment, idempotency)
  - `tests/test_leads.py` (Lead creation, tenant isolation, followups)
  - `tests/test_workflows.py` (Follow-up scheduler, inquiry pipeline, status transitions)
- **Linter:** `ruff check .` — All checks passed (0 errors)

### Database Migration
- **Revision:** `20261015_0003_hardening`
- **Current State:** Applied to PostgreSQL `missed_lead_rescue` at `20261015_0003 (head)`
- **Schema Updates:** Added `customer_phone_normalized` and indexes to `leads` and `inbound_messages`; added `default_phone_region` and `inbound_webhook_secret` to `organizations`.

### Frontend Verification
- **Unit Tests:** `npm test` — 5 passed (5 total)
- **Typecheck:** `npm run typecheck` (`tsc --noEmit`) — 0 errors
- **Linter:** `npm run lint` (`eslint .`) — 0 warnings/errors
- **Production Build:** `npm run build` (`next build`) — Compiled successfully

### Security & Tenancy Checklist
- [x] Auth routes rate-limited (login 10/min, register 5/min)
- [x] Public routes rate-limited (inbound endpoints 30/min)
- [x] Webhook HMAC validation enforced when secret configured
- [x] Constant-time comparison `hmac.compare_digest` prevents timing attacks
- [x] Raw secrets omitted from API responses and never logged
- [x] Tenant isolation verified across duplicate matching and search queries
- [x] Email timeout and errors safely logged without failing inbound transactions
