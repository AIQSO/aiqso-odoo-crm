#!/usr/bin/env python3
"""
Commercial Leads Import Script for Odoo CRM

Imports commercial leads from the multi-city commercial_leads CSV format.
Handles leads with or without contact details.

Usage:
    python3 import_commercial_leads.py <csv_file> [--city "City Name"] [--exclude-city "City"]

Example:
    # Import all cities except Fort Worth
    python3 import_commercial_leads.py ~/projects/accela/exports/commercial_leads_20251217.csv \
        --exclude-city "Fort Worth"

    # Import only Arlington
    python3 import_commercial_leads.py ~/projects/accela/exports/commercial_leads_20251217.csv \
        --city "Arlington"
"""

import argparse
import csv
import re
import sys
import xmlrpc.client
from datetime import datetime
from pathlib import Path

from config import load_odoo_config, require_config

# Category color mapping
CATEGORY_COLORS = {
    "Lead List": 10,
    "For Sale": 11,
    "Outreach Target": 4,
    "Construction": 2,
    "Premium": 6,
    "High Value": 5,
    "Medium Value": 3,
    "Low Value": 1,
    # Project categories
    "Retail": 7,
    "Office": 8,
    "Industrial": 9,
    "Restaurant": 3,
    "Medical": 4,
}


