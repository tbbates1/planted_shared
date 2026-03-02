from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
import requests

MY_APP_ID = "salesforce"

@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    name="get_products_and_prices",
    description="Retrieve all active products and their prices from the Salesforce standard price book.",
)
def get_products_and_prices(search: str = "") -> list[dict]:
    """Retrieve products and prices from Salesforce standard price book.

    Args:
        search (str): Optional search string to filter products by name. Leave blank for all.

    Returns:
        list[dict]: Products with keys: id, productId, name, productCode, description, unitPrice, isActive.
    """
    conn = connections.oauth2_client_creds(MY_APP_ID)
    base = conn.url
    access_token = conn.access_token
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

    pb_soql = "SELECT Id FROM Pricebook2 WHERE IsStandard = true LIMIT 1"
    pb_url = f"{base}/services/data/v59.0/query?q={requests.utils.quote(pb_soql)}"
    pb_resp = requests.get(pb_url, headers=headers, timeout=30)
    pb_resp.raise_for_status()
    pb_records = pb_resp.json().get("records", [])
    if not pb_records:
        return []
    pricebook_id = pb_records[0]["Id"]

    search_filter = f" AND Product2.Name LIKE '%{search}%'" if search else ""
    soql = (
        f"SELECT Id, Product2Id, Product2.Name, Product2.ProductCode, Product2.Description, "
        f"UnitPrice, IsActive "
        f"FROM PricebookEntry "
        f"WHERE IsActive = true AND Pricebook2Id = '{pricebook_id}'"
        f"{search_filter} "
        f"ORDER BY Product2.Name ASC"
    )

    url = f"{base}/services/data/v59.0/query?q={requests.utils.quote(soql)}"
    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()
    records = resp.json().get("records", [])

    return [
        {
            "id": r["Id"],
            "productId": r.get("Product2Id"),
            "name": r.get("Product2", {}).get("Name") if r.get("Product2") else None,
            "productCode": r.get("Product2", {}).get("ProductCode") if r.get("Product2") else None,
            "description": r.get("Product2", {}).get("Description") if r.get("Product2") else None,
            "unitPrice": r.get("UnitPrice"),
            "isActive": r.get("IsActive"),
        }
        for r in records
    ]
