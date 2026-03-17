# Configuration

This repo avoids hardcoding credentials. Configure connections via environment variables (preferred) or CLI flags.

## Odoo (XML-RPC)

Environment variables:

- `ODOO_URL` (example: `http://192.168.0.237:8069`)
- `ODOO_DB`
- `ODOO_USERNAME`
- `ODOO_API_KEY`

CLI flags (where supported):

- `--url`
- `--db`
- `--username`
- `--api-key`

## PostgreSQL (enrichment sync)

Environment variables:

- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`

CLI flags (supported by `scripts/sync_enriched_leads.py`):

- `--pg-host`
- `--pg-port`
- `--pg-db`
- `--pg-user`
- `--pg-password`

## Example

```bash
cp .env.example .env
set -a; source .env; set +a
python3 scripts/import_lead_list.py /path/to/leads.csv --industry "Construction"
```
