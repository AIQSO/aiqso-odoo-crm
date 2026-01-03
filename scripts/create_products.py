#!/usr/bin/env python3
"""Create AIQSO products/services in Odoo.

This script creates the AIQSO service catalog in Odoo.
It is idempotent - safe to run multiple times.

Usage:
    python create_products.py
"""

import sys
import xmlrpc.client

from config import get_odoo_connection

PRODUCTS = [
    {
        "name": "Lead Generation List - DFW",
        "type": "service",
        "list_price": 149.00,
        "invoice_policy": "order",
        "default_code": "LEAD-DFW",
        "description_sale": "Monthly curated lead list for DFW metro area. "
        "Includes commercial permits, business licenses, and property data.",
        "categ_id": 1,  # All / Saleable
    },
    {
        "name": "Lead Generation List - Multi-City",
        "type": "service",
        "list_price": 299.00,
        "invoice_policy": "order",
        "default_code": "LEAD-MULTI",
        "description_sale": "Monthly curated lead list for multiple metro areas. "
        "Covers DFW, Houston, Austin, San Antonio, and more.",
        "categ_id": 1,
    },
    {
        "name": "AI Automation Consultation",
        "type": "service",
        "list_price": 199.00,
        "invoice_policy": "delivery",
        "default_code": "CONSULT-AI",
        "description_sale": "1-hour AI automation consultation session. "
        "Discuss workflow optimization, AI integration, and automation strategy.",
        "categ_id": 1,
    },
    {
        "name": "SEO Audit Report",
        "type": "service",
        "list_price": 499.00,
        "invoice_policy": "order",
        "default_code": "SEO-AUDIT",
        "description_sale": "Comprehensive SEO audit with actionable recommendations. "
        "Includes technical analysis, content review, and competitor research.",
        "categ_id": 1,
    },
    {
        "name": "Custom Workflow Development",
        "type": "service",
        "list_price": 150.00,
        "invoice_policy": "delivery",
        "default_code": "DEV-WORKFLOW",
        "description_sale": "Per-hour custom n8n/automation workflow development. "
        "Build integrations, automate processes, and connect your tools.",
        "categ_id": 1,
    },
    {
        "name": "Enterprise Support Plan",
        "type": "service",
        "list_price": 999.00,
        "invoice_policy": "order",
        "default_code": "SUPPORT-ENT",
        "description_sale": "Monthly enterprise support with priority response. "
        "Includes dedicated support, SLA guarantees, and custom integrations.",
        "categ_id": 1,
    },
]


def create_products() -> list[int]:
    """Create AIQSO products in Odoo.

    Returns:
        List of created product IDs.
    """
    url, db, uid, password = get_odoo_connection()
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    created = []
    skipped = []

    for product in PRODUCTS:
        # Check if exists by default_code
        existing = models.execute_kw(
            db,
            uid,
            password,
            "product.template",
            "search",
            [[["default_code", "=", product["default_code"]]]],
        )

        if existing:
            skipped.append(product["name"])
            print(f"  [skip] {product['name']} (already exists)")
            continue

        product_id = models.execute_kw(
            db,
            uid,
            password,
            "product.template",
            "create",
            [product],
        )
        created.append(product_id)
        print(f"  [new]  {product['name']} (ID: {product_id})")

    return created


def list_products() -> list[dict]:
    """List all AIQSO products in Odoo.

    Returns:
        List of product dictionaries.
    """
    url, db, uid, password = get_odoo_connection()
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    products = models.execute_kw(
        db,
        uid,
        password,
        "product.template",
        "search_read",
        [[["default_code", "like", "LEAD-%"]]],
        {"fields": ["name", "default_code", "list_price", "type"]},
    )

    # Also get other AIQSO products
    other_products = models.execute_kw(
        db,
        uid,
        password,
        "product.template",
        "search_read",
        [
            [
                "|",
                "|",
                "|",
                ["default_code", "=", "CONSULT-AI"],
                ["default_code", "=", "SEO-AUDIT"],
                ["default_code", "=", "DEV-WORKFLOW"],
                ["default_code", "=", "SUPPORT-ENT"],
            ]
        ],
        {"fields": ["name", "default_code", "list_price", "type"]},
    )

    return products + other_products


def main() -> int:
    """Main entry point."""
    print("=" * 50)
    print("Creating AIQSO Products in Odoo")
    print("=" * 50)

    try:
        created = create_products()

        print("\n" + "=" * 50)
        print(f"Created {len(created)} new products")

        # List all products
        print("\n  Current AIQSO Products:")
        products = list_products()
        for p in products:
            print(f"    - {p['name']} (${p['list_price']:.2f}) [{p['default_code']}]")

        print("=" * 50)
        return 0
    except Exception as e:
        print(f"\n  ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
