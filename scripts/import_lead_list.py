#!/usr/bin/env python3
"""
Lead List Import Script for Odoo CRM

This script imports lead lists from CSV files into Odoo, creating:
- Organized category/tag structure
- Parent company for lead list organization
- Individual contacts linked to their companies
- CRM leads for pipeline tracking

Usage:
    python3 import_lead_list.py <csv_file> [--list-name "Name"] [--industry "Industry"]

Example:
    python3 import_lead_list.py ~/projects/accela-scraper/exports/fort_worth_contacts_20251217_1541.csv \
        --list-name "Fort Worth Construction" --industry "Construction"
"""

import argparse
import csv
import sys
import xmlrpc.client
from datetime import datetime
from pathlib import Path

from config import load_odoo_config, require_config

# Category color mapping
CATEGORY_COLORS = {
    "Lead List": 10,  # Purple - parent category
    "For Sale": 11,  # Pink
    "Outreach Target": 4,  # Light blue
    "Construction": 2,  # Orange
    "Premium": 6,  # Red (high value)
    "High Value": 5,  # Yellow
    "Medium Value": 3,  # Green
    "Low Value": 1,  # Gray
}


class OdooLeadImporter:
    def __init__(self, config=None):
        self.config = config or load_odoo_config()
        self.uid = None
        self.models = None
        self._connect()

    def _connect(self):
        """Establish connection to Odoo"""
        require_config(
            self.config,
            required_keys=["url", "db", "username", "api_key"],
            source_hint="ODOO_URL/ODOO_DB/ODOO_USERNAME/ODOO_API_KEY",
        )
        try:
            common = xmlrpc.client.ServerProxy(f"{self.config['url']}/xmlrpc/2/common")
            self.uid = common.authenticate(self.config["db"], self.config["username"], self.config["api_key"], {})
            if not self.uid:
                raise Exception("Authentication failed")

            self.models = xmlrpc.client.ServerProxy(f"{self.config['url']}/xmlrpc/2/object")
            print(f"✓ Connected to Odoo as user ID: {self.uid}")
        except Exception as e:
            print(f"✗ Connection failed: {e}")
            sys.exit(1)

    def _execute(self, model, method, *args, **kwargs):
        """Execute Odoo model method"""
        return self.models.execute_kw(self.config["db"], self.uid, self.config["api_key"], model, method, args, kwargs)

    def search_read(self, model, domain, fields=None, limit=None):
        """Search and read records"""
        kwargs = {}
        if fields:
            kwargs["fields"] = fields
        if limit:
            kwargs["limit"] = limit
        return self._execute(model, "search_read", domain, **kwargs)

    def create(self, model, values):
        """Create a new record"""
        result = self._execute(model, "create", [values])
        # Handle Odoo returning array or single ID
        if isinstance(result, list):
            return result[0] if result else None
        return result

    def write(self, model, ids, values):
        """Update existing records"""
        return self._execute(model, "write", ids, values)

    def search(self, model, domain, limit=None):
        """Search for record IDs"""
        kwargs = {}
        if limit:
            kwargs["limit"] = limit
        return self._execute(model, "search", domain, **kwargs)

    # ========== Category Management ==========

    def get_or_create_category(self, name, parent_id=None, color=None):
        """Get existing category or create new one"""
        domain = [("name", "=", name)]
        if parent_id:
            # Ensure parent_id is an integer, not a list
            pid = parent_id[0] if isinstance(parent_id, list) else parent_id
            domain.append(("parent_id", "=", pid))

        existing = self.search_read("res.partner.category", domain, ["id", "name"])
        if existing:
            print(f"  → Category exists: {name}")
            return existing[0]["id"]

        values = {"name": name}
        if parent_id:
            # Ensure parent_id is an integer, not a list
            values["parent_id"] = parent_id[0] if isinstance(parent_id, list) else parent_id
        if color:
            values["color"] = color

        cat_id = self.create("res.partner.category", values)
        print(f"  ✓ Created category: {name} (ID: {cat_id})")
        return cat_id

    def setup_lead_list_categories(self, industry=None):
        """Create the lead list category structure"""
        print("\n📁 Setting up category structure...")

        # Parent category: Lead List
        parent_id = self.get_or_create_category("Lead List", color=CATEGORY_COLORS["Lead List"])

        # Purpose tags under Lead List
        for_sale_id = self.get_or_create_category("For Sale", parent_id, CATEGORY_COLORS["For Sale"])
        outreach_id = self.get_or_create_category("Outreach Target", parent_id, CATEGORY_COLORS["Outreach Target"])

        # Industry category if specified
        industry_id = None
        if industry:
            industry_id = self.get_or_create_category(industry, parent_id, CATEGORY_COLORS.get(industry, 2))

        # Value tier categories
        value_cats = {}
        for tier in ["Premium", "High Value", "Medium Value", "Low Value"]:
            value_cats[tier] = self.get_or_create_category(tier, parent_id, CATEGORY_COLORS.get(tier, 0))

        return {
            "parent": parent_id,
            "for_sale": for_sale_id,
            "outreach": outreach_id,
            "industry": industry_id,
            "value_tiers": value_cats,
        }

    # ========== Company/Contact Management ==========

    def get_or_create_company(self, name, **kwargs):
        """Get existing company or create new one"""
        if not name or name.strip() == "":
            return None

        domain = [("name", "=", name), ("is_company", "=", True)]
        existing = self.search_read("res.partner", domain, ["id", "name"])

        if existing:
            if kwargs.get("category_id"):
                self.write("res.partner", [existing[0]["id"]], {"category_id": kwargs["category_id"]})
            return existing[0]["id"]

        values = {"name": name, "is_company": True, "company_type": "company", **kwargs}

        company_id = self.create("res.partner", values)
        return company_id

    def get_or_create_contact(self, name, email=None, phone=None, company_id=None, category_ids=None, **kwargs):
        """Get existing contact or create new one"""
        if not name or name.strip() == "":
            return None

        # Search by email if available (more reliable)
        if email:
            domain = [("email", "=", email)]
        else:
            domain = [("name", "=", name), ("is_company", "=", False)]

        existing = self.search_read("res.partner", domain, ["id", "name"])

        if existing:
            # Update categories if provided
            if category_ids:
                self.write(
                    "res.partner", [existing[0]["id"]], {"category_id": [(4, cat_id) for cat_id in category_ids]}
                )
            return existing[0]["id"]

        values = {"name": name, "is_company": False, "company_type": "person", "email": email, "phone": phone, **kwargs}

        if company_id:
            values["parent_id"] = company_id

        if category_ids:
            values["category_id"] = [(4, cat_id) for cat_id in category_ids]

        contact_id = self.create("res.partner", values)
        return contact_id

    def create_lead_list_company(self, list_name, category_ids=None):
        """Create parent company for lead list organization"""
        print(f"\n🏢 Creating lead list organization: {list_name}")

        # Check for parent "Lead Lists" umbrella company
        umbrella = self.search_read("res.partner", [("name", "=", "Lead Lists"), ("is_company", "=", True)], ["id"])

        if not umbrella:
            umbrella_id = self.create(
                "res.partner",
                {
                    "name": "Lead Lists",
                    "is_company": True,
                    "company_type": "company",
                    "comment": "Parent organization for all imported lead lists",
                    "category_id": [(4, category_ids["parent"])] if category_ids else [],
                },
            )
            print(f"  ✓ Created umbrella company: Lead Lists (ID: {umbrella_id})")
        else:
            umbrella_id = umbrella[0]["id"]
            print("  → Umbrella company exists: Lead Lists")
            if category_ids:
                self.write("res.partner", [umbrella_id], {"category_id": [(4, category_ids["parent"])]})

        # Create specific lead list company
        list_company = self.search_read("res.partner", [("name", "=", list_name), ("is_company", "=", True)], ["id"])

        if not list_company:
            cats = []
            if category_ids:
                cats = [(4, category_ids["parent"])]
                if category_ids.get("industry"):
                    cats.append((4, category_ids["industry"]))
                cats.append((4, category_ids["for_sale"]))
                cats.append((4, category_ids["outreach"]))

            list_company_id = self.create(
                "res.partner",
                {
                    "name": list_name,
                    "is_company": True,
                    "company_type": "company",
                    "parent_id": umbrella_id,
                    "comment": f"Lead list imported on {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                    "category_id": cats,
                },
            )
            print(f"  ✓ Created lead list company: {list_name} (ID: {list_company_id})")
        else:
            list_company_id = list_company[0]["id"]
            print(f"  → Lead list company exists: {list_name}")
            if category_ids:
                cats = [(4, category_ids["parent"])]
                if category_ids.get("industry"):
                    cats.append((4, category_ids["industry"]))
                cats.append((4, category_ids["for_sale"]))
                cats.append((4, category_ids["outreach"]))
                self.write("res.partner", [list_company_id], {"category_id": cats})

        return umbrella_id, list_company_id

    # ========== CRM Lead Management ==========

    def create_crm_lead(
        self,
        name,
        contact_id=None,
        partner_name=None,
        email=None,
        phone=None,
        expected_revenue=0,
        description=None,
        **kwargs,
    ):
        """Create a CRM lead"""
        values = {
            "name": name,
            "type": "lead",
            "partner_name": partner_name,
            "email_from": email,
            "phone": phone,
            "expected_revenue": expected_revenue,
            "description": description,
            **kwargs,
        }

        if contact_id:
            values["partner_id"] = contact_id

        lead_id = self.create("crm.lead", values)
        return lead_id

    # ========== Import Logic ==========

    def import_csv(self, csv_path, list_name=None, industry=None):
        """Import leads from CSV file"""
        csv_path = Path(csv_path).expanduser()

        if not csv_path.exists():
            print(f"✗ File not found: {csv_path}")
            sys.exit(1)

        # Auto-generate list name from filename if not provided
        if not list_name:
            list_name = f"Lead List - {csv_path.stem}"

        print(f"\n{'=' * 60}")
        print("📊 LEAD LIST IMPORT")
        print(f"{'=' * 60}")
        print(f"File: {csv_path}")
        print(f"List Name: {list_name}")
        print(f"Industry: {industry or 'General'}")

        # Setup categories
        category_ids = self.setup_lead_list_categories(industry)

        # Create lead list organization (side effects only, IDs not needed)
        _umbrella_id, _list_company_id = self.create_lead_list_company(list_name, category_ids)

        # Read and process CSV
        print("\n📥 Processing CSV file...")

        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        print(f"   Found {len(rows)} records")

        # Track statistics
        stats = {"companies_created": 0, "contacts_created": 0, "leads_created": 0, "skipped": 0}
        seen_company_ids = set()
        seen_contact_ids = set()

        # Process each row
        print("\n👥 Importing contacts and creating leads...")

        for i, row in enumerate(rows, 1):
            try:
                # Extract fields (handle various CSV column names)
                contact_name = row.get("contact_name", row.get("Contact Name", "")).strip()
                contact_email = row.get("contact_email", row.get("Email", "")).strip()
                contact_phone = row.get("contact_phone", row.get("Phone", "")).strip()
                company_name = row.get("company_name", row.get("Contact Company", "")).strip()
                owner_name = row.get("owner_name", row.get("Owner", "")).strip()

                # Valuation and scoring
                valuation_str = row.get("project_valuation", row.get("Valuation", "0"))
                try:
                    valuation = float(str(valuation_str).replace("$", "").replace(",", "").strip() or 0)
                except ValueError:
                    valuation = 0

                valuation_tier = row.get("valuation_tier", row.get("Value Tier", "UNKNOWN")).upper()
                score = row.get("score", row.get("Score", ""))

                # Permit/project info
                permit_number = row.get("permit_number", row.get("Permit #", ""))
                permit_type = row.get("permit_type", row.get("Type", ""))
                contact_role = row.get("contact_role", row.get("Contact Role", ""))

                # Skip if no contact name
                if not contact_name or contact_name in ["OUT TO BID", ""]:
                    stats["skipped"] += 1
                    continue

                # Determine category tags for this contact
                contact_cats = [category_ids["parent"]]
                if category_ids.get("industry"):
                    contact_cats.append(category_ids["industry"])

                # Add value tier tag
                tier_map = {"PREMIUM": "Premium", "HIGH": "High Value", "MEDIUM": "Medium Value", "LOW": "Low Value"}
                tier_name = tier_map.get(valuation_tier)
                if tier_name and tier_name in category_ids["value_tiers"]:
                    contact_cats.append(category_ids["value_tiers"][tier_name])

                # Create or get company
                company_id = None
                if company_name:
                    company_id = self.get_or_create_company(
                        company_name, category_id=[(4, cat) for cat in contact_cats]
                    )
                    if company_id:
                        seen_company_ids.add(company_id)

                # Create or get contact
                contact_comment = []
                if permit_number:
                    contact_comment.append(f"Permit: {permit_number}")
                if permit_type:
                    contact_comment.append(f"Type: {permit_type}")
                if contact_role:
                    contact_comment.append(f"Role: {contact_role}")
                if owner_name:
                    contact_comment.append(f"Property Owner: {owner_name}")
                if score:
                    contact_comment.append(f"Lead Score: {score}")

                contact_id = self.get_or_create_contact(
                    contact_name,
                    email=contact_email if contact_email else None,
                    phone=contact_phone if contact_phone else None,
                    company_id=company_id,
                    category_ids=contact_cats,
                    comment="\n".join(contact_comment) if contact_comment else None,
                )

                if contact_id:
                    seen_contact_ids.add(contact_id)

                # Create CRM lead
                lead_name = f"{contact_name}"
                if company_name:
                    lead_name = f"{company_name} - {contact_name}"
                if permit_number:
                    lead_name = f"[{permit_number}] {lead_name}"

                description_parts = []
                if permit_type:
                    description_parts.append(f"**Permit Type:** {permit_type}")
                if owner_name:
                    description_parts.append(f"**Property Owner:** {owner_name}")
                if contact_role:
                    description_parts.append(f"**Contact Role:** {contact_role.title()}")
                if valuation_tier:
                    description_parts.append(f"**Value Tier:** {valuation_tier}")
                if score:
                    description_parts.append(f"**Lead Score:** {score}")

                description_parts.append(f"\n**Source:** {list_name}")
                description_parts.append(f"**Imported:** {datetime.now().strftime('%Y-%m-%d')}")

                lead_id = self.create_crm_lead(
                    name=lead_name,
                    contact_id=contact_id,
                    partner_name=company_name or contact_name,
                    email=contact_email if contact_email else None,
                    phone=contact_phone if contact_phone else None,
                    expected_revenue=valuation,
                    description="\n".join(description_parts),
                )

                if lead_id:
                    stats["leads_created"] += 1

                # Progress update
                if i % 25 == 0:
                    print(f"   Processed {i}/{len(rows)} records...")

            except Exception as e:
                print(f"   ⚠ Error processing row {i}: {e}")
                stats["skipped"] += 1

        # Print summary
        print(f"\n{'=' * 60}")
        print("✅ IMPORT COMPLETE")
        print(f"{'=' * 60}")
        stats["companies_created"] = len(seen_company_ids)
        stats["contacts_created"] = len(seen_contact_ids)
        print(f"   Companies created/found: {stats['companies_created']} (unique)")
        print(f"   Contacts created/found:  {stats['contacts_created']} (unique)")
        print(f"   CRM Leads created:       {stats['leads_created']}")
        print(f"   Skipped:                 {stats['skipped']}")
        print(f"\n📌 Lead list organization: {list_name}")
        print(f"   View in Odoo: {self.config['url']}/web#model=res.partner&view_type=kanban")

        return stats


def main():
    parser = argparse.ArgumentParser(
        description="Import lead lists into Odoo CRM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("csv_file", help="Path to CSV file with lead data")
    parser.add_argument("--list-name", "-n", help="Name for this lead list")
    parser.add_argument("--industry", "-i", help="Industry category (e.g., Construction, Healthcare)")
    parser.add_argument("--url", help="Odoo URL (default from config)")
    parser.add_argument("--db", help="Odoo database name")
    parser.add_argument("--username", "-u", help="Odoo username")
    parser.add_argument("--api-key", "-k", help="Odoo API key")

    args = parser.parse_args()

    config = load_odoo_config(
        overrides={
            "url": args.url,
            "db": args.db,
            "username": args.username,
            "api_key": args.api_key,
        }
    )

    # Create importer and run
    importer = OdooLeadImporter(config)
    importer.import_csv(args.csv_file, args.list_name, args.industry)


if __name__ == "__main__":
    main()
