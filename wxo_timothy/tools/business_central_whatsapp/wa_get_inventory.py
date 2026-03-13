from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
import requests

MY_APP_ID = "business_central_wa"
COMPANY_ID = "572323a2-e013-f111-8405-7ced8d42f5ae"


@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    name="wa_get_inventory",
    description="Get inventory items from Business Central with stock levels. Returns item id, number, name, stock, and unit of measure.",
)
def wa_get_inventory(search: str = "") -> list[dict]:
    """Get inventory items from Microsoft Dynamics 365 Business Central.

    Args:
        search (str): Optional partial item name to filter by. Leave blank for all items.

    Returns:
        list[dict]: Inventory items with keys: id, number, displayName, inventory, uom.
    """
    conn = connections.oauth2_client_creds(MY_APP_ID)
    base = conn.url
    access_token = conn.access_token
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

    url = (
        f"{base}/companies({COMPANY_ID})/items"
        f"?$select=id,number,displayName,type,inventory,baseUnitOfMeasureCode"
        f"&$filter=type eq 'Inventory'"
        f"&$top=20000"
    )

    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()
    payload = resp.json()
    items = payload.get("value", [])

    while "@odata.nextLink" in payload:
        resp = requests.get(payload["@odata.nextLink"], headers=headers, timeout=60)
        resp.raise_for_status()
        payload = resp.json()
        items.extend(payload.get("value", []))

    return [
        {
            "id": i["id"],
            "number": i["number"],
            "displayName": i["displayName"],
            "inventory": i.get("inventory"),
            "uom": i.get("baseUnitOfMeasureCode"),
        }
        for i in items
    ]
