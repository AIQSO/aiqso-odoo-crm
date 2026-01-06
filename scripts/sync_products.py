#!/usr/bin/env python3
"""Sync AIQSO products/services in Odoo.

This script creates and updates the AIQSO service catalog in Odoo.
It is idempotent - safe to run multiple times.
Updates prices if they've changed.

Usage:
    python sync_products.py
    python sync_products.py --dry-run  # Preview changes without applying
"""

import argparse
import sys
import xmlrpc.client
from typing import Any, cast

from config import get_odoo_connection

# =============================================================================
# AIQSO PRODUCT CATALOG - Updated 2025-01-06
# =============================================================================
# Pricing from aiqso.io/permits and aiqso.io/pricing
# Each product has a unique billing code (default_code) for invoicing
# =============================================================================

PRODUCTS = [
    # =========================================================================
    # DFW PERMIT LEADS - From /permits page
    # =========================================================================
    {
        "name": "DFW Permit Leads - Starter",
        "type": "service",
        "list_price": 249.00,
        "invoice_policy": "order",
        "default_code": "LEAD-DFW-STARTER",
        "description_sale": (
            "DFW Permit Leads - Starter Plan. "
            "5 DFW cities (your choice), residential permits only. "
            "Daily CSV export, email notifications, basic lead scoring. "
            "Cancel anytime."
        ),
        "categ_id": 1,
    },
    {
        "name": "DFW Permit Leads - Professional",
        "type": "service",
        "list_price": 499.00,
        "invoice_policy": "order",
        "default_code": "LEAD-DFW-PRO",
        "description_sale": (
            "DFW Permit Leads - Professional Plan. "
            "10 DFW cities, residential + commercial leads. "
            "REST API access, CRM webhook integration, advanced lead scoring. "
            "Priority email support, weekly summary reports."
        ),
        "categ_id": 1,
    },
    {
        "name": "DFW Permit Leads - Business",
        "type": "service",
        "list_price": 799.00,
        "invoice_policy": "order",
        "default_code": "LEAD-DFW-BIZ",
        "description_sale": (
            "DFW Permit Leads - Business Plan (MOST POPULAR). "
            "ALL 22+ DFW cities, residential + commercial leads. "
            "Full API access, contact enrichment (phone, email). "
            "Advanced lead scoring, CRM integration, real-time notifications. "
            "Dedicated account manager."
        ),
        "categ_id": 1,
    },
    {
        "name": "DFW Permit Leads - Enterprise",
        "type": "service",
        "list_price": 1499.00,
        "invoice_policy": "order",
        "default_code": "LEAD-DFW-ENT",
        "description_sale": (
            "DFW Permit Leads - Enterprise Plan. "
            "Everything in Business plus: exclusive leads option, "
            "custom lead scoring rules, priority data delivery, "
            "white-label reports, quarterly strategy calls, "
            "custom integrations, SLA guarantee."
        ),
        "categ_id": 1,
    },
    {
        "name": "DFW Permit Leads - Agency",
        "type": "service",
        "list_price": 2499.00,
        "invoice_policy": "order",
        "default_code": "LEAD-DFW-AGENCY",
        "description_sale": (
            "DFW Permit Leads - Agency/Reseller Plan. "
            "Everything in Enterprise plus: 5 sub-accounts included, "
            "reseller rights, API rate limit increase, custom branding, "
            "white-label dashboard, volume discounts, partner support line."
        ),
        "categ_id": 1,
    },
    # Annual pricing variants
    {
        "name": "DFW Permit Leads - Starter (Annual)",
        "type": "service",
        "list_price": 199.00,
        "invoice_policy": "order",
        "default_code": "LEAD-DFW-STARTER-YR",
        "description_sale": (
            "DFW Permit Leads - Starter Plan (Annual billing). "
            "Same as Starter but billed annually at $199/mo. "
            "First 3 months at 50% off promotional rate."
        ),
        "categ_id": 1,
    },
    {
        "name": "DFW Permit Leads - Professional (Annual)",
        "type": "service",
        "list_price": 399.00,
        "invoice_policy": "order",
        "default_code": "LEAD-DFW-PRO-YR",
        "description_sale": (
            "DFW Permit Leads - Professional Plan (Annual billing). "
            "Same as Professional but billed annually at $399/mo."
        ),
        "categ_id": 1,
    },
    {
        "name": "DFW Permit Leads - Business (Annual)",
        "type": "service",
        "list_price": 649.00,
        "invoice_policy": "order",
        "default_code": "LEAD-DFW-BIZ-YR",
        "description_sale": (
            "DFW Permit Leads - Business Plan (Annual billing). " "Same as Business but billed annually at $649/mo."
        ),
        "categ_id": 1,
    },
    {
        "name": "DFW Permit Leads - Enterprise (Annual)",
        "type": "service",
        "list_price": 1199.00,
        "invoice_policy": "order",
        "default_code": "LEAD-DFW-ENT-YR",
        "description_sale": (
            "DFW Permit Leads - Enterprise Plan (Annual billing). "
            "Same as Enterprise but billed annually at $1199/mo."
        ),
        "categ_id": 1,
    },
    {
        "name": "DFW Permit Leads - Agency (Annual)",
        "type": "service",
        "list_price": 1999.00,
        "invoice_policy": "order",
        "default_code": "LEAD-DFW-AGENCY-YR",
        "description_sale": (
            "DFW Permit Leads - Agency Plan (Annual billing). " "Same as Agency but billed annually at $1999/mo."
        ),
        "categ_id": 1,
    },
    # Custom lead generation
    {
        "name": "Lead Generation - Custom Project",
        "type": "service",
        "list_price": 0.00,  # Quote-based
        "invoice_policy": "delivery",
        "default_code": "LEAD-CUSTOM",
        "description_sale": ("Custom lead generation project. " "Price determined by scope - contact sales for quote."),
        "categ_id": 1,
    },
    # =========================================================================
    # AI SERVICES
    # =========================================================================
    {
        "name": "AI Automation Consultation",
        "type": "service",
        "list_price": 199.00,
        "invoice_policy": "delivery",
        "default_code": "CONSULT-AI",
        "description_sale": (
            "1-hour AI automation consultation session. "
            "Discuss workflow optimization, AI integration, and automation strategy."
        ),
        "categ_id": 1,
    },
    {
        "name": "AI Phone Agent - Hourly",
        "type": "service",
        "list_price": 25.00,
        "invoice_policy": "delivery",
        "default_code": "AI-PHONE-HR",
        "description_sale": (
            "AI Phone Agent usage - per hour. " "Automated call handling for auto shops, salons, medical offices."
        ),
        "categ_id": 1,
    },
    {
        "name": "AI Phone Agent - Monthly",
        "type": "service",
        "list_price": 499.00,
        "invoice_policy": "order",
        "default_code": "AI-PHONE-MO",
        "description_sale": (
            "AI Phone Agent - Monthly subscription. "
            "Unlimited calls, custom voice, CRM integration, call transcripts."
        ),
        "categ_id": 1,
    },
    {
        "name": "AI Gateway Access",
        "type": "service",
        "list_price": 99.00,
        "invoice_policy": "order",
        "default_code": "AI-GATEWAY",
        "description_sale": (
            "AI Gateway API access - Monthly. "
            "Access to Cloudflare Workers AI + Ollama inference. "
            "Smart routing, response caching, multiple models."
        ),
        "categ_id": 1,
    },
    # =========================================================================
    # SEO SERVICES
    # =========================================================================
    {
        "name": "SEO Audit Report",
        "type": "service",
        "list_price": 499.00,
        "invoice_policy": "order",
        "default_code": "SEO-AUDIT",
        "description_sale": (
            "Comprehensive SEO audit with actionable recommendations. "
            "Includes technical analysis, content review, and competitor research."
        ),
        "categ_id": 1,
    },
    {
        "name": "SERP Monitoring - Monthly",
        "type": "service",
        "list_price": 149.00,
        "invoice_policy": "order",
        "default_code": "SEO-MONITOR",
        "description_sale": (
            "SERP keyword ranking monitoring - Monthly. "
            "Track up to 100 keywords, daily rank checks, competitor tracking."
        ),
        "categ_id": 1,
    },
    {
        "name": "Website SEO Scan",
        "type": "service",
        "list_price": 99.00,
        "invoice_policy": "order",
        "default_code": "SEO-SCAN",
        "description_sale": (
            "One-time website SEO scan. " "Technical health check, page speed analysis, mobile-friendliness."
        ),
        "categ_id": 1,
    },
    # =========================================================================
    # DEVELOPMENT SERVICES
    # =========================================================================
    {
        "name": "Workflow Development - Hourly",
        "type": "service",
        "list_price": 150.00,
        "invoice_policy": "delivery",
        "default_code": "DEV-WORKFLOW",
        "description_sale": (
            "Per-hour custom n8n/automation workflow development. "
            "Build integrations, automate processes, and connect your tools."
        ),
        "categ_id": 1,
    },
    {
        "name": "n8n Automation Build",
        "type": "service",
        "list_price": 0.00,  # Quote-based
        "invoice_policy": "delivery",
        "default_code": "DEV-N8N",
        "description_sale": ("Custom n8n automation workflow build. " "Fixed price per workflow - contact for quote."),
        "categ_id": 1,
    },
    {
        "name": "Custom Development Project",
        "type": "service",
        "list_price": 0.00,  # Quote-based
        "invoice_policy": "delivery",
        "default_code": "DEV-CUSTOM",
        "description_sale": (
            "Custom software development project. " "Web apps, APIs, integrations - contact for quote."
        ),
        "categ_id": 1,
    },
    # =========================================================================
    # BLOCKCHAIN / RPC SERVICES
    # =========================================================================
    {
        "name": "RPC Service - Starter",
        "type": "service",
        "list_price": 99.00,
        "invoice_policy": "order",
        "default_code": "RPC-STARTER",
        "description_sale": (
            "White-label blockchain RPC - Starter. "
            "50M requests/month, 2 endpoints. "
            "Ethereum, Polygon, Base, Arbitrum, Optimism, Solana."
        ),
        "categ_id": 1,
    },
    {
        "name": "RPC Service - Professional",
        "type": "service",
        "list_price": 399.00,
        "invoice_policy": "order",
        "default_code": "RPC-PRO",
        "description_sale": (
            "White-label blockchain RPC - Professional. " "300M requests/month, 10 endpoints, priority support."
        ),
        "categ_id": 1,
    },
    {
        "name": "RPC Service - Enterprise",
        "type": "service",
        "list_price": 0.00,  # Custom pricing
        "invoice_policy": "order",
        "default_code": "RPC-ENT",
        "description_sale": (
            "White-label blockchain RPC - Enterprise. " "Custom request limits, dedicated infrastructure, SLA."
        ),
        "categ_id": 1,
    },
    {
        "name": "WhaleWatch Alerts",
        "type": "service",
        "list_price": 49.00,
        "invoice_policy": "order",
        "default_code": "WHALE-WATCH",
        "description_sale": (
            "WhaleWatch crypto whale alerts - Monthly. "
            "Real-time notifications for large wallet movements. "
            "Discord/Telegram/Email alerts, custom thresholds."
        ),
        "categ_id": 1,
    },
    # =========================================================================
    # SUPPORT SERVICES
    # =========================================================================
    {
        "name": "Enterprise Support Plan",
        "type": "service",
        "list_price": 999.00,
        "invoice_policy": "order",
        "default_code": "SUPPORT-ENT",
        "description_sale": (
            "Monthly enterprise support with priority response. "
            "Includes dedicated support, SLA guarantees, and custom integrations."
        ),
        "categ_id": 1,
    },
    {
        "name": "Ad-hoc Support - Hourly",
        "type": "service",
        "list_price": 100.00,
        "invoice_policy": "delivery",
        "default_code": "SUPPORT-HR",
        "description_sale": ("Ad-hoc technical support - per hour. " "Troubleshooting, configuration, training."),
        "categ_id": 1,
    },
    # =========================================================================
    # MANAGED IT SERVICES - From /pricing page
    # =========================================================================
    {
        "name": "Managed IT - Starter",
        "type": "service",
        "list_price": 499.00,
        "invoice_policy": "order",
        "default_code": "MIT-STARTER",
        "description_sale": (
            "Managed IT Services - Starter. "
            "Up to 5 managed services, basic monitoring & alerts, "
            "weekly health reports, email support (48hr response), "
            "security patches & updates, monthly backup verification. "
            "99.5% uptime SLA."
        ),
        "categ_id": 1,
    },
    {
        "name": "Managed IT - Professional",
        "type": "service",
        "list_price": 999.00,
        "invoice_policy": "order",
        "default_code": "MIT-PRO",
        "description_sale": (
            "Managed IT Services - Professional. "
            "Up to 15 managed services, advanced monitoring & alerting, "
            "daily health reports, priority support (24hr response), "
            "proactive security management, daily automated backups. "
            "99.9% uptime SLA, quarterly security reviews."
        ),
        "categ_id": 1,
    },
    {
        "name": "Managed IT - Enterprise",
        "type": "service",
        "list_price": 1999.00,
        "invoice_policy": "order",
        "default_code": "MIT-ENT",
        "description_sale": (
            "Managed IT Services - Enterprise. "
            "Unlimited managed services, 24/7 real-time monitoring, "
            "real-time health dashboard, dedicated support team, "
            "advanced security operations, continuous backup & DR. "
            "99.99% uptime SLA, monthly strategy reviews, custom integrations."
        ),
        "categ_id": 1,
    },
    # =========================================================================
    # PLATFORM-AS-A-SERVICE (Per User) - From /pricing page
    # =========================================================================
    {
        "name": "Platform - Basic (Per User)",
        "type": "service",
        "list_price": 29.00,
        "invoice_policy": "order",
        "default_code": "PAAS-BASIC",
        "description_sale": (
            "AIQSO Platform - Basic (per user/month). "
            "CRM & contact management, document management, "
            "basic email templates, mobile app access, email support."
        ),
        "categ_id": 1,
    },
    {
        "name": "Platform - Professional (Per User)",
        "type": "service",
        "list_price": 49.00,
        "invoice_policy": "order",
        "default_code": "PAAS-PRO",
        "description_sale": (
            "AIQSO Platform - Professional (per user/month). "
            "Everything in Basic plus: workflow automation, "
            "email marketing tools, calendar scheduling, "
            "task management, team collaboration, priority support."
        ),
        "categ_id": 1,
    },
    {
        "name": "Platform - Enterprise (Per User)",
        "type": "service",
        "list_price": 79.00,
        "invoice_policy": "order",
        "default_code": "PAAS-ENT",
        "description_sale": (
            "AIQSO Platform - Enterprise (per user/month). "
            "Everything in Professional plus: advanced analytics, "
            "custom reporting, API access, white-label options, "
            "dedicated account manager, custom integrations, SLA guarantee."
        ),
        "categ_id": 1,
    },
    # =========================================================================
    # CONSULTING & SETUP - From /pricing page
    # =========================================================================
    {
        "name": "Small Business Setup",
        "type": "service",
        "list_price": 2500.00,  # Starting price
        "invoice_policy": "delivery",
        "default_code": "SETUP-SMB",
        "description_sale": (
            "Small Business consulting & setup ($2,500 - $5,000). "
            "For loan officers, real estate agents, insurance brokers, consultants. "
            "Custom solution design, technology deployment & configuration, "
            "workflow automation setup, CRM & document management, training."
        ),
        "categ_id": 1,
    },
    {
        "name": "Small Business Monthly Support",
        "type": "service",
        "list_price": 99.00,  # Starting price
        "invoice_policy": "order",
        "default_code": "SUPPORT-SMB",
        "description_sale": (
            "Small Business monthly support ($99 - $199/mo). "
            "Monthly optimization reviews, email & chat support, "
            "training & documentation updates."
        ),
        "categ_id": 1,
    },
    {
        "name": "Mid-Market Setup",
        "type": "service",
        "list_price": 10000.00,  # Starting price
        "invoice_policy": "delivery",
        "default_code": "SETUP-MID",
        "description_sale": (
            "Mid-Market consulting & setup ($10,000 - $25,000). "
            "For restaurants, retail, medical practices, accounting & law firms. "
            "Enterprise-grade solutions, multi-department integration, "
            "custom workflow development, advanced automation & AI."
        ),
        "categ_id": 1,
    },
    {
        "name": "Mid-Market Monthly Support",
        "type": "service",
        "list_price": 299.00,  # Starting price
        "invoice_policy": "order",
        "default_code": "SUPPORT-MID",
        "description_sale": (
            "Mid-Market monthly support ($299 - $599/mo). "
            "Weekly optimization reviews, priority phone & email support, "
            "on-site training sessions, quarterly business reviews."
        ),
        "categ_id": 1,
    },
]

