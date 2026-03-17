"""Tool: modify an existing pending order (sales quote) in Business Central (shop agent)."""

import requests
from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
from ibm_watsonx_orchestrate.run.context import AgentRun

MY_APP_ID = "business_central_wa"
COMPANY_ID = "572323a2-e013-f111-8405-7ced8d42f5ae"


@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    name="shop_modify_order",
    description="Modify an existing pending order by reference number. Replaces ALL items on the order — include every item the order should have after changes. Pass customer_id from shop_identify_customer.",
)
def shop_modify_order(
    context: AgentRun,
    customer_id: str,
    reference_number: str,
    item_id_1: str,
    quantity_1: float,
    item_id_2: str = "",
    quantity_2: float = 0,
    item_id_3: str = "",
    quantity_3: float = 0,
    item_id_4: str = "",
    quantity_4: float = 0,
    item_id_5: str = "",
    quantity_5: float = 0,
    item_id_6: str = "",
    quantity_6: float = 0,
    item_id_7: str = "",
    quantity_7: float = 0,
    item_id_8: str = "",
    quantity_8: float = 0,
    item_id_9: str = "",
    quantity_9: float = 0,
    item_id_10: str = "",
    quantity_10: float = 0,
) -> dict:
    """Modify an existing order (sales quote) in Business Central.

    REPLACES all items. Include every item the order should have after the change.

    Args:
        context: Agent run context (auto-filled).
        customer_id: Customer GUID from shop_identify_customer.
        reference_number: The order reference number (e.g. SQ0005).
        item_id_1: GUID of the first item (required).
        quantity_1: Quantity for the first item (must be > 0).
        item_id_2-10: Optional additional items and quantities.

    Returns:
        dict: Keys: success, reference_number, customer_name, lines, total.
    """
    if not customer_id:
        return {"error": "customer_id is required. Call shop_identify_customer first."}

    if not reference_number:
        return {"error": "reference_number is required. Ask the customer which order to modify."}

    if not item_id_1 or quantity_1 <= 0:
        raise ValueError("item_id_1 must be provided and quantity_1 must be > 0")

    conn = connections.oauth2_client_creds(MY_APP_ID)
    base = conn.url
    headers = {
        "Authorization": f"Bearer {conn.access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    # --- Find the quote ---
    reference_number = reference_number.strip().replace("'", "")
    resp = requests.get(
        f"{base}/companies({COMPANY_ID})/salesQuotes?$filter=number eq '{reference_number}'&$top=1",
        headers=headers, timeout=30,
    )
    resp.raise_for_status()
    quotes = resp.json().get("value", [])

    if not quotes:
        so_resp = requests.get(
            f"{base}/companies({COMPANY_ID})/salesOrders?$filter=number eq '{reference_number}'&$top=1",
            headers=headers, timeout=30,
        )
        so_resp.raise_for_status()
        if so_resp.json().get("value", []):
            return {"error": "This order has already been shipped and can no longer be modified."}
        return {"error": f"Order {reference_number} not found."}

    quote = quotes[0]
    quote_id = quote["id"]
    customer_name = quote.get("customerName", "")

    if quote.get("customerId") != customer_id:
        return {"error": "This order does not belong to your account."}

    # --- Delete existing item lines ---
    lines_url = f"{base}/companies({COMPANY_ID})/salesQuotes({quote_id})/salesQuoteLines"
    lines_resp = requests.get(lines_url, headers=headers, timeout=30)
    lines_resp.raise_for_status()
    for ln in lines_resp.json().get("value", []):
        if ln.get("lineType") == "Item":
            del_headers = {**headers, "If-Match": ln.get("@odata.etag", "")}
            requests.delete(f"{lines_url}({ln['id']})", headers=del_headers, timeout=30)

    # --- Add new item lines ---
    new_lines = [
        (item_id_1, quantity_1), (item_id_2, quantity_2), (item_id_3, quantity_3),
        (item_id_4, quantity_4), (item_id_5, quantity_5), (item_id_6, quantity_6),
        (item_id_7, quantity_7), (item_id_8, quantity_8), (item_id_9, quantity_9),
        (item_id_10, quantity_10),
    ]
    for item_id, qty in new_lines:
        if item_id and qty > 0:
            r = requests.post(
                lines_url, headers=headers,
                json={"lineType": "Item", "itemId": item_id, "quantity": qty}, timeout=30,
            )
            if not r.ok:
                return {"error": f"Failed to add item: {r.status_code}", "detail": r.text}

    # --- Read back ---
    quote_resp = requests.get(f"{base}/companies({COMPANY_ID})/salesQuotes({quote_id})", headers=headers, timeout=30)
    total = quote_resp.json().get("totalAmountExcludingTax", 0) if quote_resp.ok else 0.0

    order_lines = []
    lines_resp = requests.get(lines_url, headers=headers, timeout=30)
    if lines_resp.ok:
        for ln in lines_resp.json().get("value", []):
            if ln.get("lineType") == "Item":
                order_lines.append({
                    "description": ln.get("description", ""),
                    "quantity": ln.get("quantity", 0),
                    "unitPrice": ln.get("unitPrice", 0),
                    "lineAmount": ln.get("amountExcludingTax", 0),
                })

    return {
        "success": True,
        "reference_number": reference_number,
        "customer_name": customer_name,
        "lines": order_lines,
        "total": round(total, 2),
    }
