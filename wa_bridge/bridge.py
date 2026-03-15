"""
Planted WhatsApp Bridge Server

Receives WhatsApp messages via Twilio webhook, forwards them to the
Watson X Orchestrate WhatsApp Order Agent, and replies via Twilio.

Each phone number gets a fresh WXO thread on "hello"/"reset".
Within a session, messages reuse the same thread for multi-turn support.
"""

import os
import re
import time
import json
import base64
import logging
from datetime import datetime, timezone

import requests
from flask import Flask, request as flask_request
from twilio.rest import Client as TwilioClient
from dotenv import load_dotenv

load_dotenv()

# ── Configuration ────────────────────────────────────────────────────────────
TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

WXO_API_BASE = os.environ["WXO_API_BASE"]
WXO_API_KEY = os.environ["WXO_API_KEY"]
WXO_AGENT_ID = os.environ["WXO_AGENT_ID"]

PORT = int(os.environ.get("PORT", 5000))

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("wa_bridge")

# ── State: maps phone number → WXO thread_id ────────────────────────────────
phone_threads: dict[str, str] = {}

# ── Twilio client ────────────────────────────────────────────────────────────
twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# ── Flask app ────────────────────────────────────────────────────────────────
app = Flask(__name__)

# Greetings that trigger a new session (fresh thread)
GREETINGS = {"hello", "hi", "hey", "hallo", "hoi", "grüezi", "salut", "reset"}


# ═══════════════════════════════════════════════════════════════════════════════
#  WATSON X ORCHESTRATE API
# ═══════════════════════════════════════════════════════════════════════════════

_wxo_token: str | None = None
_wxo_token_expires: float = 0


def _get_wxo_token() -> str:
    """Exchange WXO API key for a bearer token (MCSP)."""
    global _wxo_token, _wxo_token_expires
    if _wxo_token and time.time() < _wxo_token_expires - 60:
        return _wxo_token

    try:
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
    except Exception as e:
        log.error(f"WXO token exchange failed: {e}")
        # Fallback: use API key directly
        _wxo_token = WXO_API_KEY
        _wxo_token_expires = time.time() + 3600
        return _wxo_token


def _wxo_headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_wxo_token()}",
        "Content-Type": "application/json",
    }


RUN_POLL_INTERVAL = 2
RUN_TIMEOUT = 120


def send_to_agent(
    phone: str,
    user_name: str,
    message: str,
    thread_id: str | None = None,
) -> tuple[str, str]:
    """Send a message to the WhatsApp Order Agent via the Orchestrate Runs API.

    The message is tagged with [WHATSAPP: phone | NAME: user_name] so the
    pre-invoke plugin can identify the caller.

    Returns (response_text, thread_id).
    """
    tagged_message = f"[WHATSAPP: {phone} | NAME: {user_name}] {message}"

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

    log.info(f"Sending to WXO agent (thread={thread_id}): {message[:80]}...")
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
                return content_parts[0].get("text", "Sorry, something went wrong."), new_thread_id
            return "Sorry, something went wrong.", new_thread_id

        if status in ("failed", "cancelled"):
            error = status_data.get("last_error") or status
            log.error(f"Run {run_id} {status}: {error}")
            return "Sorry, our ordering system encountered an error. Please try again.", new_thread_id

    log.error(f"Run {run_id} timed out after {RUN_TIMEOUT}s")
    return "Sorry, the request timed out. Please try again.", new_thread_id


# ═══════════════════════════════════════════════════════════════════════════════
#  TWILIO WEBHOOK
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/webhook", methods=["POST"])
def webhook():
    """Handle incoming WhatsApp messages from Twilio."""
    # Extract message data from Twilio webhook
    from_number = flask_request.form.get("From", "")  # e.g. "whatsapp:+41791234567"
    body = flask_request.form.get("Body", "").strip()
    profile_name = flask_request.form.get("ProfileName", "")

    # Clean phone number (remove "whatsapp:" prefix)
    phone = from_number.replace("whatsapp:", "")

    if not phone or not body:
        return "OK", 200

    log.info(f"WhatsApp from {profile_name} ({phone}): {body[:80]}")

    # Check if this is a reset → clear thread, reply directly (no WXO call)
    stripped = body.strip().lower()
    if stripped == "reset":
        old_thread = phone_threads.pop(phone, None)
        log.info(f"Reset for {phone} (old thread: {old_thread})")
        try:
            twilio_client.messages.create(
                from_=TWILIO_WHATSAPP_FROM,
                to=from_number,
                body="Session reset. Send *hello* to start a new conversation.",
            )
        except Exception as e:
            log.error(f"Twilio send error: {e}")
        return "OK", 200

    # Greetings start a fresh thread (but still go to WXO for the greeting response)
    if stripped in GREETINGS:
        old_thread = phone_threads.pop(phone, None)
        if old_thread:
            log.info(f"New session for {phone} (old thread: {old_thread})")

    # Get existing thread for this phone number
    thread_id = phone_threads.get(phone)

    # Send to WXO agent
    try:
        agent_response, new_thread_id = send_to_agent(phone, profile_name, body, thread_id)
        phone_threads[phone] = new_thread_id
        log.info(f"Agent response ({len(agent_response)} chars): {agent_response[:100]}...")
    except Exception as e:
        log.error(f"WXO agent error: {e}")
        agent_response = "Sorry, our ordering system is temporarily unavailable. Please try again."

    # Send reply via Twilio
    try:
        twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            to=from_number,
            body=agent_response,
        )
        log.info(f"Reply sent to {phone}")
    except Exception as e:
        log.error(f"Twilio send error: {e}")

    return "OK", 200


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok", "threads": len(phone_threads)}, 200


# ═══════════════════════════════════════════════════════════════════════════════
#  STARTUP
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    log.info("=" * 60)
    log.info("Planted WhatsApp Bridge Server")
    log.info(f"Twilio from: {TWILIO_WHATSAPP_FROM}")
    log.info(f"WXO Agent: {WXO_AGENT_ID}")
    log.info(f"Port: {PORT}")
    log.info("=" * 60)

    # Test WXO connection
    try:
        _get_wxo_token()
        log.info("Watson X Orchestrate: connected")
    except Exception as e:
        log.error(f"Watson X Orchestrate: FAILED - {e}")

    app.run(host="0.0.0.0", port=PORT, debug=False)
