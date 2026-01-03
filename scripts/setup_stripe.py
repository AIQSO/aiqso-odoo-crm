#!/usr/bin/env python3
"""Configure Stripe payment provider in Odoo.

This script enables and configures the Stripe payment provider
in Odoo 17. It requires Stripe API keys to be provided via
environment variables.

Usage:
    STRIPE_SECRET_KEY=sk_... STRIPE_PUBLISHABLE_KEY=pk_... python setup_stripe.py
"""

import os
import sys
import xmlrpc.client

from config import get_odoo_connection


def setup_stripe(stripe_secret_key: str, stripe_publishable_key: str) -> int:
    """Enable and configure Stripe payment provider in Odoo.

    Args:
        stripe_secret_key: Stripe secret key (sk_live_... or sk_test_...)
        stripe_publishable_key: Stripe publishable key (pk_live_... or pk_test_...)

    Returns:
        The payment provider ID.

    Raises:
        ValueError: If Stripe provider module is not installed.
    """
    url, db, uid, password = get_odoo_connection()
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    # Find Stripe provider
    provider_ids = models.execute_kw(
        db,
        uid,
        password,
        "payment.provider",
        "search",
        [[["code", "=", "stripe"]]],
    )

    if not provider_ids:
        raise ValueError("Stripe provider module not installed. " "Install 'payment_stripe' module in Odoo first.")

    provider_id = provider_ids[0]

    # Check current state
    current = models.execute_kw(
        db,
        uid,
        password,
        "payment.provider",
        "read",
        [provider_ids],
        {"fields": ["state", "name"]},
    )

    if current and current[0].get("state") == "enabled":
        print(f"  Stripe provider already enabled (ID: {provider_id})")
        return provider_id

    # Configure and enable
    models.execute_kw(
        db,
        uid,
        password,
        "payment.provider",
        "write",
        [
            provider_ids,
            {
                "state": "enabled",
                "stripe_secret_key": stripe_secret_key,
                "stripe_publishable_key": stripe_publishable_key,
                "company_id": 1,
            },
        ],
    )

    print(f"  Stripe provider enabled (ID: {provider_id})")
    return provider_id


def main() -> int:
    """Main entry point."""
    print("=" * 50)
    print("Setting up Stripe Payment Provider")
    print("=" * 50)

    stripe_secret = os.environ.get("STRIPE_SECRET_KEY")
    stripe_publishable = os.environ.get("STRIPE_PUBLISHABLE_KEY")

    if not stripe_secret or not stripe_publishable:
        print("ERROR: Missing required environment variables:\n" "  - STRIPE_SECRET_KEY\n" "  - STRIPE_PUBLISHABLE_KEY")
        return 1

    try:
        setup_stripe(stripe_secret, stripe_publishable)
        print("\n  Setup complete!")
        return 0
    except Exception as e:
        print(f"\n  ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
