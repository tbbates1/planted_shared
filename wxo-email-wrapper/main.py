"""
Planted Email Wrapper for Watson X Orchestrate

Receives POST requests with email_address + message, forwards to the
WXO Shop_Agent_Email via the Runs API (passing email_address as context),
polls for the agent response, and returns the result.

The agent itself sends the email via SendGrid — this wrapper just
orchestrates the one-shot interaction.
"""

import os
import asyncio
import logging

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

WO_API_KEY = os.environ["WO_API_KEY"]
WO_INSTANCE = os.environ["WO_INSTANCE"]
WO_AGENT_ID = os.environ["WO_AGENT_ID"]
TOKEN_URL = "https://iam.platform.saas.ibm.com/siusermgr/api/1.0/apikeys/token"
BASE_URL = f"{WO_INSTANCE}/v1/orchestrate"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("email-wrapper")


async def _get_token() -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TOKEN_URL,
            json={"apikey": WO_API_KEY},
            headers={"Accept": "application/json"},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()["token"]


def _auth(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def call_agent(email_address: str, message: str) -> str:
    token = await _get_token()
    headers = _auth(token)

    async with httpx.AsyncClient() as client:
        # Create a new thread (one-shot, no reuse)
        resp = await client.post(
            f"{BASE_URL}/threads",
            json={"agent_id": WO_AGENT_ID},
            headers=headers,
            timeout=30.0,
        )
        resp.raise_for_status()
        thread_id = resp.json()["thread_id"]
        log.info("Thread created: %s", thread_id)

        # Post run with context
        payload = {
            "agent_id": WO_AGENT_ID,
            "thread_id": thread_id,
            "message": {"role": "user", "content": message},
            "context": {"email_address": email_address},
        }
        resp = await client.post(
            f"{BASE_URL}/runs",
            params={"stream": "False"},
            json=payload,
            headers=headers,
            timeout=60.0,
        )
        resp.raise_for_status()
        message_id = resp.json().get("message_id", "")
        log.info("Run started, message_id=%s", message_id)

        # Poll for assistant response
        for _ in range(40):
            await asyncio.sleep(3)
            try:
                resp = await client.get(
                    f"{BASE_URL}/threads/{thread_id}/messages",
                    headers=headers,
                    timeout=30.0,
                )
                resp.raise_for_status()
                for msg in resp.json():
                    if (
                        msg.get("role") == "assistant"
                        and msg.get("parent_message_id") == message_id
                    ):
                        content = msg.get("content", [])
                        if content:
                            return content[0].get("text", "")
            except Exception as e:
                log.warning("Poll error: %s", e)

    return "Sorry, the request timed out. Please try again."


app = FastAPI(title="WXO Email Wrapper")


class SendEmailRequest(BaseModel):
    email_address: str
    message: str


@app.post("/send-email")
async def send_email(req: SendEmailRequest):
    email_address = req.email_address.strip()
    message = req.message.strip()

    if not email_address or not message:
        return {"error": "email_address and message are required."}

    log.info("Incoming email=%s msg=%s", email_address, message[:80])

    try:
        agent_reply = await call_agent(email_address, message)
        email_sent = True
    except Exception as e:
        log.error("Agent call failed: %s", e)
        agent_reply = "Sorry, our ordering system is temporarily unavailable."
        email_sent = False

    log.info("Reply (%d chars): %s", len(agent_reply), agent_reply[:100])
    return {
        "email": email_address,
        "message": agent_reply,
        "email_sent": email_sent,
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    return {"status": "ok", "service": "WXO Email Wrapper"}
