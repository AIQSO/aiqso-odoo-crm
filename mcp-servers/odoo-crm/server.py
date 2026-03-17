#!/usr/bin/env python3
"""
Odoo CRM MCP Server

Provides Claude with direct access to Odoo CRM operations:
- Search and manage leads/opportunities
- Create and send quotations
- Manage contacts
- Check pipeline status
- Create invoices

Usage:
    # Set env vars first
    set -a; source .env; set +a
    python3 mcp-servers/odoo-crm/server.py
"""

import json
import os
import sys
import xmlrpc.client
from datetime import datetime


# MCP Protocol implementation
def read_message():
    """Read a JSON-RPC message from stdin."""
    line = sys.stdin.readline()
    if not line:
        return None
    return json.loads(line)


def write_message(msg):
    """Write a JSON-RPC message to stdout."""
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


class OdooCRM:
    """Odoo CRM client for MCP operations."""

    def __init__(self):
        # Load .env file if ODOO_API_KEY not already in environment
        if not os.environ.get("ODOO_API_KEY"):
            env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
            if os.path.exists(env_path):
                with open(env_path) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, _, value = line.partition("=")
                            os.environ.setdefault(key.strip(), value.strip())

        self.url = os.environ.get("ODOO_URL", "http://192.168.0.237:8069")
        self.db = os.environ.get("ODOO_DB", "aiqso_db")
        self.username = os.environ.get("ODOO_USERNAME", "quinn@aiqso.io")
        self.api_key = os.environ.get("ODOO_API_KEY", "")
        self.uid = None
        self.models = None
        self._connect()

    def _connect(self):
        common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self.uid = common.authenticate(self.db, self.username, self.api_key, {})
        self.models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")

    def _execute(self, model, method, *args, **kwargs):
        return self.models.execute_kw(
            self.db, self.uid, self.api_key, model, method, *args, **kwargs
        )

    def search_leads(self, query="", stage=None, limit=20):
        """Search CRM leads/opportunities."""
        domain = [("type", "=", "opportunity")]
        if query:
            domain.append(
                "|",
            )
            domain.append(("name", "ilike", query))
            domain.append(("partner_name", "ilike", query))
        if stage:
            domain.append(("stage_id.name", "ilike", stage))

        return self._execute(
            "crm.lead",
            "search_read",
            [domain],
            {
                "fields": [
                    "name",
                    "partner_name",
                    "stage_id",
                    "expected_revenue",
                    "email_from",
                    "phone",
                    "tag_ids",
                    "user_id",
                    "create_date",
                ],
                "limit": limit,
                "order": "create_date desc",
            },
        )

    def get_lead(self, lead_id):
        """Get detailed lead information."""
        return self._execute(
            "crm.lead",
            "search_read",
            [[("id", "=", lead_id)]],
            {
                "fields": [
                    "name",
                    "partner_name",
                    "contact_name",
                    "email_from",
                    "phone",
                    "stage_id",
                    "expected_revenue",
                    "description",
                    "tag_ids",
                    "user_id",
                    "create_date",
                    "partner_id",
                ]
            },
        )

    def create_lead(self, name, partner_name, email="", phone="", expected_revenue=0, description=""):
        """Create a new CRM lead."""
        vals = {
            "name": name,
            "partner_name": partner_name,
            "type": "opportunity",
        }
        if email:
            vals["email_from"] = email
        if phone:
            vals["phone"] = phone
        if expected_revenue:
            vals["expected_revenue"] = expected_revenue
        if description:
            vals["description"] = description

        lead_id = self._execute("crm.lead", "create", [vals])
        return {"id": lead_id, "name": name}

    def move_lead_stage(self, lead_id, stage_name):
        """Move a lead to a different pipeline stage."""
        stages = self._execute(
            "crm.stage",
            "search_read",
            [[("name", "ilike", stage_name)]],
            {"fields": ["id", "name"], "limit": 1},
        )
        if not stages:
            return {"error": f"Stage '{stage_name}' not found"}

        self._execute("crm.lead", "write", [[lead_id], {"stage_id": stages[0]["id"]}])
        return {"success": True, "stage": stages[0]["name"]}

    def get_pipeline_summary(self):
        """Get pipeline summary by stage."""
        stages = self._execute(
            "crm.stage", "search_read", [[]], {"fields": ["name", "sequence"], "order": "sequence"}
        )
        summary = []
        for stage in stages:
            leads = self._execute(
                "crm.lead",
                "search_read",
                [[("stage_id", "=", stage["id"]), ("type", "=", "opportunity")]],
                {"fields": ["name", "expected_revenue", "partner_name"]},
            )
            total_revenue = sum(l.get("expected_revenue", 0) for l in leads)
            summary.append(
                {
                    "stage": stage["name"],
                    "count": len(leads),
                    "total_revenue": total_revenue,
                    "leads": [
                        {"name": l["name"], "revenue": l.get("expected_revenue", 0)}
                        for l in leads[:5]
                    ],
                }
            )
        return summary

    def search_contacts(self, query, limit=10):
        """Search contacts/companies."""
        domain = [
            "|",
            ("name", "ilike", query),
            ("email", "ilike", query),
        ]
        return self._execute(
            "res.partner",
            "search_read",
            [domain],
            {
                "fields": [
                    "name",
                    "email",
                    "phone",
                    "is_company",
                    "street",
                    "city",
                    "country_id",
                    "comment",
                ],
                "limit": limit,
            },
        )

    def create_contact(self, name, email="", phone="", is_company=True, comment=""):
        """Create a new contact."""
        vals = {"name": name, "is_company": is_company}
        if email:
            vals["email"] = email
        if phone:
            vals["phone"] = phone
        if comment:
            vals["comment"] = comment

        contact_id = self._execute("res.partner", "create", [vals])
        return {"id": contact_id, "name": name}

    def get_quotations(self, partner_id=None, state=None, limit=10):
        """List quotations/sales orders."""
        domain = []
        if partner_id:
            domain.append(("partner_id", "=", partner_id))
        if state:
            domain.append(("state", "=", state))

        return self._execute(
            "sale.order",
            "search_read",
            [domain],
            {
                "fields": [
                    "name",
                    "partner_id",
                    "amount_total",
                    "state",
                    "date_order",
                    "opportunity_id",
                ],
                "limit": limit,
                "order": "create_date desc",
            },
        )

    def get_invoices(self, partner_id=None, state=None, limit=10):
        """List invoices."""
        domain = [("move_type", "in", ["out_invoice", "out_refund"])]
        if partner_id:
            domain.append(("partner_id", "=", partner_id))
        if state:
            domain.append(("state", "=", state))

        return self._execute(
            "account.move",
            "search_read",
            [domain],
            {
                "fields": [
                    "name",
                    "partner_id",
                    "amount_total",
                    "amount_residual",
                    "state",
                    "payment_state",
                    "invoice_date",
                ],
                "limit": limit,
                "order": "create_date desc",
            },
        )

    def get_projects(self, limit=10):
        """List projects with task counts."""
        return self._execute(
            "project.project",
            "search_read",
            [[]],
            {
                "fields": ["name", "partner_id", "task_count", "description"],
                "limit": limit,
            },
        )

    def log_note(self, model, record_id, message):
        """Add a note/message to any record's chatter."""
        self._execute(
            model,
            "message_post",
            [[record_id]],
            {"body": message, "message_type": "comment"},
        )
        return {"success": True}


