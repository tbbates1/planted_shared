"""Shared helper: resolve customer from email_address context variable."""

import requests
from ibm_watsonx_orchestrate.run import connections

COMPANY_ID = "572323a2-e013-f111-8405-7ced8d42f5ae"


def resolve_customer(context, app_id):
    """Read email_address from context variable, look up customer in BC.

    Args:
        context: AgentRun context object.
        app_id: The connection app_id for Business Central.

    Returns:
        tuple: (customer_id, business_name)

    Raises:
        ValueError: If no email in context or customer not found.
    """
    req_context = context.request_context
    email = (
        req_context.get("email_address", "")
        or req_context.get("wxo_email_id", "")
        or req_context.get("email", "")
    )
    if not email:
        raise ValueError("No email_address found in context. The API must pass email_address as a context variable.")

    email = email.strip().lower()

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
        bc_email = (c.get("email") or "").strip().lower()
        if bc_email and bc_email == email:
            return c["id"], c["displayName"]

    raise ValueError(f"No customer found for '{email}'. This email is not registered.")
