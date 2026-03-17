#!/usr/bin/env python3
"""
Create a Solution Discovery client folder from an Odoo CRM opportunity.

Reads opportunity data from Odoo and creates a pre-populated client directory
in the solution-discovery project with intake form filled from CRM data.

Usage:
    # By opportunity ID:
    python3 scripts/create_discovery_from_odoo.py --opportunity-id 123

    # By company name (searches CRM):
    python3 scripts/create_discovery_from_odoo.py --company "Smash Lab HTX"

    # Dry run:
    python3 scripts/create_discovery_from_odoo.py --dry-run --company "Smash Lab HTX"
"""

import argparse
import os
import re
import subprocess
import sys
import xmlrpc.client
from pathlib import Path

DISCOVERY_PROJECT = Path.home() / 'projects' / 'aiqso-solution-discovery'


def slugify(name):
    """Convert company name to directory-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug.strip('-')


def get_opportunity(odoo, opp_id=None, company_name=None):
    """Fetch opportunity from Odoo."""
    common = xmlrpc.client.ServerProxy(f"{os.environ['ODOO_URL']}/xmlrpc/2/common")
    models = xmlrpc.client.ServerProxy(f"{os.environ['ODOO_URL']}/xmlrpc/2/object")

    db = os.environ['ODOO_DB']
    uid = common.authenticate(db, os.environ['ODOO_USERNAME'], os.environ['ODOO_API_KEY'], {})
    api_key = os.environ['ODOO_API_KEY']

    if opp_id:
        domain = [('id', '=', opp_id), ('type', '=', 'opportunity')]
    elif company_name:
        domain = [('partner_name', 'ilike', company_name), ('type', '=', 'opportunity')]
    else:
        return None

    opps = models.execute_kw(db, uid, api_key, 'crm.lead', 'search_read', [domain], {
        'fields': [
            'name', 'partner_id', 'partner_name', 'contact_name',
            'email_from', 'phone', 'expected_revenue', 'description',
            'stage_id', 'tag_ids', 'website',
        ],
        'limit': 1,
    })

    if not opps:
        return None

    opp = opps[0]

    # Get partner details if available
    if opp.get('partner_id'):
        partner = models.execute_kw(db, uid, api_key, 'res.partner', 'read',
            [opp['partner_id'][0]],
            {'fields': ['name', 'email', 'phone', 'website', 'comment', 'street', 'city', 'state_id', 'zip']}
        )
        if partner:
            opp['partner_details'] = partner[0]

    return opp


def main():
    parser = argparse.ArgumentParser(description='Create Solution Discovery client from Odoo opportunity')
    parser.add_argument('--opportunity-id', type=int, help='Odoo opportunity ID')
    parser.add_argument('--company', help='Company name to search')
    parser.add_argument('--dry-run', action='store_true', help='Preview without creating')
    args = parser.parse_args()

    if not args.opportunity_id and not args.company:
        parser.error("Provide --opportunity-id or --company")

    # Check solution-discovery project exists
    if not DISCOVERY_PROJECT.exists():
        print(f"Error: Solution Discovery project not found at {DISCOVERY_PROJECT}")
        sys.exit(1)

    new_client_script = DISCOVERY_PROJECT / 'scripts' / 'new-client.sh'
    if not new_client_script.exists():
        print(f"Error: new-client.sh not found at {new_client_script}")
        sys.exit(1)

    # Fetch from Odoo
    print("Fetching opportunity from Odoo...")
    opp = get_opportunity(None, opp_id=args.opportunity_id, company_name=args.company)
    if not opp:
        print("Error: Opportunity not found")
        sys.exit(1)

    company_name = opp.get('partner_name') or (opp.get('partner_details', {}).get('name', ''))
    contact_name = opp.get('contact_name', '')
    email = opp.get('email_from', '')
    phone = opp.get('phone', '')
    partner = opp.get('partner_details', {})

    slug = slugify(company_name)
    client_dir = DISCOVERY_PROJECT / 'clients' / slug

    print(f"\nOpportunity: {opp['name']}")
    print(f"Company: {company_name}")
    print(f"Contact: {contact_name}")
    print(f"Email: {email}")
    print(f"Slug: {slug}")
    print(f"Target dir: {client_dir}")

    if client_dir.exists():
        print(f"\nClient directory already exists: {client_dir}")
        print("No action needed.")
        return

    if args.dry_run:
        print(f"\n[DRY RUN] Would create client directory at {client_dir}")
        print(f"  Using new-client.sh with:")
        print(f"    --name '{company_name}'")
        print(f"    --contact-name '{contact_name}'")
        print(f"    --contact-email '{email}'")
        print(f"    --industry 'Technology'")
        return

    # Run new-client.sh
    print(f"\nCreating client directory...")
    cmd = [
        str(new_client_script),
        '--name', company_name,
        '--contact-name', contact_name or 'TBD',
        '--contact-email', email or 'tbd@example.com',
        '--industry', 'Technology',  # Default, will be updated
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(DISCOVERY_PROJECT))
    if result.returncode != 0:
        print(f"Error running new-client.sh: {result.stderr}")
        sys.exit(1)

    print(result.stdout)

    # Update intake form with Odoo data if we have partner details
    if partner:
        intake_path = client_dir / '01-intake' / 'INTAKE-FORM.md'
        if intake_path.exists():
            content = intake_path.read_text()
            # Replace placeholder values with Odoo data
            if partner.get('comment'):
                content += f"\n\n## Imported from Odoo CRM\n\n{partner['comment']}\n"
            intake_path.write_text(content)
            print(f"  Updated intake form with Odoo data")

    print(f"\nDone! Client directory: {client_dir}")
    print(f"Next: Run MCP analysis tools on this client")


if __name__ == '__main__':
    main()
