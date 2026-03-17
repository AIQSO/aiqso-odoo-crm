## AIQSO Odoo CRM Automation

[![CI](https://github.com/qvidal01/aiqso-odoo-crm/actions/workflows/ci.yml/badge.svg)](https://github.com/qvidal01/aiqso-odoo-crm/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/qvidal01/aiqso-odoo-crm/graph/badge.svg)](https://codecov.io/gh/qvidal01/aiqso-odoo-crm)

Utility scripts for importing and syncing lead data into an Odoo 19 CRM instance via XML-RPC.

### Contents

- `scripts/import_lead_list.py`: Import a single lead list CSV (companies + contacts + CRM leads).
- `scripts/import_commercial_leads.py`: Import multi-city “commercial_leads” CSV exports.
- `scripts/sync_enriched_leads.py`: Sync enriched contact details from PostgreSQL into Odoo (optionally create missing leads).
- `docs/LEAD_LIST_STRUCTURE.md`: Odoo tag/org structure used by the imports.

### Quick start

1. Setup environment:
   ```bash
   make dev                    # Creates venv, installs deps, sets up pre-commit
   ```
2. Create `.env` from `.env.example` and load it:
   ```bash
   cp .env.example .env
   set -a; source .env; set +a
   ```
3. Run an import:
   ```bash
   python3 scripts/import_lead_list.py /path/to/leads.csv --industry "Construction"
   ```

See `docs/CONFIGURATION.md` for configuration details.

### Development

```bash
make help          # Show all available commands

# Code quality
make check         # Run lint + format + typecheck
make lint-fix      # Auto-fix linting issues
make format-fix    # Auto-format code

# Testing
make test          # Run tests
make coverage      # Run tests with coverage report

# CI
make ci            # Run full CI pipeline locally
```

### Additional docs

- `ARCHITECTURE.md`: Repository layout + data flows.
- `CHANGELOG.md`: Traceable change history.
- `IMPLEMENTATION_NOTES.md`: Rationale for key decisions.
