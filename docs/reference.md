# Reference Documentation

Detailed documentation for all agents, connections, and deployment.

---

## Shop Agent UI

**Folder:** `shop_agent_ui/`
**WXO Name:** `Shop_Agent_UI`
**Channel:** WXO webchat (direct chat in browser)
**Connection:** `business_central_timothy`

Interactive chatbot for the WXO webchat UI. User identifies by email, then browses products, places/modifies/cancels orders, and reorders — all in a multi-turn conversation.

### Structure

```
shop_agent_ui/
├── agents/
│   └── Shop_Agent.yaml
└── tools/
    └── business_central_shop/
        ├── shop_identify_customer.py
        ├── shop_get_products.py
        ├── shop_get_orders.py
        ├── shop_create_order.py
        ├── shop_modify_order.py
        └── shop_cancel_order.py
```

### Tools (6)

| Tool | Description |
|---|---|
| `shop_identify_customer` | User provides email → returns customer_id, business name, last shipped order, pending orders. Called first. |
| `shop_get_products` | Returns in_stock (with IDs, prices) and out_of_stock_names (names only). |
| `shop_get_orders` | Returns shipped + pending orders for a customer_id. |
| `shop_create_order` | Creates a sales quote with up to 10 items. Takes customer_id + item IDs + quantities. |
| `shop_modify_order` | Replaces ALL items on a pending order. Takes customer_id + reference_number + new items. |
| `shop_cancel_order` | Deletes a pending sales quote (SQ####). Returns cancelled order details. |

### Usage

Open the WXO webchat UI and chat directly. No API needed.

---

## Shop Agent API

**Folder:** `shop_agent_api/`
**WXO Name:** `Shop_Agent_API`
**Channel:** REST API via Code Engine wrapper
**Connection:** `business_central_timothy`
**Context variable:** `email_address`

Same capabilities as the UI agent but accessed via HTTP. Supports multi-turn conversations via `thread_id`. Customer resolved internally from `email_address` context variable — LLM never sees customer_id.

### Structure

```
shop_agent_api/
├── agents/
│   └── Shop_Agent_API.yaml
└── tools/
    └── business_central_shop/
        ├── _customer_lookup.py
        ├── shop_get_products_email.py
        ├── shop_get_orders_email.py
        ├── shop_create_order_email.py
        ├── shop_modify_order_email.py
        ├── shop_cancel_order_email.py
        └── requirements.txt
```

### Tools (5)

| Tool | Description |
|---|---|
| `shop_get_products_email` | Returns in_stock and out_of_stock_names. No customer needed. |
| `shop_get_orders_email` | Returns shipped + pending orders. Resolves customer from context. |
| `shop_create_order_email` | Creates sales quote. Resolves customer from context. |
| `shop_modify_order_email` | Replaces all items on a pending order. Resolves customer from context. |
| `shop_cancel_order_email` | Cancels a pending order. Resolves customer from context. |

### API

**Base URL:** `https://wxo-wrapper.27n8kz0d49mj.us-south.codeengine.appdomain.cloud`
**Swagger:** `https://wxo-wrapper.27n8kz0d49mj.us-south.codeengine.appdomain.cloud/docs`

#### `POST /trigger-agent`

```bash
curl -X POST https://wxo-wrapper.27n8kz0d49mj.us-south.codeengine.appdomain.cloud/trigger-agent \
  -H "Content-Type: application/json" \
  -d '{"email_address": "timothy.bates@ibm.com", "email_body": "What products do you have?"}'
```

**Response:**
```json
{
  "email": "timothy.bates@ibm.com",
  "message": "Products:\n1. planted.steak Classic — CHF 7.95/PCS\n...",
  "thread_id": "7da28346-b615-4bed-bff7-e103a6639c3e"
}
```

Pass `thread_id` in subsequent requests to continue the conversation.

---

## Connections

| Connection | Type | Used by | Azure App |
|---|---|---|---|
| `business_central_timothy` | OAuth2 Client Creds, team | UI, API, WA agents | Business Central (a3bc5adc-...) |
| `business_central_wa` | OAuth2 Client Creds, team | Email agent (needs PDF access) | Whatsapp Business Central Agent (ee7f342c-...) |
| `sendgrid_email` | API Key | Email agent | SendGrid |

`business_central_wa` has `D365 BUS FULL ACCESS` + `API.ReadWrite.All` — required for the `pdfDocument` endpoint to download sales quote PDFs.

---

## Deploying

### WXO Tools and Agents

```bash
# Activate environment
.venv/bin/orchestrate env activate planted_henrique -a <WXO_API_KEY>

# Import tools (example for email agent)
.venv/bin/orchestrate tools import -k python \
  -f shop_agent_email/tools/business_central_shop/shop_create_quote_and_email_em.py \
  -p shop_agent_email/tools/business_central_shop \
  -r shop_agent_email/tools/business_central_shop/requirements.txt \
  -a business_central_wa -a sendgrid_email

# Import agent
.venv/bin/orchestrate agents import -f shop_agent_email/agents/Shop_Agent_Email.yaml
```

### Code Engine Wrappers

```bash
ibmcloud login --sso
ibmcloud target -g itz-wxo-69bae351a501e43911f16a
ibmcloud ce project select --id 72e41372-570d-4987-a1bb-fd5710eeffcd

ibmcloud ce app update --name wxo-wrapper --build-source /path/to/wrapper
```

| Wrapper | Code Engine App | URL |
|---|---|---|
| API Agent | `wxo-wrapper` | `https://wxo-wrapper.27n8kz0d49mj.us-south.codeengine.appdomain.cloud` |
| WhatsApp Agent | `wxo-wa-wrapper` | `https://wxo-wa-wrapper.27n8kz0d49mj.us-south.codeengine.appdomain.cloud` |
| Email Agent | `wxo-email-wrapper` | `https://wxo-email-wrapper.27n8kz0d49mj.us-south.codeengine.appdomain.cloud` |

---

## Legacy Agents

See `archive/` for the original multi-agent architecture with a master orchestrator routing to Business Central and Salesforce sub-agents.
