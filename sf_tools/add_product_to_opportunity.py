from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
import requests

MY_APP_ID = "salesforce"

@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    name="add_product_to_opportunity",
    description=(
        "Add a product line item to an existing Salesforce opportunity. "
        "Use get_products_and_prices first to find the product ID and price. "
        "Returns the new line item id."
    ),
)
def add_product_to_opportunity(
    opportunity_id: str,
    pricebook_entry_id: str,
    quantity: float,
    unit_price: float = 0,
    description: str = "",
) -> dict:
    """Add a product to an existing Salesforce opportunity as a line item.

    Args:
        opportunity_id (str): The Salesforce ID of the opportunity (required).
        pricebook_entry_id (str): The PricebookEntry ID of the product (required).
                                   Get this from get_products_and_prices — it is the 'id' field.
        quantity (float): Quantity of the product to add (required).
        unit_price (float): Override the unit price. Leave as 0 to use the standard price book price (optional).
        description (str): Optional line item description or note (optional).

    Returns:
        dict: Keys: id (str), success (bool).
    """
    conn = connections.oauth2_client_creds(MY_APP_ID)
    base = conn.url
    access_token = conn.access_token
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    # First ensure the opportunity has the standard pricebook assigned
    pb_soql = "SELECT Id FROM Pricebook2 WHERE IsStandard = true LIMIT 1"
    pb_url = f"{base}/services/data/v59.0/query?q={requests.utils.quote(pb_soql)}"
    pb_resp = requests.get(pb_url, headers=headers, timeout=30)
    pb_resp.raise_for_status()
    pb_records = pb_resp.json().get("records", [])
    if not pb_records:
        raise ValueError("No standard pricebook found in Salesforce.")
    pricebook_id = pb_records[0]["Id"]

    # Assign pricebook to opportunity if not already set
    opp_resp = requests.patch(
        f"{base}/services/data/v59.0/sobjects/Opportunity/{opportunity_id}",
        headers=headers,
        json={"Pricebook2Id": pricebook_id},
        timeout=30,
    )
    opp_resp.raise_for_status()

    # Build line item payload
    payload = {
        "OpportunityId": opportunity_id,
        "PricebookEntryId": pricebook_entry_id,
        "Quantity": quantity,
    }
    if unit_price:
        payload["UnitPrice"] = unit_price
    if description:
        payload["Description"] = description

    resp = requests.post(
        f"{base}/services/data/v59.0/sobjects/OpportunityLineItem",
        headers=headers,
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()

    return {"id": result.get("id"), "success": result.get("success", False)}
