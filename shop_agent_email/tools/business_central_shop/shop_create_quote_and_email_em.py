"""Tool: create sales quote in BC, fetch BC PDF, send form email with PDF attached."""

import requests
from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
from ibm_watsonx_orchestrate.run.context import AgentRun
from _customer_lookup_em import resolve_customer

BC_APP_ID = "business_central_wa"
SG_APP_ID = "sendgrid_email"
COMPANY_ID = "572323a2-e013-f111-8405-7ced8d42f5ae"
SEND_FROM = "timothy.bates.ibm@gmail.com"
SEND_FROM_NAME = "Planted Order Team"


def _bc_conn():
    conn = connections.oauth2_client_creds(BC_APP_ID)
    headers = {
        "Authorization": f"Bearer {conn.access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    return conn.url, headers


def _send_email(to_email, subject, html_body, pdf_base64=None, pdf_filename=None):
    """Send email via SendGrid, optionally with PDF attachment."""
    sg_conn = connections.api_key_auth(SG_APP_ID)
    payload = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": SEND_FROM, "name": SEND_FROM_NAME},
        "subject": subject,
        "content": [{"type": "text/html", "value": html_body}],
    }
    if pdf_base64 and pdf_filename:
        payload["attachments"] = [{
            "content": pdf_base64,
            "filename": pdf_filename,
            "type": "application/pdf",
            "disposition": "attachment",
        }]
    resp = requests.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={
            "Authorization": f"Bearer {sg_conn.api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    return resp.status_code in (200, 202)


def _html(text):
    """Convert plain text to styled HTML."""
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    safe = safe.replace("\n", "<br>\n")
    return (
        f'<div style="font-family:Arial,sans-serif;font-size:14px;'
        f'line-height:1.6;color:#333;">{safe}</div>'
    )


@tool(
    expected_credentials=[
        ExpectedCredentials(app_id=BC_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS),
        ExpectedCredentials(app_id=SG_APP_ID, type=ConnectionType.API_KEY_AUTH),
    ],
    name="shop_create_quote_and_email_em",
    description=(
        "Create a sales quote in Business Central and email the BC quote PDF to the customer. "
        "Pass item IDs and quantities from shop_get_products_em. Only pass in-stock items. "
        "Pass out_of_stock_notes listing any items the customer wanted that are not available. "
        "Set status to 'unrelated' if the request is not an order, or 'no_items' if nothing could be ordered. "
        "Customer is resolved automatically from email_address context variable."
    ),
)
def shop_create_quote_and_email_em(
    context: AgentRun,
    status: str = "order",
    item_id_1: str = "",
    quantity_1: float = 0,
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
    out_of_stock_notes: str = "",
) -> dict:
    """Create a sales quote and email the BC quote PDF to the customer.

    Args:
        context: Agent run context (auto-filled).
        status: One of 'order' (create quote), 'no_items' (all items OOS), 'unrelated' (not an order request).
        item_id_1: GUID of the first item.
        quantity_1: Quantity for the first item.
        item_id_2: GUID of the second item (optional).
        quantity_2: Quantity for the second item.
        item_id_3: GUID of the third item (optional).
        quantity_3: Quantity for the third item.
        item_id_4: GUID of the fourth item (optional).
        quantity_4: Quantity for the fourth item.
        item_id_5: GUID of the fifth item (optional).
        quantity_5: Quantity for the fifth item.
        item_id_6: GUID of the sixth item (optional).
        quantity_6: Quantity for the sixth item.
        item_id_7: GUID of the seventh item (optional).
        quantity_7: Quantity for the seventh item.
        item_id_8: GUID of the eighth item (optional).
        quantity_8: Quantity for the eighth item.
        item_id_9: GUID of the ninth item (optional).
        quantity_9: Quantity for the ninth item.
        item_id_10: GUID of the tenth item (optional).
        quantity_10: Quantity for the tenth item.
        out_of_stock_notes: Comma-separated list of product names the customer wanted that are out of stock.

    Returns:
        dict: Keys: success, email_sent, quote_number, message.
    """
    req_context = context.request_context
    to_email = (
        req_context.get("email_address", "")
        or req_context.get("wxo_email_id", "")
        or req_context.get("email", "")
    )

    # --- NOT REGISTERED ---
    try:
        customer_id, customer_name = resolve_customer(context, BC_APP_ID)
    except ValueError:
        if to_email:
            body = (
                "Dear Customer,\n\n"
                "Thank you for your interest in Planted products.\n\n"
                "Unfortunately, your email address is not registered in our ordering system. "
                "To set up an account, please contact our sales team at sales@planted.ch.\n\n"
                "Best regards,\n"
                "Planted Order Team"
            )
            _send_email(to_email, "RE: Your Order Request", _html(body))
            return {"success": False, "email_sent": True, "message": "Email not registered. Notification sent."}
        return {"success": False, "email_sent": False, "message": "No email in context and customer not found."}

    # --- UNRELATED REQUEST ---
    if status == "unrelated":
        body = (
            f"Dear {customer_name},\n\n"
            "Thank you for your message. This service handles product orders only.\n\n"
            "For other inquiries, please contact:\n"
            "- Logistics: logistics@planted.ch\n"
            "- Sales: sales@planted.ch\n\n"
            "Best regards,\n"
            "Planted Order Team"
        )
        sent = _send_email(to_email, "RE: Your Inquiry", _html(body))
        return {"success": True, "email_sent": sent, "message": "Unrelated request. Redirect email sent."}

    # --- NO ITEMS AVAILABLE ---
    if status == "no_items" or (not item_id_1 and not any([
        item_id_2, item_id_3, item_id_4, item_id_5,
        item_id_6, item_id_7, item_id_8, item_id_9, item_id_10
    ])):
        oos_text = ""
        if out_of_stock_notes:
            oos_text = (
                f"\nThe following items you requested are currently out of stock:\n"
                f"{out_of_stock_notes}\n"
            )
        body = (
            f"Dear {customer_name},\n\n"
            "Thank you for your order request. Unfortunately, we were unable to create a sales quote "
            f"because none of the requested items are currently available.{oos_text}\n"
            "We will notify you when these items are back in stock. "
            "In the meantime, please contact sales@planted.ch for alternative options.\n\n"
            "Best regards,\n"
            "Planted Order Team"
        )
        sent = _send_email(to_email, "RE: Your Order Request", _html(body))
        return {"success": False, "email_sent": sent, "message": "No items available. Notification sent."}

    # --- CREATE SALES QUOTE ---
    base, headers = _bc_conn()

    items = [
        (item_id_1, quantity_1), (item_id_2, quantity_2), (item_id_3, quantity_3),
        (item_id_4, quantity_4), (item_id_5, quantity_5), (item_id_6, quantity_6),
        (item_id_7, quantity_7), (item_id_8, quantity_8), (item_id_9, quantity_9),
        (item_id_10, quantity_10),
    ]

    resp = requests.post(
        f"{base}/companies({COMPANY_ID})/salesQuotes",
        headers=headers, json={"customerId": customer_id}, timeout=30,
    )
    if not resp.ok:
        return {"success": False, "email_sent": False, "message": f"BC error creating quote: {resp.status_code}"}

    quote = resp.json()
    quote_id = quote["id"]
    quote_number = quote.get("number", "")
    etag = resp.headers.get("ETag", quote.get("@odata.etag", ""))

    requests.patch(
        f"{base}/companies({COMPANY_ID})/salesQuotes({quote_id})",
        headers={**headers, "If-Match": etag},
        json={"externalDocumentNumber": "EMAIL-QUOTE"},
        timeout=30,
    )

    for item_id, qty in items:
        if item_id and qty > 0:
            r = requests.post(
                f"{base}/companies({COMPANY_ID})/salesQuotes({quote_id})/salesQuoteLines",
                headers=headers, json={"lineType": "Item", "itemId": item_id, "quantity": qty},
                timeout=30,
            )
            if not r.ok:
                return {"success": False, "email_sent": False, "message": f"BC error adding line: {r.status_code}"}

    # Fetch BC sales quote PDF via mediaReadLink
    pdf_base64 = None
    try:
        pdf_resp = requests.get(
            f"{base}/companies({COMPANY_ID})/salesQuotes({quote_id})/pdfDocument",
            headers=headers, timeout=30,
        )
        if pdf_resp.ok:
            data = pdf_resp.json()
            media_link = data.get("pdfDocumentContent@odata.mediaReadLink", "")
            if media_link:
                import base64
                pdf_bytes_resp = requests.get(
                    media_link,
                    headers={"Authorization": headers["Authorization"]},
                    timeout=30,
                )
                if pdf_bytes_resp.ok and len(pdf_bytes_resp.content) > 100:
                    pdf_base64 = base64.b64encode(pdf_bytes_resp.content).decode("ascii")
    except Exception:
        pass

    # Build email
    oos_section = ""
    if out_of_stock_notes:
        oos_section = (
            f"\nPlease note: The following items you requested are currently out of stock:\n"
            f"  {out_of_stock_notes}\n"
            f"We will notify you when these items become available.\n"
        )

    body = (
        f"Dear {customer_name},\n\n"
        f"Thank you for your order. We have created sales quote {quote_number} for you.\n"
        f"Please find your quote attached as a PDF.\n"
        f"{oos_section}\n"
        f"To confirm your order, please reply to this email with your approval.\n"
        f"To request changes, simply reply with your modifications.\n\n"
        f"Best regards,\n"
        f"Planted Order Team"
    )

    sent = _send_email(
        to_email,
        f"Your Planted Quote {quote_number}",
        _html(body),
        pdf_base64=pdf_base64,
        pdf_filename=f"{quote_number}.pdf" if pdf_base64 else None,
    )

    return {
        "success": True,
        "email_sent": sent,
        "quote_number": quote_number,
        "pdf_attached": pdf_base64 is not None,
        "message": f"Quote {quote_number} created and emailed to {to_email}.",
    }
