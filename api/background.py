"""
Background Sync Tasks

APScheduler-based background tasks for:
- Periodic Mercury transaction sync
- Auto-reconciliation of deposits
- Sync state updates

Usage:
    from background import scheduler, start_scheduler, stop_scheduler

    # Start background tasks
    start_scheduler()

    # Stop on shutdown
    stop_scheduler()
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mercury_sync")

# Sync configuration
SYNC_INTERVAL_MINUTES = int(os.getenv("MERCURY_SYNC_INTERVAL", "15"))
AUTO_RECONCILE = os.getenv("MERCURY_AUTO_RECONCILE", "true").lower() == "true"
MIN_RECONCILE_CONFIDENCE = float(os.getenv("MERCURY_MIN_CONFIDENCE", "0.7"))

# Global scheduler instance
scheduler: AsyncIOScheduler | None = None


async def sync_mercury_transactions(odoo_execute_fn=None) -> dict[str, Any]:
    """
    Sync transactions from Mercury and optionally auto-reconcile.

    Args:
        odoo_execute_fn: Odoo execute function (optional, will use global if not provided)

    Returns:
        Sync result summary
    """
    from mercury import get_mercury_client
    from sync_state import get_sync_db

    logger.info("Starting Mercury transaction sync...")

    client = get_mercury_client()
    sync_db = get_sync_db()

    result = {
        "started_at": datetime.now().isoformat(),
        "accounts_synced": 0,
        "new_transactions": 0,
        "deposits": 0,
        "withdrawals": 0,
        "reconciled": 0,
        "errors": [],
    }

    try:
        # Get all accounts for reference
        accounts = await client.get_accounts()
        result["accounts_synced"] = len(accounts)

        # Build account lookup map
        account_map = {acc.get("id"): acc.get("name", "Unknown") for acc in accounts}

        # Get last sync time (use global sync state)
        last_sync = sync_db.get_last_sync("_global")
        since_date = None

        if last_sync:
            from datetime import timedelta
            try:
                last_dt = datetime.fromisoformat(last_sync["last_sync_at"])
                since_date = last_dt - timedelta(hours=1)  # Overlap for safety
            except (ValueError, TypeError):
                pass

        logger.info(f"Fetching transactions since: {since_date}")

        # Fetch ALL transactions (Mercury's per-account endpoint may not work)
        txn_result = await client.get_transactions(
            account_id=None,  # Use global transactions endpoint
            start=since_date,
            limit=500,
        )

        transactions = txn_result.get("transactions", [])
        new_count = 0
        last_txn_id = None

        # Track new deposits for notifications
        new_deposits = []
        total_deposited = 0.0

        for txn in transactions:
            txn_id = txn.get("id", "")

            # Skip if already processed
            if sync_db.is_transaction_processed(txn_id):
                continue

            new_count += 1
            last_txn_id = txn_id

            amount = float(txn.get("amount", 0))
            is_deposit = amount > 0
            account_id = txn.get("accountId", "_unknown")
            counterparty = txn.get("counterpartyName") or "Unknown"
            txn_date = txn.get("postedAt", "")[:10] if txn.get("postedAt") else None

            if is_deposit:
                result["deposits"] += 1
                total_deposited += amount
                new_deposits.append({
                    "id": txn_id,
                    "amount": amount,
                    "counterparty": counterparty,
                    "date": txn_date,
                    "account_name": account_map.get(account_id, "Mercury"),
                })
            else:
                result["withdrawals"] += 1

            # Mark as processed
            sync_db.mark_transaction_processed(
                transaction_id=txn_id,
                account_id=account_id,
                amount=amount,
                transaction_type="credit" if is_deposit else "debit",
                description=counterparty,
                transaction_date=txn_date,
            )

        result["new_transactions"] = new_count

        # Update global sync state
        sync_db.update_sync_state(
            account_id="_global",
            last_transaction_id=last_txn_id,
            transaction_count=new_count,
        )

        logger.info(f"Sync complete: {new_count} new transactions")

        # Auto-reconcile if enabled and Odoo connection available
        if AUTO_RECONCILE and odoo_execute_fn and result["deposits"] > 0:
            logger.info("Running auto-reconciliation...")
            try:
                from reconciliation import auto_reconcile_deposits

                recon_result = await auto_reconcile_deposits(
                    mercury_client=client,
                    odoo_execute_fn=odoo_execute_fn,
                    days=1,  # Only recent for background sync
                    min_confidence=MIN_RECONCILE_CONFIDENCE,
                )
                result["reconciled"] = recon_result.get("reconciled", 0)
                result["reconciliation_details"] = recon_result

            except Exception as e:
                logger.error(f"Auto-reconciliation error: {e}")
                result["errors"].append(f"Reconciliation failed: {e}")

        result["completed_at"] = datetime.now().isoformat()
        result["success"] = True

        logger.info(
            f"Sync complete: {result['new_transactions']} new transactions, "
            f"{result['reconciled']} reconciled"
        )

        # Send Slack notifications for new deposits
        if new_deposits:
            try:
                from notifications import (
                    notify_new_deposit,
                    notify_reconciliation,
                    notify_unmatched_deposit,
                    notify_sync_summary,
                    is_slack_enabled,
                )

                if is_slack_enabled():
                    reconciled_ids = set()
                    recon_details = result.get("reconciliation_details", {})

                    # Track which transactions were reconciled
                    for detail in recon_details.get("details", []):
                        reconciled_ids.add(detail.get("transaction_id"))

                        # Notify for each reconciliation
                        await notify_reconciliation(
                            amount=detail.get("amount", 0),
                            invoice_number=f"Invoice #{detail.get('invoice_id')}",
                            counterparty=next(
                                (d["counterparty"] for d in new_deposits if d["id"] == detail.get("transaction_id")),
                                "Unknown"
                            ),
                            match_type=detail.get("match_type", "auto"),
                            confidence=detail.get("confidence", 0.5),
                        )

                    # Notify for unmatched deposits
                    unmatched_count = 0
                    for deposit in new_deposits:
                        if deposit["id"] not in reconciled_ids:
                            unmatched_count += 1
                            await notify_unmatched_deposit(
                                amount=deposit["amount"],
                                counterparty=deposit["counterparty"],
                                transaction_id=deposit["id"],
                                transaction_date=deposit["date"],
                            )

                    # Send summary if multiple transactions
                    if len(new_deposits) > 1:
                        await notify_sync_summary(
                            new_transactions=new_count,
                            deposits=len(new_deposits),
                            reconciled=result["reconciled"],
                            unmatched=unmatched_count,
                            total_deposited=total_deposited,
                        )

                    logger.info(f"Sent Slack notifications for {len(new_deposits)} deposits")

            except Exception as e:
                logger.warning(f"Failed to send Slack notifications: {e}")

    except Exception as e:
        logger.error(f"Sync error: {e}")
        result["success"] = False
        result["errors"].append(str(e))
        result["completed_at"] = datetime.now().isoformat()

    return result


# Store last sync result for status endpoint
_last_sync_result: dict[str, Any] | None = None


async def _scheduled_sync():
    """Wrapper for scheduled sync task."""
    global _last_sync_result

    # Import Odoo connection from main module
    try:
        from main import odoo as odoo_connection
        odoo_execute_fn = odoo_connection.execute
    except ImportError:
        odoo_execute_fn = None

    _last_sync_result = await sync_mercury_transactions(odoo_execute_fn)


def get_last_sync_result() -> dict[str, Any] | None:
    """Get the result of the last sync."""
    return _last_sync_result


def start_scheduler():
    """Start the background scheduler."""
    global scheduler

    if scheduler is not None:
        logger.warning("Scheduler already running")
        return

    scheduler = AsyncIOScheduler()

    # Add sync job
    scheduler.add_job(
        _scheduled_sync,
        trigger=IntervalTrigger(minutes=SYNC_INTERVAL_MINUTES),
        id="mercury_sync",
        name="Mercury Transaction Sync",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(f"Background scheduler started (interval: {SYNC_INTERVAL_MINUTES} minutes)")

    # Run initial sync after startup
    asyncio.create_task(_initial_sync())


async def _initial_sync():
    """Run initial sync shortly after startup."""
    await asyncio.sleep(5)  # Wait for app to fully start
    logger.info("Running initial sync...")
    await _scheduled_sync()


def stop_scheduler():
    """Stop the background scheduler."""
    global scheduler

    if scheduler is not None:
        scheduler.shutdown()
        scheduler = None
        logger.info("Background scheduler stopped")


def get_scheduler_status() -> dict[str, Any]:
    """Get scheduler status information."""
    if scheduler is None:
        return {
            "running": False,
            "message": "Scheduler not started",
        }

    jobs = scheduler.get_jobs()

    return {
        "running": scheduler.running,
        "interval_minutes": SYNC_INTERVAL_MINUTES,
        "auto_reconcile": AUTO_RECONCILE,
        "min_confidence": MIN_RECONCILE_CONFIDENCE,
        "jobs": [
            {
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            }
            for job in jobs
        ],
        "last_sync": _last_sync_result.get("completed_at") if _last_sync_result else None,
        "last_sync_success": _last_sync_result.get("success") if _last_sync_result else None,
    }
