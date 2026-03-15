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
    name="wa_modify_order",
    description="Modify an existing order for a verified caller. The customer is identified automatically from context. Replaces all items on the order.",
)
def wa_modify_order(
    context: AgentRun,
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

    The customer is resolved from the customer_id context variable. Only verified
    callers can modify orders, and only their own orders.

    Args:
        context (AgentRun): The agent run context (auto-filled by runtime).
        reference_number (str): The order reference number (e.g. SQ0005).
        item_id_1 (str): GUID of the first item (required).
        quantity_1 (float): Quantity for the first item (must be > 0).
        item_id_2 (str): GUID of the second item (optional).
        quantity_2 (float): Quantity for the second item.
        item_id_3 (str): GUID of the third item (optional).
        quantity_3 (float): Quantity for the third item.
        item_id_4 (str): GUID of the fourth item (optional).
        quantity_4 (float): Quantity for the fourth item.
        item_id_5 (str): GUID of the fifth item (optional).
        quantity_5 (float): Quantity for the fifth item.
        item_id_6 (str): GUID of the sixth item (optional).
        quantity_6 (float): Quantity for the sixth item.
        item_id_7 (str): GUID of the seventh item (optional).
        quantity_7 (float): Quantity for the seventh item.
        item_id_8 (str): GUID of the eighth item (optional).
        quantity_8 (float): Quantity for the eighth item.
        item_id_9 (str): GUID of the ninth item (optional).
        quantity_9 (float): Quantity for the ninth item.
        item_id_10 (str): GUID of the tenth item (optional).
        quantity_10 (float): Quantity for the tenth item.

    Returns:
        dict: Keys: success, reference_number, customer_name, lines, total.
    """
    if not item_id_1 or quantity_1 <= 0:
        raise ValueError("item_id_1 must be provided and quantity_1 must be > 0")

    conn = connections.oauth2_client_creds(MY_APP_ID)
    base = conn.url
    headers = {
        "Authorization": f"Bearer {conn.access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    # --- Resolve customer from channel phone number ---
    caller = resolve_customer(context, base, conn.access_token)
    customer_id = caller["customer_id"]
    verified = caller["verified"]

    if verified != 1 or not customer_id:
        return {"error": "Only verified customers can modify orders."}

    # Sanitize reference number
    reference_number = reference_number.strip().replace("'", "")

    # --- Find the quote ---
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
            return {"error": "This order has already been processed and can no longer be modified."}
        return {"error": f"Order {reference_number} not found."}

    quote = quotes[0]
    quote_id = quote["id"]
    customer_name = quote.get("customerName", "")

    if quote.get("customerId") != customer_id:
        return {"error": "You can only modify your own orders."}

    # --- Delete existing item lines ---
    lines_url = f"{base}/companies({COMPANY_ID})/salesQuotes({quote_id})/salesQuoteLines"
    lines_resp = requests.get(lines_url, headers=headers, timeout=30)
    lines_resp.raise_for_status()
    for ln in lines_resp.json().get("value", []):
        if ln.get("lineType") == "Item":
            del_headers = {**headers, "If-Match": ln.get("@odata.etag", "")}
            del_resp = requests.delete(f"{lines_url}({ln['id']})", headers=del_headers, timeout=30)
            if not del_resp.ok:
                return {"error": f"Failed to remove existing item: {del_resp.status_code}", "detail": del_resp.text}

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
