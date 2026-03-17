"""Tool: create a new order (sales quote) in Business Central (shop agent)."""

import requests
from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
from ibm_watsonx_orchestrate.run.context import AgentRun

MY_APP_ID = "business_central_wa"
COMPANY_ID = "572323a2-e013-f111-8405-7ced8d42f5ae"


@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    name="shop_create_order",
    description="Create a new order in Business Central. Pass customer_id from shop_identify_customer, plus item IDs and quantities from shop_get_products.",
)
def shop_create_order(
    context: AgentRun,
    customer_id: str,
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
    note: str = "",
) -> dict:
    """Create an order (draft sales quote) in Microsoft Dynamics 365 Business Central.

    Args:
        context: Agent run context (auto-filled).
        customer_id: Customer GUID from shop_identify_customer.
        item_id_1: GUID of the first item (required).
        quantity_1: Quantity for the first item (must be > 0).
        item_id_2: GUID of the second item (optional).
        quantity_2: Quantity for the second item.
        item_id_3: GUID of the third item (optional).
        quantity_3: Quantity for the third item.
        item_id_4: GUID of the fourth item (optional).
        quantity_4: Quantity for the fourth item.
        item_id_5: GUID of the fifth item (optional).
        quantity_5: Quantity for the fifth item.
        item_id_6: GUID of the sixth item (optional).
        quantity_6: Quantity for the sixth item.
        item_id_7: GUID of the seventh item (optional).
        quantity_7: Quantity for the seventh item.
        item_id_8: GUID of the eighth item (optional).
        quantity_8: Quantity for the eighth item.
        item_id_9: GUID of the ninth item (optional).
        quantity_9: Quantity for the ninth item.
        item_id_10: GUID of the tenth item (optional).
        quantity_10: Quantity for the tenth item.
        note: Optional note added as a Comment line (max 100 chars).

    Returns:
        dict: Keys: success, reference_number, customer_name, lines, total.
    """
    if not customer_id:
        return {"error": "customer_id is required. Call shop_identify_customer first."}

    if not item_id_1 or quantity_1 <= 0:
        raise ValueError("item_id_1 must be provided and quantity_1 must be > 0")

    conn = connections.oauth2_client_creds(MY_APP_ID)
    base = conn.url
    headers = {
        "Authorization": f"Bearer {conn.access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    # --- Build lines list ---
    lines = [
        (item_id_1, quantity_1), (item_id_2, quantity_2), (item_id_3, quantity_3),
        (item_id_4, quantity_4), (item_id_5, quantity_5), (item_id_6, quantity_6),
        (item_id_7, quantity_7), (item_id_8, quantity_8), (item_id_9, quantity_9),
        (item_id_10, quantity_10),
    ]

    # Tag the external document number for tracking
    ext_doc_number = "SHOP-ORDER"[:35]

    # --- Create the quote header ---
    resp = requests.post(
        f"{base}/companies({COMPANY_ID})/salesQuotes",
        headers=headers, json={"customerId": customer_id}, timeout=30,
    )
    if not resp.ok:
        return {"error": f"Failed to create order: {resp.status_code}", "detail": resp.text}
    quote = resp.json()
    quote_id = quote["id"]
    quote_number = quote.get("number", "")
    customer_name = quote.get("customerName", "")
    etag = resp.headers.get("ETag", quote.get("@odata.etag", ""))

    # --- Patch the external document number ---
    patch_headers = {**headers, "If-Match": etag}
    requests.patch(
        f"{base}/companies({COMPANY_ID})/salesQuotes({quote_id})",
        headers=patch_headers, json={"externalDocumentNumber": ext_doc_number}, timeout=30,
    )

    # --- Add item lines ---
    for item_id, qty in lines:
        if item_id and qty > 0:
            r = requests.post(
                f"{base}/companies({COMPANY_ID})/salesQuotes({quote_id})/salesQuoteLines",
                headers=headers, json={"lineType": "Item", "itemId": item_id, "quantity": qty}, timeout=30,
            )
            if not r.ok:
                return {"error": f"Failed to add line for item {item_id}: {r.status_code}", "detail": r.text}

    # --- Add a Comment line for the note ---
    note_text = (note or "").strip()[:100]
    if note_text:
        requests.post(
            f"{base}/companies({COMPANY_ID})/salesQuotes({quote_id})/salesQuoteLines",
            headers=headers, json={"lineType": "Comment", "description": note_text}, timeout=30,
        )

    # --- Read back the quote ---
    quote_resp = requests.get(f"{base}/companies({COMPANY_ID})/salesQuotes({quote_id})", headers=headers, timeout=30)
    total = quote_resp.json().get("totalAmountExcludingTax", 0) if quote_resp.ok else 0.0

    order_lines = []
    lines_resp = requests.get(
        f"{base}/companies({COMPANY_ID})/salesQuotes({quote_id})/salesQuoteLines", headers=headers, timeout=30,
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
        "success": True,
        "reference_number": quote_number,
        "customer_name": customer_name,
        "lines": order_lines,
        "total": round(total, 2),
    }
