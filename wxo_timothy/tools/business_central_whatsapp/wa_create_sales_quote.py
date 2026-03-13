from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
import requests
from datetime import date

MY_APP_ID = "business_central_wa"
COMPANY_ID = "572323a2-e013-f111-8405-7ced8d42f5ae"


@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    name="wa_create_sales_quote",
    description="Create a draft sales quote in Business Central for a customer with up to 10 item lines. The quote can later be reviewed and converted to an order in BC. Returns the quote number and id.",
)
def wa_create_sales_quote(
    customer_id: str,
    original_message: str,
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
    """Create a draft sales quote in Microsoft Dynamics 365 Business Central.

    Creates the quote header for the given customer, adds each supplied item
    line, and stores the original customer message as the external document
    number for traceability. The quote stays in Draft status until someone
    in BC reviews it and converts it to a sales order.

    Args:
        customer_id (str): The GUID of the customer (from wa_get_customers).
        original_message (str): The original WhatsApp message from the customer. Stored as externalDocumentNumber on the quote for reference.
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
        dict: Keys: quote_id, quote_number, customer_id, customer_name, status, lines_added, external_document_number.
    """
    if not item_id_1 or quantity_1 <= 0:
        raise ValueError("item_id_1 must be provided and quantity_1 must be > 0")

    conn = connections.oauth2_client_creds(MY_APP_ID)
    base = conn.url
    access_token = conn.access_token
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    # Truncate original message to 35 chars (BC externalDocumentNumber limit)
    ext_doc_number = original_message[:35] if original_message else "WhatsApp order"

    # --- Create the quote header ---
    quote_body = {
        "customerId": customer_id,
        "documentDate": str(date.today()),
        "externalDocumentNumber": ext_doc_number,
    }

    resp = requests.post(
        f"{base}/companies({COMPANY_ID})/salesQuotes",
        headers=headers,
        json=quote_body,
        timeout=30,
    )
    resp.raise_for_status()
    quote = resp.json()
    quote_id = quote["id"]
    quote_number = quote.get("number", "")
    customer_name = quote.get("customerName", "")

    # --- Add item lines ---
    lines = [
        (item_id_1, quantity_1),
        (item_id_2, quantity_2),
        (item_id_3, quantity_3),
        (item_id_4, quantity_4),
        (item_id_5, quantity_5),
        (item_id_6, quantity_6),
        (item_id_7, quantity_7),
        (item_id_8, quantity_8),
        (item_id_9, quantity_9),
        (item_id_10, quantity_10),
    ]

    lines_added = 0
    for item_id, qty in lines:
        if item_id and qty > 0:
            r = requests.post(
                f"{base}/companies({COMPANY_ID})/salesQuotes({quote_id})/salesQuoteLines",
                headers=headers,
                json={
                    "lineType": "Item",
                    "itemId": item_id,
                    "quantity": qty,
                },
                timeout=30,
            )
            r.raise_for_status()
            lines_added += 1

    return {
        "quote_id": quote_id,
        "quote_number": quote_number,
        "customer_id": customer_id,
        "customer_name": customer_name,
        "status": "Draft",
        "lines_added": lines_added,
        "external_document_number": ext_doc_number,
    }
