from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.connections import ExpectedCredentials, ConnectionType
from ibm_watsonx_orchestrate.run import connections
import requests
from datetime import datetime

MY_APP_ID = "salesforce"

@tool(
    expected_credentials=[ExpectedCredentials(app_id=MY_APP_ID, type=ConnectionType.OAUTH2_AUTH_CODE)],
    name="log_call_on_opportunity",
    description="Log a completed call activity on a Salesforce opportunity.",
)
def log_call_on_opportunity(
    opportunity_id: str,
    subject: str,
    description: str = "",
    call_date: str = "",
    duration_minutes: int = 0,
) -> dict:
    """Log a completed call (Task) on an existing Salesforce opportunity.

    Args:
        opportunity_id (str): The Salesforce ID of the opportunity (required).
        subject (str): Subject/title of the call e.g. 'Call with customer' (required).
        description (str): Notes or summary of the call (optional).
        call_date (str): Date of the call in YYYY-MM-DD format. Defaults to today (optional).
        duration_minutes (int): Duration of the call in minutes (optional).

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

    if not call_date:
        call_date = datetime.today().strftime("%Y-%m-%d")

    payload = {
        "Subject": subject,
        "WhatId": opportunity_id,
        "Status": "Completed",
        "TaskSubtype": "Call",
        "ActivityDate": call_date,
        "Description": description,
    }
    if duration_minutes:
        payload["CallDurationInSeconds"] = duration_minutes * 60

    resp = requests.post(
        f"{base}/services/data/v59.0/sobjects/Task",
        headers=headers,
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()

    return {"id": result.get("id"), "success": result.get("success", False)}
