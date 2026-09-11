# Monetized MCP AI Tools Suite ($0.50 USD) 🚀

A **Model Context Protocol (MCP)** server providing premium AI developer tools gated by **$0.50 USD API Key authorization** with automated **Stripe fiat checkout**.

Clients pay **$0.50 USD** per tool call — no crypto wallets required, pay with credit/debit card via Stripe, and receive bank payouts.

---

## Live Endpoints

- **Live Server**: [https://x402-mcp-server-production.up.railway.app/](https://x402-mcp-server-production.up.railway.app/)
- **Buy Credits via Stripe**: [https://x402-mcp-server-production.up.railway.app/buy?amount=10](https://x402-mcp-server-production.up.railway.app/buy?amount=10)
- **Check Balance**: `https://x402-mcp-server-production.up.railway.app/balance?key=YOUR_KEY`
- **MCP SSE Endpoint**: `https://x402-mcp-server-production.up.railway.app/mcp/sse`
- **Smithery Server Card**: `https://x402-mcp-server-production.up.railway.app/.well-known/mcp/server-card.json`

---

## How It Works

```
Client / Agent → POST /mcp/tools/call (without API Key)
               ← 401 Unauthorized + pricing options ($0.50 USD / call)

User / Agent   → Buys credit pack via Stripe Checkout (/buy?amount=10)
               ← Receives unique API Key pre-loaded with balance

Client / Agent → POST /mcp/tools/call + Authorization: Bearer <API_KEY>
               ← 200 OK + Tool results + Remaining balance ($0.50 deducted)
```

---

## Available Tools

| Tool | Description | Price |
|------|-------------|-------|
| `generate_synthetic_data` | Generates high-fidelity user profiles, transactions, or IoT sensor streams | **$0.50 USD** |
| `crypto_market_analytics` | Deep DEX liquidity pool metrics, 24h volume, price impact & sentiment scores | **$0.50 USD** |
| `web_content_extractor` | Clean LLM-optimized markdown summaries & structured JSON from web URLs | **$0.50 USD** |

---

## Client Integration

### Curl
```bash
curl -X POST "https://x402-mcp-server-production.up.railway.app/mcp/tools/call" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "generate_synthetic_data",
    "arguments": {"count": 3, "schema_type": "user_profile"}
  }'
```

### Python
```python
import httpx

headers = {"Authorization": "Bearer YOUR_API_KEY"}
payload = {
    "tool": "generate_synthetic_data",
    "arguments": {"count": 3, "schema_type": "user_profile"}
}

response = httpx.post(
    "https://x402-mcp-server-production.up.railway.app/mcp/tools/call",
    json=payload,
    headers=headers
)
print(response.json())
```

---

## Smithery Quick Start

```bash
# Connect this server
npx -y smithery mcp add arif-sakib/x402-mcp-server

# List tools
npx -y smithery tool list arif-sakib/x402-mcp-server
```
