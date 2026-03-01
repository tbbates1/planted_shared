from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
import requests

MY_APP_ID = "salesforce"

@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    name="get_opportunity_products",
    description="Retrieve all products and line items on a specific Salesforce opportunity.",
)
def get_opportunity_products(opportunity_id: str) -> list[dict]:
    """Retrieve all product line items on a Salesforce opportunity.

    Args:
        opportunity_id (str): The Salesforce ID of the opportunity (required).

    Returns:
        list[dict]: Line items with keys: id, productName, productCode, quantity,
                    unitPrice, totalPrice, discount, description.
    """
    conn = connections.oauth2_client_creds(MY_APP_ID)
    base = conn.url
    access_token = conn.access_token
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

    soql = (
        f"SELECT Id, PricebookEntry.Product2.Name, PricebookEntry.Product2.ProductCode, "
        f"Quantity, UnitPrice, TotalPrice, Discount, Description "
        f"FROM OpportunityLineItem "
        f"WHERE OpportunityId = '{opportunity_id}'"
    )

    url = f"{base}/services/data/v59.0/query?q={requests.utils.quote(soql)}"
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    records = resp.json().get("records", [])

    return [
        {
            "id": r["Id"],
            "productName": r.get("PricebookEntry", {}).get("Product2", {}).get("Name") if r.get("PricebookEntry") else None,
            "productCode": r.get("PricebookEntry", {}).get("Product2", {}).get("ProductCode") if r.get("PricebookEntry") else None,
            "quantity": r.get("Quantity"),
            "unitPrice": r.get("UnitPrice"),
            "totalPrice": r.get("TotalPrice"),
            "discount": r.get("Discount"),
            "description": r.get("Description"),
        }
        for r in records
    ]
