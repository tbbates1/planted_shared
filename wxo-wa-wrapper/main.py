"""
Planted WhatsApp Wrapper for Watson X Orchestrate

Receives Twilio WhatsApp webhooks, forwards messages to the WXO Shop_Agent_WA
via the Runs API (passing phone_number as context variable), polls for the
agent response, and replies with TwiML.
"""

import os
import asyncio
import logging

import httpx
from fastapi import FastAPI, Form, Response

WO_API_KEY = os.environ["WO_API_KEY"]
WO_INSTANCE = os.environ["WO_INSTANCE"]
WO_AGENT_ID = os.environ["WO_AGENT_ID"]
TOKEN_URL = "https://iam.platform.saas.ibm.com/siusermgr/api/1.0/apikeys/token"
BASE_URL = f"{WO_INSTANCE}/v1/orchestrate"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wa-wrapper")

# phone -> thread_id
phone_threads: dict[str, str] = {}


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


async def call_agent(phone: str, message: str) -> str:
    token = await _get_token()
    headers = _auth(token)

    thread_id = phone_threads.get(phone)

    async with httpx.AsyncClient() as client:
        # Create thread if needed
        if not thread_id:
            resp = await client.post(
                f"{BASE_URL}/threads",
                json={"agent_id": WO_AGENT_ID},
                headers=headers,
                timeout=30.0,
            )
            resp.raise_for_status()
            thread_id = resp.json()["thread_id"]
            phone_threads[phone] = thread_id
            log.info("New thread %s for %s", thread_id, phone)

        # Post run
        payload = {
            "agent_id": WO_AGENT_ID,
            "thread_id": thread_id,
            "message": {"role": "user", "content": message},
            "context": {"phone_number": phone},
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
        log.info("Run started for %s, message_id=%s", phone, message_id)

        # Poll for assistant response
        for _ in range(30):
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


app = FastAPI(title="WXO WhatsApp Wrapper")


def _twiml(text: str) -> Response:
    # Escape XML special chars
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    xml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{safe}</Message></Response>'
    return Response(content=xml, media_type="application/xml")


@app.post("/whatsapp")
async def whatsapp(From: str = Form(""), Body: str = Form("")):
    phone = From.replace("whatsapp:", "").strip()
    message = Body.strip()

    if not phone or not message:
        return _twiml("Sorry, I could not read your message.")

    log.info("Incoming phone=%s msg=%s", phone, message[:80])

    # Reset command
    if message.lower() == "reset":
        old = phone_threads.pop(phone, None)
        log.info("Reset for %s (old thread: %s)", phone, old)
        return _twiml("Conversation reset. Send a new message to start fresh.")

    try:
        agent_reply = await call_agent(phone, message)
    except Exception as e:
        log.error("Agent call failed: %s", e)
        agent_reply = "Sorry, our ordering system is temporarily unavailable."

    log.info("Reply (%d chars): %s", len(agent_reply), agent_reply[:100])
    return _twiml(agent_reply)


@app.get("/health")
async def health():
    return {"status": "ok", "threads": len(phone_threads)}


@app.get("/")
async def root():
    return {"status": "ok", "service": "WXO WhatsApp Wrapper"}
