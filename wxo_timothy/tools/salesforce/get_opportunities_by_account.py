from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
import requests

MY_APP_ID = "salesforce"

@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_AUTH_CODE)],
    name="get_opportunities_by_account",
    description=(
        "Retrieve all Salesforce opportunities for a specific account. "
        "Search by account name or pass an account ID directly."
    ),
)
def get_opportunities_by_account(
    account_name: str = "",
    account_id: str = "",
    stage: str = "",
) -> list[dict]:
    """Retrieve all opportunities for a specific Salesforce account.

    Args:
        account_name (str): Name of the account to search for (optional if account_id provided).
        account_id (str): Salesforce Account ID (optional if account_name provided).
        stage (str): Optional stage filter e.g. 'Closed Won'. Leave blank for all stages.

    Returns:
        list[dict]: Opportunities with keys: id, name, accountName, accountId, amount,
                    stage, closeDate, owner, description.
    """
    conn = connections.oauth2_auth_code(MY_APP_ID)
    base = conn.url
    access_token = conn.access_token
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

    if not account_id and not account_name:
        raise ValueError("Provide either account_name or account_id.")

    # Resolve account name to ID if needed
    if not account_id and account_name:
        acct_soql = f"SELECT Id FROM Account WHERE Name LIKE '%{account_name}%' LIMIT 1"
        acct_url = f"{base}/services/data/v59.0/query?q={requests.utils.quote(acct_soql)}"
        acct_resp = requests.get(acct_url, headers=headers, timeout=30)
        acct_resp.raise_for_status()
        records = acct_resp.json().get("records", [])
        if not records:
            return []
        account_id = records[0]["Id"]

    stage_filter = f" AND StageName = '{stage}'" if stage else ""
    soql = (
        f"SELECT Id, Name, Account.Name, AccountId, Amount, StageName, CloseDate, Owner.Name, Description "
        f"FROM Opportunity "
        f"WHERE AccountId = '{account_id}'"
        f"{stage_filter} "
        f"ORDER BY CloseDate ASC"
    )

    url = f"{base}/services/data/v59.0/query?q={requests.utils.quote(soql)}"
    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()
    records = resp.json().get("records", [])

    return [
        {
            "id": r["Id"],
            "name": r["Name"],
            "accountName": r.get("Account", {}).get("Name") if r.get("Account") else None,
            "accountId": r.get("AccountId"),
            "amount": r.get("Amount"),
            "stage": r.get("StageName"),
            "closeDate": r.get("CloseDate"),
            "owner": r.get("Owner", {}).get("Name") if r.get("Owner") else None,
            "description": r.get("Description"),
        }
        for r in records
    ]
