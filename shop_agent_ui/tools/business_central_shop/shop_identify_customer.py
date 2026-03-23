"""Tool: identify a customer by email address for the shop agent."""

import requests
from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
from ibm_watsonx_orchestrate.run.context import AgentRun

MY_APP_ID = "business_central_timothy"
COMPANY_ID = "572323a2-e013-f111-8405-7ced8d42f5ae"


def _bc_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}


def _fetch_customers(base: str, headers: dict) -> list[dict]:
    """Fetch all customers from BC."""
    url = (
        f"{base}/companies({COMPANY_ID})/customers"
        f"?$select=id,displayName,email,phoneNumber"
        f"&$top=20000"
    )
    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()
    payload = resp.json()
    customers = payload.get("value", [])

    while "@odata.nextLink" in payload:
        resp = requests.get(payload["@odata.nextLink"], headers=headers, timeout=60)
        resp.raise_for_status()
        payload = resp.json()
        customers.extend(payload.get("value", []))

    return customers


def _fetch_lines(base: str, headers: dict, endpoint: str, record_id: str, lines_endpoint: str) -> list[dict]:
    """Fetch item lines for a sales quote or sales order."""
    url = f"{base}/companies({COMPANY_ID})/{endpoint}({record_id})/{lines_endpoint}"
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return [
        {
            "description": ln.get("description", ""),
            "quantity": ln.get("quantity", 0),
            "unitPrice": ln.get("unitPrice", 0),
            "lineAmount": ln.get("amountExcludingTax", 0),
        }
        for ln in resp.json().get("value", [])
        if ln.get("lineType") == "Item"
    ]


@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    name="shop_identify_customer",
    description="Identify a customer by their email address. Returns customer_id, business name, last shipped order, and pending orders. Call this FIRST before any other tool.",
)
def shop_identify_customer(context: AgentRun, email_address: str) -> dict:
    """Look up a customer in Business Central by email address.

    Args:
        context: Agent run context (auto-filled).
        email_address: Customer email address (e.g. "orders@migros.ch").

    Returns:
        dict: Keys: customer_id, business_name, last_shipped, pending_orders.
    """
    if not email_address or not email_address.strip():
        return {"error": "email_address is required. Ask the customer for their email address."}

    email_address = email_address.strip().lower()

    conn = connections.oauth2_client_creds(MY_APP_ID)
    base = conn.url
    headers = _bc_headers(conn.access_token)

    customers = _fetch_customers(base, headers)

    # Match by email (case-insensitive)
    customer = None
    for c in customers:
        bc_email = (c.get("email") or "").strip().lower()
        if bc_email and bc_email == email_address:
            customer = c
            break

    if not customer:
        return {
            "error": f"No customer found matching '{email_address}'. "
            "Please check the email address and try again.",
        }

    customer_id = customer["id"]
    business_name = customer["displayName"]

    # Fetch last shipped order
    last_shipped = None
    try:
        so_url = (
            f"{base}/companies({COMPANY_ID})/salesOrders"
            f"?$filter=customerId eq {customer_id}"
            f"&$orderby=orderDate desc"
            f"&$top=1"
        )
        resp = requests.get(so_url, headers=headers, timeout=30)
        resp.raise_for_status()
        orders = resp.json().get("value", [])
        if orders:
            order = orders[0]
            item_lines = _fetch_lines(base, headers, "salesOrders", order["id"], "salesOrderLines")
            if item_lines:
                total = sum(ln["lineAmount"] for ln in item_lines)
                last_shipped = {
                    "order_number": order.get("number", ""),
                    "date": order.get("orderDate", ""),
                    "lines": item_lines,
                    "total": round(total, 2),
                }
    except Exception:
        pass

    # Fetch pending quotes
    pending_orders = []
    try:
        sq_url = (
            f"{base}/companies({COMPANY_ID})/salesQuotes"
            f"?$filter=customerId eq {customer_id}"
            f"&$orderby=documentDate desc"
            f"&$top=50"
        )
        resp = requests.get(sq_url, headers=headers, timeout=30)
        resp.raise_for_status()
        for quote in resp.json().get("value", []):
            item_lines = _fetch_lines(base, headers, "salesQuotes", quote["id"], "salesQuoteLines")
            if item_lines:
                total = sum(ln["lineAmount"] for ln in item_lines)
                pending_orders.append({
                    "reference_number": quote.get("number", ""),
                    "date": quote.get("documentDate", ""),
                    "lines": item_lines,
                    "total": round(total, 2),
                })
    except Exception:
        pass

    return {
        "customer_id": customer_id,
        "business_name": business_name,
        "last_shipped": last_shipped,
        "pending_orders": pending_orders,
    }
