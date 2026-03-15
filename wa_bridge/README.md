# WhatsApp Bridge Server

Custom middleware that connects WhatsApp (via Twilio) to the Watson X Orchestrate Order Agent. Controls thread lifecycle to prevent context pollution.

## Architecture

```
WhatsApp → Twilio Webhook → Bridge Server → WXO Runs API → Agent
                                  ↕
                          phone_threads dict
                    (new thread on hello/reset)
```

## Why a Bridge?

WXO's native WhatsApp channel creates one persistent thread per phone number. Over time, 50K+ tokens of old conversation accumulate, causing the LLM to hallucinate instead of calling tools. The bridge solves this by creating fresh WXO threads on demand.

## Setup

1. Copy `.env.example` to `.env` and fill in credentials
2. Install dependencies: `pip install -r requirements.txt`
3. Run: `python3 bridge.py`
4. Expose publicly: `ngrok http 5001`
5. Set the Twilio WhatsApp webhook to `https://<ngrok-url>/webhook`

## Session Management

- **"reset"** — clears the thread, replies with a confirmation message (no WXO call)
- **"hello"/"hi"/"hey"** — creates a fresh WXO thread, shows order greeting
- All other messages reuse the current thread for multi-turn conversation

## Environment Variables

| Variable | Description |
|----------|-------------|
| `TWILIO_ACCOUNT_SID` | Twilio Account SID |
| `TWILIO_AUTH_TOKEN` | Twilio Auth Token |
| `TWILIO_WHATSAPP_FROM` | Twilio WhatsApp number (e.g. `whatsapp:+14155238886`) |
| `WXO_API_BASE` | WXO instance URL |
| `WXO_API_KEY` | WXO API key (base64 encoded) |
| `WXO_AGENT_ID` | Agent ID for the WhatsApp Order Agent |
| `PORT` | Server port (default: 5000) |
