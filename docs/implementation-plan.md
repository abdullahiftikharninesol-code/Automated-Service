# Missed Lead Rescue implementation plan

## Architecture and proposed tree

```text
apps/
  api/
    alembic/                 # database migrations
    app/
      ai/                    # provider protocol and deterministic/mock providers
      api/routes/            # thin HTTP controllers
      core/                  # settings, auth, database, dependencies
      models/                # SQLAlchemy entities and enums
      repositories/          # organization-scoped persistence
      schemas/               # request/response contracts
      services/              # lead workflow, follow-ups, email, dashboard
      main.py
    tests/
    alembic.ini
    requirements.txt
    seed.py
  web/
    app/                     # App Router pages
    components/              # reusable UI and feature components
    lib/                     # typed API client, session, display helpers
    __tests__/
    package.json
docs/
docker-compose.yml
.env.example
README.md
```

## Phases

- [x] Phase 1 — repository skeleton, configuration, architecture plan
- [x] Phase 2 — SQLAlchemy models, database session, Alembic migration
- [x] Phase 3 — JWT authentication, password hashing, tenant context
- [x] Phase 4 — organization-scoped lead CRUD, status workflow, events
- [x] Phase 5 — public inquiry workflow and development email delivery
- [x] Phase 6 — strict AI abstraction and deterministic mock provider
- [x] Phase 7 — configurable follow-up engine and manual processing endpoint
- [x] Phase 8 — dashboard API and attention calculations
- [x] Phase 9 — responsive authenticated UI, lead list/detail/new pages
- [x] Phase 10 — public inquiry and settings UI, seed/demo polish
- [x] Phase 11 — tests, lint/type checking, documentation, final verification

## Important assumptions

- Email is optional on manually entered leads, but public inquiries require one so an acknowledgement can be delivered.
- `Needs Attention` is a computed state, not a fifth lead status: a `NEW` lead whose first deadline has passed needs attention.
- Acknowledgements are sent automatically through the configured email provider; AI follow-up drafts are never sent automatically.
- Follow-ups are persisted as actionable reminders. A manually triggered processor materializes later reminders without requiring Redis or Celery.
- Organization registration creates the owner and organization atomically. Public inquiry URLs use the organization UUID.
- Date-only customer preferences remain strings in the AI result because phrases such as “tomorrow” may be meaningful; explicit form dates are stored as ISO dates.

## Verification gates

Each phase is checked with the narrowest relevant tests first. The final gate runs backend tests, backend lint, frontend tests, frontend lint, TypeScript checking, and a production frontend build.

## Phase 2: real inbound capture

- [x] Normalized `InboundMessage` persistence and channel enum
- [x] One inbound service for manual, website form, and website webhook adapters
- [x] Generic structured AI extraction with business-type hints
- [x] Compatibility-preserving generic lead fields and migration
- [x] Configurable open-lead duplicate matching and customer message history
- [x] Console/Resend acknowledgement delivery with failure isolation
- [x] Embeddable public form and owner integration settings
- [x] Dashboard/list source badges and latest-message context
- [x] Backend and frontend coverage for the Phase 2 workflows
