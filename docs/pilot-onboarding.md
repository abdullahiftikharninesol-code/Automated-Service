# Pilot Business Onboarding Playbook (15–30 Minutes)

This operational playbook details the exact manual steps required to onboard a new small-business pilot customer onto **Missed Lead Rescue** without changing any code or deploying billing infrastructure.

---

## Overview

The onboarding process takes approximately **15 to 30 minutes** and prepares a business to:
1. Capture all incoming customer WhatsApp messages into a dedicated unified inbox.
2. Automatically extract structured customer needs, dates, and locations.
3. Automatically clarify missing information via multi-turn WhatsApp questions.
4. Notify the business owner if an inquiry remains unaddressed.
5. Enable the owner to reply directly from the web dashboard.

---

## Phase 1: Pre-requisites Checklist (5 Minutes)

Before beginning the onboarding call or session, obtain the following from the business owner:
- [ ] Business legal name and common brand name.
- [ ] Owner's primary email address (for dashboard login).
- [ ] Business industry / category (e.g., General Services, Dental, Clothing, Salon, Legal, Consulting).
- [ ] 2 to 4 key questions the business always asks every new prospect (e.g., "What service do you need?", "What date or time works best?", "What is your location/city?").
- [ ] Meta Business Manager access or a dedicated WhatsApp Business phone number.

---

## Phase 2: Create Organization & Owner Account (5 Minutes)

### Step 1: Create Organization and Owner User
You can onboard via the web dashboard at `/register` or directly via the API:

```bash
# Register pilot organization and owner
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "owner@pilotbiz.com",
    "password": "SecureTemporaryPassword2026!",
    "full_name": "Sarah Jenkins",
    "organization_name": "Apex Home Services",
    "business_type": "GENERAL"
  }'
```

*Note: Save the returned `access_token` and `organization_id`.*

### Step 2: Confirm Owner Can Sign In
1. Visit `http://localhost:3000/login`.
2. Enter the pilot owner's email and password.
3. Confirm access to the dashboard.

---

## Phase 3: Connect Meta WhatsApp Business Cloud API (5 Minutes)

In the pilot's Meta Business Manager or Meta Developers console:

1. **Obtain Meta Identifiers:**
   - **Phone Number ID:** (e.g., `108849201948291`)
   - **WABA ID:** (e.g., `109928172648192`)
   - **Display Phone Number:** (e.g., `+1 512 555 0199`)

2. **Configure Webhook in Meta Developers Console:**
   - **Callback URL:** `https://<production-or-tunnel-domain>/webhooks/whatsapp`
   - **Verify Token:** The shared verify token configured in the application environment.
   - **Subscription Fields:** Subscribe to `messages`.

3. **Bind WhatsApp Identifiers to Pilot Organization in Database:**
   Using the setup script or SQL update:
   ```powershell
   .\apps\api\.venv\Scripts\python.exe scripts/setup_demo_business.py `
     --phone-id "108849201948291" `
     --waba-id "109928172648192" `
     --display-phone "+15125550199" `
     --email "owner@pilotbiz.com"
   ```
   *(Or via `PATCH /organizations/settings` with owner credentials).*

---

## Phase 4: Configure Qualification Fields (5 Minutes)

Configure the specific questions the business needs to qualify inquiries. These can be configured via the API or `/settings`:

### Option A: Apply Standard Industry Template
```bash
curl -X POST http://localhost:8000/qualification-fields/apply-template \
  -H "Authorization: Bearer <owner_access_token>" \
  -H "Content-Type: application/json" \
  -d '{"template_name": "GENERAL"}'
```

### Option B: Configure Tailored Fields
```bash
# 1. Customer Need
curl -X POST http://localhost:8000/qualification-fields \
  -H "Authorization: Bearer <owner_access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "key": "customer_need",
    "label": "Service Requested",
    "field_type": "TEXT",
    "required": true,
    "sort_order": 0,
    "question_text": "What type of service or assistance do you need?"
  }'

# 2. Preferred Date
curl -X POST http://localhost:8000/qualification-fields \
  -H "Authorization: Bearer <owner_access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "key": "preferred_date",
    "label": "Preferred Date",
    "field_type": "TEXT",
    "required": true,
    "sort_order": 1,
    "question_text": "What date or time would you prefer?"
  }'

# 3. Location / Address
curl -X POST http://localhost:8000/qualification-fields \
  -H "Authorization: Bearer <owner_access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "key": "location",
    "label": "Service Location",
    "field_type": "TEXT",
    "required": true,
    "sort_order": 2,
    "question_text": "What city or neighborhood are you located in?"
  }'
```

---

## Phase 5: Configure Reminder Delays (2 Minutes)

Set the response reminder delay based on the business's operational style:

```bash
curl -X PATCH http://localhost:8000/organizations/settings \
  -H "Authorization: Bearer <owner_access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "owner_reminder_delay_minutes": 30,
    "owner_reminder_repeat_minutes": 60,
    "owner_reminder_max_attempts": 3
  }'
```
*Recommendations:*
- **Quick-response businesses (plumbers, lock, tow, urgent repair):** 15–30 minutes.
- **Appointment / Consultation businesses (dental, legal, design):** 60 minutes.

---

## Phase 6: Live Smoke Test & Verification (5 Minutes)

Perform a live end-to-end check with a real phone:

1. **Test Inquiry 1 (Multi-turn):**
   - Send: `"Hi, I'm interested in your service."`
   - Verify on phone: System answers within 3 seconds asking for missing details:
     `"What type of service or assistance do you need? What date or time would you prefer?"`
   - Reply on phone: `"Home inspection this Thursday in Downtown."`
   - Verify on phone: System responds with confirmation:
     `"Thanks, I’ve got the details. Someone from the team will get back to you shortly."`

2. **Verify Dashboard:**
   - Refresh the owner dashboard at `http://localhost:3000/leads`.
   - Confirm lead status shows **NEW** with qualification status **COMPLETE**.
   - Open lead detail -> inspect extracted fields:
     * Service: `Home inspection`
     * Date: `Thursday`
     * Location: `Downtown`
   - Inspect conversation thread: All inbound messages, system clarification questions, and confirmations are logged canonical in order.

3. **Owner Reply Test:**
   - In the lead detail conversation thread, type:
     `"Hi! We have an inspector available Thursday at 10 AM. Does that work for you?"`
   - Click **Send**.
   - Verify on customer phone: The message arrives as a real WhatsApp message from the business number.
   - Verify dashboard: Status shows `SENT` / `DELIVERED` badge.
   - Verify database/logs: Pending owner response reminder is automatically cancelled.

---

## Phase 7: Go Live & Handover

1. Provide the owner their login credentials:
   - URL: `https://app.missedleadrescue.com`
   - Email: `owner@pilotbiz.com`
2. Advise the owner on daily operation:
   - Keep the dashboard open on desktop or mobile browser.
   - When an unaddressed inquiry hits the reminder threshold, a notification will be generated.
   - Always reply directly within the dashboard to maintain synchronized conversation logs and stop reminder alerts.
