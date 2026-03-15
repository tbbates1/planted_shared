from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
from ibm_watsonx_orchestrate.run.context import AgentRun
import requests

MY_APP_ID = "business_central_wa"
COMPANY_ID = "572323a2-e013-f111-8405-7ced8d42f5ae"


@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    name="em_create_sales_quote",
    description="Create an order in Business Central. Pass customer_id from the [VERIFIED] tag, plus items and quantities.",
)
def em_create_sales_quote(
    context: AgentRun,
    customer_id: str,
    original_message: str,
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

    The customer is resolved automatically from the customer_id context variable
    set by the pre-invoke plugin.

    Args:
        context (AgentRun): The agent run context (auto-filled by runtime).
        original_message (str): The original email message for reference.
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
        note (str): Optional note added as a Comment line (max 100 chars).

    Returns:
        dict: Keys: success, reference_number, customer_name, lines, total.
    """
    if not item_id_1 or quantity_1 <= 0:
        raise ValueError("item_id_1 must be provided and quantity_1 must be > 0")

    conn = connections.oauth2_client_creds(MY_APP_ID)
    base = conn.url
    access_token = conn.access_token
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    # --- Validate customer_id (passed from [VERIFIED] tag) ---
    if not customer_id:
        return {"error": "customer_id is required. Pass it from the [VERIFIED] tag."}

    # --- Build lines list ---
    lines = [
        (item_id_1, quantity_1), (item_id_2, quantity_2), (item_id_3, quantity_3),
        (item_id_4, quantity_4), (item_id_5, quantity_5), (item_id_6, quantity_6),
        (item_id_7, quantity_7), (item_id_8, quantity_8), (item_id_9, quantity_9),
        (item_id_10, quantity_10),
    ]

    # Tag the external document number for tracking
    msg = (original_message or "Email order").strip()
    ext_doc_number = f"EM-V:{msg}"[:35]

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
