#!/usr/bin/env python3
"""
Push Solution Discovery client data to Odoo CRM.

Reads a solution-discovery client folder and:
1. Creates/updates Odoo contact with company info, industry, pain points
2. Creates/updates CRM opportunity with analysis data
3. Creates Sales Quotation with mapped product lines from cost analysis
4. Attaches PDF deliverables to the opportunity
5. Moves opportunity to appropriate pipeline stage

Usage:
    # Set env vars first: set -a; source .env; set +a
    python3 scripts/push_solution_to_odoo.py ~/projects/aiqso-solution-discovery/clients/smash-lab-htx/

    # Dry run (no changes):
    python3 scripts/push_solution_to_odoo.py --dry-run ~/projects/aiqso-solution-discovery/clients/smash-lab-htx/

    # Skip quotation creation:
    python3 scripts/push_solution_to_odoo.py --no-quotation ~/projects/aiqso-solution-discovery/clients/smash-lab-htx/
"""

import argparse
import base64
import os
import re
import sys
import xmlrpc.client
from pathlib import Path


# ──────────────────────────────────────────────
# Product mapping: solution-discovery → Odoo product codes
# Maps keywords in cost analysis to Odoo product catalog
# ──────────────────────────────────────────────
PRODUCT_MAP = {
    # Setup / Implementation products
    'crm': {'code': 'CRM-IMPL', 'name': 'CRM Implementation'},
    'espocrm': {'code': 'CRM-IMPL', 'name': 'CRM Implementation'},
    'website': {'code': 'WEB-DEV', 'name': 'Website Development'},
    'wordpress': {'code': 'WEB-DEV', 'name': 'Website Development'},
    'n8n': {'code': 'DEV-N8N', 'name': 'n8n Automation Build'},
    'workflow': {'code': 'DEV-N8N', 'name': 'n8n Automation Build'},
    'automation': {'code': 'AI-SETUP', 'name': 'AI Automation Setup'},
    'ai': {'code': 'AI-SETUP', 'name': 'AI Automation Setup'},
    'ollama': {'code': 'AI-SETUP', 'name': 'AI Automation Setup'},
    'flowiseai': {'code': 'AI-SETUP', 'name': 'AI Automation Setup'},
    'integration': {'code': 'INTEG-CUSTOM', 'name': 'Custom Integration'},
    'grafana': {'code': 'BI-DASH', 'name': 'Business Intelligence Dashboard'},
    'metabase': {'code': 'BI-DASH', 'name': 'Business Intelligence Dashboard'},
    'dashboard': {'code': 'BI-DASH', 'name': 'Business Intelligence Dashboard'},
    'training': {'code': 'TRAIN-2HR', 'name': 'Training Session'},
    'custom': {'code': 'DEV-CUSTOM', 'name': 'Custom Development Project'},
    'portal': {'code': 'DEV-CUSTOM', 'name': 'Custom Development Project'},

    # Monthly recurring
    'managed hosting': {'code': 'MIT-PRO', 'name': 'Managed IT - Professional'},
    'aiqso managed': {'code': 'MIT-PRO', 'name': 'Managed IT - Professional'},
    'support contract': {'code': 'SUPPORT-SMB', 'name': 'Small Business Monthly Support'},
    'aiqso support': {'code': 'SUPPORT-SMB', 'name': 'Small Business Monthly Support'},
}

# Stage mapping: solution-discovery status → Odoo CRM stage
STAGE_MAP = {
    'lead': 'New Lead',
    'discovery': 'Discovery Call',
    'analysis': 'Discovery Call',
    'proposal': 'Proposal Sent',
    'presented': 'Proposal Sent',
    'negotiating': 'Negotiation',
    'closed won': 'Won',
    'active': 'Won',
    'complete': 'Won',
    'closed lost': 'Lost',
}


