"""
Slack Notifications for Mercury Bank Integration

Sends alerts for:
- New deposits received
- Successful reconciliations
- Unmatched deposits requiring attention
"""

import os
import logging
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger("mercury_notifications")

# Configuration
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
SLACK_ENABLED = bool(SLACK_WEBHOOK_URL)


async def send_slack_message(blocks: list[dict], text: str = "Mercury Bank Alert") -> bool:
    """
    Send a message to Slack via webhook.

    Args:
        blocks: Slack Block Kit blocks
        text: Fallback text for notifications

    Returns:
        True if sent successfully
    """
    if not SLACK_ENABLED:
        logger.debug("Slack notifications disabled (no webhook URL)")
        return False

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                SLACK_WEBHOOK_URL,
                json={"text": text, "blocks": blocks},
                timeout=10.0,
            )

            if response.status_code == 200:
                logger.info("Slack notification sent successfully")
                return True
            else:
                logger.warning(f"Slack webhook returned {response.status_code}")
                return False

    except Exception as e:
        logger.error(f"Failed to send Slack notification: {e}")
        return False


async def notify_new_deposit(
    amount: float,
    counterparty: str,
    transaction_id: str,
    account_name: str = "Mercury",
    transaction_date: str | None = None,
) -> bool:
    """Send notification for a new deposit."""

    date_str = transaction_date or datetime.now().strftime("%Y-%m-%d")

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "💰 New Deposit Received",
                "emoji": True
            }
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Amount:*\n${amount:,.2f}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*From:*\n{counterparty}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Account:*\n{account_name}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Date:*\n{date_str}"
                }
            ]
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Transaction ID: `{transaction_id[:16]}...`"
                }
            ]
        }
    ]

    return await send_slack_message(blocks, f"New deposit: ${amount:,.2f} from {counterparty}")


async def notify_reconciliation(
    amount: float,
    invoice_number: str,
    counterparty: str,
    match_type: str,
    confidence: float,
) -> bool:
    """Send notification for successful reconciliation."""

    confidence_emoji = "🟢" if confidence >= 0.8 else "🟡" if confidence >= 0.5 else "🟠"

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "✅ Payment Reconciled",
                "emoji": True
            }
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Amount:*\n${amount:,.2f}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Invoice:*\n{invoice_number}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*From:*\n{counterparty}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Match:*\n{confidence_emoji} {match_type} ({confidence:.0%})"
                }
            ]
        }
    ]

    return await send_slack_message(blocks, f"Reconciled ${amount:,.2f} to {invoice_number}")


async def notify_unmatched_deposit(
    amount: float,
    counterparty: str,
    transaction_id: str,
    transaction_date: str | None = None,
) -> bool:
    """Send notification for deposit that couldn't be matched."""

    date_str = transaction_date or datetime.now().strftime("%Y-%m-%d")

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "⚠️ Unmatched Deposit",
                "emoji": True
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"A deposit of *${amount:,.2f}* from *{counterparty}* could not be automatically matched to an invoice."
            }
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Amount:*\n${amount:,.2f}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*From:*\n{counterparty}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Date:*\n{date_str}"
                }
            ]
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "💡 Create a matching invoice in Odoo or manually reconcile this payment."
                }
            ]
        }
    ]

    return await send_slack_message(blocks, f"Unmatched deposit: ${amount:,.2f} from {counterparty}")


async def notify_sync_summary(
    new_transactions: int,
    deposits: int,
    reconciled: int,
    unmatched: int,
    total_deposited: float = 0.0,
) -> bool:
    """Send daily/periodic sync summary."""

    if new_transactions == 0:
        return False  # Don't notify if nothing new

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "📊 Mercury Sync Summary",
                "emoji": True
            }
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*New Transactions:*\n{new_transactions}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Deposits:*\n{deposits}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Auto-Reconciled:*\n{reconciled}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Needs Review:*\n{unmatched}"
                }
            ]
        },
    ]

    if total_deposited > 0:
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"💵 Total deposited: *${total_deposited:,.2f}*"
                }
            ]
        })

    return await send_slack_message(blocks, f"Mercury sync: {new_transactions} new, {reconciled} reconciled")


def is_slack_enabled() -> bool:
    """Check if Slack notifications are enabled."""
    return SLACK_ENABLED