class OdooCommercialImporter:
    def __init__(self, config=None):
        self.config = config or load_odoo_config()
        self.uid = None
        self.models = None
        self._connect()
        self._category_cache = {}

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
        kwargs = {}
        if fields:
            kwargs["fields"] = fields
        if limit:
            kwargs["limit"] = limit
        return self._execute(model, "search_read", domain, **kwargs)

    def create(self, model, values):
        result = self._execute(model, "create", [values])
        if isinstance(result, list):
            return result[0] if result else None
        return result

    def write(self, model, ids, values):
        return self._execute(model, "write", ids, values)

    def search(self, model, domain, limit=None):
        kwargs = {}
        if limit:
            kwargs["limit"] = limit
        return self._execute(model, "search", domain, **kwargs)

    def get_or_create_category(self, name, parent_id=None, color=None):
        """Get existing category or create new one (with caching)"""
        cache_key = f"{name}:{parent_id}"
        if cache_key in self._category_cache:
            return self._category_cache[cache_key]

        domain = [("name", "=", name)]
        if parent_id:
            pid = parent_id[0] if isinstance(parent_id, list) else parent_id
            domain.append(("parent_id", "=", pid))

        existing = self.search_read("res.partner.category", domain, ["id", "name"])
        if existing:
            self._category_cache[cache_key] = existing[0]["id"]
            return existing[0]["id"]

        values = {"name": name}
        if parent_id:
            values["parent_id"] = parent_id[0] if isinstance(parent_id, list) else parent_id
        if color:
            values["color"] = color

        cat_id = self.create("res.partner.category", values)
        print(f"  ✓ Created category: {name} (ID: {cat_id})")
        self._category_cache[cache_key] = cat_id
        return cat_id

    def setup_categories(self):
        """Create/get the lead list category structure"""
        print("\n📁 Setting up category structure...")

        # Get or create parent Lead List category
        parent_id = self.get_or_create_category("Lead List", color=CATEGORY_COLORS["Lead List"])

        # Purpose tags
        for_sale_id = self.get_or_create_category("For Sale", parent_id, CATEGORY_COLORS["For Sale"])
        outreach_id = self.get_or_create_category("Outreach Target", parent_id, CATEGORY_COLORS["Outreach Target"])

        # Industry
        construction_id = self.get_or_create_category("Construction", parent_id, CATEGORY_COLORS["Construction"])

        # Value tiers
        value_cats = {}
        for tier in ["Premium", "High Value", "Medium Value", "Low Value"]:
            value_cats[tier] = self.get_or_create_category(tier, parent_id, CATEGORY_COLORS.get(tier, 0))

        # Project categories
        project_cats = {}
        for cat in ["Retail", "Office", "Industrial", "Restaurant", "Medical"]:
            project_cats[cat] = self.get_or_create_category(cat, parent_id, CATEGORY_COLORS.get(cat, 0))

        return {
            "parent": parent_id,
            "for_sale": for_sale_id,
            "outreach": outreach_id,
            "construction": construction_id,
            "value_tiers": value_cats,
            "project_cats": project_cats,
        }

    def get_or_create_list_company(self, city, category_ids):
        """Create lead list company for a city"""
        list_name = f"Lead List - {city} Commercial - Dec 2024"

        # Ensure umbrella company exists
        umbrella = self.search_read("res.partner", [("name", "=", "Lead Lists"), ("is_company", "=", True)], ["id"])

        if not umbrella:
            umbrella_id = self.create(
                "res.partner",
                {
                    "name": "Lead Lists",
                    "is_company": True,
                    "company_type": "company",
                    "comment": "Parent organization for all imported lead lists",
                    "category_id": [(4, category_ids["parent"])],
                },
            )
            print(f"  ✓ Created umbrella company: Lead Lists (ID: {umbrella_id})")
        else:
            umbrella_id = umbrella[0]["id"]

        # Create city-specific lead list company
        list_company = self.search_read("res.partner", [("name", "=", list_name), ("is_company", "=", True)], ["id"])

        if not list_company:
            list_company_id = self.create(
                "res.partner",
                {
                    "name": list_name,
                    "is_company": True,
                    "company_type": "company",
                    "parent_id": umbrella_id,
                    "comment": f"{city} commercial leads imported on {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                    "category_id": [
                        (4, category_ids["parent"]),
                        (4, category_ids["construction"]),
                        (4, category_ids["for_sale"]),
                        (4, category_ids["outreach"]),
                    ],
                },
            )
            print(f"  ✓ Created lead list company: {list_name} (ID: {list_company_id})")
        else:
            list_company_id = list_company[0]["id"]
            print(f"  → Lead list company exists: {list_name}")

        return list_company_id

    def parse_valuation(self, val_str):
        """Parse valuation string like '$420K' or '$1.2M' to float"""
        if not val_str or val_str == "TBD":
            return 0

        val_str = val_str.strip().upper()
        multiplier = 1

        if "K" in val_str:
            multiplier = 1000
            val_str = val_str.replace("K", "")
        elif "M" in val_str:
            multiplier = 1000000
            val_str = val_str.replace("M", "")

        # Remove $ and commas
        val_str = re.sub(r"[$,]", "", val_str)

        try:
            return float(val_str) * multiplier
        except ValueError:
            return 0

    def get_value_tier(self, valuation):
        """Determine value tier from valuation amount"""
        if valuation >= 500000:
            return "Premium"
        elif valuation >= 100000:
            return "High Value"
        elif valuation >= 25000:
            return "Medium Value"
        elif valuation > 0:
            return "Low Value"
        return None

    def map_project_category(self, project_cat):
        """Map project category to our category"""
        if not project_cat:
            return None

        project_cat = project_cat.lower()

        if "retail" in project_cat:
            return "Retail"
        elif "office" in project_cat:
            return "Office"
        elif "industrial" in project_cat or "warehouse" in project_cat:
            return "Industrial"
        elif "restaurant" in project_cat or "food" in project_cat:
            return "Restaurant"
        elif "medical" in project_cat or "health" in project_cat:
            return "Medical"
        return None

    def create_crm_lead(self, name, partner_name=None, expected_revenue=0, description=None, **kwargs):
        """Create a CRM lead"""
        values = {
            "name": name,
            "type": "lead",
            "partner_name": partner_name,
            "expected_revenue": expected_revenue,
            "description": description,
            **kwargs,
        }
        return self.create("crm.lead", values)

    def import_csv(self, csv_path, city_filter=None, exclude_cities=None):
        """Import commercial leads from CSV"""
        csv_path = Path(csv_path).expanduser()

        if not csv_path.exists():
            print(f"✗ File not found: {csv_path}")
            sys.exit(1)

        print(f"\n{'=' * 60}")
        print("📊 COMMERCIAL LEADS IMPORT")
        print(f"{'=' * 60}")
        print(f"File: {csv_path}")
        if city_filter:
            print(f"Filter: Only {city_filter}")
        if exclude_cities:
            print(f"Excluding: {', '.join(exclude_cities)}")

        # Setup categories
        category_ids = self.setup_categories()

        # Read CSV
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            all_rows = list(reader)

        # Filter rows
        rows = []
        for r in all_rows:
            city = r.get("City", "").strip()
            if city_filter and city != city_filter:
                continue
            if exclude_cities and city in exclude_cities:
                continue
            if city:  # Only include rows with a city
                rows.append(r)

        print(f"\n📥 Processing {len(rows)} records...")

        # Group by city
        cities = {}
        for r in rows:
            city = r.get("City", "Unknown").strip()
            if city not in cities:
                cities[city] = []
            cities[city].append(r)

        print(f"   Cities to import: {', '.join(cities.keys())}")

        # Track statistics
        total_stats = {"leads_created": 0, "skipped": 0, "by_city": {}}

        # Process each city
        for city, city_rows in cities.items():
            print(f"\n{'=' * 40}")
            print(f"🏙️  Importing {city} ({len(city_rows)} records)")
            print(f"{'=' * 40}")

            # Create lead list company for this city (side effect, ID not needed)
            self.get_or_create_list_company(city, category_ids)

            city_stats = {"created": 0, "skipped": 0}

            for i, row in enumerate(city_rows, 1):
                try:
                    # Extract fields
                    permit_number = row.get("Permit Number", "").strip()
                    address = row.get("Full Address", "").strip()
                    valuation_str = row.get("Valuation", "")
                    valuation = self.parse_valuation(valuation_str)
                    project_category = row.get("Project Category", "")
                    project_type = row.get("Project Type", "")
                    use_type = row.get("Use Type", "")
                    specific_use = row.get("Specific Use", "")
                    description = row.get("Project Description", "")
                    owner = row.get("Property Owner", "")
                    contractor = row.get("Contractor", "")
                    sq_ft = row.get("Square Feet", "")
                    lead_score = row.get("Lead Score", "")
                    priority = row.get("Priority", "")
                    data_source = row.get("Data Source", "")

                    # Build lead name
                    lead_name = f"[{permit_number}]" if permit_number else ""
                    if project_category:
                        lead_name += f" {project_category}"
                    if address:
                        # Shorten address for lead name
                        short_addr = address.split(",")[0] if "," in address else address
                        lead_name += f" - {short_addr}"
                    lead_name = lead_name.strip() or f"Commercial Lead - {city}"

                    # Build description
                    desc_parts = []
                    if priority:
                        desc_parts.append(f"**Priority:** {priority}")
                    if lead_score:
                        desc_parts.append(f"**Lead Score:** {lead_score}")
                    if project_type:
                        desc_parts.append(f"**Project Type:** {project_type}")
                    if use_type:
                        desc_parts.append(f"**Use Type:** {use_type}")
                    if specific_use:
                        desc_parts.append(f"**Specific Use:** {specific_use}")
                    if sq_ft:
                        desc_parts.append(f"**Square Feet:** {sq_ft}")
                    if owner:
                        desc_parts.append(f"**Property Owner:** {owner}")
                    if contractor:
                        desc_parts.append(f"**Contractor:** {contractor}")
                    if address:
                        desc_parts.append(f"**Address:** {address}")
                    if description:
                        desc_parts.append(f"\n**Description:**\n{description[:500]}...")
                    desc_parts.append(f"\n**Source:** {data_source}")
                    desc_parts.append(f"**Imported:** {datetime.now().strftime('%Y-%m-%d')}")

                    # Create CRM lead
                    lead_id = self.create_crm_lead(
                        name=lead_name,
                        partner_name=owner or contractor or city,
                        expected_revenue=valuation,
                        description="\n".join(desc_parts),
                        street=address,
                    )

                    if lead_id:
                        city_stats["created"] += 1
                    else:
                        city_stats["skipped"] += 1

                except Exception as e:
                    print(f"   ⚠ Error on row {i}: {e}")
                    city_stats["skipped"] += 1

                # Progress update
                if i % 50 == 0:
                    print(f"   Processed {i}/{len(city_rows)}...")

            print(f"   ✓ {city}: {city_stats['created']} leads created, {city_stats['skipped']} skipped")
            total_stats["leads_created"] += city_stats["created"]
            total_stats["skipped"] += city_stats["skipped"]
            total_stats["by_city"][city] = city_stats

        # Print summary
        print(f"\n{'=' * 60}")
        print("✅ IMPORT COMPLETE")
        print(f"{'=' * 60}")
        print(f"   Total Leads Created: {total_stats['leads_created']}")
        print(f"   Total Skipped:       {total_stats['skipped']}")
        print("\n   By City:")
        for city, stats in total_stats["by_city"].items():
            print(f"     {city}: {stats['created']} leads")
        print(f"\n📌 View in Odoo: {self.config['url']}/web#model=crm.lead&view_type=kanban")

        return total_stats


def main():
    parser = argparse.ArgumentParser(
        description="Import commercial leads into Odoo CRM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("csv_file", help="Path to CSV file")
    parser.add_argument("--city", "-c", help="Import only this city")
    parser.add_argument(
        "--exclude-city", "-x", action="append", default=[], help="Exclude this city (can be used multiple times)"
    )
    parser.add_argument("--url", help="Odoo URL (default from env/config)")
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

    importer = OdooCommercialImporter(config=config)
    importer.import_csv(args.csv_file, args.city, args.exclude_city)


if __name__ == "__main__":
    main()
