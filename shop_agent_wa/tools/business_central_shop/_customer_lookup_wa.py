"""Shared helper: resolve customer from phone_number context variable."""

import requests
from ibm_watsonx_orchestrate.run import connections

COMPANY_ID = "572323a2-e013-f111-8405-7ced8d42f5ae"


def _normalize_phone(raw: str) -> str:
    """Strip whitespace, dashes, parentheses — keep '+' and digits only."""
    return "".join(ch for ch in raw.strip() if ch == "+" or ch.isdigit())


def resolve_customer(context, app_id):
    """Read phone_number from context variable, look up customer in BC.

    Args:
        context: AgentRun context object.
        app_id: The connection app_id for Business Central.

    Returns:
        tuple: (customer_id, business_name)

    Raises:
        ValueError: If no phone number in context or customer not found.
    """
    req_context = context.request_context
    phone = (
        req_context.get("phone_number", "")
        or req_context.get("phoneNumber", "")
        or req_context.get("phone", "")
    )
    if not phone:
        raise ValueError("No phone_number found in context. The wrapper must pass phone_number as a context variable.")

    phone = _normalize_phone(phone)

    conn = connections.oauth2_client_creds(app_id)
    base = conn.url
    headers = {"Authorization": f"Bearer {conn.access_token}", "Accept": "application/json"}

    url = (
        f"{base}/companies({COMPANY_ID})/customers"
        f"?$select=id,displayName,email,phoneNumber"
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

    for c in customers:
        bc_phone = _normalize_phone(c.get("phoneNumber") or "")
        if bc_phone and bc_phone == phone:
            return c["id"], c["displayName"]

    raise ValueError(f"No customer found for phone '{phone}'. This phone number is not registered.")
