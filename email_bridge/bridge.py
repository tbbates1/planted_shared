"""
Planted Email Bridge Server

Polls an Outlook shared mailbox for new emails, forwards them to the
Watson X Orchestrate Email Order Agent, and replies with the agent's response.

Each email conversation thread maps to a WXO message thread for multi-turn support.
"""

import os
import re
import time
import json
import base64
import logging
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

# ── Configuration ────────────────────────────────────────────────────────────
MS_TENANT_ID = os.environ["MS_TENANT_ID"]
MS_CLIENT_ID = os.environ["MS_CLIENT_ID"]
MS_CLIENT_SECRET = os.environ["MS_CLIENT_SECRET"]
MAILBOX = os.environ["MAILBOX"]

WXO_API_BASE = os.environ["WXO_API_BASE"]
WXO_API_KEY = os.environ["WXO_API_KEY"]
WXO_AGENT_ID = os.environ["WXO_AGENT_ID"]

POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", 30))

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("email_bridge")

# ── State: maps Outlook conversationId → WXO thread_id ──────────────────────
conversation_threads: dict[str, str] = {}


# ═══════════════════════════════════════════════════════════════════════════════
#  MICROSOFT GRAPH API
# ═══════════════════════════════════════════════════════════════════════════════

_ms_token: str | None = None
_ms_token_expires: float = 0


def _get_ms_token() -> str:
    """Get or refresh a Microsoft Graph API access token."""
    global _ms_token, _ms_token_expires
    if _ms_token and time.time() < _ms_token_expires - 60:
        return _ms_token

    resp = requests.post(
        f"https://login.microsoftonline.com/{MS_TENANT_ID}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": MS_CLIENT_ID,
            "client_secret": MS_CLIENT_SECRET,
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    _ms_token = data["access_token"]
    _ms_token_expires = time.time() + data.get("expires_in", 3600)
    log.info("Microsoft Graph token refreshed")
    return _ms_token


def _graph_headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_ms_token()}",
        "Content-Type": "application/json",
    }


def fetch_unread_emails() -> list[dict]:
    """Fetch unread emails from the shared mailbox."""
    url = (
        f"https://graph.microsoft.com/v1.0/users/{MAILBOX}/mailFolders/inbox/messages"
        f"?$filter=isRead eq false"
        f"&$select=id,subject,body,from,conversationId,receivedDateTime"
        f"&$orderby=receivedDateTime asc"
        f"&$top=10"
    )
    resp = requests.get(url, headers=_graph_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json().get("value", [])


def mark_as_read(message_id: str) -> None:
    """Mark an email as read."""
    url = f"https://graph.microsoft.com/v1.0/users/{MAILBOX}/messages/{message_id}"
    requests.patch(url, headers=_graph_headers(), json={"isRead": True}, timeout=15)


def _markdown_to_html(text: str) -> str:
    """Convert simple markdown to HTML for email rendering."""
    html = text
    # Remove code block fences (```)
    html = re.sub(r"```\w*\n?", "", html)
    # Bold: **text** → <b>text</b>
    html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html)
    # Newlines → <br>
    html = html.replace("\n", "<br>\n")
    return html


def send_reply(message_id: str, reply_body: str) -> None:
    """Reply to an email."""
    url = f"https://graph.microsoft.com/v1.0/users/{MAILBOX}/messages/{message_id}/reply"
    html_body = _markdown_to_html(reply_body)
    resp = requests.post(
        url,
        headers=_graph_headers(),
        json={
            "message": {
                "body": {
                    "contentType": "HTML",
                    "content": html_body,
                },
            },
        },
        timeout=60,
    )
    if not resp.ok:
        log.error(f"Reply API error {resp.status_code}: {resp.text[:500]}")
    resp.raise_for_status()


def extract_plain_text(body: dict) -> str:
    """Extract plain text from email body (strip HTML if needed)."""
    content = body.get("content", "")
    content_type = body.get("contentType", "text")

    if content_type.lower() == "html":
        # Simple HTML tag stripping
        text = re.sub(r"<style[^>]*>.*?</style>", "", content, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"&lt;", "<", text)
        text = re.sub(r"&gt;", ">", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    return content.strip()


# ═══════════════════════════════════════════════════════════════════════════════
#  WATSON X ORCHESTRATE API
# ═══════════════════════════════════════════════════════════════════════════════

_wxo_token: str | None = None
_wxo_token_expires: float = 0


def _get_wxo_token() -> str:
    """Exchange WXO API key for a bearer token."""
    global _wxo_token, _wxo_token_expires
    if _wxo_token and time.time() < _wxo_token_expires - 60:
        return _wxo_token

    # Decode API key to get auth type and credentials
    # Format: base64(type:credentials)
    try:
        decoded = base64.b64decode(WXO_API_KEY).decode("utf-8")
        parts = decoded.split(":", 2)
        if len(parts) >= 3:
            auth_type = parts[0]
            # MCSP token exchange
            resp = requests.post(
                "https://iam.platform.saas.ibm.com/siusermgr/api/1.0/apikeys/token",
                json={"apikey": WXO_API_KEY},
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            _wxo_token = data.get("token") or data.get("access_token")
            _wxo_token_expires = time.time() + 3600
            log.info("WXO token refreshed")
            return _wxo_token
    except Exception:
        pass

    # Fallback: try using the API key directly as bearer token
    _wxo_token = WXO_API_KEY
    _wxo_token_expires = time.time() + 3600
    return _wxo_token


def _wxo_headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_wxo_token()}",
        "Content-Type": "application/json",
    }


