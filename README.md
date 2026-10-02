# Missed Lead Rescue

Missed Lead Rescue is a focused SaaS for businesses that cannot afford to lose customer inquiries. It captures website and manually entered messages, extracts useful details across industries, acknowledges the customer, schedules follow-ups, and keeps every lead visible until it is resolved.

This is intentionally not a general CRM. The dashboard centers on one question: **Who needs my attention right now?**

## What is included

- Next.js 16 App Router UI with TypeScript and Tailwind CSS
- FastAPI API with Pydantic contracts and OpenAPI docs
- PostgreSQL, SQLAlchemy 2, and Alembic
- JWT authentication with Argon2 password hashing
- Organization-scoped persistence and tenant-isolation tests
- Normalized website form, website webhook, and manual-entry workflows
- Strict AI provider abstraction with deterministic cross-industry mock behavior
- Optional OpenAI-backed structured extraction through environment variables
- Console and Resend email providers behind an email abstraction
- Persistent follow-up schedule, cancellation, timeline events, and deterministic processor
- Dashboard, lead search/filtering, lead details, follow-up drafts, notes, and settings
- Demo seed for ComfortAir HVAC

## Repository layout

```text
apps/api   FastAPI application, migration, seed, and pytest suite
apps/web   Next.js application and Vitest component tests
docs       Architecture, scope, roadmap, and implementation plan
```

## Prerequisites

- Docker Desktop or another Docker-compatible engine
- Python 3.12+
- Node.js 20.9+ (Node 22 LTS is recommended)
- npm 10+

## Windows PowerShell setup

From the repository root:

```powershell
Copy-Item .env.example .env
docker compose up -d

Set-Location apps/api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
alembic upgrade head
python seed.py
uvicorn app.main:app --reload
```

In a second PowerShell window:

```powershell
Set-Location apps/web
Copy-Item ..\..\.env.example .env.reference
"NEXT_PUBLIC_API_URL=http://localhost:8000" | Set-Content .env.local
npm install
npm run dev
```

Open `http://localhost:3000`. The seeded login is:

- Email: `owner@example.com`
- Password: `DemoPassword123!` (development only)

The seed command prints the organization UUID and exact public inquiry URL.

If PowerShell blocks npm's script shim, use `npm.cmd` in place of `npm`.

## macOS/Linux setup

```bash
cp .env.example .env
docker compose up -d

cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python seed.py
uvicorn app.main:app --reload
```

In a second terminal:

```bash
cd apps/web
printf 'NEXT_PUBLIC_API_URL=http://localhost:8000\n' > .env.local
npm install
npm run dev
```

## Environment

Copy `.env.example` to `.env`. Development defaults use the deterministic mock AI and console email provider, so no third-party key is required.

To use an LLM:

```dotenv
AI_PROVIDER=openai
OPENAI_API_KEY=your-key
OPENAI_MODEL=gpt-4.1-mini
```

Set a long random `JWT_SECRET` outside development. `CORS_ORIGINS` accepts a comma-separated list.

To send acknowledgement email through Resend:

```dotenv
EMAIL_PROVIDER=resend
RESEND_API_KEY=re_your_key
EMAIL_FROM=Your Business <inquiries@example.com>
```

Missing or failed email delivery never discards an inbound inquiry. The failure is logged and recorded on the lead timeline.

## Useful URLs

- Web app: `http://localhost:3000`
- API: `http://localhost:8000`
- Interactive API docs: `http://localhost:8000/docs`
- API health: `http://localhost:8000/health`
- Public form: `http://localhost:3000/inquiry/{organization-id}`
- Embeddable form: `http://localhost:3000/embed/inquiry/{organization-id}`
- Website webhook: `POST http://localhost:8000/public/inbound/webhook/{organization-id}`

## Follow-up processing

The application persists reminder schedules at lead creation and status changes. To deterministically process due reminders during development:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://localhost:8000/followups/process `
  -Headers @{ Authorization = "Bearer YOUR_TOKEN" }
```

The processor is represented by a small background-job contract, so a durable scheduler can invoke the same behavior later. It does not require Redis or Celery.

## Quality checks

Backend:

```powershell
Set-Location apps/api
.\.venv\Scripts\Activate.ps1
ruff check .
pytest
```

Frontend:

```powershell
Set-Location apps/web
npm run lint
npm run typecheck
npm test
npm run build
```

## Demo flow

1. Run the seed and open its printed public inquiry URL.
2. Submit David Wilson's AC-not-cooling request for tomorrow morning.
3. The deterministic AI labels it `AC Repair`, `HIGH`, and `Tomorrow · Morning`.
4. The console email provider logs the acknowledgement in the API terminal.
5. Sign in. The high-urgency new lead appears immediately in Needs Attention.
6. Open the lead to inspect the inquiry, AI summary, follow-up information, and event timeline.
7. Mark it `CONTACTED`; the old reminders are cancelled and contacted reminders are scheduled.
8. Generate and review a follow-up draft.
9. Mark it `BOOKED`; all pending follow-ups are cancelled.

## Known MVP limitations

- Console email records delivery intent in logs; configure Resend for real delivery.
- Repeat messages attach to the same lead only when the organization and email or phone match, the lead is `NEW` or `CONTACTED`, and the latest matching message is within the organization's duplicate window. `BOOKED` and `LOST` leads allow a new lead.
- Phase 2 deliberately retains `NEW`, `CONTACTED`, `BOOKED`, and `LOST`; template-specific status vocabularies remain future work.
- AI follow-up text is draft-only and has no Send action.
- The follow-up processor is manually triggerable and needs an external scheduler in deployment.
- Browser sessions use local storage. A production deployment should introduce an HTTP-only cookie/BFF session strategy and refresh-token rotation.
- Email delivery and database persistence are not yet joined by an outbox, so production delivery retries are not implemented.
- Roles exist, but advanced team administration and permission matrices are deliberately excluded.

See [architecture](docs/architecture.md), [MVP scope](docs/mvp-scope.md), and [future roadmap](docs/future-roadmap.md).
