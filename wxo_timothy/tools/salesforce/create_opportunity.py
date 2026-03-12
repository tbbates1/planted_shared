from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
import requests

MY_APP_ID = "salesforce"

@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_AUTH_CODE)],
    name="create_opportunity",
    description="Create a new opportunity in Salesforce. Returns the new opportunity id.",
)
def create_opportunity(
    name: str,
    account_id: str,
    stage: str,
    close_date: str,
    amount: float = 0,
    description: str = "",
) -> dict:
    """Create a new Salesforce opportunity.

    Args:
        name (str): Name of the opportunity (required).
        account_id (str): Salesforce Account ID to associate with (required). Use get_accounts to find.
        stage (str): Sales stage e.g. 'Prospecting', 'Qualification', 'Proposal/Price Quote',
                     'Value Proposition', 'Id. Decision Makers', 'Perception Analysis',
                     'Needs Analysis', 'Closed Won', 'Closed Lost' (required).
        close_date (str): Expected close date in YYYY-MM-DD format (required).
        amount (float): Opportunity value amount (optional).
        description (str): Additional notes or description (optional).

    Returns:
        dict: Keys: id (str), success (bool).
    """
    conn = connections.oauth2_auth_code(MY_APP_ID)
    base = conn.url
    access_token = conn.access_token
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    payload = {
        "Name": name,
        "AccountId": account_id,
        "StageName": stage,
        "CloseDate": close_date,
    }
    if amount:
        payload["Amount"] = amount
    if description:
        payload["Description"] = description

    resp = requests.post(
        f"{base}/services/data/v59.0/sobjects/Opportunity",
        headers=headers,
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()

    return {"id": result.get("id"), "success": result.get("success", False)}