RUN_POLL_INTERVAL = 2  # seconds between run status checks
RUN_TIMEOUT = 120  # max seconds to wait for a run to complete


def send_to_agent(sender_email: str, sender_name: str, message: str, thread_id: str | None = None) -> tuple[str, str]:
    """Send a message to the Email Order Agent via the Orchestrate Runs API.

    Returns (response_text, thread_id) so the caller can track the thread.
    """
    tagged_message = f"[EMAIL: {sender_email} | NAME: {sender_name}] {message}"

    url = f"{WXO_API_BASE}/v1/orchestrate/runs"
    body = {
        "agent_id": WXO_AGENT_ID,
        "message": {
            "role": "user",
            "content": tagged_message,
        },
    }

    if thread_id:
        body["thread_id"] = thread_id

    log.info(f"Sending to WXO agent: {message[:80]}...")
    resp = requests.post(url, headers=_wxo_headers(), json=body, timeout=30)
    resp.raise_for_status()

    run_data = resp.json()
    run_id = run_data["run_id"]
    new_thread_id = run_data.get("thread_id", thread_id)
    log.info(f"Run created: {run_id} (thread: {new_thread_id})")

    # Poll for completion
    status_url = f"{WXO_API_BASE}/v1/orchestrate/runs/{run_id}"
    deadline = time.time() + RUN_TIMEOUT
    while time.time() < deadline:
        time.sleep(RUN_POLL_INTERVAL)
        status_resp = requests.get(status_url, headers=_wxo_headers(), timeout=30)
        status_resp.raise_for_status()
        status_data = status_resp.json()
        status = status_data.get("status")

        if status == "completed":
            content_parts = (
                status_data.get("result", {})
                .get("data", {})
                .get("message", {})
                .get("content", [])
            )
            if content_parts:
                return content_parts[0].get("text", "Sorry, I could not process your request."), new_thread_id
            return "Sorry, I could not process your request.", new_thread_id

        if status in ("failed", "cancelled"):
            error = status_data.get("last_error") or status
            log.error(f"Run {run_id} {status}: {error}")
            return "Sorry, our ordering system encountered an error. Please try again.", new_thread_id

    log.error(f"Run {run_id} timed out after {RUN_TIMEOUT}s")
    return "Sorry, the request timed out. Please try again.", new_thread_id


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN LOOP
# ═══════════════════════════════════════════════════════════════════════════════

def process_email(email: dict) -> None:
    """Process a single incoming email."""
    message_id = email["id"]
    subject = email.get("subject", "(no subject)")
    sender = email.get("from", {}).get("emailAddress", {})
    sender_email = sender.get("address", "unknown@unknown.com")
    sender_name = sender.get("name", sender_email)
    conversation_id = email.get("conversationId", message_id)
    body_text = extract_plain_text(email.get("body", {}))

    log.info(f"New email from {sender_name} <{sender_email}>: {subject}")

    # Skip emails from ourselves (avoid reply loops)
    if sender_email.lower() == MAILBOX.lower():
        log.info("Skipping self-sent email")
        mark_as_read(message_id)
        return

    # Skip system/bounce emails (Undeliverable, NDR, etc.)
    if sender_email.lower().endswith("@planted2.onmicrosoft.com") and sender_email.lower() != MAILBOX.lower():
        log.info(f"Skipping system email from {sender_email}")
        mark_as_read(message_id)
        return
    if subject.lower().startswith("undeliverable"):
        log.info(f"Skipping bounce notification: {subject}")
        mark_as_read(message_id)
        return

    # Get existing WXO thread for this email conversation (if any)
    thread_id = conversation_threads.get(conversation_id)

    # Send to agent
    try:
        agent_response, thread_id = send_to_agent(sender_email, sender_name, body_text, thread_id)
        conversation_threads[conversation_id] = thread_id
        log.info(f"Agent response: {agent_response[:100]}...")
    except Exception as e:
        log.error(f"WXO agent error: {e}")
        agent_response = (
            "Sorry, our ordering system is temporarily unavailable. "
            "Please try again in a few minutes or contact us directly."
        )

    # Reply to the email
    try:
        send_reply(message_id, agent_response)
        log.info(f"Reply sent to {sender_email}")
    except Exception as e:
        log.error(f"Failed to send reply: {e}")

    # Mark as read
    mark_as_read(message_id)


def main() -> None:
    """Main polling loop."""
    log.info("=" * 60)
    log.info("Planted Email Bridge Server")
    log.info(f"Mailbox: {MAILBOX}")
    log.info(f"Agent ID: {WXO_AGENT_ID}")
    log.info(f"Poll interval: {POLL_INTERVAL}s")
    log.info("=" * 60)

    # Test connections on startup
    try:
        _get_ms_token()
        log.info("Microsoft Graph: connected")
    except Exception as e:
        log.error(f"Microsoft Graph: FAILED - {e}")
        return

    try:
        _get_wxo_token()
        log.info("Watson X Orchestrate: connected")
    except Exception as e:
        log.error(f"Watson X Orchestrate: FAILED - {e}")
        return

    log.info("Listening for emails...")

    while True:
        try:
            emails = fetch_unread_emails()
            if emails:
                log.info(f"Found {len(emails)} unread email(s)")
            for email in emails:
                try:
                    process_email(email)
                except Exception as e:
                    log.error(f"Error processing email {email.get('id', '?')}: {e}")
                    # Mark as read to avoid reprocessing
                    try:
                        mark_as_read(email["id"])
                    except Exception:
                        pass
        except Exception as e:
            log.error(f"Error fetching emails: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
