"""Tool: get all Planted products with availability."""

import requests
from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
from ibm_watsonx_orchestrate.run.context import AgentRun

MY_APP_ID = "business_central_wa"
COMPANY_ID = "572323a2-e013-f111-8405-7ced8d42f5ae"


@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    name="wa_get_products",
    description="Get all Planted products with prices and stock status. Returns in_stock and out_of_stock lists. Use item IDs from in_stock when creating orders.",
)
def wa_get_products(context: AgentRun, customer_id: str) -> dict:
    """Get products split by availability.

    Args:
        context: Agent run context (auto-filled).
        customer_id: Customer GUID from the [VERIFIED] tag.
    """
    if not customer_id:
        return {"error": "customer_id is required."}

    conn = connections.oauth2_client_creds(MY_APP_ID)
    base = conn.url
    headers = {"Authorization": f"Bearer {conn.access_token}", "Accept": "application/json"}

    # Fetch items
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

    in_stock, out_of_stock = [], []
    for i in items:
        entry = {"id": i["id"], "displayName": i["displayName"], "uom": i.get("baseUnitOfMeasureCode"), "unitPrice": i.get("unitPrice", 0)}
        (in_stock if i.get("inventory", 0) > 0 else out_of_stock).append(entry)

    return {"in_stock": in_stock, "out_of_stock": out_of_stock}
