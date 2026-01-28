#!/bin/bash
# Deploy Odoo Invoice API with Mercury Bank Integration to LXC 230

set -e

PROXMOX_HOST="192.168.0.165"
ODOO_CONTAINER="237"  # odoo19
API_DIR="/opt/odoo-api"
LOCAL_DIR="/Users/qvidal01/projects/odoo/api"

echo "╔════════════════════════════════════════════════════════════╗"
echo "║  Deploying Odoo API + Mercury Bank Integration             ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Verify local files exist
echo "📁 Checking local files..."
REQUIRED_FILES="main.py mercury.py sync_state.py reconciliation.py background.py notifications.py requirements.txt odoo-api.service"
for file in $REQUIRED_FILES; do
    if [[ ! -f "$LOCAL_DIR/$file" ]]; then
        echo "❌ Missing required file: $file"
        exit 1
    fi
done
echo "✅ All required files present"
echo ""

# Create temp directory on Proxmox
echo "📤 Copying files to Proxmox host..."
ssh root@${PROXMOX_HOST} "mkdir -p /tmp/odoo-api"
scp -q ${LOCAL_DIR}/main.py \
      ${LOCAL_DIR}/mercury.py \
      ${LOCAL_DIR}/sync_state.py \
      ${LOCAL_DIR}/reconciliation.py \
      ${LOCAL_DIR}/background.py \
      ${LOCAL_DIR}/notifications.py \
      ${LOCAL_DIR}/requirements.txt \
      ${LOCAL_DIR}/odoo-api.service \
      root@${PROXMOX_HOST}:/tmp/odoo-api/
echo "✅ Files copied to Proxmox"
echo ""

# Deploy to container
echo "🚀 Deploying to LXC container ${ODOO_CONTAINER}..."
ssh root@${PROXMOX_HOST} << 'ENDSSH'
CONTAINER=237
API_DIR=/opt/odoo-api

echo "  Creating directories..."
pct exec $CONTAINER -- mkdir -p $API_DIR

echo "  Pushing files to container..."
# Core API files
pct push $CONTAINER /tmp/odoo-api/main.py $API_DIR/main.py
pct push $CONTAINER /tmp/odoo-api/requirements.txt $API_DIR/requirements.txt

# Mercury integration files
pct push $CONTAINER /tmp/odoo-api/mercury.py $API_DIR/mercury.py
pct push $CONTAINER /tmp/odoo-api/sync_state.py $API_DIR/sync_state.py
pct push $CONTAINER /tmp/odoo-api/reconciliation.py $API_DIR/reconciliation.py
pct push $CONTAINER /tmp/odoo-api/background.py $API_DIR/background.py
pct push $CONTAINER /tmp/odoo-api/notifications.py $API_DIR/notifications.py

# Systemd service
pct push $CONTAINER /tmp/odoo-api/odoo-api.service /etc/systemd/system/odoo-api.service

echo "  Installing dependencies..."
pct exec $CONTAINER -- bash -c "
    cd $API_DIR
    if [[ ! -d venv ]]; then
        echo '    Creating virtual environment...'
        apt-get update -qq && apt-get install -y -qq python3-venv python3-pip
        python3 -m venv venv
    fi
    echo '    Installing Python packages...'
    venv/bin/pip install --upgrade pip -q
    venv/bin/pip install -r requirements.txt -q
    echo '    Dependencies installed'
"

echo "  Restarting service..."
pct exec $CONTAINER -- systemctl daemon-reload
pct exec $CONTAINER -- systemctl enable odoo-api
pct exec $CONTAINER -- systemctl restart odoo-api

# Wait for service to start
sleep 3

echo ""
echo "  📊 Service status:"
pct exec $CONTAINER -- systemctl status odoo-api --no-pager | head -15

# Cleanup
rm -rf /tmp/odoo-api

echo ""
echo "✅ Container deployment complete"
ENDSSH

echo ""
echo "🔍 Testing API endpoints..."
sleep 2

# Test health endpoint
echo ""
echo "1️⃣  Health check:"
curl -s http://192.168.0.237:8070/health | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f\"   Odoo: {d.get('odoo', 'unknown')}\")
    print(f\"   Mercury: {d.get('mercury', 'unknown')}\")
    print(f\"   Status: {d.get('status', 'unknown')}\")
except:
    print('   ⚠️  Could not parse response')
" || echo "   ❌ API not responding"

# Test Mercury balance
echo ""
echo "2️⃣  Mercury balance:"
curl -s http://192.168.0.237:8070/api/mercury/balance | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f\"   Available: \${d.get('total_available', 0):,.2f}\")
    print(f\"   Current: \${d.get('total_current', 0):,.2f}\")
except Exception as e:
    print(f'   ⚠️  Error: {e}')
" || echo "   ❌ Mercury endpoint not responding"

# Test Mercury status
echo ""
echo "3️⃣  Mercury sync status:"
curl -s http://192.168.0.237:8070/api/mercury/status | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f\"   Connected: {d.get('mercury_connected', False)}\")
    print(f\"   Scheduler: {'Running' if d.get('scheduler_running') else 'Stopped'}\")
    print(f\"   Interval: {d.get('sync_interval_minutes', 15)} minutes\")
    print(f\"   Auto-reconcile: {d.get('auto_reconcile', True)}\")
except Exception as e:
    print(f'   ⚠️  Error: {e}')
" || echo "   ❌ Status endpoint not responding"

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║  ✅ Deployment Complete!                                   ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "API URL: http://192.168.0.237:8070"
echo ""
echo "Endpoints:"
echo "  Invoices (existing):"
echo "    POST /api/create_invoice"
echo "    POST /api/mark_invoice_paid"
echo "    GET  /api/invoices/{id}"
echo ""
echo "  Mercury Bank (new):"
echo "    GET  /api/mercury/accounts      - List accounts & balances"
echo "    GET  /api/mercury/transactions  - Transaction history"
echo "    GET  /api/mercury/balance       - Quick balance check"
echo "    POST /api/mercury/sync          - Trigger manual sync"
echo "    POST /api/mercury/reconcile     - Auto-match to invoices"
echo "    GET  /api/mercury/unmatched     - Unreconciled deposits"
echo "    GET  /api/mercury/status        - Sync status"
echo ""
echo "Background sync: Every 15 minutes (auto-reconcile enabled)"
echo ""
