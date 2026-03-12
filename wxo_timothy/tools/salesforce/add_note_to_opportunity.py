from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
import requests

MY_APP_ID = "salesforce"

@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_AUTH_CODE)],
    name="add_note_to_opportunity",
    description="Add a note to a Salesforce opportunity. Returns the new note id.",
)
def add_note_to_opportunity(
    opportunity_id: str,
    title: str,
    body: str = "",
) -> dict:
    """Add a Note to an existing Salesforce opportunity.

    Args:
        opportunity_id (str): The Salesforce ID of the opportunity (required).
        title (str): Title of the note (required).
        body (str): Body/content of the note (optional).

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
        "Title": title,
        "Body": body,
        "ParentId": opportunity_id,
    }

    resp = requests.post(
        f"{base}/services/data/v59.0/sobjects/Note",
        headers=headers,
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()

    return {"id": result.get("id"), "success": result.get("success", False)}