class OdooClient:
    """Simple Odoo XML-RPC client."""

    def __init__(self, url, db, username, api_key):
        self.url = url
        self.db = db
        self.uid = None
        self.api_key = api_key
        self.common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
        self.models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')
        self.uid = self.common.authenticate(db, username, api_key, {})
        if not self.uid:
            raise ConnectionError(f"Failed to authenticate as {username}")

    def search(self, model, domain, limit=0):
        return self.models.execute_kw(
            self.db, self.uid, self.api_key,
            model, 'search', [domain],
            {'limit': limit} if limit else {}
        )

    def read(self, model, ids, fields):
        return self.models.execute_kw(
            self.db, self.uid, self.api_key,
            model, 'read', [ids], {'fields': fields}
        )

    def search_read(self, model, domain, fields, limit=0):
        return self.models.execute_kw(
            self.db, self.uid, self.api_key,
            model, 'search_read', [domain],
            {'fields': fields, 'limit': limit} if limit else {'fields': fields}
        )

    def create(self, model, vals):
        return self.models.execute_kw(
            self.db, self.uid, self.api_key,
            model, 'create', [vals]
        )

    def write(self, model, ids, vals):
        return self.models.execute_kw(
            self.db, self.uid, self.api_key,
            model, 'write', [ids, vals]
        )


def parse_intake_form(client_dir):
    """Parse the intake form markdown into structured data."""
    intake_path = client_dir / '01-intake' / 'INTAKE-FORM.md'
    if not intake_path.exists():
        print(f"  Warning: No intake form at {intake_path}")
        return {}

    content = intake_path.read_text()
    data = {}

    # Company name
    m = re.search(r'\*\*Company Name:\*\*\s*(.+)', content)
    data['company_name'] = m.group(1).strip() if m else client_dir.name

    # Industry — match non-empty value on same line only
    m = re.search(r'\*\*Industry:\*\*\s*(\S.+)', content)
    data['industry'] = m.group(1).strip() if m else ''

    # Employees
    m = re.search(r'\*\*Number of Employees:\*\*\s*(.+)', content)
    data['employees'] = m.group(1).strip() if m else ''

    # Revenue
    m = re.search(r'\*\*Annual Revenue Range:\*\*\s*(.+)', content)
    data['revenue'] = m.group(1).strip() if m else ''

    # Locations
    m = re.search(r'\*\*Number of Locations:\*\*\s*(.+)', content)
    data['locations'] = m.group(1).strip() if m else ''

    # Growth plans
    m = re.search(r'\*\*Growth Plans.*?:\*\*\s*(.+)', content)
    data['growth_plans'] = m.group(1).strip() if m else ''

    # Current tech
    m = re.search(r'\*\*SaaS/Software tools currently used.*?:\*\*\s*(.+)', content)
    data['current_tech'] = m.group(1).strip() if m else ''

    # Monthly spend
    m = re.search(r'\*\*Estimated monthly software spend:\*\*\s*(.+)', content)
    data['monthly_spend'] = m.group(1).strip() if m else ''

    # Budget
    m = re.search(r'\*\*Budget range for initial setup:\*\*\s*(.+)', content)
    data['budget'] = m.group(1).strip() if m else ''

    # Acceptable monthly cost
    m = re.search(r'\*\*Acceptable monthly operational cost:\*\*\s*(.+)', content)
    data['monthly_budget'] = m.group(1).strip() if m else ''

    # Go-live
    m = re.search(r'\*\*Desired go-live date:\*\*\s*(.+)', content)
    data['go_live'] = m.group(1).strip() if m else ''

    # Pain points
    pain_points = []
    for m in re.finditer(r'\[x\]\s*(.+?)—\s*Score:\s*(\d)', content):
        pain_points.append({'name': m.group(1).strip(), 'score': int(m.group(2))})
    data['pain_points'] = pain_points

    # Compliance
    m = re.search(r'\*\*Applicable regulations:\*\*\s*(.+)', content)
    data['compliance'] = m.group(1).strip() if m else ''

    # Contact info
    m = re.search(r'\*\*Primary Contact.*?:\*\*\s*(.+)', content)
    data['contact_name'] = m.group(1).strip() if m else ''
    m = re.search(r'\*\*Contact Email.*?:\*\*\s*(.+)', content)
    data['contact_email'] = m.group(1).strip() if m else ''
    m = re.search(r'\*\*Contact Phone.*?:\*\*\s*(.+)', content)
    data['contact_phone'] = m.group(1).strip() if m else ''

    # Notes section
    notes_match = re.search(r'## Notes\s*\n([\s\S]+?)(?=\n## |\Z)', content)
    data['notes'] = notes_match.group(1).strip() if notes_match else ''

    return data


def parse_status(client_dir):
    """Parse STATUS.md for pipeline stage."""
    status_path = client_dir / 'STATUS.md'
    if not status_path.exists():
        return 'proposal'  # default

    content = status_path.read_text()
    m = re.search(r'\*\*Current Stage:\*\*\s*(.+)', content)
    if m:
        return m.group(1).strip().lower()
    return 'proposal'


