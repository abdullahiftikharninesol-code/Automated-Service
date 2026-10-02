# MVP scope

## Included

- Organization registration, owner login, JWT authentication, and current-user lookup
- Website inquiry form for each organization
- Manual lead capture for phone, referral, walk-in, email, and similar sources
- HVAC-aware structured extraction, summaries, urgency, preferred date/time phrases
- Automatic acknowledgement through a development console provider
- Lead statuses: `NEW`, `CONTACTED`, `BOOKED`, `LOST`, including reopen
- Configurable reminder schedule and terminal-state cancellation
- Attention-first dashboard with five summary counts
- Lead search, four focused filters/sorts, detail view, notes, and audit timeline
- Human-reviewed follow-up draft generation
- Organization and follow-up settings
- Demo organization, owner, and representative leads
- API, component, workflow, and tenant-isolation tests

## Deliberately excluded

- Payments, subscriptions, billing, or Stripe
- SMS, Twilio, WhatsApp, or voice/phone answering
- Automatic AI sales conversations or unsupervised sales-message sending
- Mobile applications
- Complex CRM pipelines, campaigns, advanced reporting, or team permissions
- Calendar booking and field-service integrations
- Jobber, Housecall Pro, Zapier, or n8n integrations
- General multi-industry customization

## Product assumptions

- A public inquiry has an email address so it can receive an acknowledgement.
- A manual lead needs at least a phone number or email address.
- “Needs Attention” is computed from urgency and deadlines, not stored as another status.
- Follow-up records represent internal work/reminders; generated sales copy remains visible to the owner before any future send operation.
