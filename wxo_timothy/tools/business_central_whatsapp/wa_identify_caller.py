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


def normalize_phone(phone: str) -> str:
    """Strip spaces/dashes and convert 00-prefix to + for comparison."""
    phone = re.sub(r"[\s\-\(\)]", "", phone)
    if phone.startswith("00"):
        phone = "+" + phone[2:]
    return phone


def _bc_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}


def _fetch_customers(base: str, headers: dict) -> list[dict]:
    """Fetch all customers with phoneNumber from BC."""
    url = (
        f"{base}/companies({COMPANY_ID})/customers"
        f"?$select=id,number,displayName,phoneNumber"
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


def _fetch_last_order(base: str, headers: dict, customer_id: str) -> dict | None:
    """Fetch the most recent sales order for a customer, including its lines.

    Checks salesOrders first (real orders), then falls back to salesQuotes.
    """
    # Try salesOrders first (SO numbers — real orders)
    for endpoint, lines_endpoint, date_field in [
        ("salesOrders", "salesOrderLines", "orderDate"),
        ("salesQuotes", "salesQuoteLines", "documentDate"),
    ]:
        url = (
            f"{base}/companies({COMPANY_ID})/{endpoint}"
            f"?$filter=customerId eq {customer_id}"
            f"&$orderby={date_field} desc"
            f"&$top=1"
        )
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        records = resp.json().get("value", [])
        if not records:
            continue

        record = records[0]
        record_id = record["id"]

        lines_url = f"{base}/companies({COMPANY_ID})/{endpoint}({record_id})/{lines_endpoint}"
        lines_resp = requests.get(lines_url, headers=headers, timeout=30)
        lines_resp.raise_for_status()
        lines = lines_resp.json().get("value", [])

        item_lines = [
            {
                "description": ln.get("description", ""),
                "quantity": ln.get("quantity", 0),
                "unitPrice": ln.get("unitPrice", 0),
                "lineAmount": ln.get("amountExcludingTax", 0),
            }
            for ln in lines
            if ln.get("lineType") == "Item"
        ]

        if item_lines:
            return {
                "order_number": record.get("number", ""),
                "date": record.get(date_field, ""),
                "lines": item_lines,
            }

    return None


@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    description=(
        "Pre-invoke plugin that identifies the WhatsApp caller by looking up "
        "their phone number in Business Central's customer records. "
        "For verified callers it also fetches their last order for reorder context. "
        "This runs as deterministic code — the LLM cannot override it."
    ),
    kind=PythonToolKind.AGENTPREINVOKE,
    name="wa_identify_caller",
)
def wa_identify_caller(
    plugin_context: PluginContext,
    agent_pre_invoke_payload: AgentPreInvokePayload,
) -> AgentPreInvokeResult:
    """Reads the WhatsApp phone number from the runtime channel context,
    looks it up against BC customer phoneNumber fields, and prepends a
    verified/unverified note to the latest user message.

    IMPORTANT: Only customer NUMBER (e.g. C0011) is exposed to the LLM,
    never the raw GUID. Tools resolve numbers to GUIDs internally."""

    result = AgentPreInvokeResult()
    result.continue_processing = True
    result.modified_payload = agent_pre_invoke_payload

    # ── Extract channel info from runtime context ────────────────────────
    state = getattr(plugin_context, "state", None) or {}
    context = state.get("context", {}) if isinstance(state, dict) else {}
    channel = context.get("channel", {})

    if channel.get("channel_type") != "whatsapp":
        return result

    whatsapp = channel.get("whatsapp", {})
    phone = whatsapp.get("user_phone_number", "")
    user_name = whatsapp.get("user_name", "")

    if not phone:
        return result

    caller_phone = normalize_phone(phone)

    # ── Look up customer from BC ─────────────────────────────────────────
    customer = None
    last_order_info = ""
    try:
        conn = connections.oauth2_client_creds(MY_APP_ID)
        base = conn.url
        headers = _bc_headers(conn.access_token)

        customers = _fetch_customers(base, headers)

        for c in customers:
            bc_phone = normalize_phone(c.get("phoneNumber", ""))
            if bc_phone and bc_phone == caller_phone:
                customer = c
                break

        if customer:
            # Try to fetch last order for reorder context
            try:
                last_quote = _fetch_last_order(base, headers, customer["id"])
                if last_quote and last_quote["lines"]:
                    items_str = ", ".join(
                        f"{int(ln['quantity'])} x {ln['description']}"
                        f" @{ln['unitPrice']:.2f}"
                        for ln in last_quote["lines"]
                    )
                    total = sum(ln["lineAmount"] for ln in last_quote["lines"])
                    last_order_info = (
                        f" Last order ({last_quote['date']}): "
                        f"{items_str}. Total: {total:.2f}."
                    )
            except Exception:
                pass  # Non-critical — continue without last order info

    except Exception:
        # BC lookup failed — treat as unverified
        customer = None

    # ── Build the prefix ─────────────────────────────────────────────────
    if customer:
        cust_name = customer["displayName"]
        prefix = (
            f"[VERIFIED CALLER — {user_name}. "
            f"Customer: {cust_name}.{last_order_info}]"
        )
    else:
        prefix = (
            f"[UNVERIFIED CALLER — {user_name}. "
            f"No account found. "
            f"Ask for their name, phone number, business, and address. "
            f"Put that info in the order note.]"
        )

    # ── Trim history to last 20 messages to avoid stale session bleed ────
    messages = list(agent_pre_invoke_payload.messages)
    MAX_HISTORY = 20
    if len(messages) > MAX_HISTORY:
        messages = messages[-MAX_HISTORY:]
        agent_pre_invoke_payload.messages = messages

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
