from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
import requests

MY_APP_ID = "business_central"
COMPANY_ID = "572323a2-e013-f111-8405-7ced8d42f5ae"


@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_AUTH_CODE)],
    name="get_order_detail",
    description="Retrieve a sales order with its line items, individual line costs, and order totals.",
)
def get_sales_order_details(order_id: str) -> dict:
    """Fetch a sales order header and all its lines from Microsoft Dynamics 365 Business Central.

    Args:
        order_id (str): The GUID of the sales order to retrieve (returned by create_sales_order).

    Returns:
        dict: Order details containing:
            - id (str): Order GUID.
            - number (str): Human-readable order number.
            - orderDate (str): Date the order was placed.
            - status (str): Current status (e.g. Draft, Open, Released).
            - customerName (str): Name of the customer.
            - currencyCode (str): Currency of the order.
            - totalAmountExcludingTax (float): Order total before tax.
            - totalTaxAmount (float): Total tax applied.
            - totalAmountIncludingTax (float): Order total after tax.
            - lines (list[dict]): Each line contains:
                - lineNumber (int): Position of the line.
                - itemId (str): GUID of the item.
                - description (str): Item description.
                - quantity (float): Quantity ordered.
                - unitPrice (float): Price per unit.
                - lineAmount (float): quantity x unitPrice before tax.
                - taxPercent (float): Tax rate applied to this line.
                - amountIncludingTax (float): Line total after tax.
    """
    conn = connections.oauth2_auth_code(MY_APP_ID)
    base = conn.url
    access_token = conn.access_token
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

    order_resp = requests.get(
        f"{base}/companies({COMPANY_ID})/salesOrders({order_id})",
        headers=headers,
        timeout=30,
    )
    order_resp.raise_for_status()
    order = order_resp.json()

    lines_resp = requests.get(
        f"{base}/companies({COMPANY_ID})/salesOrders({order_id})/salesOrderLines",
        headers=headers,
        timeout=30,
    )
    lines_resp.raise_for_status()
    lines_data = lines_resp.json().get("value", [])

    lines = [
        {
            "lineNumber": line.get("sequence"),
            "itemId": line.get("itemId"),
            "description": line.get("description"),
            "quantity": line.get("quantity"),
            "unitPrice": line.get("unitPrice"),
            "lineAmount": line.get("lineAmount"),
            "taxPercent": line.get("taxPercent"),
            "amountIncludingTax": line.get("amountIncludingTax"),
        }
        for line in lines_data
    ]

    return {
        "id": order["id"],
        "number": order["number"],
        "orderDate": order.get("orderDate"),
        "status": order.get("status"),
        "customerName": order.get("customerName"),
        "currencyCode": order.get("currencyCode"),
        "totalAmountExcludingTax": order.get("totalAmountExcludingTax"),
        "totalTaxAmount": order.get("totalTaxAmount"),
        "totalAmountIncludingTax": order.get("totalAmountIncludingTax"),
        "lines": lines,
    }
