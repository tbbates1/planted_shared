from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
import requests

MY_APP_ID = "business_central"

@tool(expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_AUTH_CODE)])
def get_inventory() -> list[dict]:
    """Get inventory items from Microsoft Dynamics 365 Business Central.

    Returns:
        list[dict]: Inventory items with keys:
            - id (str)
            - number (str)
            - displayName (str)
            - type (str | None)
            - inventory (number | None)
            - uom (str | None)
    """
    conn = connections.oauth2_auth_code(MY_APP_ID)
    base = conn.url
    access_token = conn.access_token
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

    company_id = "572323a2-e013-f111-8405-7ced8d42f5ae"

    url = (
        f"{base}/companies({company_id})/items"
        f"?$select=id,number,displayName,type,inventory,baseUnitOfMeasureCode"
        f"&$filter=type eq 'Inventory'"
        f"&$top=20000"
    )

    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()

    payload = resp.json()
    items = payload.get("value", [])

    while "@odata.nextLink" in payload:
        next_url = payload["@odata.nextLink"]
        resp = requests.get(next_url, headers=headers, timeout=60)
        resp.raise_for_status()
        payload = resp.json()
        items.extend(payload.get("value", []))

    return [
        {
            "id": i["id"],
            "number": i["number"],
            "displayName": i["displayName"],
            "type": i.get("type"),
            "inventory": i.get("inventory"),
            "uom": i.get("baseUnitOfMeasureCode"),
        }
        for i in items
    ]
