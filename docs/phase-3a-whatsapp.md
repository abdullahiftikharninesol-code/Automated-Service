# Phase 3A — WhatsApp Business Cloud API Integration

**Date:** October 20, 2026  
**Status:** In Progress / Implementing  
**Objective:** Integrate the Meta WhatsApp Business Cloud API as the first real communication channel in Missed Lead Rescue, reusing existing Customer identity, Conversation canonical threading, AI extraction, and background reminder engines.

---

## 1. Verified Meta Cloud API Specifications

Based on official Meta Graph API documentation (verified for Graph API standards up to `v22.0` / configurable via `META_GRAPH_API_VERSION`):

### 1.1 Webhook Verification Handshake (`GET`)
- **Query Parameters Sent by Meta:**
  - `hub.mode`: Set to `"subscribe"`
  - `hub.verify_token`: Custom verification token configured in the Meta App Dashboard
  - `hub.challenge`: Random string or integer provided by Meta
- **Server Response:**
  - When `hub.mode == "subscribe"` and `hub.verify_token` matches the configured secret, the server **must** return the exact `hub.challenge` value in plain text (`text/plain`) with HTTP `200 OK`.
  - On mismatch or missing parameters, the server returns HTTP `403 Forbidden`.
  - Constant-time comparison (`hmac.compare_digest`) must be used to prevent timing side channels.

### 1.2 Webhook Signature Security (`POST`)
- **Header:** `X-Hub-Signature-256` in the format `sha256=<64-hex-digest>`.
- **Computation:** HMAC SHA-256 generated across the **raw byte body** of the request using the Meta App Secret (`META_APP_SECRET`).
- **Validation:** Constant-time verification with `hmac.compare_digest(provided_signature, expected_signature)`. Requests with missing, malformed, or invalid signatures are rejected with HTTP `401 Unauthorized` or `403 Forbidden`.

### 1.3 Webhook Payload Format
- **Root Object:** `"object": "whatsapp_business_account"`
- **Structure:**
  ```text
  entry[] -> changes[] -> value:
    metadata: { display_phone_number, phone_number_id }
    contacts[]: [{ profile: { name }, wa_id }]
    messages[]: [{ from, id (wamid), timestamp, type: "text", text: { body } }]
    statuses[]: [{ id (wamid), status: "sent"|"delivered"|"read"|"failed", timestamp, recipient_id, errors[] }]
  ```
- **Parsing Robustness:** Meta can batch multiple entries or changes in a single payload. Handlers must iterate arrays safely rather than indexing `entry[0].changes[0]` blindly.
- **Unsupported Message Types:** Non-text messages (`image`, `audio`, `video`, `document`, `location`, `contacts`, `interactive`, `reaction`) must be caught and logged safely without raising unhandled exceptions or crashing, returning HTTP 200 to prevent Meta delivery storms.

### 1.4 Sending Messages (`POST /vXX.X/{phone_number_id}/messages`)
- **Endpoint:** `https://graph.facebook.com/{version}/{phone_number_id}/messages`
- **Headers:** `Authorization: Bearer {access_token}`, `Content-Type: application/json`
- **Text Payload:**
  ```json
  {
    "messaging_product": "whatsapp",
    "recipient_type": "individual",
    "to": "1234567890",
    "type": "text",
    "text": {
      "preview_url": false,
      "body": "..."
    }
  }
  ```
- **Response:** HTTP 200 with `{"messaging_product": "whatsapp", "messages": [{"id": "wamid.HBgL..."}]}`.

### 1.5 Customer Service Window & Template Rules
- **24-Hour Service Window:** Meta allows free-form customer service messaging within 24 hours of the customer's last inbound message.
- **Outside 24 Hours:** Meta rejects free-form messages with error code `131047` ("Re-engagement message: Message failed to deliver because more than 24 hours have passed since the last client message"). Initiating conversations outside the 24-hour window requires pre-approved Meta message templates.
- **Phase 3A Application:** Automated customer acknowledgements and owner replies occur within the 24-hour window following customer inquiries.

