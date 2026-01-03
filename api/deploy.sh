#!/bin/bash
# Deploy Odoo Invoice API to LXC 230 (Odoo container)

set -e

PROXMOX_HOST="192.168.0.165"
ODOO_CONTAINER="230"
API_DIR="/opt/odoo-api"

echo "=== Deploying Odoo Invoice API ==="

# Copy files to Proxmox host first
echo "Copying files to Proxmox..."
scp -r /Users/qvidal01/projects/odoo/api/* root@${PROXMOX_HOST}:/tmp/odoo-api/

# Deploy to container
echo "Deploying to container ${ODOO_CONTAINER}..."
ssh root@${PROXMOX_HOST} << 'ENDSSH'
CONTAINER=230
API_DIR=/opt/odoo-api

# Create directory in container
pct exec $CONTAINER -- mkdir -p $API_DIR

# Copy files to container
pct push $CONTAINER /tmp/odoo-api/main.py $API_DIR/main.py
pct push $CONTAINER /tmp/odoo-api/requirements.txt $API_DIR/requirements.txt
pct push $CONTAINER /tmp/odoo-api/odoo-api.service /etc/systemd/system/odoo-api.service

# Install Python venv and dependencies
pct exec $CONTAINER -- bash -c "
    apt-get update && apt-get install -y python3-venv python3-pip
    cd $API_DIR
    python3 -m venv venv
    venv/bin/pip install --upgrade pip
    venv/bin/pip install -r requirements.txt
"

# Enable and start service
pct exec $CONTAINER -- systemctl daemon-reload
pct exec $CONTAINER -- systemctl enable odoo-api
pct exec $CONTAINER -- systemctl restart odoo-api

# Check status
echo "Service status:"
pct exec $CONTAINER -- systemctl status odoo-api --no-pager | head -10

# Cleanup
rm -rf /tmp/odoo-api

echo "=== Deployment complete ==="
ENDSSH

echo "Testing API health endpoint..."
sleep 3
curl -s http://192.168.0.230:8070/health | jq . || echo "API not reachable yet, may need a moment to start"

echo ""
echo "API deployed to http://192.168.0.230:8070"
echo "Endpoints:"
echo "  - GET  /health"
echo "  - POST /api/create_invoice"
echo "  - POST /api/mark_invoice_paid"
echo "  - GET  /api/invoices/{id}"
