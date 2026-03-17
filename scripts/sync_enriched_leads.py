#!/usr/bin/env python3
"""
Sync Enriched Leads from PostgreSQL to Odoo CRM

This script syncs enriched permit lead data from the accela-scraper PostgreSQL
database to Odoo CRM, matching by permit number and updating contact info.

Usage:
    python3 sync_enriched_leads.py [--city "Fort Worth"] [--dry-run]

Example:
    # Sync all enriched leads
    python3 sync_enriched_leads.py

    # Sync only Fort Worth, dry run first
    python3 sync_enriched_leads.py --city "Fort Worth" --dry-run
"""

import argparse
import sys
import xmlrpc.client
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor

from config import load_odoo_config, load_postgres_config, require_config


class EnrichedLeadSync:
    def __init__(self, postgres_config=None, odoo_config=None):
        self.pg_config = postgres_config or load_postgres_config()
        self.odoo_config = odoo_config or load_odoo_config()
        self.pg_conn = None
        self.odoo_uid = None
        self.odoo_models = None
        self._odoo_field_cache = {}

    def connect_postgres(self):
        """Connect to PostgreSQL database"""
        require_config(
            self.pg_config,
            required_keys=["host", "port", "database", "user", "password"],
            source_hint="POSTGRES_HOST/POSTGRES_PORT/POSTGRES_DB/POSTGRES_USER/POSTGRES_PASSWORD",
        )
        try:
            self.pg_conn = psycopg2.connect(
                host=self.pg_config["host"],
                port=self.pg_config["port"],
                database=self.pg_config["database"],
                user=self.pg_config["user"],
                password=self.pg_config["password"],
            )
            print(f"✓ Connected to PostgreSQL: {self.pg_config['host']}:{self.pg_config['port']}")
        except Exception as e:
            print(f"✗ PostgreSQL connection failed: {e}")
            sys.exit(1)

    def connect_odoo(self):
        """Connect to Odoo"""
        require_config(
            self.odoo_config,
            required_keys=["url", "db", "username", "api_key"],
            source_hint="ODOO_URL/ODOO_DB/ODOO_USERNAME/ODOO_API_KEY",
        )
        try:
            common = xmlrpc.client.ServerProxy(f"{self.odoo_config['url']}/xmlrpc/2/common")
            self.odoo_uid = common.authenticate(
                self.odoo_config["db"], self.odoo_config["username"], self.odoo_config["api_key"], {}
            )
            if not self.odoo_uid:
                raise Exception("Authentication failed")

            self.odoo_models = xmlrpc.client.ServerProxy(f"{self.odoo_config['url']}/xmlrpc/2/object")
            print(f"✓ Connected to Odoo as user ID: {self.odoo_uid}")
        except Exception as e:
            print(f"✗ Odoo connection failed: {e}")
            sys.exit(1)

    def odoo_execute(self, model, method, *args, **kwargs):
        """Execute Odoo model method"""
        return self.odoo_models.execute_kw(
            self.odoo_config["db"], self.odoo_uid, self.odoo_config["api_key"], model, method, args, kwargs
        )

    def odoo_model_fields(self, model):
        if model in self._odoo_field_cache:
            return self._odoo_field_cache[model]

        fields = self.odoo_execute(model, "fields_get", [], {"attributes": ["string"]})
        field_names = set(fields.keys()) if isinstance(fields, dict) else set()
        self._odoo_field_cache[model] = field_names
        return field_names

    def odoo_filter_values(self, model, values):
        """Drop keys that are not valid fields for this Odoo model."""
        allowed = self.odoo_model_fields(model)
        return {k: v for k, v in values.items() if k in allowed}

    def get_enriched_leads(self, city=None, min_score=50):
        """Get enriched leads from PostgreSQL that have contact info"""
        query = """
            SELECT
                pl.id as lead_id,
                p.external_permit_id as permit_number,
                p.city_name,
                p.address_line1,
                p.project_valuation,
                p.permit_type,
                p.owner_name,
                pl.contact_name,
                pl.contact_email,
                pl.contact_phone,
                pl.company_name,
                pl.contact_role,
                pl.score,
                pl.valuation_tier,
                pl.updated_at
            FROM permit_leads pl
            JOIN permits p ON pl.permit_id = p.id
            WHERE pl.is_commercial = true
                AND pl.score >= %s
                AND (
                    (pl.contact_email IS NOT NULL AND pl.contact_email != '')
                    OR (pl.contact_phone IS NOT NULL AND pl.contact_phone != '')
                )
        """

        params = [min_score]

        if city:
            query += " AND UPPER(p.city_name) = UPPER(%s)"
            params.append(city)

        query += " ORDER BY pl.updated_at DESC"

        with self.pg_conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, params)
            results = cursor.fetchall()
            return [dict(row) for row in results]

    def find_odoo_lead_by_permit(self, permit_number):
        """Find Odoo CRM lead by permit number in the name"""
        # Search for leads with permit number in the name
        domain = [("name", "ilike", f"[{permit_number}]")]
        leads = self.odoo_execute(
            "crm.lead",
            "search_read",
            domain,
            fields=["id", "name", "email_from", "phone", "partner_name", "description"],
        )

        if leads:
            return leads[0]
        return None

    def find_odoo_contact_by_email(self, email):
        """Find Odoo contact by email"""
        if not email:
            return None

        domain = [("email", "=", email)]
        contacts = self.odoo_execute("res.partner", "search_read", domain, fields=["id", "name", "email", "phone"])

        if contacts:
            return contacts[0]
        return None

    def update_odoo_lead(self, lead_id, enriched_data):
        """Update Odoo CRM lead with enriched contact data"""
        update_values = {}

        # Update contact info
        if enriched_data.get("contact_email"):
            update_values["email_from"] = enriched_data["contact_email"]

        if enriched_data.get("contact_phone"):
            # Format phone number
            phone = str(enriched_data["contact_phone"])
            if len(phone) == 10:
                phone = f"({phone[:3]}) {phone[3:6]}-{phone[6:]}"
            update_values["phone"] = phone

        if enriched_data.get("contact_name"):
            update_values["contact_name"] = enriched_data["contact_name"]

        if enriched_data.get("company_name"):
            update_values["partner_name"] = enriched_data["company_name"]

        # Add enrichment note to description
        enrichment_note = f"\n\n--- Enriched {datetime.now().strftime('%Y-%m-%d %H:%M')} ---\n"
        if enriched_data.get("contact_name"):
            enrichment_note += f"Contact: {enriched_data['contact_name']}\n"
        if enriched_data.get("contact_role"):
            enrichment_note += f"Role: {enriched_data['contact_role']}\n"
        if enriched_data.get("company_name"):
            enrichment_note += f"Company: {enriched_data['company_name']}\n"

        if enrichment_note.strip() != f"--- Enriched {datetime.now().strftime('%Y-%m-%d %H:%M')} ---":
            # Get current description and append
            lead = self.odoo_execute("crm.lead", "read", [lead_id], ["description"])
            current_desc = lead[0].get("description") or "" if lead else ""

            # Only add if not already enriched today
            today_marker = f"--- Enriched {datetime.now().strftime('%Y-%m-%d')}"
            if today_marker not in current_desc:
                update_values["description"] = current_desc + enrichment_note

        if update_values:
            update_values = self.odoo_filter_values("crm.lead", update_values)
            if not update_values:
                return False
            self.odoo_execute("crm.lead", "write", [lead_id], update_values)
            return True

        return False

    def update_odoo_contact(self, contact_id, enriched_data):
        """Update Odoo contact with enriched data"""
        update_values = {}

        if enriched_data.get("contact_phone") and enriched_data["contact_phone"]:
            phone = str(enriched_data["contact_phone"])
            if len(phone) == 10:
                phone = f"({phone[:3]}) {phone[3:6]}-{phone[6:]}"
            update_values["phone"] = phone

        if enriched_data.get("company_name"):
            # Check if company exists, link to it
            company = self.odoo_execute(
                "res.partner",
                "search_read",
                [("name", "=", enriched_data["company_name"]), ("is_company", "=", True)],
                fields=["id"],
            )
            if company:
                update_values["parent_id"] = company[0]["id"]

        if update_values:
            update_values = self.odoo_filter_values("res.partner", update_values)
            if not update_values:
                return False
            self.odoo_execute("res.partner", "write", [contact_id], update_values)
            return True

        return False

    def create_odoo_lead(self, enriched_data):
        """Create a new CRM lead in Odoo from enriched PostgreSQL data"""
        permit_number = enriched_data.get("permit_number", "")
        city = enriched_data.get("city_name", "Unknown")

        # Build lead name
        lead_name = f"[{permit_number}]" if permit_number else ""
        if enriched_data.get("company_name"):
            lead_name += f" {enriched_data['company_name']}"
        if enriched_data.get("contact_name"):
            lead_name += f" - {enriched_data['contact_name']}"
        lead_name = lead_name.strip() or f"Lead - {permit_number}"

        # Format phone
        phone = enriched_data.get("contact_phone")
        if phone:
            phone = str(phone)
            if len(phone) == 10:
                phone = f"({phone[:3]}) {phone[3:6]}-{phone[6:]}"

        # Build description
        desc_parts = []
        if enriched_data.get("permit_type"):
            desc_parts.append(f"**Permit Type:** {enriched_data['permit_type']}")
        if enriched_data.get("owner_name"):
            desc_parts.append(f"**Property Owner:** {enriched_data['owner_name']}")
        if enriched_data.get("contact_role"):
            desc_parts.append(f"**Contact Role:** {enriched_data['contact_role']}")
        if enriched_data.get("score"):
            desc_parts.append(f"**Lead Score:** {enriched_data['score']}")
        if enriched_data.get("valuation_tier"):
            desc_parts.append(f"**Value Tier:** {enriched_data['valuation_tier']}")
        desc_parts.append("\n**Source:** PostgreSQL Enrichment Sync")
        desc_parts.append(f"**City:** {city}")
        desc_parts.append(f"**Synced:** {datetime.now().strftime('%Y-%m-%d')}")

        values = {
            "name": lead_name,
            "type": "lead",
            "partner_name": enriched_data.get("company_name") or enriched_data.get("contact_name") or city,
            "expected_revenue": float(enriched_data.get("project_valuation") or 0),
            "description": "\n".join(desc_parts),
        }

        # Only add optional fields if they have values (avoid None)
        if enriched_data.get("contact_name"):
            values["contact_name"] = enriched_data["contact_name"]
        if enriched_data.get("contact_email"):
            values["email_from"] = enriched_data["contact_email"]
        if phone:
            values["phone"] = phone
        if enriched_data.get("address_line1"):
            values["street"] = enriched_data["address_line1"]

        try:
            values = self.odoo_filter_values("crm.lead", values)
            lead_id = self.odoo_execute("crm.lead", "create", [values])
            if isinstance(lead_id, list):
                lead_id = lead_id[0] if lead_id else None
            return lead_id
        except Exception as e:
            print(f"   ⚠ Failed to create lead: {e}")
            return None

    def sync(self, city=None, dry_run=False, create_new=False):
        """Main sync process

        Args:
            city: Filter by city name
            dry_run: Show what would be done without making changes
            create_new: Create new leads in Odoo for permits not found
        """
        print(f"\n{'=' * 60}")
        print("🔄 ENRICHED LEADS SYNC")
        print(f"{'=' * 60}")
        if city:
            print(f"City Filter: {city}")
        if dry_run:
            print("Mode: DRY RUN (no changes will be made)")
        if create_new:
            print("Create New: Will create leads for permits not in Odoo")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Connect to both systems
        self.connect_postgres()
        self.connect_odoo()

        # Get enriched leads from PostgreSQL
        print("\n📥 Fetching enriched leads from PostgreSQL...")
        enriched_leads = self.get_enriched_leads(city=city)
        print(f"   Found {len(enriched_leads)} enriched leads with contact info")

        if not enriched_leads:
            print("   No enriched leads to sync.")
            return {"synced": 0, "not_found": 0, "skipped": 0}

        # Track statistics
        stats = {"synced": 0, "created": 0, "not_found": 0, "skipped": 0, "contacts_updated": 0}

        # Process each enriched lead
        print("\n🔄 Syncing to Odoo...")

        for i, lead in enumerate(enriched_leads, 1):
            permit_number = lead.get("permit_number", "")

            if not permit_number:
                stats["skipped"] += 1
                continue

            # Find matching Odoo lead
            odoo_lead = self.find_odoo_lead_by_permit(permit_number)

            if not odoo_lead:
                # Lead not found in Odoo
                if create_new:
                    # Only create if there's actual contact info
                    if not lead.get("contact_email") or lead.get("contact_email") == "None":
                        stats["skipped"] += 1
                        continue

                    if dry_run:
                        print(
                            f"   [DRY RUN] Would CREATE: [{permit_number}] {lead.get('contact_name')} - {lead.get('contact_email')}"
                        )
                        stats["created"] += 1
                    else:
                        # Create new lead in Odoo
                        new_lead_id = self.create_odoo_lead(lead)
                        if new_lead_id:
                            stats["created"] += 1
                else:
                    stats["not_found"] += 1
                continue

            # Check if Odoo lead already has this email
            if odoo_lead.get("email_from") == lead.get("contact_email"):
                stats["skipped"] += 1
                continue

            if dry_run:
                print(
                    f"   [DRY RUN] Would UPDATE: [{permit_number}] {lead.get('contact_name')} - {lead.get('contact_email')}"
                )
                stats["synced"] += 1
            else:
                # Update the Odoo lead
                if self.update_odoo_lead(odoo_lead["id"], lead):
                    stats["synced"] += 1

                    # Also update contact if exists
                    if lead.get("contact_email"):
                        contact = self.find_odoo_contact_by_email(lead["contact_email"])
                        if contact:
                            if self.update_odoo_contact(contact["id"], lead):
                                stats["contacts_updated"] += 1

            # Progress update
            if i % 25 == 0:
                print(f"   Processed {i}/{len(enriched_leads)}...")

        # Print summary
        print(f"\n{'=' * 60}")
        print("✅ SYNC COMPLETE")
        print(f"{'=' * 60}")
        print(f"   Leads Created:       {stats['created']}")
        print(f"   Leads Updated:       {stats['synced']}")
        print(f"   Contacts Updated:    {stats['contacts_updated']}")
        if not create_new:
            print(f"   Not Found in Odoo:   {stats['not_found']} (use --create-new to import)")
        print(f"   Skipped (no change): {stats['skipped']}")
        print(f"\n📌 View in Odoo: {self.odoo_config['url']}/web#model=crm.lead&view_type=kanban")

        # Close connections
        if self.pg_conn:
            self.pg_conn.close()

        return stats