# MCP Tool definitions
TOOLS = [
    {
        "name": "search_leads",
        "description": "Search CRM leads and opportunities by name, company, or stage. Returns pipeline data.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term (name or company)"},
                "stage": {"type": "string", "description": "Filter by stage name (e.g., 'New Lead', 'Proposal Sent', 'Won')"},
                "limit": {"type": "integer", "description": "Max results (default 20)", "default": 20},
            },
        },
    },
    {
        "name": "get_lead",
        "description": "Get detailed information about a specific CRM lead/opportunity by ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "integer", "description": "Odoo lead/opportunity ID"},
            },
            "required": ["lead_id"],
        },
    },
    {
        "name": "create_lead",
        "description": "Create a new CRM lead/opportunity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Opportunity name"},
                "partner_name": {"type": "string", "description": "Company name"},
                "email": {"type": "string", "description": "Contact email"},
                "phone": {"type": "string", "description": "Contact phone"},
                "expected_revenue": {"type": "number", "description": "Expected deal value"},
                "description": {"type": "string", "description": "Notes/description"},
            },
            "required": ["name", "partner_name"],
        },
    },
    {
        "name": "move_lead_stage",
        "description": "Move a lead to a different pipeline stage (e.g., 'Qualified', 'Proposal Sent', 'Won').",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "integer", "description": "Lead ID"},
                "stage_name": {"type": "string", "description": "Target stage name"},
            },
            "required": ["lead_id", "stage_name"],
        },
    },
    {
        "name": "pipeline_summary",
        "description": "Get a summary of the entire CRM pipeline — leads per stage, revenue totals.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_contacts",
        "description": "Search contacts and companies by name or email.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term"},
                "limit": {"type": "integer", "description": "Max results", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "create_contact",
        "description": "Create a new contact or company in Odoo.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Contact/company name"},
                "email": {"type": "string", "description": "Email address"},
                "phone": {"type": "string", "description": "Phone number"},
                "is_company": {"type": "boolean", "description": "True for company, false for individual", "default": True},
                "comment": {"type": "string", "description": "Internal notes"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "list_quotations",
        "description": "List sales quotations/orders. Filter by partner or state.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "partner_id": {"type": "integer", "description": "Filter by contact ID"},
                "state": {"type": "string", "description": "Filter by state (draft, sent, sale, cancel)"},
                "limit": {"type": "integer", "description": "Max results", "default": 10},
            },
        },
    },
    {
        "name": "list_invoices",
        "description": "List invoices. Filter by partner or state.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "partner_id": {"type": "integer", "description": "Filter by contact ID"},
                "state": {"type": "string", "description": "Filter by state (draft, posted)"},
                "limit": {"type": "integer", "description": "Max results", "default": 10},
            },
        },
    },
    {
        "name": "list_projects",
        "description": "List all projects with task counts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max results", "default": 10},
            },
        },
    },
    {
        "name": "log_note",
        "description": "Add a note to any record's chatter (leads, contacts, invoices, etc.).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Odoo model (e.g., 'crm.lead', 'res.partner', 'account.move')",
                },
                "record_id": {"type": "integer", "description": "Record ID"},
                "message": {"type": "string", "description": "Note content (HTML supported)"},
            },
            "required": ["model", "record_id", "message"],
        },
    },
]