# Legacy products to deprecate/update
LEGACY_PRODUCTS = {
    "LEAD-DFW": "LEAD-DFW-BIZ",  # Old code -> redirect to Business tier
    "LEAD-MULTI": "LEAD-DFW-BIZ",  # Old code -> redirect to Business tier
}


def sync_products(dry_run: bool = False) -> dict[str, list[str]]:
    """Sync AIQSO products in Odoo.

    Creates new products and updates prices for existing ones.

    Args:
        dry_run: If True, only preview changes without applying.

    Returns:
        Dict with 'created', 'updated', 'skipped' lists.
    """
    url, db, uid, password = get_odoo_connection()
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    results: dict[str, list[str]] = {"created": [], "updated": [], "skipped": []}

    for product in PRODUCTS:
        code = product["default_code"]

        # Check if exists by default_code
        existing = cast(
            list[dict[str, Any]],
            models.execute_kw(
                db,
                uid,
                password,
                "product.template",
                "search_read",
                [[["default_code", "=", code]]],
                {"fields": ["id", "name", "list_price"]},
            ),
        )

        if existing:
            existing_product = existing[0]
            existing_price = existing_product["list_price"]
            new_price = product["list_price"]

            # Check if price needs update
            if abs(existing_price - new_price) > 0.01:
                if dry_run:
                    print(f"  [update] {product['name']} [{code}]: " f"${existing_price:.2f} -> ${new_price:.2f}")
                else:
                    models.execute_kw(
                        db,
                        uid,
                        password,
                        "product.template",
                        "write",
                        [
                            [existing_product["id"]],
                            {
                                "list_price": new_price,
                                "description_sale": product["description_sale"],
                            },
                        ],
                    )
                    print(f"  [update] {product['name']} [{code}]: " f"${existing_price:.2f} -> ${new_price:.2f}")
                results["updated"].append(f"{product['name']} [{code}]")
            else:
                results["skipped"].append(f"{product['name']} [{code}]")
                print(f"  [skip]   {product['name']} [{code}] (no changes)")
        else:
            # Create new product
            if dry_run:
                print(f"  [create] {product['name']} [{code}]: ${product['list_price']:.2f}")
            else:
                product_id = models.execute_kw(
                    db,
                    uid,
                    password,
                    "product.template",
                    "create",
                    [product],
                )
                print(f"  [create] {product['name']} [{code}]: " f"${product['list_price']:.2f} (ID: {product_id})")
            results["created"].append(f"{product['name']} [{code}]")

    return results


