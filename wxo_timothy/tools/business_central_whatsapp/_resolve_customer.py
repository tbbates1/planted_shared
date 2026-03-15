"""Shared helper: resolve WhatsApp caller to a Business Central customer.

Reads ``channel.customer_id`` from the request context (set by the WXO
platform) and queries BC for the customer's display name to determine
verified vs. unverified status.
"""

import requests

COMPANY_ID = "572323a2-e013-f111-8405-7ced8d42f5ae"
UNVERIFIED_DISPLAY_NAME = "WhatsApp Unverified"


def resolve_customer(context, base: str, access_token: str) -> dict:
    """Resolve the WhatsApp caller to a BC customer.

    Returns dict with keys: customer_id, verified (0|1), phone_digits,
    session_quote_id (str, unverified only).
    """
    rc = context.request_context

    # Fast path: already resolved in this run
    cached = rc.get("_resolved_customer_id")
    if cached is not None:
        return {
            "customer_id": cached,
            "verified": rc.get("_resolved_verified", 0),
            "phone_digits": rc.get("_resolved_phone_digits", ""),
            "session_quote_id": rc.get("_resolved_session_quote_id", ""),
        }

    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

    # --- Read from channel context ---
    channel = rc.get("channel") or {}
    customer_id = channel.get("customer_id", "") if isinstance(channel, dict) else ""
    whatsapp = channel.get("whatsapp", {}) if isinstance(channel, dict) else {}
    phone = whatsapp.get("user_phone_number", "")
    phone_digits = phone.lstrip("+") if phone else ""

    if not customer_id:
        # No channel customer_id — look up "WhatsApp Unverified" by name
        customer_id = _lookup_unverified_customer(base, headers)

    # --- Determine verified status by checking customer display name ---
    verified = 0
    if customer_id:
        try:
            resp = requests.get(
                f"{base}/companies({COMPANY_ID})/customers({customer_id})"
                f"?$select=displayName",
                headers=headers, timeout=15,
            )
            if resp.ok:
                name = resp.json().get("displayName", "")
                verified = 0 if name.lower() == UNVERIFIED_DISPLAY_NAME.lower() else 1
            else:
                # Customer ID is stale/invalid — fall back to unverified
                customer_id = _lookup_unverified_customer(base, headers)
        except Exception:
            customer_id = _lookup_unverified_customer(base, headers)

    # --- For unverified callers, find their session quote ---
    session_sq = ""
    if verified == 0 and customer_id and phone_digits:
        try:
            session_sq = _fetch_session_quote(base, headers, customer_id, phone_digits)
        except Exception:
            pass

    result = {
        "customer_id": customer_id,
        "verified": verified,
        "phone_digits": phone_digits,
        "session_quote_id": session_sq,
    }

    # Cache in context for later tools in this run
    try:
        rc["_resolved_customer_id"] = result["customer_id"]
        rc["_resolved_verified"] = result["verified"]
        rc["_resolved_phone_digits"] = result["phone_digits"]
        rc["_resolved_session_quote_id"] = result["session_quote_id"]
    except Exception:
        pass

    return result


def _lookup_unverified_customer(base: str, headers: dict) -> str:
    """Find the 'WhatsApp Unverified' customer by name or number."""
    # Try exact name match first
    url = (
        f"{base}/companies({COMPANY_ID})/customers"
        f"?$filter=displayName eq '{UNVERIFIED_DISPLAY_NAME}'"
        f"&$select=id,displayName&$top=1"
    )
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.ok:
            customers = resp.json().get("value", [])
            if customers:
                return customers[0]["id"]
    except Exception:
        pass

    # Fallback: case-insensitive scan (BC OData eq may be case-sensitive)
    try:
        url_all = (
            f"{base}/companies({COMPANY_ID})/customers"
            f"?$select=id,displayName&$top=5000"
        )
        resp = requests.get(url_all, headers=headers, timeout=30)
        if resp.ok:
            target = UNVERIFIED_DISPLAY_NAME.lower()
            for c in resp.json().get("value", []):
                if c.get("displayName", "").lower() == target:
                    return c["id"]
    except Exception:
        pass

    return ""


def _fetch_session_quote(base: str, headers: dict, customer_id: str, phone_digits: str) -> str:
    """Find the most recent SQ for an unverified caller by phone prefix."""
    phone_prefix = f"WA-U:{phone_digits}:"
    url = (
        f"{base}/companies({COMPANY_ID})/salesQuotes"
        f"?$filter=customerId eq {customer_id}"
        f" and startswith(externalDocumentNumber, '{phone_prefix}')"
        f"&$orderby=documentDate desc&$top=1&$select=number"
    )
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    quotes = resp.json().get("value", [])
    return quotes[0].get("number", "") if quotes else ""
