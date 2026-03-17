# AIQSO Odoo CRM - Claude Code Reference

## Project Overview

This is the central repository for AIQSO's Odoo 19 CRM system, containing:
- Custom Python client library for Odoo XML-RPC API
- Lead list import/export scripts
- Infrastructure data management
- Service integrations (Cloudflare, Listmonk)
- Backup automation for Synology NAS

## Quick Reference

### Odoo Connection

| Setting | Value |
|---------|-------|
| **URL** | `ODOO_URL` (example: `http://192.168.0.237:8069`) |
| **Database** | `ODOO_DB` |
| **Username** | `ODOO_USERNAME` |
| **API Key** | `ODOO_API_KEY` |

### Key Files

| File | Purpose |
|------|---------|
| `scripts/import_lead_list.py` | Import lead lists from CSV to CRM |
| `docs/LEAD_LIST_STRUCTURE.md` | Lead list organization documentation |

### Common Operations

```bash
# Import lead list
set -a; source .env; set +a
python3 scripts/import_lead_list.py ~/path/to/leads.csv \
    --list-name "List Name" --industry "Construction"

# Test Odoo connection
curl http://192.168.0.237:8069/web/webclient/version_info
```

## Lead List Import

### Structure Overview

```
Lead Lists (Parent Company)
├── Lead List - [Industry] - [Date]
│   ├── Company A
│   │   ├── Contact 1 → CRM Lead
│   │   └── Contact 2 → CRM Lead
│   └── Company B
│       └── Contact 3 → CRM Lead
```

### Categories/Tags

| Category | Purpose | Color |
|----------|---------|-------|
| Lead List | Parent tag for all lead lists | Purple |
| For Sale | Leads available for sale | Pink |
| Outreach Target | Leads for direct outreach | Light Blue |
| Premium | $500k+ valuation | Red |
| High Value | $100k-$500k | Yellow |
| Medium Value | $25k-$100k | Green |
| Low Value | <$25k | Gray |

### Import Usage

```bash
# Basic import (auto-generates list name)
python3 scripts/import_lead_list.py data.csv

# Full options
python3 scripts/import_lead_list.py data.csv \
    --list-name "Fort Worth Construction - Dec 2024" \
    --industry "Construction"
```

### CSV Fields Supported

- `contact_name`, `contact_email`, `contact_phone`
- `company_name`, `owner_name`
- `project_valuation`, `valuation_tier`, `score`
- `permit_number`, `permit_type`, `contact_role`

## Odoo API Usage

### Python XML-RPC Connection

```python
import os
import xmlrpc.client

url = os.environ["ODOO_URL"]
db = os.environ["ODOO_DB"]
username = os.environ["ODOO_USERNAME"]
api_key = os.environ["ODOO_API_KEY"]

# Authenticate
common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
uid = common.authenticate(db, username, api_key, {})

# Execute queries
models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

# Search and read
leads = models.execute_kw(db, uid, api_key,
    'crm.lead', 'search_read',
    [[]],
    {'fields': ['name', 'partner_name', 'expected_revenue'], 'limit': 10}
)

# Create record
lead_id = models.execute_kw(db, uid, api_key,
    'crm.lead', 'create',
    [{'name': 'New Lead', 'partner_name': 'Company'}]
)
```

### Key Odoo Models

| Model | Purpose |
|-------|---------|
| `res.partner` | Contacts and Companies |
| `res.partner.category` | Contact Tags/Categories |
| `crm.lead` | CRM Leads and Opportunities |
| `crm.stage` | CRM Pipeline Stages |
| `project.project` | Projects |
| `project.task` | Project Tasks |

## Current Odoo Data

### CRM Stages
1. New
2. Qualified
3. Proposition
4. Won

### Contact Categories
- Infrastructure, Proxmox, Network, Storage
- AI/ML, Cloud, Client, Lead, Partner, Vendor
- Lead List (parent), For Sale, Outreach Target
- Premium, High Value, Medium Value, Low Value

## Web Interface URLs

| View | URL |
|------|-----|
| Contacts | http://192.168.0.237:8069/web#model=res.partner |
| CRM Leads | http://192.168.0.237:8069/web#model=crm.lead |
| Projects | http://192.168.0.237:8069/web#model=project.project |

## Troubleshooting

### Connection Issues
```bash
# Check Odoo is running
curl http://192.168.0.237:8069/web/webclient/version_info

# Test authentication
python3 -c "
import xmlrpc.client
import os
common = xmlrpc.client.ServerProxy('http://192.168.0.237:8069/xmlrpc/2/common')
uid = common.authenticate(os.environ['ODOO_DB'], os.environ['ODOO_USERNAME'], os.environ['ODOO_API_KEY'], {})
print(f'Authenticated as UID: {uid}')
"
```

### Import Errors
- Ensure CSV is UTF-8 encoded
- Check for duplicate records
- Verify user has write permissions on CRM and Contacts
