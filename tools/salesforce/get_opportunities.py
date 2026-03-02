from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
import requests
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

MY_APP_ID = "salesforce"

@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
    name="get_opportunities",
    description=(
        "Retrieve Salesforce opportunities filtered by a date range and optional stage. "
        "Supports preset ranges like 'last_month', 'this_quarter', 'last_quarter', "
        "'this_year', 'last_year', 'last_N_days', or a custom 'from_date'/'to_date'. "
        "Optionally filter by stage (e.g. 'Prospecting', 'Closed Won'). Leave stage blank for all."
    ),
)
def get_opportunities(
    preset: str = "",
    last_n_days: int = 0,
    from_date: str = "",
    to_date: str = "",
    stage: str = "",
) -> list[dict]:
    """Retrieve Salesforce opportunities filtered by date range and optional stage.

    Args:
        preset (str): One of: 'this_month', 'last_month', 'this_quarter', 'last_quarter',
                      'this_year', 'last_year', 'last_n_days'. Leave blank to use from_date/to_date.
        last_n_days (int): Number of days back from today. Used when preset='last_n_days'.
        from_date (str): Start date in YYYY-MM-DD format (used when no preset).
        to_date (str): End date in YYYY-MM-DD format (used when no preset).
        stage (str): Optional opportunity stage filter e.g. 'Closed Won', 'Prospecting'. Leave blank for all.

    Returns:
        list[dict]: Opportunities with keys: id, name, accountName, amount, stage, closeDate, owner, description.
    """
    today = datetime.today()

    if preset == "this_month":
        from_date = today.replace(day=1).strftime("%Y-%m-%d")
        to_date = today.strftime("%Y-%m-%d")
    elif preset == "last_month":
        first_of_this = today.replace(day=1)
        last_month_end = first_of_this - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        from_date = last_month_start.strftime("%Y-%m-%d")
        to_date = last_month_end.strftime("%Y-%m-%d")
    elif preset == "this_quarter":
        quarter = (today.month - 1) // 3
        from_date = datetime(today.year, quarter * 3 + 1, 1).strftime("%Y-%m-%d")
        to_date = today.strftime("%Y-%m-%d")
    elif preset == "last_quarter":
        quarter = (today.month - 1) // 3
        if quarter == 0:
            lq_start = datetime(today.year - 1, 10, 1)
            lq_end = datetime(today.year - 1, 12, 31)
        else:
            lq_start = datetime(today.year, (quarter - 1) * 3 + 1, 1)
            lq_end = datetime(today.year, quarter * 3, 1) - timedelta(days=1)
        from_date = lq_start.strftime("%Y-%m-%d")
        to_date = lq_end.strftime("%Y-%m-%d")
    elif preset == "this_year":
        from_date = datetime(today.year, 1, 1).strftime("%Y-%m-%d")
        to_date = today.strftime("%Y-%m-%d")
    elif preset == "last_year":
        from_date = datetime(today.year - 1, 1, 1).strftime("%Y-%m-%d")
        to_date = datetime(today.year - 1, 12, 31).strftime("%Y-%m-%d")
    elif preset == "last_n_days" and last_n_days > 0:
        from_date = (today - timedelta(days=last_n_days)).strftime("%Y-%m-%d")
        to_date = today.strftime("%Y-%m-%d")

    if not from_date or not to_date:
        raise ValueError("Provide a preset or both from_date and to_date.")

    conn = connections.oauth2_client_creds(MY_APP_ID)
    base = conn.url
    access_token = conn.access_token
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

    stage_filter = f" AND StageName = '{stage}'" if stage else ""
    soql = (
        f"SELECT Id, Name, Account.Name, Amount, StageName, CloseDate, Owner.Name, Description "
        f"FROM Opportunity "
        f"WHERE CloseDate >= {from_date} AND CloseDate <= {to_date}"
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
            "amount": r.get("Amount"),
            "stage": r.get("StageName"),
            "closeDate": r.get("CloseDate"),
            "owner": r.get("Owner", {}).get("Name") if r.get("Owner") else None,
            "description": r.get("Description"),
        }
        for r in records
    ]