def list_all_products() -> list[dict[str, Any]]:
    """List all products in Odoo with AIQSO billing codes."""
    url, db, uid, password = get_odoo_connection()
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    # Get all products with a default_code
    products = cast(
        list[dict[str, Any]],
        models.execute_kw(
            db,
            uid,
            password,
            "product.template",
            "search_read",
            [[["default_code", "!=", False]]],
            {
                "fields": ["name", "default_code", "list_price", "type"],
                "order": "default_code",
            },
        ),
    )

    return products


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Sync AIQSO products in Odoo")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without applying them",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all current products and exit",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("AIQSO Products Sync - Odoo")
    print("=" * 60)

    if args.list:
        print("\nCurrent products with billing codes:\n")
        products = list_all_products()
        for p in products:
            print(f"  [{p['default_code']:20}] ${p['list_price']:>8.2f}  {p['name']}")
        print(f"\nTotal: {len(products)} products")
        return 0

    if args.dry_run:
        print("\n  DRY RUN - No changes will be made\n")

    try:
        results = sync_products(dry_run=args.dry_run)

        print("\n" + "=" * 60)
        print("Summary:")
        print(f"  Created: {len(results['created'])}")
        print(f"  Updated: {len(results['updated'])}")
        print(f"  Skipped: {len(results['skipped'])}")
        print("=" * 60)

        if not args.dry_run:
            print("\nAll products with billing codes:")
            products = list_all_products()
            for p in products:
                print(f"  [{p['default_code']:20}] ${p['list_price']:>8.2f}  {p['name']}")

        return 0
    except Exception as e:
        print(f"\n  ERROR: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
