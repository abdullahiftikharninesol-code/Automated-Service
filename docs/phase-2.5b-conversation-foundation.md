# Phase 2.5B — Customer + Conversation Foundation Implementation Plan

**Date:** October 16, 2026  
**Status:** Complete  
**Objective:** Establish the canonical data model and service layer for future omnichannel communication without implementing Phase 3 connector integrations (WhatsApp/Meta/Twilio/Email inbox).

---

## 1. Architectural Intent & Domain Separation

In the expanded omnichannel vision:
- **Lead** is a sales/pipeline opportunity (status: `NEW`, `CONTACTED`, `BOOKED`, `LOST`).
- **Customer** is the persistent identity of the human/business contacting the organization.
- **Conversation** is a thread of communication over a specific channel with state and timeline.
- **ConversationMessage** is the canonical, immutable message record (direction: `INBOUND` or `OUTBOUND`, sender: `CUSTOMER`, `OWNER`, `SYSTEM`, or `AI`).

```text
Organization (Tenant Boundary)
    │
    ├── Customer (Identity: Normalized E.164 Phone & Lowercase Email)
    │     │
    │     ├── Conversation (Channel thread, status, waiting_on)
    │     │     │
    │     │     ├── ConversationMessage (Canonical message: INBOUND/OUTBOUND)
    │     │     │
    │     │     └── Lead (Associated sales inquiry / opportunity)
    │     │
    │     └── Lead (Customer has many historical leads)
```

### Key Cardinalities
1. **One Organization -> Many Customers**
2. **One Customer -> Many Conversations**
3. **One Conversation -> Many ConversationMessages**
4. **One Customer -> Many Leads**
5. **One Conversation -> Optional Lead association** (`lead_id` on Conversation and `primary_conversation_id` on Lead)

---

## 2. Models Specification

### 2.1 Customer Model (`apps/api/app/models/customer.py`)
- `id`: UUID (Primary Key)
- `organization_id`: UUID (Foreign Key -> `organizations.id` ON DELETE CASCADE, indexed)
- `name`: String(160), nullable
- `email`: String(320), nullable
- `email_normalized`: String(320), nullable, indexed
- `phone`: String(60), nullable
- `phone_normalized`: String(60), nullable, indexed
- `metadata`: JSON (default `{}`)
- `last_contact_at`: DateTime(timezone=True), nullable
- `created_at`: DateTime(timezone=True)
- `updated_at`: DateTime(timezone=True)

**Indexes:**
- `ix_customers_org`: `(organization_id)`
- `ix_customers_org_email_norm`: `(organization_id, email_normalized)`
- `ix_customers_org_phone_norm`: `(organization_id, phone_normalized)`

### 2.2 Conversation Model (`apps/api/app/models/conversation.py`)
- `id`: UUID (Primary Key)
- `organization_id`: UUID (Foreign Key -> `organizations.id` ON DELETE CASCADE, indexed)
- `customer_id`: UUID (Foreign Key -> `customers.id` ON DELETE SET NULL, nullable, indexed)
- `lead_id`: UUID (Foreign Key -> `leads.id` ON DELETE SET NULL, nullable, indexed)
- `channel`: Enum(`InboundChannel` / `Channel`)
- `status`: Enum(`ConversationStatus`: `OPEN`, `CLOSED`, `ARCHIVED`)
- `waiting_on`: Enum(`WaitingOn`: `OWNER`, `CUSTOMER`, `SYSTEM`, `NONE`)
- `subject`: String(255), nullable
- `external_thread_id`: String(255), nullable
- `last_message_at`: DateTime(timezone=True), nullable
- `last_inbound_at`: DateTime(timezone=True), nullable
- `last_outbound_at`: DateTime(timezone=True), nullable
- `created_at`: DateTime(timezone=True)
- `updated_at`: DateTime(timezone=True)

**Indexes:**
- `ix_conversations_org_status`: `(organization_id, status)`
- `ix_conversations_org_customer`: `(organization_id, customer_id)`
- `ix_conversations_org_lead`: `(organization_id, lead_id)`
- `ix_conversations_org_last_msg`: `(organization_id, last_message_at)`

### 2.3 ConversationMessage Model (`apps/api/app/models/conversation_message.py`)
- `id`: UUID (Primary Key)
- `organization_id`: UUID (Foreign Key -> `organizations.id` ON DELETE CASCADE, indexed)
- `conversation_id`: UUID (Foreign Key -> `conversations.id` ON DELETE CASCADE, indexed)
- `direction`: Enum(`MessageDirection`: `INBOUND`, `OUTBOUND`)
- `channel`: Enum(`InboundChannel` / `Channel`)
- `sender_type`: Enum(`MessageSenderType`: `CUSTOMER`, `OWNER`, `SYSTEM`, `AI`)
- `body`: Text
- `external_message_id`: String(255), nullable
- `delivery_status`: Enum(`MessageDeliveryStatus`: `PENDING`, `SENT`, `DELIVERED`, `READ`, `FAILED`), nullable
- `metadata`: JSON (default `{}`)
- `sent_at`: DateTime(timezone=True)
- `created_at`: DateTime(timezone=True)

**Indexes & Constraints:**
- `ix_conv_messages_org_conv`: `(organization_id, conversation_id)`
- `ix_conv_messages_sent`: `(conversation_id, sent_at)`
- UniqueConstraint: `(organization_id, channel, external_message_id)` named `uq_conv_messages_external`

### 2.4 Lead Model Updates (`apps/api/app/models/lead.py`)
- `customer_id`: UUID (Foreign Key -> `customers.id` ON DELETE SET NULL, nullable, indexed)
- `primary_conversation_id`: UUID (Foreign Key -> `conversations.id` ON DELETE SET NULL, nullable, indexed)

