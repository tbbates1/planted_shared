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
    name="wa_preview_order",
    description="Preview an order with accurate pricing from Business Central including VAT. Creates a temporary quote, reads back totals, then deletes it. Use this BEFORE confirming with the customer.",
)
def wa_preview_order(
    context: AgentRun,
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
    """Preview an order with accurate pricing from Business Central.

    Creates a temporary sales quote to get BC-calculated totals including VAT,
    then immediately deletes it. No quote is kept — this is purely for preview.
    The customer is resolved from the customer_id context variable.

    Args:
        context (AgentRun): The agent run context (auto-filled by runtime).
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
        dict: Keys: subtotal, tax, total, customer_name, lines (with description, quantity, unitPrice, lineAmount).
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

    if not customer_id:
        return {"error": "Could not identify customer. Please try again."}

    # --- Build lines list ---
    lines = [
        (item_id_1, quantity_1), (item_id_2, quantity_2), (item_id_3, quantity_3),
        (item_id_4, quantity_4), (item_id_5, quantity_5), (item_id_6, quantity_6),
        (item_id_7, quantity_7), (item_id_8, quantity_8), (item_id_9, quantity_9),
        (item_id_10, quantity_10),
    ]

    # --- Create a temporary quote ---
    resp = requests.post(
        f"{base}/companies({COMPANY_ID})/salesQuotes",
        headers=headers, json={"customerId": customer_id}, timeout=30,
    )
    if not resp.ok:
        return {"error": f"Failed to create preview: {resp.status_code}", "detail": resp.text}

    quote = resp.json()
    quote_id = quote["id"]
    customer_name = quote.get("customerName", "")
    quote_etag = resp.headers.get("ETag", quote.get("@odata.etag", ""))

    try:
        # --- Add item lines ---
        for item_id, qty in lines:
            if item_id and qty > 0:
                r = requests.post(
                    f"{base}/companies({COMPANY_ID})/salesQuotes({quote_id})/salesQuoteLines",
                    headers=headers,
                    json={"lineType": "Item", "itemId": item_id, "quantity": qty},
                    timeout=30,
                )
                if not r.ok:
                    return {"error": f"Failed to add item {item_id}: {r.status_code}", "detail": r.text}

        # --- Read back the quote for BC-calculated totals ---
        quote_resp = requests.get(
            f"{base}/companies({COMPANY_ID})/salesQuotes({quote_id})",
            headers=headers, timeout=30,
        )
        subtotal = 0.0
        tax = 0.0
        total = 0.0
        if quote_resp.ok:
            q = quote_resp.json()
            subtotal = q.get("totalAmountExcludingTax", 0)
            tax = q.get("totalTaxAmount", 0)
            total = q.get("totalAmountIncludingTax", 0)
            quote_etag = quote_resp.headers.get("ETag", q.get("@odata.etag", quote_etag))

        # --- Read back lines with BC prices ---
        order_lines = []
        lines_resp = requests.get(
            f"{base}/companies({COMPANY_ID})/salesQuotes({quote_id})/salesQuoteLines",
            headers=headers, timeout=30,
        )
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
            "customer_name": customer_name,
            "lines": order_lines,
            "subtotal": round(subtotal, 2),
            "tax": round(tax, 2),
            "total": round(total, 2),
        }

    finally:
        # --- Always delete the temporary quote ---
        del_headers = {**headers, "If-Match": quote_etag}
        requests.delete(
            f"{base}/companies({COMPANY_ID})/salesQuotes({quote_id})",
            headers=del_headers, timeout=30,
        )