def main():
    parser = argparse.ArgumentParser(
        description="Sync enriched leads from PostgreSQL to Odoo CRM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--city", "-c", help="Filter by city name")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Show what would be synced without making changes")
    parser.add_argument("--create-new", action="store_true", help="Create new leads in Odoo for permits not found")
    parser.add_argument("--url", help="Odoo URL (default from env/config)")
    parser.add_argument("--db", help="Odoo database name")
    parser.add_argument("--username", "-u", help="Odoo username")
    parser.add_argument("--api-key", "-k", help="Odoo API key")
    parser.add_argument("--pg-host", help="PostgreSQL host")
    parser.add_argument("--pg-port", type=int, help="PostgreSQL port")
    parser.add_argument("--pg-db", help="PostgreSQL database")
    parser.add_argument("--pg-user", help="PostgreSQL user")
    parser.add_argument("--pg-password", help="PostgreSQL password")

    args = parser.parse_args()

    odoo_config = load_odoo_config(
        overrides={
            "url": args.url,
            "db": args.db,
            "username": args.username,
            "api_key": args.api_key,
        }
    )
    pg_config = load_postgres_config(
        overrides={
            "host": args.pg_host,
            "port": args.pg_port,
            "database": args.pg_db,
            "user": args.pg_user,
            "password": args.pg_password,
        }
    )

    syncer = EnrichedLeadSync(postgres_config=pg_config, odoo_config=odoo_config)
    syncer.sync(city=args.city, dry_run=args.dry_run, create_new=args.create_new)


if __name__ == "__main__":
    main()
