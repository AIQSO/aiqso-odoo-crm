"""
Sync State Tracking

SQLite-based tracking for Mercury transaction sync:
- Last sync timestamp per account
- Processed transaction IDs (deduplication)
- Reconciliation status

Database file: /tmp/mercury_sync.db (or configurable)
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any

# Database path - use environment variable or default
SYNC_DB_PATH = os.getenv("MERCURY_SYNC_DB", "/tmp/mercury_sync.db")


class SyncStateDB:
    """
    SQLite database for tracking sync state.

    Tables:
    - sync_state: Last sync time per account
    - processed_transactions: Transaction IDs that have been processed
    - reconciliation_log: Log of matched transactions to invoices
    """

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or SYNC_DB_PATH
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        with self._get_connection() as conn:
            conn.executescript("""
                -- Sync state per account
                CREATE TABLE IF NOT EXISTS sync_state (
                    account_id TEXT PRIMARY KEY,
                    last_sync_at TEXT NOT NULL,
                    last_transaction_id TEXT,
                    transaction_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                -- Processed transactions (dedup)
                CREATE TABLE IF NOT EXISTS processed_transactions (
                    transaction_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    amount REAL NOT NULL,
                    transaction_type TEXT NOT NULL,
                    description TEXT,
                    transaction_date TEXT,
                    processed_at TEXT NOT NULL,
                    reconciled INTEGER DEFAULT 0,
                    invoice_id INTEGER,
                    payment_id INTEGER
                );

                -- Reconciliation log
                CREATE TABLE IF NOT EXISTS reconciliation_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transaction_id TEXT NOT NULL,
                    invoice_id INTEGER NOT NULL,
                    payment_id INTEGER,
                    amount REAL NOT NULL,
                    match_type TEXT NOT NULL,
                    match_confidence REAL DEFAULT 1.0,
                    created_at TEXT NOT NULL,
                    UNIQUE(transaction_id, invoice_id)
                );

                -- Indexes
                CREATE INDEX IF NOT EXISTS idx_processed_account
                    ON processed_transactions(account_id);
                CREATE INDEX IF NOT EXISTS idx_processed_date
                    ON processed_transactions(transaction_date);
                CREATE INDEX IF NOT EXISTS idx_processed_reconciled
                    ON processed_transactions(reconciled);
                CREATE INDEX IF NOT EXISTS idx_reconciliation_invoice
                    ON reconciliation_log(invoice_id);
            """)

    @contextmanager
    def _get_connection(self):
        """Get database connection with context manager."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # =========================================================================
    # Sync State Methods
    # =========================================================================

    def get_last_sync(self, account_id: str) -> dict[str, Any] | None:
        """Get last sync info for an account."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM sync_state WHERE account_id = ?",
                (account_id,)
            ).fetchone()
            return dict(row) if row else None

    def update_sync_state(
        self,
        account_id: str,
        last_transaction_id: str | None = None,
        transaction_count: int = 0,
    ):
        """Update sync state for an account."""
        now = datetime.now().isoformat()

        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO sync_state (
                    account_id, last_sync_at, last_transaction_id,
                    transaction_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    last_sync_at = excluded.last_sync_at,
                    last_transaction_id = COALESCE(excluded.last_transaction_id, last_transaction_id),
                    transaction_count = transaction_count + excluded.transaction_count,
                    updated_at = excluded.updated_at
            """, (account_id, now, last_transaction_id, transaction_count, now, now))

    def get_all_sync_states(self) -> list[dict[str, Any]]:
        """Get sync state for all accounts."""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM sync_state ORDER BY updated_at DESC").fetchall()
            return [dict(row) for row in rows]

    # =========================================================================
    # Transaction Processing Methods
    # =========================================================================

    def is_transaction_processed(self, transaction_id: str) -> bool:
        """Check if a transaction has already been processed."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM processed_transactions WHERE transaction_id = ?",
                (transaction_id,)
            ).fetchone()
            return row is not None

    def is_transaction_reconciled(self, transaction_id: str) -> bool:
        """Check if a transaction has already been reconciled."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT reconciled FROM processed_transactions WHERE transaction_id = ?",
                (transaction_id,)
            ).fetchone()
            return row is not None and row[0] == 1

    def mark_transaction_processed(
        self,
        transaction_id: str,
        account_id: str,
        amount: float,
        transaction_type: str,
        description: str | None = None,
        transaction_date: str | None = None,
    ):
        """Mark a transaction as processed."""
        now = datetime.now().isoformat()

        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO processed_transactions (
                    transaction_id, account_id, amount, transaction_type,
                    description, transaction_date, processed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                transaction_id, account_id, amount, transaction_type,
                description, transaction_date, now
            ))

    def get_unreconciled_transactions(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get transactions that haven't been reconciled to invoices."""
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM processed_transactions
                WHERE reconciled = 0 AND amount > 0
                ORDER BY transaction_date DESC
                LIMIT ?
            """, (limit,)).fetchall()
            return [dict(row) for row in rows]

    def mark_transaction_reconciled(
        self,
        transaction_id: str,
        invoice_id: int,
        payment_id: int | None = None,
    ):
        """Mark a transaction as reconciled to an invoice."""
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE processed_transactions
                SET reconciled = 1, invoice_id = ?, payment_id = ?
                WHERE transaction_id = ?
            """, (invoice_id, payment_id, transaction_id))

    # =========================================================================
    # Reconciliation Log Methods
    # =========================================================================

    def log_reconciliation(
        self,
        transaction_id: str,
        invoice_id: int,
        amount: float,
        match_type: str,
        payment_id: int | None = None,
        match_confidence: float = 1.0,
    ):
        """Log a reconciliation match."""
        now = datetime.now().isoformat()

        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO reconciliation_log (
                    transaction_id, invoice_id, payment_id, amount,
                    match_type, match_confidence, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                transaction_id, invoice_id, payment_id,
                amount, match_type, match_confidence, now
            ))

            # Also update processed_transactions
            conn.execute("""
                UPDATE processed_transactions
                SET reconciled = 1, invoice_id = ?, payment_id = ?
                WHERE transaction_id = ?
            """, (invoice_id, payment_id, transaction_id))

    def get_reconciliation_history(
        self,
        limit: int = 50,
        invoice_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get reconciliation history."""
        with self._get_connection() as conn:
            if invoice_id:
                rows = conn.execute("""
                    SELECT * FROM reconciliation_log
                    WHERE invoice_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (invoice_id, limit)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM reconciliation_log
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (limit,)).fetchall()
            return [dict(row) for row in rows]

    # =========================================================================
    # Stats and Reporting
    # =========================================================================

    def get_stats(self) -> dict[str, Any]:
        """Get sync statistics."""
        with self._get_connection() as conn:
            total = conn.execute(
                "SELECT COUNT(*) as count FROM processed_transactions"
            ).fetchone()["count"]

            reconciled = conn.execute(
                "SELECT COUNT(*) as count FROM processed_transactions WHERE reconciled = 1"
            ).fetchone()["count"]

            unreconciled = conn.execute(
                "SELECT COUNT(*) as count FROM processed_transactions WHERE reconciled = 0 AND amount > 0"
            ).fetchone()["count"]

            last_sync = conn.execute(
                "SELECT MAX(last_sync_at) as last FROM sync_state"
            ).fetchone()["last"]

            return {
                "total_transactions": total,
                "reconciled": reconciled,
                "unreconciled_deposits": unreconciled,
                "last_sync": last_sync,
            }

    def reset(self):
        """Reset all sync state (use with caution)."""
        with self._get_connection() as conn:
            conn.executescript("""
                DELETE FROM sync_state;
                DELETE FROM processed_transactions;
                DELETE FROM reconciliation_log;
            """)


# Singleton instance
_db: SyncStateDB | None = None


def get_sync_db() -> SyncStateDB:
    """Get or create singleton database instance."""
    global _db
    if _db is None:
        _db = SyncStateDB()
    return _db
