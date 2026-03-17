# Architecture

## Purpose

This repository contains small, operational scripts that move lead/contact data into an Odoo 19 CRM instance:

- Import CSV lead lists into Odoo Contacts + CRM Leads.
- Import multi-city commercial lead exports into CRM Leads.
- Sync enriched contact details (email/phone/company) from a PostgreSQL database into existing Odoo leads.

## Repository Layout

- `scripts/`
  - `import_lead_list.py`: CSV → Odoo Contacts/Companies + CRM leads.
  - `import_commercial_leads.py`: Commercial CSV → CRM leads grouped per city.
  - `sync_enriched_leads.py`: PostgreSQL → Odoo updates (and optional create).
  - `odoo-sync.sh`: Cron-friendly wrapper that activates `venv/`, loads `.env`, and writes logs.
  - `config.py`: Centralized configuration loader + required-key validation.
- `docs/`: Operational documentation (tag structure, configuration).
- `logs/`: Runtime logs (ignored by git).

## Data Flows

### 1) CSV Lead List Import

1. Read CSV records.
2. Ensure Odoo tags (`res.partner.category`) exist.
3. Ensure “Lead Lists” umbrella company exists, then ensure one “Lead List - …” company exists.
4. Create/update:
   - Companies (`res.partner` with `is_company=True`)
   - Contacts (`res.partner` with `is_company=False`) linked to company (`parent_id`)
   - CRM leads (`crm.lead`) linked to the contact (`partner_id`)

### 2) Enrichment Sync

1. Query PostgreSQL for enriched leads (contact email/phone present).
2. Match Odoo leads by permit number embedded in the lead name (`[PERMIT]`).
3. Update Odoo lead fields and append an “Enriched …” note to the description.
4. Optionally create new Odoo leads when no match exists.

## Configuration & Secrets

All scripts prefer environment variables for credentials. See `docs/CONFIGURATION.md`.

`.env` is supported for local/dev usage and is intentionally ignored by git.

## Operational Assumptions

- Odoo is reachable over HTTP and has XML-RPC enabled.
- The Odoo user has permissions to read/write:
  - `res.partner`, `res.partner.category`, `crm.lead`
- PostgreSQL is reachable from the machine running sync jobs.