def handle_request(odoo, method, params):
    """Handle incoming MCP JSON-RPC request."""

    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "odoo-crm", "version": "1.0.0"},
        }

    if method == "tools/list":
        return {"tools": TOOLS}

    if method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments", {})

        try:
            if tool_name == "search_leads":
                result = odoo.search_leads(args.get("query", ""), args.get("stage"), args.get("limit", 20))
            elif tool_name == "get_lead":
                result = odoo.get_lead(args["lead_id"])
            elif tool_name == "create_lead":
                result = odoo.create_lead(**args)
            elif tool_name == "move_lead_stage":
                result = odoo.move_lead_stage(args["lead_id"], args["stage_name"])
            elif tool_name == "pipeline_summary":
                result = odoo.get_pipeline_summary()
            elif tool_name == "search_contacts":
                result = odoo.search_contacts(args["query"], args.get("limit", 10))
            elif tool_name == "create_contact":
                result = odoo.create_contact(**args)
            elif tool_name == "list_quotations":
                result = odoo.get_quotations(args.get("partner_id"), args.get("state"), args.get("limit", 10))
            elif tool_name == "list_invoices":
                result = odoo.get_invoices(args.get("partner_id"), args.get("state"), args.get("limit", 10))
            elif tool_name == "list_projects":
                result = odoo.get_projects(args.get("limit", 10))
            elif tool_name == "log_note":
                result = odoo.log_note(args["model"], args["record_id"], args["message"])
            else:
                return {"content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}], "isError": True}

            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2, default=str),
                    }
                ]
            }
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    if method == "notifications/initialized":
        return None  # No response needed

    return {"error": {"code": -32601, "message": f"Unknown method: {method}"}}


def main():
    """Main MCP server loop."""
    odoo = OdooCRM()
    sys.stderr.write(f"Odoo CRM MCP Server connected (uid={odoo.uid})\n")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = request.get("method", "")
        params = request.get("params", {})
        request_id = request.get("id")

        result = handle_request(odoo, method, params)

        if result is None:
            continue  # Notification, no response needed

        response = {"jsonrpc": "2.0", "id": request_id}
        if "error" in result:
            response["error"] = result["error"]
        else:
            response["result"] = result

        write_message(response)


if __name__ == "__main__":
    main()
