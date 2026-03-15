"""Tool: create a sales quote (order) in Business Central."""

import json
import requests
from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
from ibm_watsonx_orchestrate.run.context import AgentRun

MY_APP_ID = "business_central_wa"
COMPANY_ID = "572323a2-e013-f111-8405-7ced8d42f5ae"


@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    name="wa_create_quote",
    description='Create a new order (sales quote). Pass items as a JSON string: \'[{"item_id":"GUID","qty":10}]\'. Returns BC-calculated prices with VAT and a reference number.',
)
def wa_create_quote(context: AgentRun, customer_id: str, items: str, note: str = "") -> dict:
    """Create a sales quote.

    Args:
        context: Agent run context (auto-filled).
        customer_id: Customer GUID from the [VERIFIED] tag.
        items: JSON array string of {"item_id": "GUID", "qty": number}.
        note: Optional delivery note.
    """
    if not customer_id:
        return {"error": "customer_id is required."}

    conn = connections.oauth2_client_creds(MY_APP_ID)
    base = conn.url
    headers = {"Authorization": f"Bearer {conn.access_token}", "Accept": "application/json", "Content-Type": "application/json"}

    # Parse items
    try:
        item_list = json.loads(items)
        if not isinstance(item_list, list) or not item_list:
            return {"error": "items must be a non-empty JSON array of {item_id, qty}."}
    except (json.JSONDecodeError, TypeError):
        return {"error": "items must be valid JSON: '[{\"item_id\":\"GUID\",\"qty\":10}]'"}

    # Create quote header
    resp = requests.post(
        f"{base}/companies({COMPANY_ID})/salesQuotes",
        headers=headers, json={"customerId": customer_id}, timeout=30,
    )
    if not resp.ok:
        return {"error": f"Failed to create order: {resp.status_code}"}
    quote = resp.json()
    quote_id = quote["id"]
    quote_number = quote.get("number", "")
    etag = resp.headers.get("ETag", quote.get("@odata.etag", ""))

    # Patch external doc number
    patch_data = {"externalDocumentNumber": "WA-V"}
    patch_headers = {**headers, "If-Match": etag}
    requests.patch(f"{base}/companies({COMPANY_ID})/salesQuotes({quote_id})", headers=patch_headers, json=patch_data, timeout=30)

    # Add item lines
    lines_url = f"{base}/companies({COMPANY_ID})/salesQuotes({quote_id})/salesQuoteLines"
    for item in item_list:
        item_id = item.get("item_id", "")
        qty = item.get("qty", 0)
        if item_id and qty > 0:
            r = requests.post(lines_url, headers=headers, json={"lineType": "Item", "itemId": item_id, "quantity": qty}, timeout=30)
            if not r.ok:
                return {"error": f"Failed to add item {item_id}: {r.status_code}", "detail": r.text}

    # Add note as comment line
    if note and note.strip():
        requests.post(lines_url, headers=headers, json={"lineType": "Comment", "description": note.strip()[:100]}, timeout=30)

    # Read back totals
    q_resp = requests.get(f"{base}/companies({COMPANY_ID})/salesQuotes({quote_id})", headers=headers, timeout=30)
    subtotal = tax = total = 0.0
    if q_resp.ok:
        q = q_resp.json()
        subtotal = q.get("totalAmountExcludingTax", 0)
        tax = q.get("totalTaxAmount", 0)
        total = q.get("totalAmountIncludingTax", 0)

    # Read back lines
    order_lines = []
    l_resp = requests.get(lines_url, headers=headers, timeout=30)
    if l_resp.ok:
        for ln in l_resp.json().get("value", []):
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
        "lines": order_lines,
        "subtotal": round(subtotal, 2),
        "tax": round(tax, 2),
        "total": round(total, 2),
    }
