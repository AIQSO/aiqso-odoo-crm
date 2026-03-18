# Helpdesk Integration — Next Steps

**Date:** 2026-03-17
**Status:** Workflows built, not yet activated

---

## What's Done

- [x] Decided architecture: Zammad (helpdesk.aiqso.io) + Odoo CRM via n8n
- [x] Built 3 n8n workflow JSONs with Config node (no env vars needed)
- [x] Updated MCP server to v1.1.0 with helpdesk tools
- [x] Wrote architecture docs (`docs/HELPDESK_ARCHITECTURE.md`)
- [x] Verified email loop fix works (Odoo context flags tested on live instance)
- [x] Imported workflows into n8n (inactive)

---

## Tomorrow's Tasks

### 1. Configure Workflow Credentials (5 min each)

Open each workflow in n8n and edit the **first Code node** ("Config"):

**Workflow: Zammad → Odoo Ticket Sync**
- Replace `REPLACE_WITH_YOUR_ODOO_API_KEY` with your Odoo API key

**Workflow: Zammad Ticket Closed → Odoo Update**
- Replace `REPLACE_WITH_YOUR_ODOO_API_KEY` with your Odoo API key

**Workflow: Odoo Client Won → Create Zammad Customer**
- Replace `REPLACE_WITH_YOUR_ODOO_API_KEY` with your Odoo API key
- Replace `REPLACE_WITH_YOUR_ZAMMAD_API_TOKEN` with your Zammad token
  - Get it from: Zammad → Profile (top right) → Token Access → Create token
  - Permissions needed: `ticket.agent`, `admin.user`

### 2. Connect Slack Credentials (2 min each)

Each workflow has Slack nodes. After import, open each Slack node and select your existing Slack OAuth2 credential from the dropdown. The channel `#crm-updates` is already set.

### 3. Create Zammad Webhooks (5 min)

In Zammad admin (https://helpdesk.aiqso.io) → Manage → Webhooks → Add:

| Name | Endpoint |
|------|----------|
| Odoo Ticket Sync | `https://automation.aiqso.io/webhook/zammad-ticket` |
| Odoo Ticket Close | `https://automation.aiqso.io/webhook/zammad-ticket-closed` |

### 4. Create Zammad Triggers (5 min)

In Zammad admin → Manage → Triggers → Add:

**Trigger 1: "New Ticket → Odoo"**
- Conditions: Ticket → State → is → new
- Execute: Notification → Webhook → select "Odoo Ticket Sync"

**Trigger 2: "Ticket Closed → Odoo"**
- Conditions: Ticket → State → has changed to → closed
- Execute: Notification → Webhook → select "Odoo Ticket Close"

### 5. Test (10 min)

**Test the sync workflow first:**
1. Activate "Zammad → Odoo Ticket Sync" in n8n
2. Create a test ticket in Zammad:
   ```bash
   curl -X POST "https://helpdesk.aiqso.io/api/v1/tickets" \
     -H "Authorization: Token token=YOUR_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"title":"Test Integration","group":"Users","customer_id":3,"article":{"body":"Testing Odoo sync","type":"note"}}'
   ```
3. Check: Odoo should have a new lead named `[Zammad #XXXXX] Test Integration`
4. Check: Slack #crm-updates should have a notification
5. If it works, delete the test lead in Odoo

**Test the close workflow:**
1. Activate "Zammad Ticket Closed → Odoo Update" in n8n
2. Close the test ticket in Zammad
3. Check: The Odoo lead should have a close note in its chatter

**Test the Won → Zammad workflow:**
1. Activate "Odoo Client Won → Create Zammad Customer"
2. Move a test lead to "Won" stage in Odoo (must have an email)
3. Wait up to 1 hour (or manually trigger the workflow in n8n)
4. Check: Zammad should have a new customer

### 6. Optional: Embed Zammad Form on crm.aiqso.io (15 min)

Add the ticket submission form to the Odoo portal. See `docs/HELPDESK_ARCHITECTURE.md` for the embed code.

Steps:
1. In Zammad admin → Channels → Form → Enable
2. Copy the generated JS snippet
3. In Odoo → Website → Edit → add HTML block with the Zammad form script
4. Or add it to the portal template via Odoo's website editor

### 7. Update CLAUDE.md (2 min)

Add to the Project Overview section:
```
- Service integrations (Cloudflare, Listmonk, Zammad Helpdesk)
- Helpdesk integration (Zammad ↔ Odoo via n8n)
```

Add to Key Files table:
```
| docs/HELPDESK_ARCHITECTURE.md | Zammad ↔ Odoo helpdesk integration |
```

---

## Credentials Quick Reference

| Credential | Where to Find |
|------------|---------------|
| Odoo API Key | `.env` in this repo, or Bitwarden "Odoo API" |
| Zammad API Token | Zammad → Profile → Token Access (create new if needed) |
| Slack OAuth2 | Already configured in n8n (reuse existing) |
| n8n API Key | Settings → n8n API in the n8n UI |

## Architecture Reference

See `docs/HELPDESK_ARCHITECTURE.md` for:
- Full architecture diagram
- Email routing table
- Zammad embed code (form + live chat)
- Email loop prevention details
- MCP server tools

## Key URLs

| Service | URL |
|---------|-----|
| Zammad | https://helpdesk.aiqso.io |
| Odoo CRM | https://crm.aiqso.io |
| n8n | https://automation.aiqso.io |
| MeshCentral | https://mesh.aiqso.io |
| Slack | #crm-updates channel |
