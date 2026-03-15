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
    name="wa_create_sales_quote",
    description="Create an order in Business Central. The customer is identified automatically from context. Just pass items and quantities.",
)
def wa_create_sales_quote(
    context: AgentRun,
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
    business_name: str = "",
    contact_name: str = "",
    delivery_address: str = "",
) -> dict:
    """Create an order (draft sales quote) in Microsoft Dynamics 365 Business Central.

    The customer is resolved automatically from the customer_id context variable
    set by the pre-invoke plugin. For unverified callers, the order is placed under
    the generic 'Whatsapp Unverified' account (C0012).

    Args:
        context (AgentRun): The agent run context (auto-filled by runtime).
        original_message (str): The original WhatsApp message for reference.
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
        note (str): Optional delivery note (e.g. "leave at back door").
        business_name (str): Business name for shipping (unverified callers).
        contact_name (str): Contact person name for shipping (unverified callers).
        delivery_address (str): Delivery address for shipping (unverified callers).

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

    # --- Resolve customer from channel phone number ---
    caller = resolve_customer(context, base, access_token)
    customer_id = caller["customer_id"]
    verified = caller["verified"]
    phone_digits = caller["phone_digits"]

    if not customer_id:
        return {"error": "Could not identify customer. Please try again."}

    # --- Build lines list ---
    lines = [
        (item_id_1, quantity_1), (item_id_2, quantity_2), (item_id_3, quantity_3),
        (item_id_4, quantity_4), (item_id_5, quantity_5), (item_id_6, quantity_6),
        (item_id_7, quantity_7), (item_id_8, quantity_8), (item_id_9, quantity_9),
        (item_id_10, quantity_10),
    ]

    # Tag with caller phone for session quote tracking (unverified) or just verified prefix
    prefix = "WA-V:" if verified == 1 else f"WA-U:{phone_digits}:"
    msg = (original_message or "WhatsApp order").strip()
    ext_doc_number = f"{prefix}{msg}"[:35]

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

    # --- Patch quote header: external doc number + shipping info ---
    patch_data = {"externalDocumentNumber": ext_doc_number}

    # For unverified callers, set shipping fields from provided info
    if business_name:
        patch_data["shipToName"] = business_name.strip()[:100]
    if contact_name:
        patch_data["shipToContact"] = contact_name.strip()[:100]
    if delivery_address:
        patch_data["shipToAddressLine1"] = delivery_address.strip()[:100]
    if phone_digits:
        patch_data["phoneNumber"] = f"+{phone_digits}"
    patch_headers = {**headers, "If-Match": etag}
    patch_resp = requests.patch(
        f"{base}/companies({COMPANY_ID})/salesQuotes({quote_id})",
        headers=patch_headers, json=patch_data, timeout=30,
    )
    if patch_resp.ok:
        etag = patch_resp.headers.get("ETag", patch_resp.json().get("@odata.etag", etag))

    # --- Add item lines ---
    for item_id, qty in lines:
        if item_id and qty > 0:
            r = requests.post(
                f"{base}/companies({COMPANY_ID})/salesQuotes({quote_id})/salesQuoteLines",
                headers=headers, json={"lineType": "Item", "itemId": item_id, "quantity": qty}, timeout=30,
            )
            if not r.ok:
                return {"error": f"Failed to add line for item {item_id}: {r.status_code}", "detail": r.text}

    # --- Add optional delivery note as Comment line ---
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
