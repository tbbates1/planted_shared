"""Tool: cancel (delete) a pending sales quote by reference number (email channel)."""

import requests
from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
from ibm_watsonx_orchestrate.run.context import AgentRun

MY_APP_ID = "business_central_wa"
COMPANY_ID = "572323a2-e013-f111-8405-7ced8d42f5ae"


@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    name="em_cancel_quote",
    description="Cancel a pending order by reference number (SQ####). Pass customer_id from the [VERIFIED] tag. Shipped orders (SO) cannot be cancelled.",
)
def em_cancel_quote(context: AgentRun, customer_id: str, quote_number: str) -> dict:
    """Cancel a pending sales quote.

    Args:
        context: Agent run context (auto-filled).
        customer_id: Customer GUID from the [VERIFIED] tag.
        quote_number: The SQ reference number (e.g. SQ0006).
    """
    if not customer_id:
        return {"error": "customer_id is required. Pass it from the [VERIFIED] tag."}

    if not quote_number:
        return {"error": "quote_number is required."}

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

    # Delete the quote
    del_headers = {**headers, "If-Match": quote.get("@odata.etag", "")}
    del_resp = requests.delete(
        f"{base}/companies({COMPANY_ID})/salesQuotes({quote['id']})",
        headers=del_headers, timeout=30,
    )
    if not del_resp.ok:
        return {"error": f"Failed to cancel: {del_resp.status_code}"}

    return {"success": True, "message": f"Order {quote_number} has been cancelled."}