def parse_cost_analysis(client_dir):
    """Parse cost analysis for quotation line items."""
    cost_path = client_dir / '05-cost-analysis' / 'COST-ANALYSIS.md'
    if not cost_path.exists():
        print(f"  Warning: No cost analysis at {cost_path}")
        return [], {}

    content = cost_path.read_text()
    lines = []

    # Parse the AIQSO Hosted table (Option A)
    # Look for lines like: | Component | $X,XXX | $XXX | $X,XXX | Notes |
    in_option_a = False
    for line in content.split('\n'):
        if 'Option A' in line or 'AIQSO-Hosted' in line or 'AIQSO Hosted' in line:
            in_option_a = True
            continue
        if in_option_a and ('Option B' in line or '---' == line.strip()):
            if 'Option B' in line:
                break

        if not in_option_a:
            continue

        # Skip subtotals, headers, separators
        if not line.strip().startswith('|'):
            continue
        if '---' in line or 'Component' in line or 'subtotal' in line.lower():
            continue
        if 'TOTAL' in line:
            continue
        if line.count('|') < 4:
            continue

        parts = [p.strip() for p in line.split('|')]
        parts = [p for p in parts if p]  # remove empty

        if len(parts) < 4:
            continue

        component = parts[0].strip('*').strip()
        if not component or component.startswith('Phase') or component.startswith('**Phase'):
            continue

        # Parse setup cost
        setup_str = parts[1].replace('$', '').replace(',', '').strip()
        setup = 0.0
        try:
            setup = float(setup_str) if setup_str and setup_str != '0' else 0.0
        except ValueError:
            pass

        # Parse monthly cost
        monthly_str = parts[2].replace('$', '').replace(',', '').strip()
        monthly = 0.0
        try:
            monthly = float(monthly_str) if monthly_str and monthly_str != '0' else 0.0
        except ValueError:
            pass

        # Notes
        notes = parts[4] if len(parts) > 4 else ''

        if setup > 0 or monthly > 0:
            lines.append({
                'component': component,
                'setup': setup,
                'monthly': monthly,
                'notes': notes,
            })

    # Parse totals
    totals = {}
    m = re.search(r'\*\*TOTAL \(All Phases\)\*\*.*?\*\*\$([0-9,]+)\*\*.*?\*\*\$([0-9,]+)/mo\*\*', content)
    if m:
        totals['setup_total'] = float(m.group(1).replace(',', ''))
        totals['monthly_total'] = float(m.group(2).replace(',', ''))

    return lines, totals


def find_deliverables(client_dir):
    """Find PDF/HTML deliverables to attach."""
    deliverable_dir = client_dir / '10-deliverables'
    files = []
    if deliverable_dir.exists():
        for f in deliverable_dir.iterdir():
            if f.suffix in ['.pdf', '.html', '.xlsx']:
                files.append(f)

    # Also check proposals
    proposal_dir = client_dir / '04-proposals'
    if proposal_dir.exists():
        for f in proposal_dir.iterdir():
            if f.suffix in ['.pdf', '.md'] and 'EXECUTIVE' in f.name.upper():
                files.append(f)

    return files


def map_product(component_name, odoo_products):
    """Map a cost analysis component to an Odoo product."""
    component_lower = component_name.lower()

    # Try direct mapping
    for keyword, mapping in PRODUCT_MAP.items():
        if keyword in component_lower:
            # Find the Odoo product by code
            for prod in odoo_products:
                if prod.get('default_code') == mapping['code']:
                    return prod
            break

    # Fallback: try matching by name similarity
    for prod in odoo_products:
        prod_name_lower = prod['name'].lower()
        for word in component_lower.split():
            if len(word) > 3 and word in prod_name_lower:
                return prod

    return None


