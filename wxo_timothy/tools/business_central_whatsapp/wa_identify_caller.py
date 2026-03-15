"""Pre-invoke plugin: identifies WhatsApp caller by phone lookup.

Sets customer_id context variable. Prepends a compact data tag with
customer identity and order history. Rejects unverified callers.
Handles "reset" keyword to clear thread history.
"""

import json
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
WXO_INSTANCE_BASE = "https://api.eu-central-1.dl.watson-orchestrate.ibm.com/instances/20260227-1116-3427-60dc-5ca812e30631"

GREETINGS = {"hello", "hi", "hey", "hallo", "hoi", "grüezi", "salut"}


def _normalize_phone(phone: str) -> str:
    phone = re.sub(r"[\s\-\(\)]", "", phone)
    if phone.startswith("00"):
        phone = "+" + phone[2:]
    return phone


def _bc_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _fetch_customers(base: str, headers: dict) -> list[dict]:
    url = f"{base}/companies({COMPANY_ID})/customers?$select=id,displayName,phoneNumber&$top=20000"
    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    customers = data.get("value", [])
    while "@odata.nextLink" in data:
        resp = requests.get(data["@odata.nextLink"], headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        customers.extend(data.get("value", []))
    return customers


def _fetch_lines(base: str, headers: dict, endpoint: str, record_id: str, lines_ep: str) -> list[dict]:
    url = f"{base}/companies({COMPANY_ID})/{endpoint}({record_id})/{lines_ep}"
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


def _build_order_context(base: str, headers: dict, customer_id: str) -> str:
    """Build compact order summary string for the LLM tag."""
    parts = []

    # Last shipped order
    resp = requests.get(
        f"{base}/companies({COMPANY_ID})/salesOrders"
        f"?$filter=customerId eq {customer_id}&$orderby=orderDate desc&$top=1",
        headers=headers, timeout=30,
    )
    resp.raise_for_status()
    orders = resp.json().get("value", [])
    if orders:
        o = orders[0]
        lines = _fetch_lines(base, headers, "salesOrders", o["id"], "salesOrderLines")
        if lines:
            items = " & ".join(f"{int(l['quantity'])} x {l['description']} @{l['unitPrice']:.2f}" for l in lines)
            total = sum(l["lineAmount"] for l in lines)
            parts.append(f"LAST_SHIPPED: {o.get('number','')} ({o.get('orderDate','')}): {items}. Total: {total:.2f}")

    # All pending quotes
    resp = requests.get(
        f"{base}/companies({COMPANY_ID})/salesQuotes"
        f"?$filter=customerId eq {customer_id}&$orderby=documentDate desc&$top=20",
        headers=headers, timeout=30,
    )
    resp.raise_for_status()
    pending = []
    for q in resp.json().get("value", []):
        lines = _fetch_lines(base, headers, "salesQuotes", q["id"], "salesQuoteLines")
        if lines:
            items = " & ".join(f"{int(l['quantity'])} x {l['description']} @{l['unitPrice']:.2f}" for l in lines)
            total = sum(l["lineAmount"] for l in lines)
            pending.append(f"{q.get('number','')} ({q.get('documentDate','')}): {items}. Total: {total:.2f}")
    if pending:
        parts.append("PENDING: " + "; ".join(pending))

    return " | ".join(parts)


def _try_clear_thread(plugin_context: PluginContext, payload: AgentPreInvokePayload):
    """Delete the WXO message thread to clear old conversation history."""
    try:
        state = getattr(plugin_context, "state", {}) or {}
        ctx = state.get("context", {}) if isinstance(state, dict) else {}
        thread_id = ctx.get("wxo_thread_id", "")
        if not thread_id:
            print("[wa_identify_caller] No wxo_thread_id found")
            return

        auth_token = None
        if payload.headers and payload.headers.authorization:
            auth_token = payload.headers.authorization
            if not auth_token.startswith("Bearer "):
                auth_token = f"Bearer {auth_token}"
        if not auth_token:
            print("[wa_identify_caller] No auth token in payload")
            return

        url = f"{WXO_INSTANCE_BASE}/v1/orchestrate/threads/{thread_id}"
        print(f"[wa_identify_caller] Deleting thread: {url}")
        resp = requests.delete(url, headers={"Authorization": auth_token}, timeout=10)
        print(f"[wa_identify_caller] Delete response: {resp.status_code}")
        if not resp.ok:
            print(f"[wa_identify_caller] Delete error: {resp.text[:200]}")
    except Exception as e:
        print(f"[wa_identify_caller] Thread clear failed: {e}")


@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    description="Pre-invoke plugin: identifies WhatsApp caller by phone lookup against Business Central.",
    kind=PythonToolKind.AGENTPREINVOKE,
    name="wa_identify_caller",
)
def wa_identify_caller(
    plugin_context: PluginContext,
    agent_pre_invoke_payload: AgentPreInvokePayload,
) -> AgentPreInvokeResult:
    result = AgentPreInvokeResult()
    result.continue_processing = True
    result.modified_payload = agent_pre_invoke_payload

    # Extract channel info
    state = getattr(plugin_context, "state", None) or {}
    ctx = state.get("context", {}) if isinstance(state, dict) else {}
    channel = ctx.get("channel", {})

    # Support both native WhatsApp channel and bridge-based channel
    whatsapp = channel.get("whatsapp", {}) if isinstance(channel, dict) else {}
    phone = whatsapp.get("user_phone_number", "")
    user_name = whatsapp.get("user_name", "")

    # If no channel info, try parsing [WHATSAPP: phone | NAME: name] tag from message
    if not phone:
        msgs = agent_pre_invoke_payload.messages
        if msgs:
            msg_text = ""
            m = msgs[-1]
            if hasattr(m, "content"):
                if hasattr(m.content, "text"):
                    msg_text = m.content.text or ""
                elif isinstance(m.content, str):
                    msg_text = m.content
            tag_match = re.match(r"\[WHATSAPP:\s*(\+?\d+)\s*\|\s*NAME:\s*(.+?)\]", msg_text)
            if tag_match:
                phone = tag_match.group(1)
                user_name = tag_match.group(2).strip()

    if not phone:
        return result

    if not phone:
        return result

    caller_phone = _normalize_phone(phone)

    # Get user message text
    messages = agent_pre_invoke_payload.messages
    original = ""
    last_msg = None
    if messages:
        last_msg = messages[-1]
        if hasattr(last_msg, "content"):
            if hasattr(last_msg.content, "text"):
                original = last_msg.content.text or ""
            elif isinstance(last_msg.content, str):
                original = last_msg.content

    stripped = original.strip().lower()

    # Handle "reset" — clear thread and start fresh
    if stripped == "reset":
        _try_clear_thread(plugin_context, agent_pre_invoke_payload)
        if last_msg:
            agent_pre_invoke_payload.messages = [last_msg]
        original = "hello"

    # Look up customer
    customer = None
    try:
        conn = connections.oauth2_client_creds(MY_APP_ID)
        base = conn.url
        headers = _bc_headers(conn.access_token)
        customers = _fetch_customers(base, headers)

        for c in customers:
            bc_phone = _normalize_phone(c.get("phoneNumber", ""))
            if bc_phone and bc_phone == caller_phone:
                customer = c
                break
    except Exception:
        pass

    if not customer:
        # Reject unverified callers
        result.continue_processing = False
        if last_msg:
            last_msg.content.text = "Sorry, this phone number is not registered. Please contact Planted to set up your account."
            result.modified_payload = agent_pre_invoke_payload
        return result

    # Set context variables
    ctx["customer_id"] = customer["id"]

    # Build order context
    order_info = ""
    try:
        order_info = _build_order_context(base, headers, customer["id"])
    except Exception:
        pass

    # Build compact data tag — NO behavioral instructions
    tag = (
        f"[VERIFIED customer_id={customer['id']} "
        f"name={user_name} business={customer['displayName']} | "
        f"{order_info}]"
    )

    if last_msg:
        last_msg.content.text = f"{tag}\n\n{original}"

        # Override system prompt to counteract old conversation history.
        # The LLM has 50K+ tokens of old messages with stale tool names
        # and bad patterns. This injection forces it to use current tools.
        agent_pre_invoke_payload.system_prompt = (
            "CRITICAL: Ignore ALL previous conversation history and tool names. "
            "The ONLY tools that exist are: wa_get_products, wa_get_orders, wa_create_quote, wa_cancel_quote. "
            "There are NO other tools. If you call any other tool name, it will fail. "
            "You MUST call a tool for every action. Never say you did something without calling a tool first. "
            "If a tool returns an error, tell the customer the error — do NOT make up a success response."
        )

        result.modified_payload = agent_pre_invoke_payload

    return result
