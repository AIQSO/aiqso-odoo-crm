#!/usr/bin/env python3
"""Health check for Odoo portal integration.

This script verifies that all integration components are working:
- Odoo server accessibility
- Stripe payment provider configuration
- n8n automation platform
- Product catalog

Usage:
    python health_check.py
"""

import os
import sys
import xmlrpc.client

try:
    import requests

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from config import load_odoo_config, require_config


def check_odoo() -> bool:
    """Verify Odoo is accessible and responding.

    Returns:
        True if Odoo is healthy.
    """
    try:
        config = load_odoo_config()
        url = config["url"]

        common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
        version = common.version()

        print(f"  [OK] Odoo {version['server_version']} responding at {url}")
        return True
    except Exception as e:
        print(f"  [FAIL] Odoo check failed: {e}")
        return False


def check_odoo_auth() -> bool:
    """Verify Odoo authentication works.

    Returns:
        True if authentication succeeds.
    """
    try:
        config = load_odoo_config()
        require_config(config, ["url", "db", "username", "api_key"], "ODOO_*")

        url = config["url"]
        db = config["db"]
        username = config["username"]
        api_key = config["api_key"]

        common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
        uid = common.authenticate(db, username, api_key, {})

        if uid:
            print(f"  [OK] Odoo authentication successful (uid: {uid})")
            return True
        else:
            print("  [FAIL] Odoo authentication failed - invalid credentials")
            return False
    except Exception as e:
        print(f"  [FAIL] Odoo authentication failed: {e}")
        return False


def check_stripe() -> bool:
    """Verify Stripe provider is enabled in Odoo.

    Returns:
        True if Stripe is configured and enabled.
    """
    try:
        config = load_odoo_config()
        require_config(config, ["url", "db", "username", "api_key"], "ODOO_*")

        url = config["url"]
        db = config["db"]
        username = config["username"]
        api_key = config["api_key"]

        common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
        uid = common.authenticate(db, username, api_key, {})
        models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

        providers = models.execute_kw(
            db,
            uid,
            api_key,
            "payment.provider",
            "search_read",
            [[["code", "=", "stripe"]]],
            {"fields": ["state", "name"]},
        )

        if providers and providers[0]["state"] == "enabled":
            print("  [OK] Stripe payment provider enabled")
            return True
        elif providers:
            print(f"  [WARN] Stripe provider exists but state is: {providers[0]['state']}")
            return False
        else:
            print("  [FAIL] Stripe provider not found - install payment_stripe module")
            return False
    except Exception as e:
        print(f"  [FAIL] Stripe check failed: {e}")
        return False


def check_n8n() -> bool:
    """Verify n8n is accessible.

    Returns:
        True if n8n is healthy.
    """
    if not REQUESTS_AVAILABLE:
        print("  [SKIP] n8n check skipped (requests module not installed)")
        return True

    try:
        n8n_url = os.environ.get("N8N_URL", "https://automation.aiqso.io")
        resp = requests.get(f"{n8n_url}/healthz", timeout=5)

        if resp.status_code == 200:
            print(f"  [OK] n8n responding at {n8n_url}")
            return True
        else:
            print(f"  [FAIL] n8n returned status {resp.status_code}")
            return False
    except requests.exceptions.Timeout:
        print("  [FAIL] n8n connection timed out")
        return False
    except requests.exceptions.ConnectionError:
        print("  [FAIL] n8n connection refused")
        return False
    except Exception as e:
        print(f"  [FAIL] n8n check failed: {e}")
        return False


def check_products() -> bool:
    """Verify AIQSO products exist in Odoo.

    Returns:
        True if products are configured.
    """
    try:
        config = load_odoo_config()
        require_config(config, ["url", "db", "username", "api_key"], "ODOO_*")

        url = config["url"]
        db = config["db"]
        username = config["username"]
        api_key = config["api_key"]

        common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
        uid = common.authenticate(db, username, api_key, {})
        models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

        # Count lead generation products
        lead_count = models.execute_kw(
            db,
            uid,
            api_key,
            "product.template",
            "search_count",
            [[["default_code", "like", "LEAD-%"]]],
        )

        # Count other AIQSO products
        other_count = models.execute_kw(
            db,
            uid,
            api_key,
            "product.template",
            "search_count",
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
        )

        total = lead_count + other_count

        if total >= 6:
            print(f"  [OK] {total} AIQSO products found")
            return True
        elif total > 0:
            print(f"  [WARN] Only {total}/6 expected products found")
            return False
        else:
            print("  [FAIL] No AIQSO products found - run create_products.py")
            return False
    except Exception as e:
        print(f"  [FAIL] Products check failed: {e}")
        return False


def check_portal_module() -> bool:
    """Verify portal module is installed.

    Returns:
        True if portal module is installed.
    """
    try:
        config = load_odoo_config()
        require_config(config, ["url", "db", "username", "api_key"], "ODOO_*")

        url = config["url"]
        db = config["db"]
        username = config["username"]
        api_key = config["api_key"]

        common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
        uid = common.authenticate(db, username, api_key, {})
        models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

        modules = models.execute_kw(
            db,
            uid,
            api_key,
            "ir.module.module",
            "search_read",
            [[["name", "=", "portal"], ["state", "=", "installed"]]],
            {"fields": ["name", "state"]},
        )

        if modules:
            print("  [OK] Portal module installed")
            return True
        else:
            print("  [FAIL] Portal module not installed")
            return False
    except Exception as e:
        print(f"  [FAIL] Portal module check failed: {e}")
        return False


def main() -> int:
    """Run all health checks."""
    print("=" * 50)
    print("AIQSO Portal Integration Health Check")
    print("=" * 50)
    print()

    checks = [
        ("Odoo Server", check_odoo),
        ("Odoo Auth", check_odoo_auth),
        ("Portal Module", check_portal_module),
        ("Stripe Provider", check_stripe),
        ("n8n Automation", check_n8n),
        ("Product Catalog", check_products),
    ]

    results = []
    for name, check_fn in checks:
        print(f"\n{name}:")
        results.append(check_fn())

    passed = sum(results)
    total = len(results)

    print("\n" + "=" * 50)
    print(f"Health Check Results: {passed}/{total} passed")

    if passed == total:
        print("  All systems operational!")
        print("=" * 50)
        return 0
    else:
        print("  Some checks failed - review output above")
        print("=" * 50)
        return 1


if __name__ == "__main__":
    sys.exit(main())
