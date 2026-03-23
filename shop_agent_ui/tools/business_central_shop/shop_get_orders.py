"""Tool: get order history for a customer (shop agent)."""

import requests
from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
from ibm_watsonx_orchestrate.run.context import AgentRun

MY_APP_ID = "business_central_timothy"
COMPANY_ID = "572323a2-e013-f111-8405-7ced8d42f5ae"


@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    name="shop_get_orders",
    description="Get recent order history for a customer. Returns shipped orders and pending orders. Pass customer_id from shop_identify_customer.",
)
def shop_get_orders(context: AgentRun, customer_id: str, limit: int = 50) -> dict:
    """Fetch recent orders for the customer, both pending (editable) and shipped.

    Args:
        context: Agent run context (auto-filled).
        customer_id: Customer GUID from shop_identify_customer.
        limit: Number of recent orders to return per type (default 50, max 50).

    Returns:
        dict: Keys: shipped (list), pending (list). Each order has reference_number, date, lines, total, editable.
    """
    if not customer_id:
        return {"error": "customer_id is required. Call shop_identify_customer first."}

    limit = max(1, min(limit, 50))

    conn = connections.oauth2_client_creds(MY_APP_ID)
    base = conn.url
    headers = {"Authorization": f"Bearer {conn.access_token}", "Accept": "application/json"}

    shipped = []
    pending = []

    # Fetch salesQuotes (pending / editable)
    sq_resp = requests.get(
        f"{base}/companies({COMPANY_ID})/salesQuotes"
        f"?$filter=customerId eq {customer_id}&$orderby=documentDate desc&$top={limit}",
        headers=headers, timeout=30,
    )
    sq_resp.raise_for_status()
    for quote in sq_resp.json().get("value", []):
        lines_resp = requests.get(
            f"{base}/companies({COMPANY_ID})/salesQuotes({quote['id']})/salesQuoteLines",
            headers=headers, timeout=30,
        )
        lines_resp.raise_for_status()
        item_lines = []
        total = 0.0
        for ln in lines_resp.json().get("value", []):
            if ln.get("lineType") == "Item":
                amount = ln.get("amountExcludingTax", 0)
                total += amount
                item_lines.append({
                    "description": ln.get("description", ""),
                    "quantity": ln.get("quantity", 0),
                    "unitPrice": ln.get("unitPrice", 0),
                    "lineAmount": amount,
                })
        if item_lines:
            pending.append({
                "reference_number": quote.get("number", ""),
                "date": quote.get("documentDate", ""),
                "lines": item_lines,
                "total": round(total, 2),
                "editable": True,
            })

    # Fetch salesOrders (shipped / not editable)
    so_resp = requests.get(
        f"{base}/companies({COMPANY_ID})/salesOrders"
        f"?$filter=customerId eq {customer_id}&$orderby=orderDate desc&$top={limit}",
        headers=headers, timeout=30,
    )
    so_resp.raise_for_status()
    for order in so_resp.json().get("value", []):
        lines_resp = requests.get(
            f"{base}/companies({COMPANY_ID})/salesOrders({order['id']})/salesOrderLines",
            headers=headers, timeout=30,
        )
        lines_resp.raise_for_status()
        item_lines = []
        total = 0.0
        for ln in lines_resp.json().get("value", []):
            if ln.get("lineType") == "Item":
                amount = ln.get("amountExcludingTax", 0)
                total += amount
                item_lines.append({
                    "description": ln.get("description", ""),
                    "quantity": ln.get("quantity", 0),
                    "unitPrice": ln.get("unitPrice", 0),
                    "lineAmount": amount,
                })
        if item_lines:
            shipped.append({
                "reference_number": order.get("number", ""),
                "date": order.get("orderDate", ""),
                "lines": item_lines,
                "total": round(total, 2),
                "editable": False,
            })

    return {"shipped": shipped, "pending": pending}
