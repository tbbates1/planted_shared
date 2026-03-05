from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
import requests

MY_APP_ID = "business_central"
COMPANY_ID = "572323a2-e013-f111-8405-7ced8d42f5ae"


@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    name="get_orders_by_date_range",
    description=(
        "Retrieve all sales orders placed within a given date range from Microsoft Dynamics 365 "
        "Business Central. Dates must be in YYYY-MM-DD format."
    ),
)
def get_orders_by_date_range(date_from: str, date_to: str) -> list[dict]:
    """Retrieve all sales orders whose order date falls within the specified range.

    Args:
        date_from (str): Start of the date range in ISO format YYYY-MM-DD (inclusive).
        date_to (str): End of the date range in ISO format YYYY-MM-DD (inclusive).

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
    for label, value in (("date_from", date_from), ("date_to", date_to)):
        parts = value.split("-")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            raise ValueError(f"{label} must be in YYYY-MM-DD format, got: {value!r}")

    conn = connections.oauth2_client_creds(MY_APP_ID)
    base = conn.url
    access_token = conn.access_token
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

    select = (
        "id,number,orderDate,status,customerId,customerName,"
        "totalAmountExcludingTax,totalAmountIncludingTax,currencyCode"
    )
    odata_filter = f"orderDate ge {date_from} and orderDate le {date_to}"
    url = (
        f"{base}/companies({COMPANY_ID})/salesOrders"
        f"?$filter={odata_filter}"
        f"&$select={select}"
        f"&$orderby=orderDate asc"
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
