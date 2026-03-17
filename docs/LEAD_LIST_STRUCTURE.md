# Lead List Organization Structure

This document describes how lead lists are organized in Odoo CRM.

## Overview

Lead lists imported into Odoo follow a hierarchical structure that enables:
- Easy identification of lead sources
- Segmentation by industry/vertical
- Value tier classification
- Dual-purpose tracking (for sale + outreach)

## Organization Hierarchy

```
Lead Lists (Parent Company)
├── Lead List - Fort Worth Construction - Dec 2024
│   ├── LINBECK GROUP, LLC (Company)
│   │   ├── JEROD RANKIN (Contact) → CRM Lead
│   │   └── ...
│   ├── Mission Ridge Consultants (Company)
│   │   ├── Freddie Newsom (Contact) → CRM Lead
│   │   └── ...
│   └── ...
├── Lead List - Healthcare - Jan 2025
│   └── ...
└── Lead List - [Industry] - [Date]
    └── ...
```

## Category/Tag Structure

```
Lead List (Parent Category - Purple)
├── For Sale (Pink)
├── Outreach Target (Light Blue)
├── Construction (Orange) - Industry
├── Healthcare (Green) - Industry
├── Premium (Red) - Value Tier ($500k+)
├── High Value (Yellow) - Value Tier ($100k-$500k)
├── Medium Value (Green) - Value Tier ($25k-$100k)
└── Low Value (Gray) - Value Tier (<$25k)
```

## Data Flow

```
CSV File → Import Script → Odoo
    │
    ├── Creates/Updates Companies
    │   └── Tagged with Lead List + Industry + Value Tier
    │
    ├── Creates/Updates Contacts
    │   └── Linked to Company + Tagged
    │
    └── Creates CRM Leads
        └── Linked to Contact + Expected Revenue
```

## Import Script Usage

### Basic Import
```bash
set -a; source .env; set +a
python3 ~/projects/odoo/scripts/import_lead_list.py \
    ~/projects/accela-scraper/exports/fort_worth_contacts_20251217_1541.csv
```

### Full Options
```bash
set -a; source .env; set +a
python3 ~/projects/odoo/scripts/import_lead_list.py \
    ~/projects/accela-scraper/exports/fort_worth_contacts_20251217_1541.csv \
    --list-name "Fort Worth Construction - Dec 2024" \
    --industry "Construction"
```

### Command Line Options
| Option | Description |
|--------|-------------|
| `csv_file` | Path to CSV file (required) |
| `--list-name, -n` | Custom name for the lead list |
| `--industry, -i` | Industry category (Construction, Healthcare, etc.) |
| `--url` | Odoo URL override |
| `--db` | Database name override |
| `--username, -u` | Username override |
| `--api-key, -k` | API key override |

## CSV Field Mapping

The import script handles multiple CSV column name formats:

| Expected Field | Alternative Names |
|---------------|-------------------|
| `contact_name` | `Contact Name` |
| `contact_email` | `Email` |
| `contact_phone` | `Phone` |
| `company_name` | `Contact Company` |
| `owner_name` | `Owner` |
| `project_valuation` | `Valuation` |
| `valuation_tier` | `Value Tier` |
| `score` | `Score` |
| `permit_number` | `Permit #` |
| `permit_type` | `Type` |
| `contact_role` | `Contact Role` |

## Value Tier Classification

| Tier | Valuation Range | Tag Color |
|------|-----------------|-----------|
| PREMIUM | $500,000+ | Red |
| HIGH | $100,000 - $499,999 | Yellow |
| MEDIUM | $25,000 - $99,999 | Green |
| LOW | < $25,000 | Gray |
| UNKNOWN | No valuation | No tag |

## Viewing Imported Data

### In Odoo Web Interface

1. **All Lead List Contacts:**
   - Go to Contacts → Filter by "Lead List" category

2. **Specific Lead List:**
   - Filter by the specific list name (e.g., "Fort Worth Construction")

3. **CRM Pipeline:**
   - Go to CRM → Leads
   - All imported leads appear in "New" stage

4. **By Value Tier:**
   - Filter contacts/leads by "Premium", "High Value", etc.

### Direct URLs
- Contacts: `http://192.168.0.237:8069/web#model=res.partner&view_type=kanban`
- CRM Leads: `http://192.168.0.237:8069/web#model=crm.lead&view_type=kanban`

## Duplicate Handling

The import script:
- **Companies:** Checks by exact name match, updates if exists
- **Contacts:** Checks by email (if available) or name match
- **CRM Leads:** Always creates new (allows multiple leads per contact)

## Best Practices

1. **Naming Convention:**
   - Use format: `Lead List - [Industry/Source] - [Date]`
   - Example: `Lead List - Fort Worth Construction - Dec 2024`

2. **Before Import:**
   - Verify CSV data quality
   - Remove obvious duplicates
   - Ensure email addresses are valid

3. **After Import:**
   - Review in Odoo CRM
   - Assign to sales team members
   - Move high-value leads through pipeline

4. **Multiple Lists:**
   - Each import creates a new child company under "Lead Lists"
   - Categories are shared across all lists
   - Easy to filter by specific list or across all

## Troubleshooting

### Connection Issues
```bash
# Test Odoo connection
curl http://192.168.0.237:8069/web/webclient/version_info
```

### API Authentication
- Verify API key is valid
- Check user has CRM and Contacts access rights

### Import Errors
- Check CSV encoding (should be UTF-8)
- Verify all required fields exist
- Check Odoo server logs: `/var/log/odoo/odoo.log`

## Automated Enrichment Sync

The system automatically syncs enriched lead data from the accela-scraper PostgreSQL database to Odoo CRM.

### Schedule (AI Server - 192.168.0.234)

| Time | Job | Description |
|------|-----|-------------|
| 6:00 AM | `accela-enrich.sh` | Scrapes permit portals for contact data |
| 7:00 AM | `odoo-sync.sh` | Syncs enriched data to Odoo CRM |

### Sync Script Usage

```bash
# Manual sync (from AI server)
cd /aidata/projects/odoo-sync
source venv/bin/activate
set -a; source .env; set +a
python3 scripts/sync_enriched_leads.py

# With options
python3 scripts/sync_enriched_leads.py --city "Fort Worth"  # Filter by city
python3 scripts/sync_enriched_leads.py --create-new        # Create new leads
python3 scripts/sync_enriched_leads.py --dry-run           # Preview changes
```

### What Gets Synced

The sync matches leads by permit number and updates:
- Contact email
- Contact phone
- Contact name
- Company name

New leads can be created for permits found in PostgreSQL but not in Odoo (with `--create-new`).

### Logs

- Enrichment: `/aidata/projects/accela-scraper/logs/enrichment.log`
- Odoo Sync: `/aidata/projects/odoo-sync/logs/sync_YYYYMMDD.log`
- Cron: `/aidata/projects/odoo-sync/logs/cron.log`

## Related Files

| File | Purpose |
|------|---------|
| `scripts/import_lead_list.py` | Import leads from CSV with contacts |
| `scripts/import_commercial_leads.py` | Import multi-city commercial data |
| `scripts/sync_enriched_leads.py` | Sync enriched data from PostgreSQL |
| `scripts/odoo-sync.sh` | Wrapper script for cron automation |
| `docs/LEAD_LIST_STRUCTURE.md` | This documentation |
