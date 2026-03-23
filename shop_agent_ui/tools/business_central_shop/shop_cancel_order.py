"""Tool: cancel (delete) a pending sales quote by reference number (shop agent)."""

import requests
from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
from ibm_watsonx_orchestrate.run.context import AgentRun

MY_APP_ID = "business_central_timothy"
COMPANY_ID = "572323a2-e013-f111-8405-7ced8d42f5ae"


@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    name="shop_cancel_order",
    description="Cancel a pending order by reference number (SQ####). Shipped orders (SO) cannot be cancelled. Returns the cancelled order details. Pass customer_id from shop_identify_customer.",
)
def shop_cancel_order(context: AgentRun, customer_id: str, quote_number: str) -> dict:
    """Cancel a pending sales quote. Returns order details before deletion.

    Args:
        context: Agent run context (auto-filled).
        customer_id: Customer GUID from shop_identify_customer.
        quote_number: The SQ reference number (e.g. SQ0006).

    Returns:
        dict: Keys: success, message, lines, total (on success) or error (on failure).
    """
    if not customer_id:
        return {"error": "customer_id is required. Call shop_identify_customer first."}

    if not quote_number:
        return {"error": "quote_number is required. Ask the customer which order to cancel."}

    conn = connections.oauth2_client_creds(MY_APP_ID)
    base = conn.url
    headers = {
        "Authorization": f"Bearer {conn.access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    # Sanitize
    quote_number = quote_number.strip().replace("'", "")

    # Find the quote
    resp = requests.get(
        f"{base}/companies({COMPANY_ID})/salesQuotes?$filter=number eq '{quote_number}'&$top=1",
        headers=headers, timeout=30,
    )
    resp.raise_for_status()
    quotes = resp.json().get("value", [])

    if not quotes:
        # Check if it's a shipped order
        so_resp = requests.get(
            f"{base}/companies({COMPANY_ID})/salesOrders?$filter=number eq '{quote_number}'&$top=1",
            headers=headers, timeout=30,
        )
        so_resp.raise_for_status()
        if so_resp.json().get("value", []):
            return {"error": "This order has been shipped and cannot be cancelled."}
        return {"error": f"Order {quote_number} not found."}

    quote = quotes[0]
    if quote.get("customerId") != customer_id:
        return {"error": "This order does not belong to your account."}

    quote_id = quote["id"]

    # Fetch order lines before deletion so we can report what was cancelled
    cancelled_lines = []
    cancelled_total = 0.0
    lines_resp = requests.get(
        f"{base}/companies({COMPANY_ID})/salesQuotes({quote_id})/salesQuoteLines",
        headers=headers, timeout=30,
    )
    if lines_resp.ok:
        for ln in lines_resp.json().get("value", []):
            if ln.get("lineType") == "Item":
                amount = ln.get("amountExcludingTax", 0)
                cancelled_total += amount
                cancelled_lines.append({
                    "description": ln.get("description", ""),
                    "quantity": ln.get("quantity", 0),
                    "unitPrice": ln.get("unitPrice", 0),
                    "lineAmount": amount,
                })

    # Delete the quote
    del_headers = {**headers, "If-Match": quote.get("@odata.etag", "")}
    del_resp = requests.delete(
        f"{base}/companies({COMPANY_ID})/salesQuotes({quote_id})",
        headers=del_headers, timeout=30,
    )
    if not del_resp.ok:
        return {"error": f"Failed to cancel: {del_resp.status_code}"}

    return {
        "success": True,
        "message": f"Order {quote_number} has been cancelled.",
        "lines": cancelled_lines,
        "total": round(cancelled_total, 2),
    }
