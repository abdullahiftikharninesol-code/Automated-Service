# WhatsApp Cloud API — Local Development & Setup Guide

This guide walks through configuring Meta's WhatsApp Business Cloud API with Missed Lead Rescue for local development and testing.

---

## 1. Prerequisites

1. A Meta Developer Account at [developers.facebook.com](https://developers.facebook.com/).
2. A Meta App with the **WhatsApp** product added.
3. Access to a Meta Test WhatsApp Business Account (automatically provided in Meta App Dashboard under WhatsApp > API Setup).
4. A tunneling tool to expose your local FastAPI server over public HTTPS:
   - [Cloudflare Tunnel (`cloudflared`)](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) (Recommended: stable, free, no session timeouts)
   - OR [ngrok](https://ngrok.com/)

---

## 2. Local Setup Steps

### Step 1: Start the Backend API
Start the FastAPI server locally:
```powershell
Set-Location apps/api
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```
Verify the API is accessible at `http://localhost:8000/health`.

### Step 2: Expose Backend via HTTPS Tunnel

#### Using Cloudflare Tunnel:
```bash
cloudflared tunnel --url http://localhost:8000
```
This generates a public URL, for example: `https://your-subdomain.trycloudflare.com`.

#### Using ngrok:
```bash
ngrok http 8000
```
This generates a public URL, for example: `https://xxxx-xx-xx.ngrok-free.app`.

### Step 3: Configure Environment Variables
In your `.env` file (copied from `.env.example`):
```dotenv
# Meta WhatsApp Settings
META_GRAPH_API_VERSION=v22.0
META_APP_SECRET=your_meta_app_secret_here
META_WHATSAPP_VERIFY_TOKEN=your_secure_verify_token_here
META_WHATSAPP_ACCESS_TOKEN=your_temporary_or_system_user_token
META_WHATSAPP_PHONE_NUMBER_ID=your_meta_test_phone_number_id
META_WHATSAPP_BUSINESS_ACCOUNT_ID=your_meta_waba_id
WHATSAPP_ENABLED=true
WHATSAPP_PROVIDER=meta  # Use "mock" for offline automated tests
```

### Step 4: Configure Webhook in Meta App Dashboard
1. Go to **developers.facebook.com** -> Your App -> **WhatsApp** -> **Configuration**.
2. Under **Webhook**, click **Edit**:
   - **Callback URL:** `https://your-tunnel-url/webhooks/whatsapp`
   - **Verify Token:** The value of `META_WHATSAPP_VERIFY_TOKEN` configured in your `.env`.
3. Click **Verify and Save**. Meta will dispatch a `GET` challenge to your server. Your API will respond with HTTP 200 and return the challenge string.
4. Under **Webhook Fields**, click **Manage** and subscribe to:
   - `messages` (Mandatory: delivers customer messages and delivery status updates)

### Step 5: Test Inbound Inquiries
1. Under **WhatsApp** -> **API Setup**, add your personal phone number as a test recipient.
2. Open WhatsApp on your phone and send a text message to the Meta Test Number provided in the dashboard.
3. Observe the API terminal logs:
   - Webhook received and signature validated.
   - Organization resolved from receiving `phone_number_id`.
   - Customer created/reused with E.164 normalization.
   - Lead created and AI extraction executed.
   - Automated WhatsApp acknowledgment sent back to your phone.
   - Conversation waiting on `OWNER`.
   - Owner reminder engine scheduled.
4. Check your Missed Lead Rescue dashboard at `http://localhost:3000` to inspect the lead, AI extraction summary, and conversation messages.

---

## 3. Limitations of Meta Test Mode
- Test numbers can only exchange messages with up to 5 verified phone numbers added in the Meta App Dashboard.
- Access tokens generated from the API Setup page expire after 24 hours. For persistent testing, create a System User in Meta Business Suite with the `whatsapp_business_messaging` permission to generate a permanent token.
