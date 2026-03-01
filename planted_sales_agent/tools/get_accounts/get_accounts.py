from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
import requests

MY_APP_ID = "salesforce"

@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    name="get_accounts",
    description="Retrieve all Salesforce accounts with key details including name, industry, phone, and billing address.",
)
def get_accounts(search: str = "") -> list[dict]:
    """Retrieve Salesforce accounts, optionally filtered by name search.

    Args:
        search (str): Optional search string to filter accounts by name. Leave blank for all.

    Returns:
        list[dict]: Accounts with keys: id, name, industry, phone, website, billingCity, billingCountry.
    """
    conn = connections.oauth2_client_creds(MY_APP_ID)
    base = conn.url
    access_token = conn.access_token
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

    search_filter = f" WHERE Name LIKE '%{search}%'" if search else ""
    soql = (
        f"SELECT Id, Name, Industry, Phone, Website, BillingCity, BillingCountry "
        f"FROM Account"
        f"{search_filter} "
        f"ORDER BY Name ASC"
    )

    url = f"{base}/services/data/v59.0/query?q={requests.utils.quote(soql)}"
    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()
    records = resp.json().get("records", [])

    return [
        {
            "id": r["Id"],
            "name": r["Name"],
            "industry": r.get("Industry"),
            "phone": r.get("Phone"),
            "website": r.get("Website"),
            "billingCity": r.get("BillingCity"),
            "billingCountry": r.get("BillingCountry"),
        }
        for r in records
    ]
