from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
from ibm_watsonx_orchestrate.run.context import AgentRun
import requests

MY_APP_ID = "business_central_wa"
COMPANY_ID = "572323a2-e013-f111-8405-7ced8d42f5ae"


@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    name="em_get_my_orders",
    description="Get recent order history. Pass customer_id from the [VERIFIED] tag.",
)
def em_get_my_orders(context: AgentRun, customer_id: str, limit: int = 1) -> list[dict]:
    """Fetch recent orders for the customer.

    Args:
        context (AgentRun): The agent run context (auto-filled by runtime).
        customer_id (str): Customer GUID from the [VERIFIED] tag.
        limit (int): Number of recent orders to return (default 1, max 5).

    Returns:
        list[dict]: Recent orders with keys: reference_number, date, lines, total, editable.
    """
    if not customer_id:
        return [{"error": "customer_id is required. Pass it from the [VERIFIED] tag."}]

    limit = max(1, min(limit, 5))

    conn = connections.oauth2_client_creds(MY_APP_ID)
    base = conn.url
    headers = {"Authorization": f"Bearer {conn.access_token}", "Accept": "application/json"}

    results = []

    # Fetch salesQuotes (editable)
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
            results.append({
                "reference_number": quote.get("number", ""),
                "date": quote.get("documentDate", ""),
                "lines": item_lines,
                "total": round(total, 2),
                "editable": True,
            })

    # Fetch salesOrders (not editable)
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
            results.append({
                "reference_number": order.get("number", ""),
                "date": order.get("orderDate", ""),
                "lines": item_lines,
                "total": round(total, 2),
                "editable": False,
            })

    results.sort(key=lambda r: r["date"], reverse=True)
    return results[:limit]
