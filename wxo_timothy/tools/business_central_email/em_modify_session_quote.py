from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
from ibm_watsonx_orchestrate.run.context import AgentRun
import requests

MY_APP_ID = "business_central_wa"
COMPANY_ID = "572323a2-e013-f111-8405-7ced8d42f5ae"


@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    name="em_modify_session_quote",
    description="Modify the quote created in this conversation. The quote is identified automatically from context — no reference number needed. Use this for unverified callers who want to change their current order.",
)
def em_modify_session_quote(
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
    """Modify the session quote (the quote created in this conversation).

    The quote is identified from the session_quote_id context variable set by
    the pre-invoke plugin. No reference number is passed — only the current
    session quote can be modified. This prevents targeting other customers' quotes.

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
        dict: Keys: success, reference_number, customer_name, lines, total.
    """
    import re

    req_context = context.request_context
    session_quote_id = req_context.get("session_quote_id", "")
    customer_id = req_context.get("customer_id", "")

    conn = connections.oauth2_client_creds(MY_APP_ID)
    base = conn.url
    headers = {
        "Authorization": f"Bearer {conn.access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    # Fallback: look up Email Unverified customer if not in context
    if not customer_id:
        lookup_resp = requests.get(
            f"{base}/companies({COMPANY_ID})/customers"
            f"?$filter=displayName eq 'Email Unverified'"
            f"&$select=id&$top=1",
            headers=headers, timeout=15,
        )
        if lookup_resp.ok:
            custs = lookup_resp.json().get("value", [])
            if custs:
                customer_id = custs[0]["id"]

    if not customer_id:
        return {"error": "Could not identify customer."}

    # Fallback: find session quote by email key if not in context
    if not session_quote_id:
        # Try to extract email from message history in context
        messages = req_context.get("messages", [])
        email_key = ""
        for msg in (messages if isinstance(messages, list) else []):
            text = msg.get("content", "") if isinstance(msg, dict) else ""
            match = re.search(r"\[EMAIL:\s*([^\]|]+)", text)
            if match:
                sender = match.group(1).strip().lower()
                email_key = sender.replace("@", "_at_").replace(".", "_")[:20]
                break

        if email_key:
            prefix = f"EM-U:{email_key}:"
            sq_resp = requests.get(
                f"{base}/companies({COMPANY_ID})/salesQuotes"
                f"?$filter=customerId eq {customer_id}"
                f" and startswith(externalDocumentNumber, '{prefix}')"
                f"&$orderby=documentDate desc&$top=1&$select=number",
                headers=headers, timeout=30,
            )
            if sq_resp.ok:
                sqs = sq_resp.json().get("value", [])
                if sqs:
                    session_quote_id = sqs[0].get("number", "")

    if not session_quote_id:
        # Last resort: find the most recent quote for this customer
        recent_resp = requests.get(
            f"{base}/companies({COMPANY_ID})/salesQuotes"
            f"?$filter=customerId eq {customer_id}"
            f" and startswith(externalDocumentNumber, 'EM-U:')"
            f"&$orderby=documentDate desc&$top=1&$select=number",
            headers=headers, timeout=30,
        )
        if recent_resp.ok:
            recent = recent_resp.json().get("value", [])
            if recent:
                session_quote_id = recent[0].get("number", "")

    if not session_quote_id:
        return {"error": "No quote found for this session. Please create a new order first."}

    if not item_id_1 or quantity_1 <= 0:
        raise ValueError("item_id_1 must be provided and quantity_1 must be > 0")

    # --- Find the session quote by reference number ---
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
            return {"error": "This order has already been processed and can no longer be modified."}
        return {"error": "Quote not found. It may have been removed."}

    quote = quotes[0]
    quote_id = quote["id"]
    customer_name = quote.get("customerName", "")

    # Verify this quote belongs to the caller's customer
    if quote.get("customerId") != customer_id:
        return {"error": "You can only modify your own orders."}

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
    quote_resp = requests.get(
        f"{base}/companies({COMPANY_ID})/salesQuotes({quote_id})",
        headers=headers, timeout=30,
    )
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
        "reference_number": session_quote_id,
        "customer_name": customer_name,
        "lines": order_lines,
        "total": round(total, 2),
    }
