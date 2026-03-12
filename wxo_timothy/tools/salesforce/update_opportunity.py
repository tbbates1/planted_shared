from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
import requests

MY_APP_ID = "salesforce"

@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_AUTH_CODE)],
    name="update_opportunity",
    description=(
        "Update fields on an existing Salesforce opportunity. "
        "Only provide the fields you want to change — all fields are optional except opportunity_id."
    ),
)
def update_opportunity(
    opportunity_id: str,
    name: str = "",
    stage: str = "",
    close_date: str = "",
    amount: float = 0,
    description: str = "",
    account_id: str = "",
) -> dict:
    """Update an existing Salesforce opportunity.

    Args:
        opportunity_id (str): The Salesforce ID of the opportunity to update (required).
        name (str): New name for the opportunity (optional).
        stage (str): New stage e.g. 'Closed Won', 'Prospecting' (optional).
        close_date (str): New close date in YYYY-MM-DD format (optional).
        amount (float): New opportunity amount (optional).
        description (str): New description or notes (optional).
        account_id (str): New account ID to reassign to (optional).

    Returns:
        dict: Keys: success (bool), opportunity_id (str).
    """
    conn = connections.oauth2_auth_code(MY_APP_ID)
    base = conn.url
    access_token = conn.access_token
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    payload = {}
    if name:
        payload["Name"] = name
    if stage:
        payload["StageName"] = stage
    if close_date:
        payload["CloseDate"] = close_date
    if amount:
        payload["Amount"] = amount
    if description:
        payload["Description"] = description
    if account_id:
        payload["AccountId"] = account_id

    if not payload:
        raise ValueError("At least one field to update must be provided.")

    resp = requests.patch(
        f"{base}/services/data/v59.0/sobjects/Opportunity/{opportunity_id}",
        headers=headers,
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()

    return {"success": True, "opportunity_id": opportunity_id}