def push_to_odoo(client_dir, dry_run=False, no_quotation=False):
    """Main function: push solution-discovery data to Odoo."""

    client_dir = Path(client_dir).resolve()
    client_slug = client_dir.name

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Pushing {client_slug} to Odoo CRM")
    print(f"  Client directory: {client_dir}")

    # ── Parse all client data ──
    print("\n1. Parsing client data...")
    intake = parse_intake_form(client_dir)
    status = parse_status(client_dir)
    cost_lines, cost_totals = parse_cost_analysis(client_dir)
    deliverables = find_deliverables(client_dir)

    company_name = intake.get('company_name', client_slug)
    print(f"  Company: {company_name}")
    print(f"  Industry: {intake.get('industry', 'N/A')}")
    print(f"  Stage: {status}")
    print(f"  Cost lines: {len(cost_lines)}")
    print(f"  Deliverables: {len(deliverables)}")

    if dry_run:
        print("\n  [DRY RUN] Would create/update:")
        print(f"    - Contact: {company_name}")
        print(f"    - Opportunity: {company_name} - Technology Solution")
        if not no_quotation:
            print(f"    - Quotation with {len(cost_lines)} line items")
            for line in cost_lines:
                print(f"      - {line['component']}: setup=${line['setup']:.0f}, monthly=${line['monthly']:.0f}")
            if cost_totals:
                print(f"    - Total: setup=${cost_totals.get('setup_total', 0):.0f}, monthly=${cost_totals.get('monthly_total', 0):.0f}")
        print(f"    - {len(deliverables)} attachments")
        return

    # ── Connect to Odoo ──
    print("\n2. Connecting to Odoo...")
    odoo = OdooClient(
        url=os.environ['ODOO_URL'],
        db=os.environ['ODOO_DB'],
        username=os.environ['ODOO_USERNAME'],
        api_key=os.environ['ODOO_API_KEY'],
    )
    print(f"  Authenticated as UID {odoo.uid}")

    # ── Load Odoo reference data ──
    odoo_products = odoo.search_read(
        'product.product',
        [('type', '=', 'service'), ('active', '=', True)],
        ['id', 'name', 'default_code', 'list_price', 'product_tmpl_id']
    )
    odoo_stages = odoo.search_read('crm.stage', [], ['id', 'name', 'sequence'])
    odoo_tags = odoo.search_read('crm.tag', [], ['id', 'name'])

    # ── 3. Create/Update Contact ──
    print("\n3. Creating/updating contact...")

    # Check if company already exists
    existing = odoo.search('res.partner', [
        ('name', 'ilike', company_name),
        ('is_company', '=', True)
    ], limit=1)

    # Build internal note from intake data
    pain_summary = '\n'.join(
        f"  - {p['name']} (severity: {p['score']}/5)"
        for p in intake.get('pain_points', [])
    )
    internal_note = f"""=== Solution Discovery Import ===
Industry: {intake.get('industry', 'N/A')}
Employees: {intake.get('employees', 'N/A')}
Revenue: {intake.get('revenue', 'N/A')}
Locations: {intake.get('locations', 'N/A')}
Growth Plans: {intake.get('growth_plans', 'N/A')}
Current Tech: {intake.get('current_tech', 'N/A')}
Monthly Software Spend: {intake.get('monthly_spend', 'N/A')}
Compliance: {intake.get('compliance', 'N/A')}

Pain Points:
{pain_summary}

Budget: {intake.get('budget', 'N/A')}
Monthly Budget: {intake.get('monthly_budget', 'N/A')}
Go-Live: {intake.get('go_live', 'N/A')}

Notes: {intake.get('notes', '')}
"""

    partner_vals = {
        'name': company_name,
        'is_company': True,
        'comment': internal_note,
        'industry_id': False,  # Would need industry lookup
        'website': '',
    }

    # Add contact info if available
    if intake.get('contact_email'):
        partner_vals['email'] = intake['contact_email']
    if intake.get('contact_phone'):
        partner_vals['phone'] = intake['contact_phone']

    if existing:
        partner_id = existing[0]
        odoo.write('res.partner', [partner_id], partner_vals)
        print(f"  Updated existing contact: {company_name} (id={partner_id})")
    else:
        partner_id = odoo.create('res.partner', partner_vals)
        print(f"  Created new contact: {company_name} (id={partner_id})")

    # ── 4. Create/Update Opportunity ──
    print("\n4. Creating/updating opportunity...")

    # Find the target CRM stage
    target_stage_name = STAGE_MAP.get(status, 'Proposal Sent')
    target_stage = next(
        (s for s in odoo_stages if s['name'] == target_stage_name),
        odoo_stages[0]  # fallback to first stage
    )

    # Calculate expected revenue from cost analysis
    expected_revenue = cost_totals.get('setup_total', 0)
    if cost_totals.get('monthly_total'):
        expected_revenue += cost_totals['monthly_total'] * 12  # First year

    # Check for existing opportunity
    existing_opp = odoo.search('crm.lead', [
        ('partner_id', '=', partner_id),
        ('type', '=', 'opportunity'),
    ], limit=1)

    opp_name = f"{company_name} - Technology Solution"
    opp_description = f"""Solution Discovery Analysis
===========================

Company: {company_name}
Industry: {intake.get('industry', 'N/A')}
Source: Solution Discovery ({client_slug})

Setup Cost: ${cost_totals.get('setup_total', 0):,.0f}
Monthly Recurring: ${cost_totals.get('monthly_total', 0):,.0f}/mo
Annual Recurring: ${cost_totals.get('monthly_total', 0) * 12:,.0f}/yr

Pain Points (top 3):
{chr(10).join(f"- {p['name']} ({p['score']}/5)" for p in sorted(intake.get('pain_points', []), key=lambda x: x['score'], reverse=True)[:3])}

Compliance: {intake.get('compliance', 'N/A')}
Go-Live: {intake.get('go_live', 'N/A')}
"""

    # Find relevant tags
    tag_ids = []
    for tag in odoo_tags:
        if tag['name'] in ['Hot Lead', 'SMB', 'Inbound']:
            tag_ids.append(tag['id'])

    opp_vals = {
        'name': opp_name,
        'partner_id': partner_id,
        'type': 'opportunity',
        'stage_id': target_stage['id'],
        'expected_revenue': expected_revenue,
        'description': opp_description,
        'tag_ids': [(6, 0, tag_ids)] if tag_ids else False,
    }

    if existing_opp:
        opp_id = existing_opp[0]
        odoo.write('crm.lead', [opp_id], opp_vals)
        print(f"  Updated opportunity: {opp_name} (id={opp_id})")
    else:
        opp_id = odoo.create('crm.lead', opp_vals)
        print(f"  Created opportunity: {opp_name} (id={opp_id})")

    print(f"  Stage: {target_stage_name}")
    print(f"  Expected revenue: ${expected_revenue:,.0f}")

    # ── 5. Create Sales Quotation ──
    if not no_quotation and cost_lines:
        print("\n5. Creating sales quotation...")

        # Check for existing quotation
        existing_so = odoo.search('sale.order', [
            ('partner_id', '=', partner_id),
            ('state', 'in', ['draft', 'sent']),
        ], limit=1)

        if existing_so:
            so_id = existing_so[0]
            print(f"  Quotation already exists (id={so_id}), updating...")
            # Delete existing lines
            existing_lines = odoo.search('sale.order.line', [('order_id', '=', so_id)])
            if existing_lines:
                odoo.models.execute_kw(
                    odoo.db, odoo.uid, odoo.api_key,
                    'sale.order.line', 'unlink', [existing_lines]
                )
        else:
            # Find payment term
            net30 = odoo.search('account.payment.term', [('name', 'ilike', '30 Days')], limit=1)

            so_vals = {
                'partner_id': partner_id,
                'opportunity_id': opp_id,
                'note': f'Solution Discovery proposal for {company_name}.\n'
                        f'Source: {client_slug}\n\n'
                        f'Option A: AIQSO-Hosted (Recommended)',
            }
            if net30:
                so_vals['payment_term_id'] = net30[0]

            so_id = odoo.create('sale.order', so_vals)
            print(f"  Created quotation (id={so_id})")

        # Add line items
        line_count = 0
        used_products = set()
        sequence = 10

        for cost_item in cost_lines:
            product = map_product(cost_item['component'], odoo_products)

            if cost_item['setup'] > 0:
                if product and product['id'] not in used_products:
                    line_vals = {
                        'order_id': so_id,
                        'product_id': product['id'],
                        'name': f"{cost_item['component']}" + (f" — {cost_item['notes']}" if cost_item['notes'] else ''),
                        'product_uom_qty': 1,
                        'price_unit': cost_item['setup'],
                        'sequence': sequence,
                    }
                    used_products.add(product['id'])
                else:
                    # No product match — create as description-only line
                    # Use first service product as carrier
                    line_vals = {
                        'order_id': so_id,
                        'name': f"{cost_item['component']} (Setup)" + (f" — {cost_item['notes']}" if cost_item['notes'] else ''),
                        'product_uom_qty': 1,
                        'price_unit': cost_item['setup'],
                        'display_type': False,
                        'sequence': sequence,
                    }
                    if product:
                        line_vals['product_id'] = product['id']

                try:
                    odoo.create('sale.order.line', line_vals)
                    line_count += 1
                    print(f"    + {cost_item['component']}: ${cost_item['setup']:,.0f} (setup)")
                except Exception as e:
                    print(f"    ! Failed: {cost_item['component']}: {str(e)[:80]}")
                sequence += 10

            # Monthly recurring items
            if cost_item['monthly'] > 0:
                monthly_product = None
                component_lower = cost_item['component'].lower()
                if 'hosting' in component_lower or 'aiqso' in component_lower:
                    # Map to managed IT tier based on price
                    if cost_item['monthly'] >= 999:
                        monthly_product = next((p for p in odoo_products if p.get('default_code') == 'MIT-ENT'), None)
                    elif cost_item['monthly'] >= 499:
                        monthly_product = next((p for p in odoo_products if p.get('default_code') == 'MIT-PRO'), None)
                    else:
                        monthly_product = next((p for p in odoo_products if p.get('default_code') == 'MIT-STARTER'), None)
                elif 'support' in component_lower:
                    monthly_product = next((p for p in odoo_products if p.get('default_code') == 'SUPPORT-SMB'), None)

                line_vals = {
                    'order_id': so_id,
                    'name': f"{cost_item['component']} (Monthly)" + (f" — {cost_item['notes']}" if cost_item['notes'] else ''),
                    'product_uom_qty': 12,  # 12 months
                    'price_unit': cost_item['monthly'],
                    'sequence': sequence,
                }
                if monthly_product:
                    line_vals['product_id'] = monthly_product['id']

                try:
                    odoo.create('sale.order.line', line_vals)
                    line_count += 1
                    print(f"    + {cost_item['component']}: ${cost_item['monthly']:,.0f}/mo × 12 (recurring)")
                except Exception as e:
                    print(f"    ! Failed monthly {cost_item['component']}: {str(e)[:80]}")
                sequence += 10

        print(f"  Total quotation lines: {line_count}")

    # ── 6. Attach deliverables ──
    if deliverables:
        print(f"\n6. Attaching {len(deliverables)} deliverable(s)...")
        for filepath in deliverables:
            try:
                with open(filepath, 'rb') as f:
                    file_data = base64.b64encode(f.read()).decode()

                odoo.create('ir.attachment', {
                    'name': filepath.name,
                    'datas': file_data,
                    'res_model': 'crm.lead',
                    'res_id': opp_id,
                    'mimetype': 'application/pdf' if filepath.suffix == '.pdf'
                                else 'text/html' if filepath.suffix == '.html'
                                else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                })
                print(f"    Attached: {filepath.name}")
            except Exception as e:
                print(f"    Failed to attach {filepath.name}: {e}")

    # ── Summary ──
    print(f"\n{'='*50}")
    print(f"DONE: {company_name}")
    print(f"  Contact: id={partner_id}")
    print(f"  Opportunity: id={opp_id} → {target_stage_name}")
    print(f"  Expected Revenue: ${expected_revenue:,.0f}")
    if not no_quotation and cost_lines:
        print(f"  Quotation: id={so_id}")
    print(f"  Odoo URL: {os.environ['ODOO_URL']}/web#id={opp_id}&model=crm.lead")


def main():
    parser = argparse.ArgumentParser(
        description='Push Solution Discovery client data to Odoo CRM'
    )
    parser.add_argument('client_dir', help='Path to the client directory')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without writing to Odoo')
    parser.add_argument('--no-quotation', action='store_true', help='Skip quotation creation')
    args = parser.parse_args()

    # Validate env vars
    required_vars = ['ODOO_URL', 'ODOO_DB', 'ODOO_USERNAME', 'ODOO_API_KEY']
    missing = [v for v in required_vars if not os.environ.get(v)]
    if missing and not args.dry_run:
        print(f"Error: Missing environment variables: {', '.join(missing)}")
        print("Run: set -a; source .env; set +a")
        sys.exit(1)

    # Validate client directory
    client_dir = Path(args.client_dir)
    if not client_dir.is_dir():
        print(f"Error: Not a directory: {client_dir}")
        sys.exit(1)
    if not (client_dir / '01-intake').exists():
        print(f"Error: Not a solution-discovery client directory (no 01-intake/): {client_dir}")
        sys.exit(1)

    push_to_odoo(client_dir, dry_run=args.dry_run, no_quotation=args.no_quotation)


if __name__ == '__main__':
    main()
