"""
Invoice Reconciliation Logic

Matches Mercury bank transactions to Odoo invoices using multiple strategies:
1. By invoice number in transaction memo
2. By exact amount + customer email in memo
3. By amount + date proximity

When matched:
- Creates payment in Odoo
- Reconciles invoice + payment
- Updates sync state
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sync_state import SyncStateDB, get_sync_db


@dataclass
class MatchResult:
    """Result of a transaction-to-invoice match attempt."""

    matched: bool
    invoice_id: int | None = None
    invoice_number: str | None = None
    match_type: str | None = None  # 'invoice_number', 'amount_email', 'amount_date'
    confidence: float = 0.0
    details: str | None = None


@dataclass
class ReconciliationResult:
    """Result of reconciling a transaction."""

    success: bool
    transaction_id: str
    invoice_id: int | None = None
    payment_id: int | None = None
    match_type: str | None = None
    error: str | None = None


class InvoiceMatcher:
    """
    Matches Mercury transactions to Odoo invoices.

    Usage:
        matcher = InvoiceMatcher(odoo_connection)
        match = await matcher.find_match(transaction)
        if match.matched:
            result = await matcher.reconcile(transaction, match)
    """

    # Patterns for finding invoice numbers in transaction descriptions
    INVOICE_PATTERNS = [
        r"INV[/-]?\d{4}[/-]\d+",  # INV/2025/0001, INV-2025-0001
        r"Invoice\s*#?\s*(\d+)",   # Invoice #123, Invoice 123
        r"Inv\s*#?\s*(\d+)",       # Inv #123
        r"AIQSO[/-]?\d+",          # AIQSO-001
    ]

    # Patterns for email extraction
    EMAIL_PATTERN = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"

    def __init__(self, odoo_execute_fn, sync_db: SyncStateDB | None = None):
        """
        Initialize matcher.

        Args:
            odoo_execute_fn: Function to execute Odoo XML-RPC calls
                             Signature: execute(model, method, *args, **kwargs)
            sync_db: Sync state database (optional, uses singleton if not provided)
        """
        self.odoo_execute = odoo_execute_fn
        self.sync_db = sync_db or get_sync_db()

    def _extract_invoice_number(self, text: str) -> str | None:
        """Extract invoice number from text."""
        if not text:
            return None

        for pattern in self.INVOICE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0).upper()

        return None

    def _extract_email(self, text: str) -> str | None:
        """Extract email address from text."""
        if not text:
            return None

        match = re.search(self.EMAIL_PATTERN, text)
        return match.group(0).lower() if match else None

    def _get_open_invoices(self, filters: list | None = None) -> list[dict[str, Any]]:
        """Get open (unpaid) invoices from Odoo."""
        base_filters = [
            ["move_type", "=", "out_invoice"],
            ["state", "=", "posted"],
            ["payment_state", "in", ["not_paid", "partial"]],
        ]

        if filters:
            base_filters.extend(filters)

        return self.odoo_execute(
            "account.move",
            "search_read",
            base_filters,
            fields=[
                "id", "name", "partner_id", "amount_total", "amount_residual",
                "invoice_date", "ref", "narration",
            ],
        )

    def _get_partner_email(self, partner_id: int) -> str | None:
        """Get email for a partner."""
        partners = self.odoo_execute(
            "res.partner",
            "read",
            [partner_id],
            fields=["email"],
        )
        return partners[0].get("email") if partners else None

    # =========================================================================
    # Matching Strategies
    # =========================================================================

    def match_by_invoice_number(
        self,
        transaction: dict[str, Any],
    ) -> MatchResult:
        """
        Strategy 1: Match by invoice number in transaction memo.

        Highest confidence - explicit reference to invoice.
        """
        counterparty = transaction.get("counterpartyName") or ""
        note = transaction.get("note") or ""
        description = counterparty + " " + note
        invoice_number = self._extract_invoice_number(description)

        if not invoice_number:
            return MatchResult(matched=False)

        # Search for invoice by name (number)
        invoices = self._get_open_invoices([["name", "ilike", invoice_number]])

        if not invoices:
            # Try searching in ref field
            invoices = self._get_open_invoices([["ref", "ilike", invoice_number]])

        if invoices:
            invoice = invoices[0]
            return MatchResult(
                matched=True,
                invoice_id=invoice["id"],
                invoice_number=invoice["name"],
                match_type="invoice_number",
                confidence=1.0,
                details=f"Found invoice number '{invoice_number}' in transaction memo",
            )

        return MatchResult(matched=False)

    def match_by_amount_and_email(
        self,
        transaction: dict[str, Any],
    ) -> MatchResult:
        """
        Strategy 2: Match by exact amount + customer email in memo.

        High confidence - amount matches and email identifies customer.
        """
        amount = abs(float(transaction.get("amount", 0)))
        counterparty = transaction.get("counterpartyName") or ""
        note = transaction.get("note") or ""
        description = counterparty + " " + note
        email = self._extract_email(description)

        if not email or amount <= 0:
            return MatchResult(matched=False)

        # Find partner by email
        partners = self.odoo_execute(
            "res.partner",
            "search_read",
            [["email", "=ilike", email]],
            fields=["id"],
        )

        if not partners:
            return MatchResult(matched=False)

        partner_id = partners[0]["id"]

        # Find invoice for this partner with matching amount
        invoices = self._get_open_invoices([
            ["partner_id", "=", partner_id],
            ["amount_residual", ">=", amount - 0.01],
            ["amount_residual", "<=", amount + 0.01],
        ])

        if invoices:
            invoice = invoices[0]
            return MatchResult(
                matched=True,
                invoice_id=invoice["id"],
                invoice_number=invoice["name"],
                match_type="amount_email",
                confidence=0.9,
                details=f"Matched amount ${amount:.2f} to customer {email}",
            )

        return MatchResult(matched=False)

    def match_by_amount_and_date(
        self,
        transaction: dict[str, Any],
        date_tolerance_days: int = 60,
    ) -> MatchResult:
        """
        Strategy 3: Match by amount + date proximity.

        Medium confidence - amount matches, date is close.
        Returns best match if multiple candidates.
        """
        amount = abs(float(transaction.get("amount", 0)))
        txn_date_str = transaction.get("postedAt") or transaction.get("createdAt")

        if amount <= 0 or not txn_date_str:
            return MatchResult(matched=False)

        # Parse transaction date
        try:
            txn_date = datetime.fromisoformat(txn_date_str.replace("Z", "+00:00")).date()
        except (ValueError, AttributeError):
            return MatchResult(matched=False)

        # Find invoices with matching amount
        invoices = self._get_open_invoices([
            ["amount_residual", ">=", amount - 0.01],
            ["amount_residual", "<=", amount + 0.01],
        ])

        if not invoices:
            return MatchResult(matched=False)

        # Score by date proximity
        best_match = None
        best_score = 0.0

        for invoice in invoices:
            inv_date_str = invoice.get("invoice_date")
            if not inv_date_str:
                continue

            try:
                inv_date = datetime.strptime(inv_date_str, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue

            # Calculate days difference
            days_diff = abs((txn_date - inv_date).days)

            if days_diff <= date_tolerance_days:
                # Score: higher for closer dates
                score = 1.0 - (days_diff / (date_tolerance_days + 1))

                if score > best_score:
                    best_score = score
                    best_match = invoice

        if best_match:
            return MatchResult(
                matched=True,
                invoice_id=best_match["id"],
                invoice_number=best_match["name"],
                match_type="amount_date",
                confidence=0.7 * best_score,  # Lower base confidence for this strategy
                details=f"Matched amount ${amount:.2f} within {date_tolerance_days} days",
            )

        return MatchResult(matched=False)

    def find_match(
        self,
        transaction: dict[str, Any],
        min_confidence: float = 0.5,
    ) -> MatchResult:
        """
        Try all matching strategies and return best match.

        Strategies are tried in order of confidence:
        1. Invoice number in memo (confidence: 1.0)
        2. Amount + email (confidence: 0.9)
        3. Amount + date (confidence: 0.5-0.7)

        Args:
            transaction: Mercury transaction dict
            min_confidence: Minimum confidence threshold

        Returns:
            Best MatchResult above threshold, or non-matched result
        """
        # Only try to match credit transactions (deposits)
        amount = float(transaction.get("amount", 0))
        if amount <= 0:
            return MatchResult(matched=False, details="Not a deposit")

        # Strategy 1: Invoice number
        result = self.match_by_invoice_number(transaction)
        if result.matched and result.confidence >= min_confidence:
            return result

        # Strategy 2: Amount + email
        result = self.match_by_amount_and_email(transaction)
        if result.matched and result.confidence >= min_confidence:
            return result

        # Strategy 3: Amount + date
        result = self.match_by_amount_and_date(transaction)
        if result.matched and result.confidence >= min_confidence:
            return result

        return MatchResult(matched=False, details="No matching invoice found")

    # =========================================================================
    # Reconciliation
    # =========================================================================

    def create_payment(
        self,
        invoice_id: int,
        amount: float,
        reference: str,
        payment_date: str | None = None,
    ) -> int:
        """
        Create a payment in Odoo and reconcile with invoice.

        Args:
            invoice_id: Odoo invoice ID
            amount: Payment amount
            reference: Payment reference (e.g., Mercury transaction ID)
            payment_date: Payment date (defaults to today)

        Returns:
            Payment ID
        """
        import xmlrpc.client

        # Get invoice details
        invoice = self.odoo_execute(
            "account.move",
            "read",
            [invoice_id],
            fields=["currency_id", "partner_id", "amount_residual"],
        )[0]

        # Get bank journal
        journals = self.odoo_execute(
            "account.journal",
            "search_read",
            [["type", "=", "bank"]],
            fields=["id"],
            limit=1,
        )

        if not journals:
            raise ValueError("No bank journal found in Odoo")

        journal_id = journals[0]["id"]

        # Get payment method line
        payment_method_lines = self.odoo_execute(
            "account.payment.method.line",
            "search_read",
            [["journal_id", "=", journal_id], ["payment_type", "=", "inbound"]],
            fields=["id"],
            limit=1,
        )

        # Create payment
        payment_vals = {
            "payment_type": "inbound",
            "partner_type": "customer",
            "partner_id": invoice["partner_id"][0],
            "amount": min(amount, invoice["amount_residual"]),
            "currency_id": invoice["currency_id"][0],
            "journal_id": journal_id,
            "memo": f"Mercury: {reference}",  # Odoo 17+ uses 'memo' instead of 'ref'
            "date": payment_date or datetime.now().strftime("%Y-%m-%d"),
        }

        if payment_method_lines:
            payment_vals["payment_method_line_id"] = payment_method_lines[0]["id"]

        payment_id = self.odoo_execute("account.payment", "create", payment_vals)

        # Post payment
        try:
            self.odoo_execute("account.payment", "action_post", [payment_id])
        except xmlrpc.client.Fault:
            pass  # May return None but succeed

        # Get payment move for reconciliation
        payment = self.odoo_execute(
            "account.payment",
            "read",
            [payment_id],
            fields=["move_id"],
        )[0]

        # Reconcile invoice and payment
        invoice_lines = self.odoo_execute(
            "account.move.line",
            "search_read",
            [
                ["move_id", "=", invoice_id],
                ["account_type", "=", "asset_receivable"],
                ["reconciled", "=", False],
            ],
            fields=["id"],
        )

        payment_lines = self.odoo_execute(
            "account.move.line",
            "search_read",
            [
                ["move_id", "=", payment["move_id"][0]],
                ["account_type", "=", "asset_receivable"],
                ["reconciled", "=", False],
            ],
            fields=["id"],
        )

        if invoice_lines and payment_lines:
            line_ids = [l["id"] for l in invoice_lines + payment_lines]
            try:
                self.odoo_execute("account.move.line", "reconcile", line_ids)
            except xmlrpc.client.Fault:
                pass  # May return None but succeed

        return payment_id

    def reconcile_transaction(
        self,
        transaction: dict[str, Any],
        match: MatchResult,
    ) -> ReconciliationResult:
        """
        Reconcile a matched transaction by creating payment in Odoo.

        Args:
            transaction: Mercury transaction dict
            match: Successful MatchResult

        Returns:
            ReconciliationResult with payment details
        """
        if not match.matched or not match.invoice_id:
            return ReconciliationResult(
                success=False,
                transaction_id=transaction.get("id", "unknown"),
                error="No match to reconcile",
            )

        txn_id = transaction.get("id", "")
        amount = abs(float(transaction.get("amount", 0)))

        try:
            # Create payment in Odoo
            payment_id = self.create_payment(
                invoice_id=match.invoice_id,
                amount=amount,
                reference=txn_id,
                payment_date=transaction.get("postedAt", "")[:10] if transaction.get("postedAt") else None,
            )

            # Log reconciliation
            self.sync_db.log_reconciliation(
                transaction_id=txn_id,
                invoice_id=match.invoice_id,
                amount=amount,
                match_type=match.match_type or "unknown",
                payment_id=payment_id,
                match_confidence=match.confidence,
            )

            return ReconciliationResult(
                success=True,
                transaction_id=txn_id,
                invoice_id=match.invoice_id,
                payment_id=payment_id,
                match_type=match.match_type,
            )

        except Exception as e:
            return ReconciliationResult(
                success=False,
                transaction_id=txn_id,
                invoice_id=match.invoice_id,
                error=str(e),
            )


async def auto_reconcile_deposits(
    mercury_client,
    odoo_execute_fn,
    days: int = 7,
    min_confidence: float = 0.7,
) -> dict[str, Any]:
    """
    Convenience function to auto-reconcile recent deposits.

    Args:
        mercury_client: MercuryClient instance
        odoo_execute_fn: Odoo execute function
        days: Days of history to check
        min_confidence: Minimum match confidence

    Returns:
        Summary of reconciliation results
    """
    from mercury import MercuryClient

    sync_db = get_sync_db()
    matcher = InvoiceMatcher(odoo_execute_fn, sync_db)

    # Get recent deposits
    deposits = await mercury_client.get_recent_deposits(days=days)

    results = {
        "processed": 0,
        "matched": 0,
        "reconciled": 0,
        "skipped": 0,
        "errors": [],
        "details": [],
    }

    for txn in deposits:
        txn_id = txn.get("id", "")

        # Skip already reconciled (not just processed)
        if sync_db.is_transaction_reconciled(txn_id):
            results["skipped"] += 1
            continue

        results["processed"] += 1

        # Try to find match
        match = matcher.find_match(txn, min_confidence=min_confidence)

        if match.matched:
            results["matched"] += 1

            # Reconcile
            recon = matcher.reconcile_transaction(txn, match)

            if recon.success:
                results["reconciled"] += 1
                results["details"].append({
                    "transaction_id": txn_id,
                    "invoice_id": recon.invoice_id,
                    "payment_id": recon.payment_id,
                    "amount": float(txn.get("amount", 0)),
                    "match_type": match.match_type,
                })
            else:
                results["errors"].append({
                    "transaction_id": txn_id,
                    "error": recon.error,
                })
        else:
            # Mark as processed but not reconciled
            sync_db.mark_transaction_processed(
                transaction_id=txn_id,
                account_id=txn.get("accountId", ""),
                amount=float(txn.get("amount", 0)),
                transaction_type="credit",
                description=txn.get("counterpartyName", ""),
                transaction_date=txn.get("postedAt", "")[:10] if txn.get("postedAt") else None,
            )

    return results
