# AIQSO Customer Portal Integration Guide

> **Version**: 1.0.0
> **Last Updated**: 2025-12-30
> **CI/CD Pipeline**: GitHub Actions with self-hosted runner

## Executive Summary

Integrate Odoo 17 customer portal with AIQSO website, n8n automation, and AI services to provide a seamless customer experience for billing, service access, and support. This guide creates a production-ready CI/CD pipeline that can be built, monitored, maintained, and enhanced.

## Current State Assessment

### What's Already Built

| Component | Status | Location |
|-----------|--------|----------|
| Odoo 17 CRM | Running (147 modules) | LXC 230 (192.168.0.230:8069) |
| Portal Module | Installed but unconfigured | Odoo |
| eCommerce Module | Installed | Odoo |
| Payment Engine | Installed (providers disabled) | Odoo |
| n8n Automation | 45+ active workflows | LXC 232 |
| Odoo Python SDK | v0.8.0 | ~/projects/odoo/ |
| Website Auth | JWT + OAuth | ~/projects/aiqso-website/ |
| AI Server | Ollama (29 models) | 192.168.0.234 |

### What's Being Built

1. Payment provider configuration (Stripe)
2. Portal users and invitation flow
3. Products/services catalog in Odoo
4. Payment automation workflows in n8n
5. Website ↔ Odoo portal integration
6. Customer self-service features
7. CI/CD pipeline for Odoo customizations

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          CUSTOMER TOUCHPOINTS                           │
├─────────────────────────────────────────────────────────────────────────┤
│  aiqso.io          portal.aiqso.io       cal.aiqso.io    crm.aiqso.io  │
│  (Marketing)       (Customer Portal)     (Bookings)      (Admin CRM)   │
└────────┬──────────────────┬─────────────────┬────────────────┬─────────┘
         │                  │                 │                │
         ▼                  ▼                 ▼                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         AUTOMATION LAYER (n8n)                          │
├─────────────────────────────────────────────────────────────────────────┤
│  Contact Forms → Lead Creation → Notifications → AI Classification     │
│  Payments → Invoice Gen → Fulfillment → Customer Onboarding           │
│  Bookings → Calendar Sync → Zoom Links → Follow-up Sequences          │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         ▼                       ▼                       ▼
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│   Odoo CRM      │   │   Listmonk      │   │   AI Server     │
│   (LXC 230)     │   │   (LXC 231)     │   │   (Ollama)      │
├─────────────────┤   ├─────────────────┤   ├─────────────────┤
│ • Contacts      │   │ • Newsletters   │   │ • Lead Scoring  │
│ • Leads         │   │ • Campaigns     │   │ • Chat Support  │
│ • Invoices      │   │ • Subscribers   │   │ • RAG Docs      │
│ • Products      │   │ • Automations   │   │ • Classification│
│ • Payments      │   └─────────────────┘   └─────────────────┘
│ • Portal Users  │
└─────────────────┘
```

## Quick Start

```bash
# 1. Ensure you're in the odoo project
cd ~/projects/odoo

# 2. Activate virtual environment
source venv/bin/activate

# 3. Configure environment
cp .env.example .env
# Edit .env with your credentials

# 4. Create products in Odoo
python scripts/create_products.py

# 5. Run health check
python scripts/health_check.py
```

## Implementation Phases

### Phase 1: Odoo Configuration (Week 1)
- [ ] Enable Stripe payment provider
- [ ] Configure portal.aiqso.io domain
- [ ] Create AIQSO products/services catalog
- [ ] Set up customer invitation workflow
- [ ] Configure email templates

### Phase 2: n8n Payment Workflows (Week 2)
- [ ] Stripe webhook handlers
- [ ] Invoice generation automation
- [ ] Payment confirmation notifications
- [ ] Failed payment retry logic
- [ ] Subscription lifecycle management

### Phase 3: Website Integration (Week 3)
- [ ] Implement Odoo portal redirect/SSO
- [ ] Add payment UI components
- [ ] Sync invoice data to client portal
- [ ] Implement download delivery system
- [ ] Customer dashboard enhancements

### Phase 4: AI Enhancement (Week 4)
- [ ] Customer support chatbot (RAG)
- [ ] Lead scoring automation
- [ ] Personalized recommendations
- [ ] Automated follow-up sequences

### Phase 5: CI/CD & Monitoring (Week 5)
- [ ] Deployment automation
- [ ] Health checks and alerts
- [ ] Backup automation
- [ ] Performance monitoring

## Products/Services Catalog

| Product | Code | Type | Price | Delivery |
|---------|------|------|-------|----------|
| Lead Generation List - DFW | LEAD-DFW | Service | $149/mo | Download |
| Lead Generation List - Multi-City | LEAD-MULTI | Service | $299/mo | Download |
| AI Automation Consultation | CONSULT-AI | Service | $199/hr | Booking |
| SEO Audit Report | SEO-AUDIT | Service | $499 | Delivery |
| Custom Workflow Development | DEV-WORKFLOW | Service | $150/hr | Project |
| Enterprise Support Plan | SUPPORT-ENT | Subscription | $999/mo | Ongoing |

## Environment Variables

Required environment variables in `.env`:

```bash
# Odoo
ODOO_URL=https://crm.aiqso.io
ODOO_DB=aiqso_db
ODOO_USERNAME=quinn@aiqso.io
ODOO_API_KEY=<from-odoo-settings>

