# Configuration

## Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

### Available Variables

```bash
# Copy to .env and fill in values, then:
#   set -a; source .env; set +a

# --- Odoo XML-RPC ---
ODOO_URL=http://192.168.0.237:8069
ODOO_DB=aiqso_db
ODOO_USERNAME=quinn@aiqso.io
ODOO_API_KEY=__REPLACE_ME__

# --- PostgreSQL (enrichment sync) ---
POSTGRES_HOST=192.168.0.71
POSTGRES_PORT=5433
POSTGRES_DB=permits_db
POSTGRES_USER=permits
POSTGRES_PASSWORD=__REPLACE_ME__
```
