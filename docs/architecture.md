# Architecture

## System shape

Missed Lead Rescue is a monorepo with a browser client, stateless HTTP API, and PostgreSQL database.

```text
Customer inquiry --> form / webhook / manual adapter --> normalized inbound pipeline --> PostgreSQL
                                                   │
                                      AI provider + email provider
                                                   │
Owner browser ─────> Next.js workspace ────────────┘
```

## Frontend

`apps/web` uses Next.js 16 App Router, strict TypeScript, React, and Tailwind CSS. Public authentication and inquiry pages sit outside the protected route group. The workspace layout validates the stored bearer token through `GET /auth/me` before rendering dashboard routes.

The typed API client is intentionally small. Pages own only display state and call cohesive API workflows; business decisions such as follow-up cancellation remain in the backend.

## API

`apps/api/app` is separated by responsibility:

- `api/routes`: HTTP parsing, dependencies, status codes, and response schemas
- `schemas`: strict Pydantic input/output contracts
- `services`: business workflows and transaction boundaries
- `repositories`: tenant-scoped persistence queries
- `models`: SQLAlchemy entities and domain enums
- `ai`: provider protocol and provider implementations
- `jobs`: host-independent background job contract
- `core`: settings, database sessions, and security

FastAPI generates OpenAPI documentation at `/docs`.

## Database

PostgreSQL is the runtime store. UUID primary keys avoid guessable sequential identifiers. Organization IDs are present on users, leads, events, and follow-ups. Compound indexes support status dashboards, scheduled work, and event timelines. Alembic owns schema changes.

All timestamps are written in UTC. Organization timezones are stored as IANA names, with display conversion left to UI boundaries.

## Authentication and tenancy

Registration creates an organization and owner in one transaction. Passwords are hashed with Argon2 through `pwdlib`; login returns a signed, expiring JWT.

Protected endpoints derive the organization from the authenticated user. Lead lookup and list methods require both resource ID and organization ID. Cross-organization misses return 404 to avoid revealing resource existence. Tests exercise lead and organization isolation.

## Inbound request flow

1. A thin channel adapter normalizes website forms, website webhooks, or manual entry into `InboundMessageCreate`.
2. `InboundLeadService` validates the organization and stores the original `InboundMessage` before processing.
3. The configured AI provider extracts generic intent, category/service, product details, timing, location, urgency, and a factual summary.
4. A recent open lead with the same organization and email or phone is enriched; otherwise a lead is created. Explicit customer fields win over extracted values.
5. Message, AI, lead, acknowledgement, delivery, and follow-up events are recorded.
6. Acknowledgement delivery is attempted when email exists. Provider failure is logged and recorded without rolling back the inquiry.
7. New leads receive the configured follow-up schedule; repeat messages preserve the existing schedule.
8. The workflow commits and returns the lead UUID and status.

The duplicate window is configurable per organization. Only `NEW` and `CONTACTED` leads are eligible. `BOOKED` and `LOST` are terminal for matching purposes, so a later inquiry creates a new lead. External channel message IDs are unique per organization and channel, providing an idempotency extension point for future connectors.

## AI abstraction

`AIProvider` defines extraction, acknowledgement generation, and follow-up generation. `MockAIProvider` is deterministic and recognizes representative service, retail, dental, scheduling, product, location, and urgency language. It returns null for unknown structured fields and flags hazard language without offering repair advice. `OpenAIProvider` uses the same generic Pydantic response schema and receives the organization business type as a prompt hint, not as a separate workflow.

The provider is chosen through `AI_PROVIDER`; all service logic depends on the protocol rather than a vendor SDK.

## Email abstraction

`EmailProvider` exposes one `send` operation. `ConsoleEmailProvider` logs development messages and `ResendEmailProvider` calls Resend's HTTPS API. Provider choice and credentials come from environment settings; secrets are never returned by settings endpoints.

## Compatibility decisions

The `service_type` database column remains available for Phase 1 clients. New processing also stores `intent`, `category_or_service`, `product_name`, `product_variant`, `quantity`, and provider-specific additional fields. Existing service data is backfilled into `category_or_service` by the migration.

The status values remain `NEW`, `CONTACTED`, `BOOKED`, and `LOST` in Phase 2. Replacing them with template-specific labels would destabilize the established follow-up workflow and is deferred.

## Follow-up engine

The schedule belongs to each organization. A new lead receives reminders at the first-attention threshold, second-reminder threshold, and final threshold. Moving to `CONTACTED` cancels that schedule and creates contacted/final reminders. `BOOKED` and `LOST` cancel all pending reminders and clear `next_followup_at`; reopening creates a fresh schedule.

High-urgency and emergency new leads appear in Needs Attention immediately. Other unresolved leads appear when their next reminder is due.

`FollowUpSweepJob` processes due rows deterministically, marks them complete, records timeline events, and advances each lead's next reminder. The protected `/followups/process` endpoint is the local development trigger. A hosted scheduler can call the same job later.

## Failure boundaries

Pydantic rejects malformed input before business logic runs. Expected missing/unauthorized resources receive controlled 4xx responses. Unexpected exceptions are logged; production responses omit internal details. A transactional outbox and provider retries are explicit post-MVP work.