---

## 3. Service Layer Architecture

### 3.1 CustomerService (`apps/api/app/services/customer.py`)
- **Matching Priority within Organization:**
  1. `phone_normalized` match against `Customer.phone_normalized`
  2. `email_normalized` match against `Customer.email_normalized`
- **Conflict Handling:**
  - If incoming phone matches Customer A and incoming email matches Customer B:
    - Do NOT merge customer records.
    - Deterministically reuse Customer A (phone prioritized as primary mobile identity).
    - Log identity conflict warning.
- **Normalization:**
  - Phone normalized using `app.core.phone.normalize_phone_number` and organization's `default_phone_region`.
  - Email normalized using `.strip().lower()`.

### 3.2 ConversationService (`apps/api/app/services/conversation.py`)
- **Conversation Reuse Rule:**
  - If an `OPEN` conversation exists for the same `(organization_id, customer_id, channel)`:
    - If associated with an open lead or created within duplicate window -> reuse it.
  - Otherwise, create a new `Conversation`.
- **Message Appending:**
  - `append_inbound_message()`: checks `external_message_id` for idempotency, sets `waiting_on=WaitingOn.OWNER`, updates `last_inbound_at` and `last_message_at`.
  - `append_outbound_message()`: records outbound message (e.g. system email acknowledgement), sets `waiting_on=WaitingOn.CUSTOMER`, updates `last_outbound_at` and `last_message_at`.

### 3.3 InboundLeadService Refactoring
```text
Inbound Request
    ↓
Check Idempotency (external_message_id)
    ↓
CustomerService.find_or_create_customer()
    ↓
ConversationService.get_or_create_open_conversation()
    ↓
ConversationService.append_inbound_message()
    ↓
(Keep InboundMessage for historical audit/compatibility)
    ↓
AI Information Extraction
    ↓
Find or Create Lead (linked to customer_id & primary_conversation_id)
    ↓
Commit Lead & Messages
    ↓
Send Acknowledgement & record OUTBOUND ConversationMessage
```

---

## 4. Migration & Backfill Strategy (0004)

1. **Schema Creation:**
   - Create tables `customers`, `conversations`, `conversation_messages`.
   - Add nullable foreign keys `customer_id` and `primary_conversation_id` to `leads`.
2. **Backfill:**
   - For existing leads in `leads`:
     - Group by `organization_id` and contact information to create distinct `Customer` rows.
     - Associate `leads.customer_id`.
     - Create a historical `Conversation` for each lead.
     - Associate `leads.primary_conversation_id`.
   - For existing `inbound_messages`:
     - Populate corresponding `conversation_messages` under the lead's conversation.
3. **Safety:**
   - Nullable foreign keys ensure zero downtime and total backward compatibility.
   - Deleting a Lead never deletes Customer or Conversation history (`ondelete="SET NULL"`).

---

## 5. Normalized Future Adapter Contract

Future channel connectors (WhatsApp, Email inbox, Instagram, Phone/SMS) must conform to this canonical contract:

```python
@dataclass(frozen=True)
class NormalizedInboundMessage:
    organization_id: uuid.UUID
    channel: InboundChannel  # WEBSITE_FORM, WEBSITE_WEBHOOK, WHATSAPP, EMAIL, etc.
    customer_name: str
    customer_email: str | None
    customer_phone: str | None
    body: str
    external_message_id: str | None = None
    external_thread_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    received_at: datetime | None = None
```

All channel adapters transform provider-specific webhooks into `NormalizedInboundMessage` and invoke the same `InboundLeadService` / `ConversationService`.

---

## 6. Backward Compatibility & InboundMessage Deprecation Path

- `InboundMessage` remains populated during Phase 2.5B to avoid breaking existing event logs or direct query assumptions.
- `GET /leads/{lead_id}/messages` continues to function seamlessly.
- New endpoints `GET /conversations`, `GET /conversations/{id}`, `GET /conversations/{id}/messages`, `GET /customers`, and `GET /customers/{id}` provide direct access to the new domain models.
- `InboundMessage` is marked deprecated and scheduled for transition in a future cleanup phase after all reads switch to `ConversationMessage`.

---

## 7. Risks & Mitigations

| Risk | Mitigation |
| :--- | :--- |
| Circular cascades between Lead and Conversation | `ondelete="SET NULL"` on cross-references. |
| Accidental cross-tenant customer matching | All queries strictly scoped by `organization_id`. |
| Conflict when phone matches Customer A but email matches Customer B | Deterministic rule: reuse phone match, log conflict, never merge records silently. |
| Inbound form/webhook regression | All 32 existing tests must continue passing untouched. |

---

## 8. Verification Results

- **Alembic Migrations:**
  - Forward: `20261015_0003` -> `20261016_0004 (head)` applied cleanly.
  - Rollback: `20261016_0004` -> `20261015_0003` downgraded cleanly.
  - Fresh upgrade: Re-applied `20261016_0004` cleanly with 0 errors.
- **Backend Tests:**
  - 38/38 tests passed (`pytest`).
  - Added `test_conversations.py` with multi-tenant isolation, matching priority, idempotency, and API route tests.
  - All 32 existing tests continue to pass with zero regressions.
- **Backend Linting:**
  - `ruff check .` passed with 0 errors.
- **Frontend Verification:**
  - `vitest`: 5/5 tests passed across 4 test suites.
  - `tsc --noEmit`: Clean, 0 type errors.
  - `eslint .`: Clean, 0 warnings/errors.
  - `next build`: Optimized production bundle built successfully.
