import re
import requests
from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.tools.types import (
    PythonToolKind,
    PluginContext,
    AgentPreInvokePayload,
    AgentPreInvokeResult,
)
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections

MY_APP_ID = "business_central_wa"
COMPANY_ID = "572323a2-e013-f111-8405-7ced8d42f5ae"
UNVERIFIED_DISPLAY_NAME = "WhatsApp Unverified"


def normalize_phone(phone: str) -> str:
    """Strip spaces/dashes and convert 00-prefix to + for comparison."""
    phone = re.sub(r"[\s\-\(\)]", "", phone)
    if phone.startswith("00"):
        phone = "+" + phone[2:]
    return phone


def _bc_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}


def _fetch_customers(base: str, headers: dict) -> list[dict]:
    """Fetch all customers from BC. Only id, displayName, phoneNumber — no customer number."""
    url = (
        f"{base}/companies({COMPANY_ID})/customers"
        f"?$select=id,displayName,phoneNumber"
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

    return customers


def _fetch_lines(base: str, headers: dict, endpoint: str, record_id: str, lines_endpoint: str) -> list[dict]:
    """Fetch item lines for a sales quote or sales order."""
    url = f"{base}/companies({COMPANY_ID})/{endpoint}({record_id})/{lines_endpoint}"
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return [
        {
            "description": ln.get("description", ""),
            "quantity": ln.get("quantity", 0),
            "unitPrice": ln.get("unitPrice", 0),
            "lineAmount": ln.get("amountExcludingTax", 0),
        }
        for ln in resp.json().get("value", [])
        if ln.get("lineType") == "Item"
    ]


def _fetch_order_context(base: str, headers: dict, customer_id: str) -> dict:
    """Fetch the last shipped order (SO) and any pending quotes (SQ) for a customer."""
    context = {"last_shipped": None, "pending_quotes": []}

    so_url = (
        f"{base}/companies({COMPANY_ID})/salesOrders"
        f"?$filter=customerId eq {customer_id}"
        f"&$orderby=orderDate desc"
        f"&$top=1"
    )
    resp = requests.get(so_url, headers=headers, timeout=30)
    resp.raise_for_status()
    orders = resp.json().get("value", [])
    if orders:
        order = orders[0]
        item_lines = _fetch_lines(base, headers, "salesOrders", order["id"], "salesOrderLines")
        if item_lines:
            context["last_shipped"] = {
                "order_number": order.get("number", ""),
                "date": order.get("orderDate", ""),
                "lines": item_lines,
            }

    sq_url = (
        f"{base}/companies({COMPANY_ID})/salesQuotes"
        f"?$filter=customerId eq {customer_id}"
        f"&$orderby=documentDate desc"
        f"&$top=3"
    )
    resp = requests.get(sq_url, headers=headers, timeout=30)
    resp.raise_for_status()
    for quote in resp.json().get("value", []):
        item_lines = _fetch_lines(base, headers, "salesQuotes", quote["id"], "salesQuoteLines")
        if item_lines:
            context["pending_quotes"].append({
                "quote_number": quote.get("number", ""),
                "date": quote.get("documentDate", ""),
                "lines": item_lines,
            })

    return context


def _fetch_session_quote(base: str, headers: dict, customer_id: str, phone_digits: str) -> str:
    """Find the most recent SQ for an unverified caller by their phone in externalDocumentNumber."""
    phone_prefix = f"WA-U:{phone_digits}:"
    url = (
        f"{base}/companies({COMPANY_ID})/salesQuotes"
        f"?$filter=customerId eq {customer_id}"
        f" and startswith(externalDocumentNumber, '{phone_prefix}')"
        f"&$orderby=documentDate desc"
        f"&$top=1"
        f"&$select=number"
    )
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    quotes = resp.json().get("value", [])
    if quotes:
        return quotes[0].get("number", "")
    return ""


@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    description=(
        "Pre-invoke plugin that identifies the WhatsApp caller by phone lookup "
        "against Business Central customers. Sets context variables: customer_id, "
        "customer_name, verified, session_quote_id. The LLM never sees these values."
    ),
    kind=PythonToolKind.AGENTPREINVOKE,
    name="wa_identify_caller",
)
def wa_identify_caller(
    plugin_context: PluginContext,
    agent_pre_invoke_payload: AgentPreInvokePayload,
) -> AgentPreInvokeResult:
    """Identifies the WhatsApp caller by phone lookup against BC customers.
    Sets context variables for tools. Prepends greeting tag for the LLM.
    Customer IDs and GUIDs flow through context only — never exposed to the LLM."""

    result = AgentPreInvokeResult()
    result.continue_processing = True
    result.modified_payload = agent_pre_invoke_payload

    # ── Extract channel info from runtime context ────────────────────────
    state = getattr(plugin_context, "state", None) or {}
    ctx = state.get("context", {}) if isinstance(state, dict) else {}
    channel = ctx.get("channel", {})

    if channel.get("channel_type") != "whatsapp":
        return result

    whatsapp = channel.get("whatsapp", {})
    phone = whatsapp.get("user_phone_number", "")
    user_name = whatsapp.get("user_name", "")

    if not phone:
        return result

    caller_phone = normalize_phone(phone)
    # Phone digits without + for externalDocumentNumber matching
    phone_digits = caller_phone.lstrip("+")

    # ── Look up customer from BC ─────────────────────────────────────────
    customer = None
    last_order_info = ""
    try:
        conn = connections.oauth2_client_creds(MY_APP_ID)
        base = conn.url
        headers = _bc_headers(conn.access_token)

        customers = _fetch_customers(base, headers)

        # Match by phone number
        for c in customers:
            bc_phone = normalize_phone(c.get("phoneNumber", ""))
            if bc_phone and bc_phone == caller_phone:
                customer = c
                break

        if customer:
            # ── Verified caller ──────────────────────────────────────────
            ctx["customer_id"] = customer["id"]
            ctx["customer_name"] = customer["displayName"]
            ctx["verified"] = 1
            ctx["session_quote_id"] = ""

            # Fetch order history for greeting context
            try:
                order_ctx = _fetch_order_context(base, headers, customer["id"])

                if order_ctx["last_shipped"]:
                    shipped = order_ctx["last_shipped"]
                    items_str = ", ".join(
                        f"{int(ln['quantity'])} x {ln['description']}"
                        f" @{ln['unitPrice']:.2f}"
                        for ln in shipped["lines"]
                    )
                    total = sum(ln["lineAmount"] for ln in shipped["lines"])
                    last_order_info = (
                        f" Last shipped order {shipped['order_number']}"
                        f" ({shipped['date']}): {items_str}."
                        f" Total: {total:.2f}."
                    )

                if order_ctx["pending_quotes"]:
                    parts = []
                    for q in order_ctx["pending_quotes"]:
                        items_str = ", ".join(
                            f"{int(ln['quantity'])} x {ln['description']}"
                            f" @{ln['unitPrice']:.2f}"
                            for ln in q["lines"]
                        )
                        total = sum(ln["lineAmount"] for ln in q["lines"])
                        parts.append(
                            f"{q['quote_number']} ({q['date']}): {items_str}."
                            f" Total: {total:.2f}"
                        )
                    last_order_info += (
                        f" Pending quotes (still being processed):"
                        f" {'; '.join(parts)}."
                    )
            except Exception:
                pass

        else:
            # ── Unverified caller ────────────────────────────────────────
            unverified_customer = next(
                (c for c in customers
                 if c["displayName"].lower() == UNVERIFIED_DISPLAY_NAME.lower()),
                None,
            )
            ctx["customer_id"] = unverified_customer["id"] if unverified_customer else ""
            ctx["customer_name"] = ""
            ctx["verified"] = 0

            session_sq = ""
            if unverified_customer:
                try:
                    session_sq = _fetch_session_quote(
                        base, headers, unverified_customer["id"], phone_digits,
                    )
                except Exception:
                    pass
            ctx["session_quote_id"] = session_sq

    except Exception:
        customer = None
        ctx["customer_id"] = ""
        ctx["customer_name"] = ""
        ctx["verified"] = 0
        ctx["session_quote_id"] = ""

    # ── Build the prefix (greeting context — NO customer_id or GUID) ─────
    if customer:
        cust_name = customer["displayName"]
        prefix = (
            f"[VERIFIED CALLER — Name: {user_name}. "
            f"Business: {cust_name}. "
            f"Always greet as 'Hi {user_name} from {cust_name}!'. "
            f"To cancel orders use wa_cancel_order (one call per reference number).{last_order_info}]"
        )
    else:
        prefix = (
            f"[UNVERIFIED CALLER — Name: {user_name}. Phone: {phone}. "
            f"No account found. "
            f"MANDATORY: Your first action MUST be to call wa_get_inventory. "
            f"Then show ALL products with prices in your reply. "
            f"Also ask for business name and delivery address. "
            f"Combine everything in ONE message. "
            f"To modify their order use wa_modify_session_quote — NO reference number needed. "
            f"To cancel use wa_cancel_session_quote. "
            f"Put all details in the order note.]"
        )

    # ── Session boundary: trim history in-place ──────────────────────────
    # WhatsApp threads persist across orders. Old history poisons the LLM.
    # Modify the list IN-PLACE (assignment doesn't work — property is read-only).
    import re as _re
    messages = agent_pre_invoke_payload.messages
    MAX_HISTORY = 6
    if messages and len(messages) > 1:
        # Extract text from latest message to check for greeting
        last_text = ""
        lm = messages[-1]
        if hasattr(lm, "content"):
            if hasattr(lm.content, "text"):
                last_text = (lm.content.text or "").strip().lower()
            elif isinstance(lm.content, str):
                last_text = lm.content.strip().lower()

        greeting_re = r"^(hello|hi|hey|hallo|hoi|grüezi|guten\s*tag)\b"
        if _re.match(greeting_re, last_text):
            # New session → keep only the current message (in-place)
            keep = messages[-1:]
            messages.clear()
            messages.extend(keep)
        elif len(messages) > MAX_HISTORY:
            # Trim to last N messages (in-place)
            keep = messages[-MAX_HISTORY:]
            messages.clear()
            messages.extend(keep)

    # ── Prepend to the latest user message ───────────────────────────────
    if messages:
        last_msg = messages[-1]
        original = ""
        if hasattr(last_msg, "content"):
            if hasattr(last_msg.content, "text"):
                original = last_msg.content.text or ""
            elif isinstance(last_msg.content, str):
                original = last_msg.content
        last_msg.content.text = f"{prefix}\n\n{original}"
        result.modified_payload = agent_pre_invoke_payload

    return result
