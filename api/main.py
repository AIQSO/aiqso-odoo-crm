#!/usr/bin/env python3
"""
Odoo Invoice API Service

REST API wrapper for Odoo XML-RPC to handle invoice operations from n8n webhooks.
Endpoints:
  - POST /api/create_invoice - Create invoice from Stripe checkout
  - POST /api/mark_invoice_paid - Mark invoice as paid
  - GET /api/invoices/{invoice_id} - Get invoice details
  - GET /health - Health check
"""

import os
import xmlrpc.client
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

app = FastAPI(
    title="AIQSO Odoo Invoice API",
    description="REST API for Odoo invoice operations",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration from environment
ODOO_URL = os.getenv("ODOO_URL", "http://localhost:8069")
ODOO_DB = os.getenv("ODOO_DB", "aiqso_db")
ODOO_USERNAME = os.getenv("ODOO_USERNAME", "admin")
ODOO_API_KEY = os.getenv("ODOO_API_KEY", "")


class OdooConnection:
    """Manages Odoo XML-RPC connection."""

    def __init__(self):
        self._uid: int | None = None
        self._models = None

    def authenticate(self) -> int:
        """Authenticate and return user ID."""
        if self._uid is None:
            common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common", allow_none=True)
            self._uid = common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_API_KEY, {})
            if not self._uid:
                raise HTTPException(status_code=500, detail="Odoo authentication failed")
        return self._uid

    @property
    def models(self):
        """Get models proxy."""
        if self._models is None:
            self._models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object", allow_none=True)
        return self._models

    def execute(self, model: str, method: str, *args, **kwargs):
        """Execute Odoo method."""
        uid = self.authenticate()
        return self.models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, model, method, list(args), kwargs)


# Singleton connection
odoo = OdooConnection()


def get_odoo() -> OdooConnection:
    """Dependency to get Odoo connection."""
    return odoo


# Request/Response Models
class CreateInvoiceRequest(BaseModel):
    customer_email: EmailStr
    amount: float
    stripe_session_id: str
    description: str | None = "Stripe Payment"
    product_code: str | None = None


class CreateInvoiceResponse(BaseModel):
    success: bool
    invoice_id: int
    invoice_number: str
    message: str


class MarkPaidRequest(BaseModel):
    invoice_id: int | None = None
    stripe_session_id: str | None = None
    payment_id: str
    amount: float | None = None


class MarkPaidResponse(BaseModel):
    success: bool
    invoice_id: int
    payment_id: int
    message: str


class InvoiceResponse(BaseModel):
    id: int
    name: str
    partner_name: str
    partner_email: str
    amount_total: float
    amount_residual: float
    state: str
    payment_state: str
    invoice_date: str | None
    stripe_session_id: str | None


# Endpoints
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        odoo.authenticate()
        return {"status": "healthy", "odoo": "connected", "timestamp": datetime.utcnow().isoformat()}
    except Exception as e:
        return {"status": "unhealthy", "odoo": "disconnected", "error": str(e)}


