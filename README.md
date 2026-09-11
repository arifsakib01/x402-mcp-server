# x402-Gated MCP Server 💰

A **Model Context Protocol (MCP)** server that charges AI agents per-call via the **x402 micropayment protocol** (USDC on Base).

Agents pay **$0.05 USDC** per tool call — no API keys, no subscriptions, just pay-per-use crypto.

## How It Works

```
Agent → POST /mcp/tools/call (no payment)
     ← 402 + pricing payload (how much, where to pay)

Agent → signs USDC tx on Base
     → POST /mcp/tools/call + X-Payment-Signature: 0x...
     ← 200 + tool results ✅
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure (copy and edit .env)
cp .env.example .env
# Set PAYMENT_WALLET_ADDRESS=0xYourWallet

# Run server
python server.py

# Test the payment flow (in another terminal)
python client.py
```

## Available Tools

| Tool | Description | Price |
|------|-------------|-------|
| `generate_synthetic_data` | Generates user profiles, transactions, or IoT sensor data | 0.05 USDC |
| `crypto_market_analytics` | Deep DEX liquidity, 24h volume, and sentiment score on Base network | 0.05 USDC |
| `web_content_extractor` | Clean markdown summaries, key takeaways, and structured JSON from URLs | 0.05 USDC |

## Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | None | Health check + payment config |
| GET | `/mcp/sse` | x402 | MCP SSE connection |
| POST | `/mcp/messages/` | x402 | MCP JSON-RPC messages |
| POST | `/mcp/tools/call` | x402 | REST tool invocation |

## Deploy to Railway

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/template)

```bash
# Or via CLI:
railway login
railway init
railway up
# Set env vars in Railway dashboard:
#   PAYMENT_WALLET_ADDRESS=0x...
#   VERIFY_MODE=onchain
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PAYMENT_WALLET_ADDRESS` | Yes | - | Your Base wallet for receiving USDC |
| `PAYMENT_AMOUNT` | No | `0.05` | Price per call in USDC |
| `VERIFY_MODE` | No | `mock` | `onchain` for production, `mock` for dev |
| `BASE_RPC_URL` | No | `https://mainnet.base.org` | Base RPC endpoint |
| `PORT` | No | `8402` | Server port |

## Architecture

```
┌─────────────────────────────────────────────┐
│                FastAPI App                   │
│  ┌───────────────────────────────────────┐  │
│  │    x402 Payment Middleware (ASGI)     │  │
│  │    ┌─────────────────────────────┐    │  │
│  │    │   MCP SSE Transport         │    │  │
│  │    │   └─ /mcp/sse              │    │  │
│  │    │   └─ /mcp/messages/        │    │  │
│  │    │   REST Endpoint             │    │  │
│  │    │   └─ /mcp/tools/call       │    │  │
│  │    └─────────────────────────────┘    │  │
│  └───────────────────────────────────────┘  │
│  Health Check (public)                       │
│  └─ /                                        │
└─────────────────────────────────────────────┘
```

## Tech Stack

- **FastAPI** + **uvicorn** — ASGI web server
- **MCP SDK v2** — Model Context Protocol
- **web3.py** — On-chain USDC verification on Base
- **httpx** — Async HTTP client

## License

MIT
