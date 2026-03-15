"""Tool: get customer's last shipped order and all pending quotes."""

import requests
from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
from ibm_watsonx_orchestrate.run.context import AgentRun

MY_APP_ID = "business_central_wa"
COMPANY_ID = "572323a2-e013-f111-8405-7ced8d42f5ae"


def _get_lines(base: str, headers: dict, endpoint: str, record_id: str, lines_ep: str) -> list[dict]:
    resp = requests.get(f"{base}/companies({COMPANY_ID})/{endpoint}({record_id})/{lines_ep}", headers=headers, timeout=30)
    resp.raise_for_status()
    return [
        {"description": ln.get("description", ""), "quantity": ln.get("quantity", 0),
         "unitPrice": ln.get("unitPrice", 0), "lineAmount": ln.get("amountExcludingTax", 0)}
        for ln in resp.json().get("value", []) if ln.get("lineType") == "Item"
    ]


@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    name="wa_get_orders",
    description="Get the customer's last shipped order and all pending orders. Returns fresh data from Business Central.",
)
def wa_get_orders(context: AgentRun, customer_id: str) -> dict:
    """Get order history.

    Args:
        context: Agent run context (auto-filled).
        customer_id: Customer GUID from the [VERIFIED] tag.
    """
    if not customer_id:
        return {"error": "customer_id is required."}

    conn = connections.oauth2_client_creds(MY_APP_ID)
    base = conn.url
    headers = {"Authorization": f"Bearer {conn.access_token}", "Accept": "application/json"}

    result = {"last_shipped": None, "pending": []}

    # Last shipped order
    resp = requests.get(
        f"{base}/companies({COMPANY_ID})/salesOrders"
        f"?$filter=customerId eq {customer_id}&$orderby=orderDate desc&$top=1",
        headers=headers, timeout=30,
    )
    resp.raise_for_status()
    for o in resp.json().get("value", []):
        lines = _get_lines(base, headers, "salesOrders", o["id"], "salesOrderLines")
        if lines:
            result["last_shipped"] = {
                "number": o.get("number", ""), "date": o.get("orderDate", ""),
                "lines": lines, "total": round(sum(l["lineAmount"] for l in lines), 2),
            }

    # All pending quotes
    resp = requests.get(
        f"{base}/companies({COMPANY_ID})/salesQuotes"
        f"?$filter=customerId eq {customer_id}&$orderby=documentDate desc&$top=20",
        headers=headers, timeout=30,
    )
    resp.raise_for_status()
    for q in resp.json().get("value", []):
        lines = _get_lines(base, headers, "salesQuotes", q["id"], "salesQuoteLines")
        if lines:
            result["pending"].append({
                "number": q.get("number", ""), "date": q.get("documentDate", ""),
                "lines": lines, "total": round(sum(l["lineAmount"] for l in lines), 2),
            })

    return result
