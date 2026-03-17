#!/bin/bash
# Daily Odoo Lead Sync Cron Script
# Syncs enriched leads from PostgreSQL to Odoo CRM
#
# Install:
#   1. Copy to /opt/odoo-sync/ on container 237
#   2. Copy .env.cron with credentials (see .env.cron.example)
#   3. chmod +x cron-sync.sh
#
# Cron: 0 6 * * * /opt/odoo-sync/cron-sync.sh >> /var/log/odoo-sync.log 2>&1

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"

echo "$LOG_PREFIX Starting Odoo lead sync..."

# Load credentials from .env.cron (not committed to git)
if [ -f "$SCRIPT_DIR/.env.cron" ]; then
    set -a
    source "$SCRIPT_DIR/.env.cron"
    set +a
else
    echo "$LOG_PREFIX ERROR: Missing $SCRIPT_DIR/.env.cron"
    exit 1
fi

# Run sync
cd "$SCRIPT_DIR"
python3 sync_enriched_leads.py

echo "$LOG_PREFIX Sync complete"