# Stripe
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PUBLISHABLE_KEY=pk_live_...

# n8n
N8N_URL=https://automation.aiqso.io
N8N_API_KEY=<your-n8n-api-key>
N8N_STRIPE_WEBHOOK=https://automation.aiqso.io/webhook/stripe
N8N_INVOICE_WEBHOOK=https://automation.aiqso.io/webhook/invoice-created
N8N_ONBOARD_WEBHOOK=https://automation.aiqso.io/webhook/customer-onboard

# Portal
PORTAL_DOMAIN=portal.aiqso.io
```

## Critical Integration Points

### 1. Stripe → Odoo → n8n Flow

```
Customer pays on portal.aiqso.io
  → Stripe processes payment
  → Webhook to n8n (/webhook/stripe)
  → n8n creates Odoo invoice (paid)
  → n8n triggers fulfillment workflow
  → Customer receives confirmation + downloads
```

### 2. Website Auth → Odoo Portal

**Recommended Approach**: Embed Odoo data in aiqso.io/client-portal (seamless UX, single domain)

```
User logs into aiqso.io
  → Website fetches customer data from Odoo
  → Displays invoices, subscriptions, downloads
  → All on same domain (no redirect)
```

### 3. AI Support Integration

```
Customer asks question in portal
  → n8n receives chat message
  → RAG search against AIQSO docs
  → Ollama generates response
  → Response sent to customer
  → If escalation needed → Create Odoo ticket
```

## Scripts Reference

### `scripts/create_products.py`
Creates the AIQSO service catalog in Odoo. Idempotent - safe to run multiple times.

```bash
python scripts/create_products.py
```

### `scripts/setup_stripe.py`
Enables and configures the Stripe payment provider in Odoo.

```bash
STRIPE_SECRET_KEY=sk_live_xxx STRIPE_PUBLISHABLE_KEY=pk_live_xxx python scripts/setup_stripe.py
```

### `scripts/invite_portal_user.py`
Invites a customer to the Odoo portal.

```bash
python scripts/invite_portal_user.py customer@example.com "Customer Name" "Company Inc"
```

### `scripts/health_check.py`
Verifies all integrations are working correctly.

```bash
python scripts/health_check.py
```

## n8n Workflows

| Workflow | File | Purpose |
|----------|------|---------|
| Stripe Payment Webhook | `n8n-workflows/stripe-webhook.json` | Handle Stripe payment events |
| Customer Onboarding | `n8n-workflows/customer-onboard.json` | Welcome sequence for new customers |
| Invoice Created | `n8n-workflows/invoice-created.json` | Invoice notification automation |
| Subscription Management | `n8n-workflows/subscription-mgmt.json` | Subscription lifecycle handling |

## CI/CD Pipeline

### Deployment (`.github/workflows/deploy.yml`)

Triggers on:
- Push to `main` branch (scripts/ or n8n-workflows/ changes)
- Manual workflow dispatch

Actions:
1. Run tests on ubuntu-latest
2. Deploy scripts via self-hosted runner
3. Import n8n workflows
4. Run health checks
5. Notify Slack

### Backups (`.github/workflows/backup.yml`)

Runs daily at 2 AM:
1. Backup Odoo database to Synology NAS
2. Export n8n workflows to NAS
3. Cleanup backups older than 30 days

## Cloudflare Tunnel Configuration

Add to tunnel config:

```yaml
- hostname: portal.aiqso.io
  service: http://192.168.0.230:8069
```

## Testing

### Run Unit Tests
```bash
make test
```

### Run Integration Tests
```bash
pytest -m integration
```

### Run Health Check
```bash
python scripts/health_check.py
```

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Portal signup → first payment | < 5 min | n8n tracking |
| Invoice delivery time | < 1 min | Automation logs |
| Support response time | < 30 sec | AI chatbot |
| Payment success rate | > 95% | Stripe dashboard |
| Customer satisfaction | > 4.5/5 | Portal feedback |

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Stripe API changes | Version lock, webhook validation |
| Odoo upgrade breaks integrations | Test in staging, backup before updates |
| n8n workflow failures | Error handler workflow, Slack alerts |
| Data sync issues | Idempotency keys, reconciliation scripts |

## Rollback Plan

1. Disable Stripe provider in Odoo
2. Redirect portal.aiqso.io to maintenance page
3. Restore from PBS backup (daily snapshots)
4. Revert n8n workflow versions
5. Notify affected customers

## Support

- **Repository**: ~/projects/odoo
- **Documentation**: This file (PORTAL_SETUP.md)
- **Architecture**: See ARCHITECTURE.md
- **Changelog**: See CHANGELOG.md
