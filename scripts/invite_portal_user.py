#!/usr/bin/env python3
"""Invite customer to Odoo portal.

This script creates a partner (if needed) and sends a portal
invitation email to the customer.

Usage:
    python invite_portal_user.py <email> <name> [company]

Example:
    python invite_portal_user.py customer@example.com "John Doe" "Acme Corp"
"""

import sys
import xmlrpc.client

from config import get_odoo_connection


def find_partner_by_email(email: str) -> int | None:
    """Find a partner by email address.

    Args:
        email: Email address to search for.

    Returns:
        Partner ID if found, None otherwise.
    """
    url, db, uid, password = get_odoo_connection()
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    partner_ids = models.execute_kw(
        db,
        uid,
        password,
        "res.partner",
        "search",
        [[["email", "=", email]]],
    )

    return partner_ids[0] if partner_ids else None


def create_partner(email: str, name: str, company: str | None = None) -> int:
    """Create a new partner in Odoo.

    Args:
        email: Partner email address.
        name: Partner name.
        company: Optional company name.

    Returns:
        The created partner ID.
    """
    url, db, uid, password = get_odoo_connection()
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    partner_data = {
        "name": name,
        "email": email,
        "customer_rank": 1,
    }

    if company:
        partner_data["company_name"] = company

    partner_id = models.execute_kw(
        db,
        uid,
        password,
        "res.partner",
        "create",
        [partner_data],
    )

    return partner_id


def invite_to_portal(partner_id: int) -> bool:
    """Send portal invitation to a partner.

    Args:
        partner_id: The partner ID to invite.

    Returns:
        True if invitation was sent successfully.
    """
    url, db, uid, password = get_odoo_connection()
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    # Create portal wizard
    wizard_id = models.execute_kw(
        db,
        uid,
        password,
        "portal.wizard",
        "create",
        [{"partner_ids": [(6, 0, [partner_id])]}],
    )

    # Execute invitation
    models.execute_kw(
        db,
        uid,
        password,
        "portal.wizard",
        "action_apply",
        [[wizard_id]],
    )

    return True


def invite_portal_user(email: str, name: str, company: str | None = None) -> tuple[int, bool]:
    """Invite a customer to the Odoo portal.

    Creates a partner if one doesn't exist, then sends a portal invitation.

    Args:
        email: Customer email address.
        name: Customer name.
        company: Optional company name.

    Returns:
        Tuple of (partner_id, was_created).
    """
    # Find or create partner
    partner_id = find_partner_by_email(email)
    was_created = False

    if partner_id:
        print(f"  Found existing partner: {partner_id}")
    else:
        partner_id = create_partner(email, name, company)
        was_created = True
        print(f"  Created partner: {partner_id}")

    # Send portal invitation
    invite_to_portal(partner_id)
    print(f"  Portal invitation sent to {email}")

    return partner_id, was_created


def main() -> int:
    """Main entry point."""
    if len(sys.argv) < 3:
        print("Usage: invite_portal_user.py <email> <name> [company]")
        print("\nExample:")
        print('  python invite_portal_user.py customer@example.com "John Doe" "Acme"')
        return 1

    email = sys.argv[1]
    name = sys.argv[2]
    company = sys.argv[3] if len(sys.argv) > 3 else None

    print("=" * 50)
    print("Inviting Customer to Odoo Portal")
    print("=" * 50)
    print(f"  Email: {email}")
    print(f"  Name: {name}")
    if company:
        print(f"  Company: {company}")
    print()

    try:
        partner_id, was_created = invite_portal_user(email, name, company)
        print("\n" + "=" * 50)
        status = "created and invited" if was_created else "invited"
        print(f"  Partner {status} successfully!")
        print("=" * 50)
        return 0
    except Exception as e:
        print(f"\n  ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
