from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
import requests

MY_APP_ID = "business_central"
COMPANY_ID = "572323a2-e013-f111-8405-7ced8d42f5ae"


@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_AUTH_CODE)],
    name="get_orders_for_customer",
    description="Retrieve all sales orders for a specific customer from Microsoft Dynamics 365 Business Central.",
)
def get_orders_for_customer(customer_id: str) -> list[dict]:
    """Retrieve all sales orders belonging to a specific customer.

    Args:
        customer_id (str): The GUID of the customer whose orders to fetch
            (use get_customers to look up customer GUIDs).

    Returns:
        list[dict]: A list of sales orders. Each entry contains:
            - id (str): Order GUID.
            - number (str): Human-readable order number.
            - orderDate (str): ISO date the order was placed.
            - status (str): Current status (e.g. Draft, Open, Released).
            - customerId (str): Customer GUID.
            - customerName (str): Customer display name.
            - totalAmountExcludingTax (float): Order total before tax.
            - totalAmountIncludingTax (float): Order total after tax.
            - currencyCode (str): Currency of the order.
    """
    conn = connections.oauth2_auth_code(MY_APP_ID)
    base = conn.url
    access_token = conn.access_token
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

    select = (
        "id,number,orderDate,status,customerId,customerName,"
        "totalAmountExcludingTax,totalAmountIncludingTax,currencyCode"
    )
    url = (
        f"{base}/companies({COMPANY_ID})/salesOrders"
        f"?$filter=customerId eq {customer_id}"
        f"&$select={select}"
        f"&$top=20000"
    )

    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()
    payload = resp.json()
    orders = payload.get("value", [])

    while "@odata.nextLink" in payload:
        resp = requests.get(payload["@odata.nextLink"], headers=headers, timeout=60)
        resp.raise_for_status()
        payload = resp.json()
        orders.extend(payload.get("value", []))

    return [
        {
            "id": o["id"],
            "number": o["number"],
            "orderDate": o.get("orderDate"),
            "status": o.get("status"),
            "customerId": o.get("customerId"),
            "customerName": o.get("customerName"),
            "totalAmountExcludingTax": o.get("totalAmountExcludingTax"),
            "totalAmountIncludingTax": o.get("totalAmountIncludingTax"),
            "currencyCode": o.get("currencyCode"),
        }
        for o in orders
    ]
