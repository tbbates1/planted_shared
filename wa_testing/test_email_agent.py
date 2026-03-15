"""Quick test for the Email Order Agent via WXO API — no real emails needed."""

import sys
import time
import requests
from dotenv import load_dotenv
import os

load_dotenv("email_bridge/.env")

WXO_API_BASE = os.environ["WXO_API_BASE"]
WXO_API_KEY = os.environ["WXO_API_KEY"]
WXO_AGENT_ID = os.environ["WXO_AGENT_ID"]

_token = None
_token_expires = 0

def _get_token():
    global _token, _token_expires
    if _token and time.time() < _token_expires:
        return _token
    resp = requests.post(
        "https://iam.platform.saas.ibm.com/siusermgr/api/1.0/apikeys/token",
        json={"apikey": WXO_API_KEY},
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    _token = data.get("token") or data.get("access_token")
    _token_expires = time.time() + 3600
    return _token

def _headers():
    return {"Authorization": f"Bearer {_get_token()}", "Content-Type": "application/json"}

def send(message, sender_email="tbbates12@gmail.com", sender_name="Timothy Bates", thread_id=None):
    tagged = f"[EMAIL: {sender_email} | NAME: {sender_name}] {message}"
    body = {"agent_id": WXO_AGENT_ID, "message": {"role": "user", "content": tagged}}
    if thread_id:
        body["thread_id"] = thread_id

    print(f"\n{'='*60}")
    print(f">>> {message}")
    print(f"{'='*60}")

    resp = requests.post(f"{WXO_API_BASE}/v1/orchestrate/runs", headers=_headers(), json=body, timeout=30)
    resp.raise_for_status()
    run_data = resp.json()
    run_id = run_data["run_id"]
    thread_id = run_data.get("thread_id", thread_id)

    for _ in range(60):
        time.sleep(2)
        sr = requests.get(f"{WXO_API_BASE}/v1/orchestrate/runs/{run_id}", headers=_headers(), timeout=30)
        sr.raise_for_status()
        sd = sr.json()
        status = sd.get("status")
        if status == "completed":
            parts = sd.get("result", {}).get("data", {}).get("message", {}).get("content", [])
            reply = parts[0].get("text", "(empty)") if parts else "(empty)"
            print(f"\n<<< {reply}\n")
            return reply, thread_id
        if status in ("failed", "cancelled"):
            error = sd.get("result", {}).get("data", {}).get("message", {}).get("content", [])
            err_text = error[0].get("text", str(sd)) if error else str(sd)
            print(f"\n!!! FAILED: {err_text}\n")
            return err_text, thread_id

    print("\n!!! TIMEOUT\n")
    return "(timeout)", thread_id

if __name__ == "__main__":
    msg = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Hi, I'd like to order 50 schnitzel and 20 bratwurst please."
    send(msg)
