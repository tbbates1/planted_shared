# Planted Order Agent

![Architecture](photos/029.png)

Automated order processing for [Planted](https://www.planted.ch) powered by watsonx Orchestrate and Microsoft Dynamics 365 Business Central. Customers place orders via email or WhatsApp — the agent creates sales quotes in BC and responds automatically.

---

## Shop Agent Email

**One request → one sales quote → one email with BC PDF attached.**

The email agent receives an order request, creates a sales quote in Business Central, downloads the official BC quote as a PDF, and emails it to the customer — all in a single step.

### How it works

```
POST /send-email {email_address, message}
  → WXO agent parses order, matches products
  → Creates sales quote in Business Central
  → Downloads BC sales quote PDF
  → Sends email with PDF attached via SendGrid
  → Returns confirmation
```

### API

```bash
curl -X POST https://wxo-email-wrapper.27n8kz0d49mj.us-south.codeengine.appdomain.cloud/send-email \
  -H "Content-Type: application/json" \
  -d '{
    "email_address": "timothy.bates@ibm.com",
    "message": "Order 200 planted.steak Classic and 100 planted.duck Asian Style"
  }'
```

**Response:**
```json
{
  "email": "timothy.bates@ibm.com",
  "message": "Quote SQ0118 created and emailed.",
  "email_sent": true
}
```

**Swagger UI:** [wxo-email-wrapper.../docs](https://wxo-email-wrapper.27n8kz0d49mj.us-south.codeengine.appdomain.cloud/docs)

### Handles 4 scenarios

| Scenario | What happens |
|---|---|
| Valid order | Creates BC quote → emails PDF to customer |
| Partial out-of-stock | Creates quote with available items, notes OOS items in email |
| All items out-of-stock | Sends email: "items unavailable" |
| Unregistered email | Sends email: "not registered, contact sales@planted.ch" |

### Structure

```
shop_agent_email/
├── agents/Shop_Agent_Email.yaml
└── tools/business_central_shop/
    ├── _customer_lookup_em.py              # email → customer_id
    ├── shop_get_products_em.py             # product catalog
    └── shop_create_quote_and_email_em.py   # creates quote + fetches PDF + sends email
```

---

## Shop Agent WhatsApp

**Interactive order agent on WhatsApp via Twilio.**

Customers text the WhatsApp number to browse products, place orders, modify, cancel, and reorder — just like chatting with a person. Customer identified by phone number.

### How it works

```
Customer sends WhatsApp message
  → Twilio webhook → Code Engine wrapper
  → WXO agent processes with phone_number context
  → Agent responds via TwiML → WhatsApp reply
```

### Setup

Set this webhook URL in Twilio Sandbox settings ("When a message comes in"):

```
https://wxo-wa-wrapper.27n8kz0d49mj.us-south.codeengine.appdomain.cloud/whatsapp
```

### Commands

| Message | What happens |
|---|---|
| `hi` | Greets by name, shows last order and pending orders |
| `what products do you have` | Lists in-stock products with prices |
| `order 200 planted.steak Classic` | Creates sales quote immediately |
| `cancel SQ0105` | Cancels a pending order |
| `reorder my last order` | Checks stock, reorders available items |
| `reset` | Clears conversation, starts fresh |

### Structure

```
shop_agent_wa/
├── agents/Shop_Agent_WA.yaml
└── tools/business_central_shop/
    ├── _customer_lookup_wa.py       # phone → customer_id
    ├── shop_get_products_wa.py
    ├── shop_get_orders_wa.py
    ├── shop_create_order_wa.py
    ├── shop_modify_order_wa.py
    └── shop_cancel_order_wa.py
```

---

## Other Agents

- **[Shop Agent UI](docs/reference.md#shop-agent-ui)** — Interactive webchat agent in WXO UI (`shop_agent_ui/`)
- **[Shop Agent API](docs/reference.md#shop-agent-api)** — REST API agent with multi-turn conversations (`shop_agent_api/`)
- **[Connections & Deployment](docs/reference.md#connections)** — BC connections, SendGrid, Code Engine deployment
- **[Legacy Agents](docs/reference.md#legacy-agents)** — Original multi-agent orchestrator (archived)

Full reference documentation: [docs/reference.md](docs/reference.md)
