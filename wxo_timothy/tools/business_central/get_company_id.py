from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
import requests

MY_APP_ID = "business_central"

@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_AUTH_CODE)]
)
def get_company_id() -> list[dict]:
    """Returns all Business Central companies with their IDs and names."""

    conn = connections.oauth2_auth_code(MY_APP_ID)
    base = conn.url
    access_token = conn.access_token
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

    resp = requests.get(f"{base}/companies", headers=headers, timeout=60)
    resp.raise_for_status()

    return resp.json()["value"]
