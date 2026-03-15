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
    name="wa_cancel_order",
    description="Cancel and delete an order by reference number. Only for verified callers. The customer is identified automatically from context.",
)
def wa_cancel_order(
    context: AgentRun,
    reference_number: str,
) -> dict:
    """Cancel and delete an order (sales quote) in Business Central.

    The customer is resolved from the customer_id context variable. Only verified
    callers can cancel orders, and only their own orders.

    Args:
        context (AgentRun): The agent run context (auto-filled by runtime).
        reference_number (str): The order reference number (e.g. SQ0005).

    Returns:
        dict: Keys: success, message.
    """
    if not reference_number:
        raise ValueError("reference_number is required")

    conn = connections.oauth2_client_creds(MY_APP_ID)
    base = conn.url
    headers = {
        "Authorization": f"Bearer {conn.access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    caller = resolve_customer(context, base, conn.access_token)
    customer_id = caller["customer_id"]
    verified = caller["verified"]

    if verified != 1 or not customer_id:
        return {"error": "Only verified customers can cancel orders."}

    # Find the quote
    resp = requests.get(
        f"{base}/companies({COMPANY_ID})/salesQuotes"
        f"?$filter=number eq '{reference_number}'&$top=1",
        headers=headers, timeout=30,
    )
    resp.raise_for_status()
    quotes = resp.json().get("value", [])

    if not quotes:
        so_resp = requests.get(
            f"{base}/companies({COMPANY_ID})/salesOrders"
            f"?$filter=number eq '{reference_number}'&$top=1",
            headers=headers, timeout=30,
        )
        so_resp.raise_for_status()
        if so_resp.json().get("value", []):
            return {"error": "This order has already been processed and can no longer be cancelled."}
        return {"error": f"Order {reference_number} not found."}

    quote = quotes[0]
    quote_id = quote["id"]
    etag = quote.get("@odata.etag", "")

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
        "message": f"Order {reference_number} has been cancelled and deleted.",
    }
