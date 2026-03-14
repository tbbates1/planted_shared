import re
from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
from ibm_watsonx_orchestrate.run.context import AgentRun
import requests

MY_APP_ID = "business_central_wa"
COMPANY_ID = "572323a2-e013-f111-8405-7ced8d42f5ae"


def _normalize_phone(phone: str) -> str:
    phone = re.sub(r"[\s\-\(\)]", "", phone)
    if phone.startswith("00"):
        phone = "+" + phone[2:]
    return phone


def _lookup_customer_by_phone(base: str, headers: dict, phone: str) -> dict | None:
    """Find a customer by matching their phone number."""
    caller_phone = _normalize_phone(phone)
    url = (
        f"{base}/companies({COMPANY_ID})/customers"
        f"?$select=id,number,displayName,phoneNumber"
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

    for c in customers:
        bc_phone = _normalize_phone(c.get("phoneNumber", ""))
        if bc_phone and bc_phone == caller_phone:
            return c
    return None


@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    name="wa_get_my_orders",
    description="Get recent order history for the current WhatsApp caller. The customer is identified automatically. Only works for verified callers with an account.",
)
def wa_get_my_orders(context: AgentRun, limit: int = 1) -> list[dict]:
    """Fetch recent orders for the current WhatsApp caller.

    The customer is resolved automatically. Only works for verified callers.

    Args:
        context (AgentRun): The agent run context (auto-filled by runtime).
        limit (int): Number of recent orders to return (default 1, max 5).

    Returns:
        list[dict]: Recent orders with keys: date, lines, total.
    """
    limit = max(1, min(limit, 5))

    conn = connections.oauth2_client_creds(MY_APP_ID)
    base = conn.url
    access_token = conn.access_token
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

    # Resolve customer from WhatsApp phone number
    req_context = context.request_context
    channel = req_context.get("channel", {})
    phone = channel.get("whatsapp", {}).get("user_phone_number", "")

    if not phone:
        return [{"error": "No phone number found in context."}]

    customer = _lookup_customer_by_phone(base, headers, phone)
    if not customer:
        return [{"error": "No account found for this phone number."}]

    customer_id = customer["id"]

    results = []

    # Fetch salesQuotes (editable — not yet processed)
    sq_url = (
        f"{base}/companies({COMPANY_ID})/salesQuotes"
        f"?$filter=customerId eq {customer_id}"
        f"&$orderby=documentDate desc"
        f"&$top={limit}"
    )
    sq_resp = requests.get(sq_url, headers=headers, timeout=30)
    sq_resp.raise_for_status()
    for quote in sq_resp.json().get("value", []):
        lines_url = f"{base}/companies({COMPANY_ID})/salesQuotes({quote['id']})/salesQuoteLines"
        lines_resp = requests.get(lines_url, headers=headers, timeout=30)
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

    # Fetch salesOrders (not editable — already processed)
    so_url = (
        f"{base}/companies({COMPANY_ID})/salesOrders"
        f"?$filter=customerId eq {customer_id}"
        f"&$orderby=orderDate desc"
        f"&$top={limit}"
    )
    so_resp = requests.get(so_url, headers=headers, timeout=30)
    so_resp.raise_for_status()
    for order in so_resp.json().get("value", []):
        lines_url = f"{base}/companies({COMPANY_ID})/salesOrders({order['id']})/salesOrderLines"
        lines_resp = requests.get(lines_url, headers=headers, timeout=30)
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

    # Sort by date descending, return up to limit
    results.sort(key=lambda r: r["date"], reverse=True)
    return results[:limit]
