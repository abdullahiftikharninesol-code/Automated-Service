# Future roadmap

## Before production pilot

- Add an HTTP-only cookie/BFF authentication flow, refresh-token rotation, rate limiting, and account recovery.
- Add a transactional outbox, a real email provider such as Resend/SES, delivery webhooks, retries, and suppression handling.
- Host `FollowUpSweepJob` on a durable scheduler and add operational alerts.
- Add structured application telemetry, error monitoring, backups, and a deployment runbook.
- Run accessibility and mobile field tests with several HVAC owners.

## After workflow validation

- Missed-call detection and call-source ingestion
- SMS and WhatsApp channels with explicit consent and compliance controls
- Calendar availability and booking
- Jobber and Housecall Pro synchronization
- Lightweight team invitations and assignment
- AI receptionist support with human escalation
- Billing and subscription management
- Conversion and response-time analytics
- Zapier/n8n webhooks where customers demonstrate demand

Each item should be validated against the central product promise before implementation: keep every inquiry visible until it is booked or lost without turning the product into a heavyweight CRM.
