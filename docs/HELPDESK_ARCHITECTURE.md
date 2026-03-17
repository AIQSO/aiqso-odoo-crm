# Helpdesk Architecture — Zammad + Odoo Integration

## Overview

AIQSO uses **Zammad** (helpdesk.aiqso.io) as the dedicated helpdesk system, integrated with **Odoo CRM** via n8n workflows. Odoo 19 Community Edition does not include a Helpdesk module (Enterprise-only), so Zammad provides best-of-breed ticketing while Odoo handles CRM, invoicing, and projects.

**MeshCentral** (mesh.aiqso.io) provides remote desktop access during support sessions.

## Architecture Diagram

```
Customer submits ticket
        ↓
    ┌───────────┐         ┌──────────────┐
    │  Zammad    │────────→│  n8n         │
    │  LXC 242   │ webhook │  automation  │
    │  :8080     │         │  .aiqso.io   │
    └───────────┘         └──────┬───────┘
                                 │
                    ┌────────────┼────────────┐
                    ↓            ↓             ↓
              ┌──────────┐ ┌─────────┐ ┌──────────┐
              │ Odoo CRM  │ │ Slack   │ │ ntfy     │
              │ LXC 237   │ │ #crm-   │ │ push     │
              │ :8069     │ │ updates │ │ notifs   │
              └──────────┘ └─────────┘ └──────────┘
```

## Services

| Service | URL | Container | Purpose |
|---------|-----|-----------|---------|
| **Zammad** | https://helpdesk.aiqso.io | LXC 242 (192.168.0.242) | Ticket management, customer portal |
| **Odoo CRM** | https://crm.aiqso.io | LXC 237 (192.168.0.237) | Lead tracking, invoicing, projects |
| **MeshCentral** | https://mesh.aiqso.io | - | Remote desktop support sessions |
| **n8n** | https://automation.aiqso.io | - | Workflow automation |

## Email Routing

| Email | Destination | Creates |
|-------|-------------|---------|
| helpdesk@aiqso.io | Gmail → "Support" label → Zammad | Zammad ticket |
| support@aiqso.io | Gmail → "Support" label → Zammad | Zammad ticket |
| info@aiqso.io | Gmail → Odoo fetchmail (IMAP) | CRM lead |

## n8n Workflows

### Active

| Workflow | File | Webhook | Purpose |
|----------|------|---------|---------|
| Zammad → Odoo Sync | `zammad-odoo-sync.json` | `/webhook/zammad-ticket` | New ticket → Odoo lead (no-email) + Slack |
| Zammad Close Sync | `zammad-ticket-close-sync.json` | `/webhook/zammad-ticket-closed` | Closed ticket → log note on Odoo lead + Slack |
| Odoo Won → Zammad | `odoo-client-won-to-zammad.json` | Hourly schedule | Won lead → create Zammad customer |
| Slack Notifications | (existing) | `/webhook/zammad-slack` | Ticket → Slack #crm-updates |

### Email Loop Prevention

The Zammad → Odoo workflow uses Odoo's context flags to prevent notification emails:

```python
context = {
    'mail_create_nosubscribe': True,  # Don't auto-subscribe followers
    'mail_create_nolog': True,        # Don't create "Lead created" log
    'mail_notrack': True,             # Don't track field changes
    'tracking_disable': True,         # Disable all tracking
}
```

This was the fix for the 2025-12-31 email loop incident (1,075 spam tickets).

## Zammad Configuration

### Triggers (in Zammad admin)

| Trigger | Webhook | Fires When |
|---------|---------|------------|
| New Ticket → Odoo | `/webhook/zammad-ticket` | Ticket created (state = new) |
| Ticket Closed → Odoo | `/webhook/zammad-ticket-closed` | Ticket state changed to closed |
| Slack Notification | `/webhook/zammad-slack` | Any new ticket |

### Postmaster Filters (13 active)

Block automated emails from creating tickets: no-reply senders, CI/CD failures, login notifications, payment alerts, social media, newsletters, Google services. Reduces noise by ~85-90%.

## Embedding Zammad on External Sites

### Ticket Form Widget

Add to any page (e.g., crm.aiqso.io portal):

```html
<!-- In <head> -->
<script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>

<!-- Before </body> -->
<script id="zammad_form_script"
  src="https://helpdesk.aiqso.io/assets/form/form.js"></script>
<script>
$(function() {
  $('#support-form').ZammadForm({
    messageTitle: 'Contact AIQSO Support',
    messageSubmit: 'Submit Ticket',
    messageThankYou: 'Thank you! Your ticket number is #%s. We will respond shortly.',
    modal: true,
    showTitle: true,
    attachmentSupport: true
  });
});
</script>
<button id="support-form">Get Support</button>
```

### Live Chat Widget

Enable in Zammad admin → Channels → Chat. Only shows when agents are online.

```html
<script src="https://helpdesk.aiqso.io/assets/chat/chat.min.js"></script>
<script>
$(function() {
  new ZammadChat({
    chatId: 1,
    background: '#0a1628',
    fontSize: '12px'
  });
});
</script>
```

## MCP Server Tools

The Odoo CRM MCP server (v1.1.0) includes helpdesk-aware tools:

| Tool | Purpose |
|------|---------|
| `search_support_tickets` | Find CRM leads created from Zammad tickets |
| `create_lead_silent` | Create lead without notification emails |
| `support_summary` | Ticket counts by Odoo pipeline stage |

## Setup Checklist

- [x] Zammad running on LXC 242
- [x] Email routing (helpdesk@, support@ → Zammad)
- [x] Postmaster filters (13 active)
- [x] Slack notifications working
- [x] MeshCentral for remote access
- [ ] Zammad → Odoo n8n workflow (re-enable with no-email context)
- [ ] Zammad ticket close → Odoo note workflow (new)
- [ ] Odoo won → Zammad customer workflow (new)
- [ ] Zammad triggers configured for new webhooks
- [ ] Zammad ticket form embedded on crm.aiqso.io
- [ ] ZAMMAD_API_TOKEN added to n8n environment