---

## 2. Architecture & Channel Separation

WhatsApp is integrated strictly as a **channel adapter**:
```text
┌──────────────────────────────────────────────────────────┐
│              Meta WhatsApp Business Cloud                │
└────────────────────────────┬─────────────────────────────┘
                             │ Webhook POST / GET
                             ▼
┌──────────────────────────────────────────────────────────┐
│              FastAPI Route (/webhooks/whatsapp)          │
│    - X-Hub-Signature-256 HMAC Validation                 │
│    - hub.challenge Handshake Verification                │
└────────────────────────────┬─────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────┐
│              WhatsAppInboundAdapter                      │
│    - Multi-entry payload unpacking                       │
│    - WhatsAppOrganizationResolver (by phone_number_id)   │
│    - Status updates -> WhatsAppStatusHandler             │
│    - Text messages -> InboundLeadService.process         │
└────────────────────────────┬─────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────┐
│              Existing Core Services (Reused)             │
│    - CustomerService.find_or_create (E.164 normalized)   │
│    - ConversationService (channel=WHATSAPP)              │
│    - AI Information Extraction                           │
│    - Lead creation / enrichment                          │
│    - FollowUpService (OWNER_RESPONSE_REMINDER)           │
│    - Automated WhatsApp Acknowledgement (SYSTEM)         │
└──────────────────────────────────────────────────────────┘
```

### Core Design Rules:
1. **Zero Domain Duplication:** WhatsApp does not replicate customer matching, lead enrichment, reminder claiming, or conversation models.
2. **Deterministic Acknowledgement:** When a customer sends a WhatsApp message, a deterministic acknowledgment is sent via the `WhatsAppProvider`. This outbound message is tagged `sender_type = MessageSenderType.SYSTEM`, leaving `waiting_on = WaitingOn.OWNER` so the 1-hour owner reminder remains active.
3. **Owner Reply Lifecycle:** When an owner replies via `POST /conversations/{id}/reply`, the outbound message is tagged `sender_type = MessageSenderType.OWNER`, setting `waiting_on = WaitingOn.CUSTOMER` and cancelling pending owner response reminders.

---

## 3. Tenant Routing Strategy (`phone_number_id`)

- Multi-tenancy is enforced by mapping Meta's receiving `phone_number_id` (from `metadata.phone_number_id`) to the receiving `Organization.whatsapp_phone_number_id`.
- The webhook endpoint **never** accepts a client-provided `organization_id`.
- If an unrecognized `phone_number_id` arrives, the adapter logs a structured warning and returns HTTP 200 without creating any data, preventing cross-tenant leakage.

---

## 4. Idempotency & Delivery Status Progression

### 4.1 Message Deduplication
- Meta frequently retries webhooks. Every inbound message has a unique `wamid` (`external_message_id`).
- `InboundLeadService` and `ConversationService` check `(organization_id, channel, external_message_id)`. If already processed, the duplicate is ignored cleanly without re-running AI extraction, sending duplicate acknowledgements, or creating duplicate reminders.

### 4.2 Status Progression (No Backwards Regression)
Delivery receipts arrive asynchronously via webhook status updates:
- Order hierarchy: `PENDING (0) -> SENT (1) -> DELIVERED (2) -> READ (3)`.
- If an outbound message is already marked `READ`, a delayed `DELIVERED` status callback will not regress the message status back to `DELIVERED`.
- Repeated `DELIVERED` or `READ` events are idempotent.
- `FAILED` captures provider error codes and descriptions in message metadata.

---

## 5. Security & Secret Protection

- `META_APP_SECRET` and `META_WHATSAPP_ACCESS_TOKEN` are managed securely via environment configuration and service abstractions.
- Secrets are **never** returned in API responses (`GET /organizations/{id}`, etc.) or written to application logs.
- Webhook endpoints enforce `X-Hub-Signature-256` using constant-time comparison.
- Rate limiting on `/webhooks/whatsapp` is set to a generous threshold (`60/minute` or configurable) to prevent burst dropouts from Meta while protecting server resources.
