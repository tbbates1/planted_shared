from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
import requests

MY_APP_ID = "business_central_wa"
COMPANY_ID = "572323a2-e013-f111-8405-7ced8d42f5ae"


@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    name="wa_get_inventory",
    description="Get Planted products from Business Central. Returns two lists: in_stock (available to order) and out_of_stock (currently unavailable). Each item has id, name, unit price.",
)
def wa_get_inventory(search: str = "") -> dict:
    """Get products from Microsoft Dynamics 365 Business Central, split by availability.

    Args:
        search (str): Optional partial item name to filter by. Leave blank for all items.

    Returns:
        dict: Two keys — "in_stock" and "out_of_stock". Each is a list of items
              with keys: id, displayName, uom, unitPrice.
    """
    conn = connections.oauth2_client_creds(MY_APP_ID)
    base = conn.url
    access_token = conn.access_token
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

    url = (
        f"{base}/companies({COMPANY_ID})/items"
        f"?$select=id,number,displayName,type,baseUnitOfMeasureCode,unitPrice,inventory"
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

    in_stock = []
    out_of_stock = []
    for i in items:
        item_data = {
            "id": i["id"],
            "displayName": i["displayName"],
            "uom": i.get("baseUnitOfMeasureCode"),
            "unitPrice": i.get("unitPrice", 0),
        }
        if i.get("inventory", 0) > 0:
            in_stock.append(item_data)
        else:
            out_of_stock.append(item_data)

    return {"in_stock": in_stock, "out_of_stock": out_of_stock}
