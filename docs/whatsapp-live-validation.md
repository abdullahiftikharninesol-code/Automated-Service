# Meta WhatsApp Cloud API — Live Validation & Operations Guide

This document provides exact, comprehensive, step-by-step instructions for the human operator to connect Missed Lead Rescue to a real Meta WhatsApp Business Cloud API environment and validate live end-to-end communication with real phones.

---

## 1. Meta Developer Portal Setup (Graph API v22.0)

Follow these exact steps in the Meta Developers console:

### Step 1: Open Meta Developers Console
1. Navigate to [developers.facebook.com](https://developers.facebook.com/) and sign in.
2. Click **My Apps** in the top right navigation.

### Step 2: App Selection or Creation
1. If you do not have an existing app:
   - Click **Create App**.
   - Select **Other** as the use case -> Click **Next**.
   - Select App Type: **Business** -> Click **Next**.
   - Provide an App Name (e.g., `Missed Lead Rescue Pilot`) and associate your Business Account.
   - Click **Create App**.

### Step 3: Add WhatsApp Product
1. From the App Dashboard left sidebar, navigate to **Add Product** or scroll to find **WhatsApp**.
2. Click **Set Up** on the WhatsApp card.
3. This creates a WhatsApp Business Account (WABA) sandbox automatically.

### Step 4: Locate Test / Connected Phone Number
1. In the left navigation, click **WhatsApp** -> **API Setup** (or **Getting Started**).
2. Locate the following identifiers:
   - **Phone Number ID:** (A numeric string, e.g., `105554443332221`)
   - **WhatsApp Business Account ID (WABA ID):** (A numeric string, e.g., `109998887776665`)
   - **From Phone Number:** (Meta's test sender number, e.g., `+1 555-025-xxxx`)

### Step 5: Generate Access Token
1. **For Immediate Development (24-hour token):**
   - On the **API Setup** page, copy the **Temporary access token**.
2. **For Pilot / Production (Permanent System User Token):**
   - Go to [business.facebook.com/settings](https://business.facebook.com/settings).
   - Under **Users** -> **System Users**, click **Add**.
   - Name the user (e.g., `lead-rescue-bot`) and set role to **Admin**.
   - Click **Add Assets** -> assign the Meta App and the WhatsApp Account.
   - Click **Generate New Token**:
     - Select your App.
     - Token expiration: **Never**.
     - Permissions required:
       * `whatsapp_business_messaging`
       * `whatsapp_business_management`
   - Copy and securely store the generated token.

### Step 6: App Secret
1. In the Meta Developers console, go to **App Settings** -> **Basic**.
2. Next to **App Secret**, click **Show** (you may be prompted for your Facebook password).
3. Copy the App Secret. This is used by our backend to verify the cryptographic HMAC signature (`X-Hub-Signature-256`) on incoming webhooks.

### Step 7: Verify Token
1. Choose an arbitrary random string for the verification handshake (e.g., `mr-lead-rescue-prod-verify-99182`).

---

## 2. HTTPS Tunneling for Local Validation

Meta cannot reach `http://localhost:8000` directly. A public HTTPS callback URL is required.

### Recommended Option: Cloudflare Tunnel (`cloudflared`)
Cloudflare Tunnel is free, fast, does not expire sessions, and requires no registration:
```bash
# Expose port 8000
cloudflared tunnel --url http://localhost:8000
```
Output will display a temporary public domain, for example:
`https://rapid-silver-alpha.trycloudflare.com`

### Alternative Option: ngrok
```bash
ngrok http 8000
```
Output will display:
`https://1234-56-78-90.ngrok-free.app`

### Canonical Callback URL
Your Meta Webhook Callback URL is:
```text
https://<your-tunnel-domain>/webhooks/whatsapp
```
*(Example: `https://rapid-silver-alpha.trycloudflare.com/webhooks/whatsapp`)*

---

## 3. Webhook Configuration & Handshake

1. In the Meta Developers console, go to **WhatsApp** -> **Configuration**.
2. Beside **Webhook**, click **Edit**:
   - **Callback URL:** `https://<your-tunnel-domain>/webhooks/whatsapp`
   - **Verify Token:** The verify token configured in your `.env` (`META_WHATSAPP_VERIFY_TOKEN`).
3. Click **Verify and Save**.
   - Meta sends a `GET` request with `hub.mode=subscribe`, `hub.verify_token`, and `hub.challenge`.
   - The backend validates the token using constant-time comparison and returns the plaintext challenge with HTTP 200.
4. Under **Webhook Fields**, click **Manage**:
   - Check the box for `messages`.
   - Click **Done**.
   *(Note: The `messages` field delivers all customer inbound text, images, and message status receipts like `sent`, `delivered`, and `read`).*

---

## 4. Test Recipient Setup (Sandbox Mode)

If using Meta's Test Phone Number (sandbox mode):
1. Go to **WhatsApp** -> **API Setup**.
2. Under **Step 5: Select phone numbers**, locate the **To** field.
3. Click **Manage phone number list**.
4. Add your real WhatsApp phone number (with country code, e.g., `+92 300 1234567` or `+1 512 555 0199`).
5. Meta will send a 6-digit verification code to your WhatsApp. Enter the code to verify your number.
6. Only verified test numbers can send and receive messages with the test sandbox number.

---

## 5. Environment Configuration Summary

Update `.env` in the repository root:
```dotenv
# WhatsApp Integration Flags
WHATSAPP_ENABLED=true
WHATSAPP_PROVIDER=meta
META_GRAPH_API_VERSION=v22.0

# Meta Credentials
META_WHATSAPP_ACCESS_TOKEN=<your-system-user-or-temp-token>
META_APP_SECRET=<your-meta-app-secret>
META_WHATSAPP_VERIFY_TOKEN=<your-verify-token>
META_WHATSAPP_PHONE_NUMBER_ID=<your-meta-phone-number-id>
META_WHATSAPP_BUSINESS_ACCOUNT_ID=<your-meta-waba-id>

# Background Jobs & Reminders
BACKGROUND_JOBS_ENABLED=true
REMINDER_SWEEP_INTERVAL_SECONDS=60
```

Run the readiness audit:
```powershell
.\apps\api\.venv\Scripts\python.exe scripts/check_live_readiness.py
```
Ensure all items report `PASS` / `CONFIGURED` and status is `LIVE READINESS: READY`.

---

## 6. Seed Demo Business Organization

Map the Demo Business to Meta's receiving phone number ID:
```powershell
.\apps\api\.venv\Scripts\python.exe scripts/setup_demo_business.py --phone-id <your-meta-phone-number-id> --waba-id <your-meta-waba-id>
```

This binds:
- Organization name: `Demo Business`
- Business type: `GENERAL`
- WhatsApp receiving phone number ID matching Meta
- 3 generic qualification fields: `customer_need`, `preferred_date`, `location`
- Demo owner login: `demo@example.com` / `DemoPassword123!`

---

## 7. Execution Checklist for Live Pilot Validation

| Step | Action | Expected Result | Verified |
| :--- | :--- | :--- | :--- |
| **1** | Start local backend (`uvicorn app.main:app --port 8000`) | API healthy at `http://localhost:8000/health` | [ ] |
| **2** | Start HTTPS tunnel | Public URL generated | [ ] |
| **3** | Save Webhook in Meta Developers portal | Verification handshake succeeds (HTTP 200) | [ ] |
| **4** | Subscribe to `messages` field | Subscription active in Meta Dashboard | [ ] |
| **5** | Send test message from phone ("Hi, I need help.") | Inbound webhook received, clarification question sent back to phone | [ ] |
| **6** | Reply from phone with missing details ("Friday in Islamabad.") | Second clarification or confirmation message received on phone | [ ] |
| **7** | Reply with needed service ("Consultation service.") | Qualification COMPLETE, confirmation sent, lead shows in dashboard | [ ] |
| **8** | Inspect owner dashboard (`http://localhost:3000/leads`) | Lead appears with extracted fields and full conversation thread | [ ] |
| **9** | Owner replies from dashboard | Real WhatsApp message arrives on customer phone | [ ] |
| **10** | Observe status callbacks | Delivery statuses update: `SENT` -> `DELIVERED` -> `READ` | [ ] |
| **11** | Verify reminder cancellation | Owner reply automatically cancels pending reminder | [ ] |

---

## 8. Common Meta Cloud API Troubleshooting

### 1. HTTP 403 on Inbound Webhook (`Invalid webhook signature`)
- **Cause:** `META_APP_SECRET` in `.env` does not match the App Secret of the Meta App sending the webhook.
- **Fix:** Copy the App Secret from **App Settings** -> **Basic** in Meta Developers console.

### 2. HTTP 401 on Outbound Message (`OAuthException: Error validating access token`)
- **Cause:** Temporary access token has expired (24h lifespan).
- **Fix:** Generate a new temporary token or create a permanent System User token.

### 3. HTTP 400 on Outbound Message (`Recipient phone number not in allowed list`)
- **Cause:** Using a sandbox test number to message an unverified personal phone.
- **Fix:** Go to **WhatsApp** -> **API Setup** in Meta portal and add the customer phone number to the allowed recipient list.

### 4. Monotonic Status Warning in Logs (`Ignored redundant or regressional status`)
- **Behavior:** Meta occasionally delivers callbacks out-of-order (e.g. `delivered` after `read`).
- **Explanation:** Missed Lead Rescue strictly enforces forward-only status rank progression (`PENDING` < `SENT` < `DELIVERED` < `READ`). Regressive callbacks are safely ignored and logged.
