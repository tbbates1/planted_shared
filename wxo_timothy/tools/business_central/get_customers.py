from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
import requests

MY_APP_ID = "business_central"

@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_AUTH_CODE)]
)
def get_customers() -> list[dict]:
    """Gets all customers from Microsoft Dynamics 365 Business Central.

    Returns:
        list[dict]: Customers with keys: id, number, displayName.
    """

    conn = connections.oauth2_auth_code(MY_APP_ID)
    base = conn.url
    company_id = "572323a2-e013-f111-8405-7ced8d42f5ae"
    access_token = conn.access_token

    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

    url = (
        f"{base}/companies({company_id})/customers"
        f"?$select=id,number,displayName"
        f"&$top=20000"
    )

    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()
    payload = resp.json()

    customers = payload.get("value", [])

    while "@odata.nextLink" in payload:
        resp = requests.get(payload["@odata.nextLink"], headers=headers, timeout=60)
        resp.raise_for_status()
        payload = resp.json()
        customers.extend(payload.get("value", []))

    return [
        {"id": c["id"], "number": c["number"], "displayName": c["displayName"]}
        for c in customers
    ]
