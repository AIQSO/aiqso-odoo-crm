"""
Mercury Bank API Client

Provides access to Mercury banking API for:
- Account information and balances
- Transaction history
- Treasury balances

API Docs: https://docs.mercury.com/reference
"""

import os
from datetime import datetime
from typing import Any

import httpx

# Mercury API configuration
MERCURY_API_BASE = "https://api.mercury.com/api/v1"
MERCURY_API_TOKEN = os.getenv("MERCURY_API_TOKEN", "")


class MercuryAPIError(Exception):
    """Raised when Mercury API returns an error."""

    def __init__(self, status_code: int, message: str, details: dict | None = None):
        self.status_code = status_code
        self.message = message
        self.details = details or {}
        super().__init__(f"Mercury API Error ({status_code}): {message}")


class MercuryClient:
    """
    Mercury Bank API client.

    Usage:
        client = MercuryClient()
        accounts = await client.get_accounts()
        transactions = await client.get_transactions(account_id)
    """

    def __init__(self, api_token: str | None = None):
        self.api_token = api_token or MERCURY_API_TOKEN
        if not self.api_token:
            raise ValueError("Mercury API token is required. Set MERCURY_API_TOKEN environment variable.")
        self._client: httpx.AsyncClient | None = None

    @property
    def headers(self) -> dict[str, str]:
        """Get request headers with authentication."""
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=MERCURY_API_BASE,
                headers=self.headers,
                timeout=30.0,
            )
        return self._client

    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(self, method: str, endpoint: str, **kwargs) -> dict[str, Any]:
        """Make an API request and handle errors."""
        client = await self._get_client()

        try:
            response = await client.request(method, endpoint, **kwargs)

            if response.status_code >= 400:
                try:
                    error_data = response.json()
                    message = error_data.get("error", error_data.get("message", response.text))
                except Exception:
                    message = response.text

                raise MercuryAPIError(response.status_code, message)

            if response.status_code == 204:
                return {}

            return response.json()

        except httpx.RequestError as e:
            raise MercuryAPIError(0, f"Request failed: {e}") from e

    # =========================================================================
    # Account Endpoints
    # =========================================================================

    async def get_accounts(self) -> list[dict[str, Any]]:
        """
        Get all Mercury accounts.

        Returns list of accounts with:
        - id, name, status, type
        - availableBalance, currentBalance
        - routingNumber, accountNumber
        """
        data = await self._request("GET", "/accounts")
        return data.get("accounts", [])

    async def get_account(self, account_id: str) -> dict[str, Any]:
        """Get a specific account by ID."""
        return await self._request("GET", f"/accounts/{account_id}")

    # =========================================================================
    # Transaction Endpoints
    # =========================================================================

    async def get_transactions(
        self,
        account_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
        start: datetime | None = None,
        end: datetime | None = None,
        status: str | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        """
        Get transactions.

        Args:
            account_id: Filter by specific account (None = all accounts)
            limit: Max transactions to return (default 100)
            offset: Pagination offset
            start: Filter transactions after this date
            end: Filter transactions before this date
            status: Filter by status (pending, sent, cancelled, failed)
            search: Search term for description/counterparty

        Returns:
            Dict with 'transactions' list and 'total' count
        """
        params: dict[str, Any] = {
            "limit": min(limit, 500),  # Mercury max is 500
            "offset": offset,
        }

        if start:
            params["start"] = start.strftime("%Y-%m-%d")
        if end:
            params["end"] = end.strftime("%Y-%m-%d")
        if status:
            params["status"] = status
        if search:
            params["search"] = search

        if account_id:
            endpoint = f"/accounts/{account_id}/transactions"
        else:
            endpoint = "/transactions"

        return await self._request("GET", endpoint, params=params)

    async def get_transaction(self, transaction_id: str) -> dict[str, Any]:
        """Get a specific transaction by ID."""
        return await self._request("GET", f"/transactions/{transaction_id}")

    # =========================================================================
    # Balance / Treasury Endpoints
    # =========================================================================

    async def get_treasury(self) -> dict[str, Any]:
        """
        Get treasury account information.

        Returns:
        - availableBalance, currentBalance (in dollars)
        - id, status, createdAt
        """
        return await self._request("GET", "/treasury")

    async def get_total_balance(self) -> dict[str, float]:
        """
        Get total balance across all accounts.

        Returns dict with:
        - total_available: Sum of available balances
        - total_current: Sum of current balances
        - accounts: List of account summaries
        """
        accounts = await self.get_accounts()

        total_available = 0.0
        total_current = 0.0
        account_summaries = []

        for account in accounts:
            available = float(account.get("availableBalance", 0))
            current = float(account.get("currentBalance", 0))
            total_available += available
            total_current += current

            account_summaries.append({
                "id": account.get("id"),
                "name": account.get("name"),
                "type": account.get("type"),
                "available_balance": available,
                "current_balance": current,
            })

        return {
            "total_available": total_available,
            "total_current": total_current,
            "accounts": account_summaries,
        }

    # =========================================================================
    # Convenience Methods
    # =========================================================================

    async def get_recent_deposits(
        self,
        days: int = 7,
        min_amount: float | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get recent credit transactions (deposits).

        Args:
            days: Number of days to look back
            min_amount: Minimum transaction amount filter

        Returns:
            List of credit transactions
        """
        from datetime import timedelta

        end = datetime.now()
        start = end - timedelta(days=days)

        result = await self.get_transactions(start=start, end=end)
        transactions = result.get("transactions", [])

        # Filter to credits only
        deposits = [
            t for t in transactions
            if float(t.get("amount", 0)) > 0  # Positive = credit/deposit
        ]

        if min_amount:
            deposits = [t for t in deposits if float(t.get("amount", 0)) >= min_amount]

        return deposits

    async def health_check(self) -> dict[str, Any]:
        """
        Check Mercury API connectivity.

        Returns dict with status and account count.
        """
        try:
            accounts = await self.get_accounts()
            return {
                "status": "healthy",
                "connected": True,
                "account_count": len(accounts),
                "timestamp": datetime.now().isoformat(),
            }
        except MercuryAPIError as e:
            return {
                "status": "unhealthy",
                "connected": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }


# Singleton instance for convenience
_client: MercuryClient | None = None


def get_mercury_client() -> MercuryClient:
    """Get or create singleton Mercury client."""
    global _client
    if _client is None:
        _client = MercuryClient()
    return _client


async def close_mercury_client():
    """Close the singleton client."""
    global _client
    if _client:
        await _client.close()
        _client = None
