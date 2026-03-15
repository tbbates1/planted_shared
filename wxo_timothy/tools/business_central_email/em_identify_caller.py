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
UNVERIFIED_DISPLAY_NAME = "Email Unverified"

EMAIL_TAG_PATTERN = re.compile(r"\[EMAIL:\s*([^\]]+)\]")


def _bc_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}


def _fetch_customers(base: str, headers: dict) -> list[dict]:
    """Fetch all customers from BC. Only id, displayName, email — no customer number."""
    url = (
        f"{base}/companies({COMPANY_ID})/customers"
        f"?$select=id,displayName,email"
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


def _fetch_session_quote(base: str, headers: dict, customer_id: str, email_key: str) -> str:
    """Find the most recent SQ for an unverified email caller by their email in externalDocumentNumber."""
    email_prefix = f"EM-U:{email_key}:"
    url = (
        f"{base}/companies({COMPANY_ID})/salesQuotes"
        f"?$filter=customerId eq {customer_id}"
        f" and startswith(externalDocumentNumber, '{email_prefix}')"
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
        "Pre-invoke plugin that identifies the email caller by email lookup "
        "against Business Central customers. Sets context variables: customer_id, "
        "customer_name, verified, session_quote_id. The LLM never sees these values."
    ),
    kind=PythonToolKind.AGENTPREINVOKE,
    name="em_identify_caller",
)
def em_identify_caller(
    plugin_context: PluginContext,
    agent_pre_invoke_payload: AgentPreInvokePayload,
) -> AgentPreInvokeResult:
    """Identifies the email caller by email lookup against BC customers.
    Sets context variables for tools. Prepends greeting tag for the LLM.
    Customer IDs and GUIDs flow through context only — never exposed to the LLM."""

    result = AgentPreInvokeResult()
    result.continue_processing = True
    result.modified_payload = agent_pre_invoke_payload

    # ── Extract email from message text ──────────────────────────────────
    messages = list(agent_pre_invoke_payload.messages)
    if not messages:
        return result

    last_msg = messages[-1]
    original = ""
    if hasattr(last_msg, "content"):
        if hasattr(last_msg.content, "text"):
            original = last_msg.content.text or ""
        elif isinstance(last_msg.content, str):
            original = last_msg.content

    match = EMAIL_TAG_PATTERN.search(original)
    if not match:
        return result

    sender_email = match.group(1).strip().lower()
    clean_message = EMAIL_TAG_PATTERN.sub("", original).strip()

    # Email key for externalDocumentNumber (replace @ and . for safe OData filtering)
    email_key = sender_email.replace("@", "_at_").replace(".", "_")[:20]

    # ── Access the runtime context to set context variables ──────────────
    state = getattr(plugin_context, "state", None) or {}
    ctx = state.get("context", {}) if isinstance(state, dict) else {}

    # ── Look up customer from BC ─────────────────────────────────────────
    customer = None
    last_order_info = ""
    try:
        conn = connections.oauth2_client_creds(MY_APP_ID)
        base = conn.url
        headers = _bc_headers(conn.access_token)

        customers = _fetch_customers(base, headers)

        # Match by email
        for c in customers:
            bc_email = (c.get("email") or "").strip().lower()
            if bc_email and bc_email == sender_email:
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
            # Find "Email Unverified" fallback from the same customer list
            unverified_customer = next(
                (c for c in customers
                 if c["displayName"].lower() == UNVERIFIED_DISPLAY_NAME.lower()),
                None,
            )
            ctx["customer_id"] = unverified_customer["id"] if unverified_customer else ""
            ctx["customer_name"] = ""
            ctx["verified"] = 0

            # Find the most recent session quote for this email
            session_sq = ""
            if unverified_customer:
                try:
                    session_sq = _fetch_session_quote(
                        base, headers, unverified_customer["id"], email_key,
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
            f"[VERIFIED CALLER — {cust_name}. "
            f"Email: {sender_email}.{last_order_info}]"
        )
    else:
        prefix = (
            f"[UNVERIFIED CALLER — {sender_email}. "
            f"No account found for this email address. "
            f"Ask for business name and delivery address. Infer name from the email if possible. "
            f"Put that info in the order note.]"
        )

    # ── Trim history to last 20 messages ────────────────────────────────
    MAX_HISTORY = 20
    if len(messages) > MAX_HISTORY:
        messages = messages[-MAX_HISTORY:]
        agent_pre_invoke_payload.messages = messages

    # ── Prepend to the latest user message ──────────────────────────────
    last_msg = messages[-1]
    last_msg.content.text = f"{prefix}\n\n{clean_message}"
    result.modified_payload = agent_pre_invoke_payload

    return result
