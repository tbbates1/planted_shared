"""Tool: get all Planted products with availability and pricing for the shop agent."""

import requests
from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
from ibm_watsonx_orchestrate.run.context import AgentRun

MY_APP_ID = "business_central_timothy"
COMPANY_ID = "572323a2-e013-f111-8405-7ced8d42f5ae"


@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    name="shop_get_products",
    description="Get all Planted products with prices and stock status. Returns in_stock (full details) and out_of_stock_names (names only). Use item IDs from in_stock when creating orders.",
)
def shop_get_products(context: AgentRun) -> dict:
    """Get products split by availability.

    Args:
        context: Agent run context (auto-filled).

    Returns:
        dict: Keys: in_stock (list of dicts with id, displayName, uom, unitPrice), out_of_stock_names (list of product name strings).
    """
    conn = connections.oauth2_client_creds(MY_APP_ID)
    base = conn.url
    headers = {"Authorization": f"Bearer {conn.access_token}", "Accept": "application/json"}

    url = (
        f"{base}/companies({COMPANY_ID})/items"
        f"?$select=id,displayName,baseUnitOfMeasureCode,unitPrice,inventory"
        f"&$filter=type eq 'Inventory'&$top=20000"
    )
    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    items = data.get("value", [])
    while "@odata.nextLink" in data:
        resp = requests.get(data["@odata.nextLink"], headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        items.extend(data.get("value", []))

    in_stock, out_of_stock_names = [], []
    for i in items:
        if i.get("inventory", 0) > 0:
            in_stock.append({
                "id": i["id"],
                "displayName": i["displayName"],
                "uom": i.get("baseUnitOfMeasureCode"),
                "unitPrice": i.get("unitPrice", 0),
            })
        else:
            out_of_stock_names.append(i["displayName"])

    return {"in_stock": in_stock, "out_of_stock_names": out_of_stock_names}