@app.post("/api/create_invoice", response_model=CreateInvoiceResponse)
async def create_invoice(request: CreateInvoiceRequest, odoo: OdooConnection = Depends(get_odoo)):
    """
    Create an invoice from a Stripe checkout session.

    - Finds or creates customer by email
    - Creates draft invoice with line items
    - Posts the invoice
    - Stores Stripe session ID in metadata
    """
    try:
        # Find or create partner by email
        partner_ids = odoo.execute("res.partner", "search", [["email", "=", request.customer_email]])

        if partner_ids:
            partner_id = partner_ids[0]
        else:
            # Create new partner
            partner_id = odoo.execute(
                "res.partner",
                "create",
                {
                    "name": request.customer_email.split("@")[0].title(),
                    "email": request.customer_email,
                    "customer_rank": 1,
                },
            )

        # Find product by code if provided, else use generic service
        product_id = None
        if request.product_code:
            products = odoo.execute(
                "product.product", "search_read", [["default_code", "=", request.product_code]], fields=["id"]
            )
            if products:
                product_id = products[0]["id"]

        if not product_id:
            # Use or create a generic "Stripe Payment" product
            products = odoo.execute(
                "product.product", "search_read", [["default_code", "=", "STRIPE-PAYMENT"]], fields=["id"]
            )
            if products:
                product_id = products[0]["id"]
            else:
                # Create the product
                template_id = odoo.execute(
                    "product.template",
                    "create",
                    {
                        "name": "Stripe Payment",
                        "type": "service",
                        "default_code": "STRIPE-PAYMENT",
                        "list_price": 0,
                        "invoice_policy": "order",
                    },
                )
                products = odoo.execute(
                    "product.product", "search_read", [["product_tmpl_id", "=", template_id]], fields=["id"]
                )
                product_id = products[0]["id"]

        # Create invoice
        invoice_vals = {
            "move_type": "out_invoice",
            "partner_id": partner_id,
            "invoice_date": datetime.now().strftime("%Y-%m-%d"),
            "ref": request.stripe_session_id,  # Store Stripe session ID
            "narration": f"Stripe Session: {request.stripe_session_id}",
            "invoice_line_ids": [
                (
                    0,
                    0,
                    {
                        "product_id": product_id,
                        "name": request.description,
                        "quantity": 1,
                        "price_unit": request.amount,
                    },
                )
            ],
        }

        invoice_id = odoo.execute("account.move", "create", invoice_vals)

        # Post the invoice (validate it)
        odoo.execute("account.move", "action_post", [invoice_id])

        # Get invoice number
        invoice = odoo.execute("account.move", "read", [invoice_id], fields=["name"])[0]

        return CreateInvoiceResponse(
            success=True,
            invoice_id=invoice_id,
            invoice_number=invoice["name"],
            message=f"Invoice {invoice['name']} created and posted",
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/mark_invoice_paid", response_model=MarkPaidResponse)
async def mark_invoice_paid(request: MarkPaidRequest, odoo: OdooConnection = Depends(get_odoo)):
    """
    Mark an invoice as paid by registering a payment.

    Can find invoice by:
    - invoice_id directly
    - stripe_session_id (stored in ref field)
    """
    try:
        invoice_id = request.invoice_id

        # Find invoice by Stripe session ID if not provided directly
        if not invoice_id and request.stripe_session_id:
            invoices = odoo.execute(
                "account.move",
                "search_read",
                [["ref", "=", request.stripe_session_id], ["move_type", "=", "out_invoice"]],
                fields=["id", "amount_residual"],
            )
            if invoices:
                invoice_id = invoices[0]["id"]

        if not invoice_id:
            raise HTTPException(status_code=404, detail="Invoice not found")

        # Get invoice details
        invoice = odoo.execute(
            "account.move",
            "read",
            [invoice_id],
            fields=["name", "amount_residual", "state", "payment_state", "currency_id", "partner_id"],
        )[0]

        if invoice["payment_state"] == "paid":
            return MarkPaidResponse(
                success=True, invoice_id=invoice_id, payment_id=0, message=f"Invoice {invoice['name']} is already paid"
            )

        if invoice["state"] != "posted":
            raise HTTPException(status_code=400, detail=f"Invoice is not posted (state: {invoice['state']})")

        # Get default payment journal (Bank)
        journals = odoo.execute("account.journal", "search_read", [["type", "=", "bank"]], fields=["id"], limit=1)
        if not journals:
            raise HTTPException(status_code=500, detail="No bank journal found")
        journal_id = journals[0]["id"]

        # Create payment
        payment_amount = request.amount if request.amount else invoice["amount_residual"]

        # Find payment method line for inbound bank payments
        payment_method_lines = odoo.execute(
            "account.payment.method.line",
            "search_read",
            [["journal_id", "=", journal_id], ["payment_type", "=", "inbound"]],
            fields=["id"],
            limit=1,
        )

        payment_vals = {
            "payment_type": "inbound",
            "partner_type": "customer",
            "partner_id": invoice["partner_id"][0],
            "amount": payment_amount,
            "currency_id": invoice["currency_id"][0],
            "journal_id": journal_id,
            "ref": request.payment_id,  # Stripe payment intent ID
        }

        # Add payment method line if found
        if payment_method_lines:
            payment_vals["payment_method_line_id"] = payment_method_lines[0]["id"]

        payment_id = odoo.execute("account.payment", "create", payment_vals)

        # Post the payment (may return None, causing XML-RPC fault)
        try:
            odoo.execute("account.payment", "action_post", [payment_id])
        except xmlrpc.client.Fault:
            pass  # Odoo returns None which causes fault, but action may have succeeded

        # Verify payment was posted
        payment = odoo.execute("account.payment", "read", [payment_id], fields=["move_id", "state"])[0]

        if payment["state"] != "posted":
            raise HTTPException(status_code=500, detail="Failed to post payment")

        # Get receivable lines from both invoice and payment for reconciliation
        invoice_lines = odoo.execute(
            "account.move.line",
            "search_read",
            [["move_id", "=", invoice_id], ["account_type", "=", "asset_receivable"], ["reconciled", "=", False]],
            fields=["id"],
        )

        payment_lines = odoo.execute(
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
                odoo.execute("account.move.line", "reconcile", line_ids)
            except xmlrpc.client.Fault:
                pass  # Reconcile returns None which causes Fault, but action succeeds

        return MarkPaidResponse(
            success=True,
            invoice_id=invoice_id,
            payment_id=payment_id,
            message=f"Payment registered for invoice {invoice['name']}",
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/invoices/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(invoice_id: int, odoo: OdooConnection = Depends(get_odoo)):
    """Get invoice details by ID."""
    try:
        invoices = odoo.execute(
            "account.move",
            "read",
            [invoice_id],
            fields=[
                "name",
                "partner_id",
                "amount_total",
                "amount_residual",
                "state",
                "payment_state",
                "invoice_date",
                "ref",
            ],
        )

        if not invoices:
            raise HTTPException(status_code=404, detail="Invoice not found")

        invoice = invoices[0]

        # Get partner email
        partner = odoo.execute("res.partner", "read", [invoice["partner_id"][0]], fields=["email"])[0]

        return InvoiceResponse(
            id=invoice["id"],
            name=invoice["name"],
            partner_name=invoice["partner_id"][1],
            partner_email=partner.get("email", ""),
            amount_total=invoice["amount_total"],
            amount_residual=invoice["amount_residual"],
            state=invoice["state"],
            payment_state=invoice["payment_state"],
            invoice_date=invoice["invoice_date"] if invoice["invoice_date"] else None,
            stripe_session_id=invoice["ref"] if invoice["ref"] else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/invoices/by-stripe/{stripe_session_id}", response_model=InvoiceResponse)
async def get_invoice_by_stripe(stripe_session_id: str, odoo: OdooConnection = Depends(get_odoo)):
    """Get invoice by Stripe session ID."""
    try:
        invoices = odoo.execute(
            "account.move",
            "search_read",
            [["ref", "=", stripe_session_id], ["move_type", "=", "out_invoice"]],
            fields=[
                "name",
                "partner_id",
                "amount_total",
                "amount_residual",
                "state",
                "payment_state",
                "invoice_date",
                "ref",
            ],
        )

        if not invoices:
            raise HTTPException(status_code=404, detail="Invoice not found")

        invoice = invoices[0]

        # Get partner email
        partner = odoo.execute("res.partner", "read", [invoice["partner_id"][0]], fields=["email"])[0]

        return InvoiceResponse(
            id=invoice["id"],
            name=invoice["name"],
            partner_name=invoice["partner_id"][1],
            partner_email=partner.get("email", ""),
            amount_total=invoice["amount_total"],
            amount_residual=invoice["amount_residual"],
            state=invoice["state"],
            payment_state=invoice["payment_state"],
            invoice_date=invoice["invoice_date"] if invoice["invoice_date"] else None,
            stripe_session_id=invoice["ref"] if invoice["ref"] else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8070)
