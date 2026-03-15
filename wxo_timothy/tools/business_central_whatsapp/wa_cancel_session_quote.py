from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
from ibm_watsonx_orchestrate.run.context import AgentRun
import requests

from _resolve_customer import resolve_customer

MY_APP_ID = "business_central_wa"
COMPANY_ID = "572323a2-e013-f111-8405-7ced8d42f5ae"


@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    name="wa_cancel_session_quote",
    description="Cancel and delete the order created in this conversation. The order is identified automatically from context — no reference number needed. Use this for unverified callers who want to cancel their current order.",
)
def wa_cancel_session_quote(
    context: AgentRun,
) -> dict:
    """Cancel and delete the session quote (the order created in this conversation).

    The quote is identified from the session_quote_id context variable set by
    the pre-invoke plugin. No reference number is passed — only the current
    session quote can be cancelled.

    Args:
        context (AgentRun): The agent run context (auto-filled by runtime).

    Returns:
        dict: Keys: success, message.
    """
    conn = connections.oauth2_client_creds(MY_APP_ID)
    base = conn.url
    headers = {
        "Authorization": f"Bearer {conn.access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    caller = resolve_customer(context, base, conn.access_token)
    customer_id = caller["customer_id"]
    session_quote_id = caller["session_quote_id"]

    if not session_quote_id:
        return {"error": "No order found for this session. Nothing to cancel."}

    if not customer_id:
        return {"error": "Could not identify customer."}

    # Find the session quote
    resp = requests.get(
        f"{base}/companies({COMPANY_ID})/salesQuotes"
        f"?$filter=number eq '{session_quote_id}'&$top=1",
        headers=headers, timeout=30,
    )
    resp.raise_for_status()
    quotes = resp.json().get("value", [])

    if not quotes:
        so_resp = requests.get(
            f"{base}/companies({COMPANY_ID})/salesOrders"
            f"?$filter=number eq '{session_quote_id}'&$top=1",
            headers=headers, timeout=30,
        )
        so_resp.raise_for_status()
        if so_resp.json().get("value", []):
            return {"error": "This order has already been processed and can no longer be cancelled."}
        return {"error": "Order not found. It may have already been removed."}

    quote = quotes[0]
    quote_id = quote["id"]
    etag = quote.get("@odata.etag", "")

    # Verify this quote belongs to the caller's customer
    if quote.get("customerId") != customer_id:
        return {"error": "You can only cancel your own orders."}

    # Delete the quote
    del_headers = {**headers, "If-Match": etag}
    del_resp = requests.delete(
        f"{base}/companies({COMPANY_ID})/salesQuotes({quote_id})",
        headers=del_headers, timeout=30,
    )
    if not del_resp.ok:
        return {"error": f"Failed to cancel order: {del_resp.status_code}", "detail": del_resp.text}

    return {
        "success": True,
        "message": f"Order {session_quote_id} has been cancelled and deleted.",
    }
