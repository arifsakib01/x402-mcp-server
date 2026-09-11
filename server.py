"""
Fiat-Monetized MCP Server — FastAPI Transport Layer ($0.50 USD / Call)
======================================================================
This module is the HTTP entry-point. It provides:

  1. An **ASGI middleware** implementing API Key Authentication ($0.50 USD/call).
  2. MCP **Server-Sent Events (SSE)** endpoint at ``/mcp/sse`` for MCP clients.
  3. MCP **JSON-RPC Message** endpoint at ``/mcp/messages/``.
  4. A REST convenience endpoint at ``/mcp/tools/call``.
  5. A glassmorphic web dashboard at ``/`` with live API playground.
  6. Smithery metadata card at ``/.well-known/mcp/server-card.json``.
  7. **Stripe Checkout** — ``/buy`` creates a payment session for API credits.
  8. **Balance tracking** — per-key credit ledger with $0.50 deduction per call.
  9. **Stripe Webhooks** — ``/stripe/webhook`` processes completed payments.

Payment Architecture (Stripe Fiat)
-----------------------------------
- **Price**: $0.50 USD per tool call.
- **Purchase**: Users buy credit packs via Stripe Checkout ($5 / $10 / $25).
- **Balance**: Each API key tracks remaining USD balance; calls deduct $0.50.
- **Payouts**: Stripe settles to your connected bank account automatically.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from contextlib import asynccontextmanager

import stripe
from dotenv import load_dotenv
from fastapi import FastAPI
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

from mcp_tools import invoke_tool, mcp_server

# ══════════════════════════════════════════════════════════════════════════════
# Environment & Configuration
# ══════════════════════════════════════════════════════════════════════════════

load_dotenv()

PRICE_PER_CALL: float = float(os.getenv("PRICE_PER_CALL", "0.50"))
ADMIN_API_KEY: str = os.getenv("ADMIN_API_KEY", "mcp_key_live_master_998877665544332211")
STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8402"))
BASE_URL: str = os.getenv("BASE_URL", "https://x402-mcp-server-production.up.railway.app")

# Initialize Stripe
stripe.api_key = STRIPE_SECRET_KEY

# ══════════════════════════════════════════════════════════════════════════════
# In-Memory Balance Ledger (use a database in production)
# ══════════════════════════════════════════════════════════════════════════════

# { api_key: { "balance_usd": float, "total_calls": int, "total_spent": float } }
API_KEY_BALANCES: dict[str, dict] = {
    ADMIN_API_KEY: {
        "balance_usd": 999999.00,  # Admin key has unlimited balance
        "total_calls": 0,
        "total_spent": 0.0,
    },
    "mcp_key_demo_client_123456": {
        "balance_usd": 5.00,  # Demo key starts with $5.00 (10 calls)
        "total_calls": 0,
        "total_spent": 0.0,
    },
}

# Track Stripe session → generated API key mapping
PENDING_SESSIONS: dict[str, dict] = {}

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("mcp_server")


def _generate_api_key() -> str:
    """Generate a unique API key."""
    raw = f"mcp_{time.time_ns()}_{os.urandom(8).hex()}"
    return f"mcp_key_{hashlib.sha256(raw.encode()).hexdigest()[:32]}"


# ══════════════════════════════════════════════════════════════════════════════
# API Key Authorization Middleware ($0.50 USD / Call) with Balance Checking
# ══════════════════════════════════════════════════════════════════════════════

class APIKeyAuthMiddleware:
    """
    ASGI Middleware enforcing API Key Authorization ($0.50 USD/call).
    Now also checks the caller's balance before allowing tool execution.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        method: str = scope.get("method", "GET").upper()

        # Handle non-GET calls on /mcp/sse gracefully
        if path in ("/mcp/sse", "/mcp/sse/") and method != "GET":
            response = JSONResponse(
                status_code=200,
                content={
                    "jsonrpc": "2.0",
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "tools": {"listChanged": True},
                            "resources": {},
                            "prompts": {},
                        },
                        "serverInfo": {
                            "name": "x402-mcp-server",
                            "title": "Monetized MCP AI Tools Suite ($0.50 USD)",
                            "description": "A suite of premium MCP tools (Synthetic Data Generator, Crypto Market Analytics, Web Extractor) gated by $0.50 USD API Key authorization with automated Stripe fiat checkout.",
                            "homepage": "https://x402-mcp-server-production.up.railway.app/",
                            "website_url": "https://x402-mcp-server-production.up.railway.app/",
                            "icon": "https://raw.githubusercontent.com/arifsakib01/x402-mcp-server/main/icon.png",
                            "version": "2.0.0",
                        },
                    },
                },
            )
            await response(scope, receive, send)
            return

        # Allow public endpoints freely (dashboard, health, buy, stripe, etc.)
        if (
            not path.startswith("/mcp")
            or "server-card.json" in path
            or "mcp.json" in path
            or path in ("/mcp/sse", "/mcp/sse/")
        ):
            await self.app(scope, receive, send)
            return

        # Parse authorization headers
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", [])
        }

        api_key = headers.get("x-api-key")
        auth_header = headers.get("authorization", "")

        if not api_key and auth_header.lower().startswith("bearer "):
            api_key = auth_header[7:].strip()

        # Check if key exists in balance ledger
        if not api_key or api_key not in API_KEY_BALANCES:
            logger.info("🚫  401 Unauthorized for %s (invalid or missing API Key)", path)
            response = JSONResponse(
                status_code=401,
                content={
                    "error": "Unauthorized — API Key Required",
                    "message": (
                        f"This MCP tool execution requires a valid API Key (${PRICE_PER_CALL:.2f} USD per call). "
                        "Include 'Authorization: Bearer <API_KEY>' or 'X-API-Key: <API_KEY>' header."
                    ),
                    "buy_credits": f"{BASE_URL}/buy",
                    "pricing": {
                        "amount_usd": PRICE_PER_CALL,
                        "currency": "USD",
                        "credit_packs": {
                            "$5 (10 calls)": f"{BASE_URL}/buy?amount=5",
                            "$10 (20 calls)": f"{BASE_URL}/buy?amount=10",
                            "$25 (50 calls)": f"{BASE_URL}/buy?amount=25",
                        },
                    },
                },
                headers={
                    "WWW-Authenticate": 'Bearer realm="MCP Tool Execution"',
                    "X-Price-USD": str(PRICE_PER_CALL),
                },
            )
            await response(scope, receive, send)
            return

        # Check balance
        account = API_KEY_BALANCES[api_key]
        if account["balance_usd"] < PRICE_PER_CALL:
            logger.info("💸  402 Insufficient balance for key %s… (balance: $%.2f)", api_key[:16], account["balance_usd"])
            response = JSONResponse(
                status_code=402,
                content={
                    "error": "Insufficient Balance",
                    "message": f"Your API key balance is ${account['balance_usd']:.2f} USD, but each call costs ${PRICE_PER_CALL:.2f} USD.",
                    "balance_usd": account["balance_usd"],
                    "price_per_call_usd": PRICE_PER_CALL,
                    "top_up": f"{BASE_URL}/buy",
                    "credit_packs": {
                        "$5 (10 calls)": f"{BASE_URL}/buy?amount=5",
                        "$10 (20 calls)": f"{BASE_URL}/buy?amount=10",
                        "$25 (50 calls)": f"{BASE_URL}/buy?amount=25",
                    },
                },
            )
            await response(scope, receive, send)
            return

        # Deduct balance
        account["balance_usd"] -= PRICE_PER_CALL
        account["total_calls"] += 1
        account["total_spent"] += PRICE_PER_CALL
        logger.info(
            "✅  API Key Authorized for %s (key: %s…, charged $%.2f, remaining: $%.2f)",
            path, api_key[:16], PRICE_PER_CALL, account["balance_usd"],
        )
        await self.app(scope, receive, send)


# ══════════════════════════════════════════════════════════════════════════════
# REST Tool Call Endpoint
# ══════════════════════════════════════════════════════════════════════════════

async def handle_rest_tool_call(request: Request):
    """POST /mcp/tools/call — invoke an MCP tool via plain REST."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON in request body"})

    tool_name = body.get("tool")
    arguments = body.get("arguments", {})

    if not tool_name:
        return JSONResponse(status_code=400, content={"error": "Missing required 'tool' field"})

    # Extract API key to show remaining balance in response
    api_key = request.headers.get("x-api-key")
    auth_header = request.headers.get("authorization", "")
    if not api_key and auth_header.lower().startswith("bearer "):
        api_key = auth_header[7:].strip()
    remaining = API_KEY_BALANCES.get(api_key, {}).get("balance_usd", 0)

    try:
        results = await invoke_tool(tool_name, arguments)
        return JSONResponse(content={
            "status": "success",
            "tool": tool_name,
            "price_usd": PRICE_PER_CALL,
            "remaining_balance_usd": round(remaining, 2),
            "authorized": True,
            "results": results,
        })
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except Exception:
        logger.exception("Tool execution error")
        return JSONResponse(status_code=500, content={"error": "Internal tool execution error"})


# ══════════════════════════════════════════════════════════════════════════════
# FastAPI Application Assembly & Endpoints
# ══════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀  Fiat-Monetized MCP Server starting…")
    logger.info("   💰  Price : $%.2f USD / call", PRICE_PER_CALL)
    logger.info("   🔑  Master Key: %s", ADMIN_API_KEY)
    logger.info("   💳  Stripe : %s", "CONNECTED" if STRIPE_SECRET_KEY and not STRIPE_SECRET_KEY.startswith("sk_test_place") else "TEST MODE")
    logger.info("   📡  MCP SSE : http://%s:%s/mcp/sse", HOST, PORT)
    logger.info("   🔧  REST    : http://%s:%s/mcp/tools/call", HOST, PORT)
    logger.info("   🛒  Buy     : http://%s:%s/buy", HOST, PORT)
    yield
    logger.info("🛑  MCP Server shutting down")


app = FastAPI(
    title="Fiat-Monetized MCP Server",
    description="Model Context Protocol server with Stripe payments ($0.50 USD / call)",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(APIKeyAuthMiddleware)


# ── Stripe Checkout: Buy API Credits ─────────────────────────────────────────

@app.get("/buy")
async def buy_credits(request: Request, amount: int = 10):
    """
    Create a Stripe Checkout session for buying API credits.
    
    Query params:
        amount: USD amount to purchase (default $10). Options: 5, 10, 25, 50, 100
    
    Example: GET /buy?amount=10  → Redirects to Stripe Checkout for $10 (20 calls)
    """
    # Validate amount
    valid_amounts = [5, 10, 25, 50, 100]
    if amount not in valid_amounts:
        amount = 10  # Default to $10

    num_calls = int(amount / PRICE_PER_CALL)

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"MCP API Credits — {num_calls} Tool Calls",
                        "description": f"${amount} USD credit pack for {num_calls} MCP tool executions at ${PRICE_PER_CALL:.2f}/call",
                    },
                    "unit_amount": amount * 100,  # Stripe uses cents
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"{BASE_URL}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{BASE_URL}/payment/cancelled",
            metadata={
                "credit_amount_usd": str(amount),
                "num_calls": str(num_calls),
            },
        )

        # Store pending session
        PENDING_SESSIONS[session.id] = {
            "amount_usd": amount,
            "num_calls": num_calls,
            "status": "pending",
        }

        logger.info("🛒  Stripe Checkout created: $%d USD (%d calls) → %s", amount, num_calls, session.id)
        return RedirectResponse(url=session.url, status_code=303)

    except stripe.error.StripeError as e:
        logger.error("Stripe error: %s", str(e))
        return JSONResponse(status_code=500, content={
            "error": "Payment processing error",
            "message": str(e),
        })


@app.get("/payment/success")
async def payment_success(session_id: str = ""):
    """Handle successful Stripe Checkout — generate API key with purchased credits."""
    if not session_id:
        return HTMLResponse("<h1>Missing session ID</h1>", status_code=400)

    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except stripe.error.StripeError:
        return HTMLResponse("<h1>Invalid session</h1>", status_code=400)

    if session.payment_status != "paid":
        return HTMLResponse("<h1>Payment not completed</h1>", status_code=402)

    # Check if we already processed this session
    pending = PENDING_SESSIONS.get(session_id, {})
    if pending.get("status") == "completed":
        api_key = pending.get("api_key", "")
        amount = pending.get("amount_usd", 0)
        num_calls = pending.get("num_calls", 0)
    else:
        # Generate new API key with credits
        amount = int(session.metadata.get("credit_amount_usd", "10"))
        num_calls = int(session.metadata.get("num_calls", str(int(amount / PRICE_PER_CALL))))
        api_key = _generate_api_key()

        API_KEY_BALANCES[api_key] = {
            "balance_usd": float(amount),
            "total_calls": 0,
            "total_spent": 0.0,
        }

        # Mark session as completed
        PENDING_SESSIONS[session_id] = {
            "status": "completed",
            "api_key": api_key,
            "amount_usd": amount,
            "num_calls": num_calls,
        }

        logger.info("💰  Payment confirmed! Generated key %s… with $%d balance (%d calls)", api_key[:20], amount, num_calls)

    # Return a nice success page
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Payment Successful!</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; font-family: 'Outfit', sans-serif; }}
        body {{ background: #0b0f19; color: #f1f5f9; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 2rem; }}
        .card {{ background: rgba(22,28,45,0.85); border: 1px solid rgba(0,230,118,0.3); border-radius: 20px; padding: 3rem; max-width: 600px; text-align: center; backdrop-filter: blur(12px); }}
        .check {{ font-size: 4rem; margin-bottom: 1rem; }}
        h1 {{ font-size: 2rem; margin-bottom: 0.5rem; color: #00e676; }}
        .details {{ background: #060911; border: 1px solid rgba(255,255,255,0.12); border-radius: 12px; padding: 1.5rem; margin: 1.5rem 0; text-align: left; }}
        .row {{ display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.06); }}
        .row:last-child {{ border-bottom: none; }}
        .label {{ color: #94a3b8; }}
        .value {{ font-family: 'JetBrains Mono', monospace; color: #00f2fe; }}
        .key-box {{ background: #060911; border: 2px solid #00e676; border-radius: 10px; padding: 1rem; margin: 1rem 0; word-break: break-all; font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; color: #00e676; cursor: pointer; }}
        .key-box:hover {{ background: rgba(0,230,118,0.05); }}
        .warn {{ color: #ff9800; font-size: 0.85rem; margin-top: 0.5rem; }}
        .btn {{ display: inline-block; background: linear-gradient(135deg, #4facfe, #7f00ff); color: #fff; font-weight: 600; padding: 12px 24px; border-radius: 10px; text-decoration: none; margin-top: 1.5rem; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="check">✅</div>
        <h1>Payment Successful!</h1>
        <p style="color: #94a3b8;">Your API credits are ready to use.</p>

        <div class="details">
            <div class="row"><span class="label">Amount Paid</span><span class="value">${amount}.00 USD</span></div>
            <div class="row"><span class="label">Credits</span><span class="value">{num_calls} tool calls</span></div>
            <div class="row"><span class="label">Price per Call</span><span class="value">${PRICE_PER_CALL:.2f} USD</span></div>
        </div>

        <p style="font-weight: 600; margin-bottom: 0.5rem;">🔑 Your API Key:</p>
        <div class="key-box" onclick="navigator.clipboard.writeText('{api_key}'); this.style.borderColor='#4facfe'; this.innerHTML='✅ Copied to clipboard!'; setTimeout(()=>{{this.innerHTML='{api_key}'; this.style.borderColor='#00e676';}}, 2000);">
            {api_key}
        </div>
        <p class="warn">⚠️ Save this key now — it won't be shown again!</p>

        <p style="color: #94a3b8; font-size: 0.9rem; margin-top: 1rem;">
            Use it as: <code style="color: #00f2fe;">Authorization: Bearer {api_key[:20]}...</code>
        </p>

        <a href="/" class="btn">← Back to Dashboard</a>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/payment/cancelled")
async def payment_cancelled():
    """Handle cancelled Stripe Checkout."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Payment Cancelled</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Outfit', sans-serif; }
        body { background: #0b0f19; color: #f1f5f9; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
        .card { background: rgba(22,28,45,0.85); border: 1px solid rgba(255,152,0,0.3); border-radius: 20px; padding: 3rem; max-width: 500px; text-align: center; }
        h1 { color: #ff9800; margin-bottom: 1rem; }
        a { display: inline-block; background: linear-gradient(135deg, #4facfe, #7f00ff); color: #fff; font-weight: 600; padding: 12px 24px; border-radius: 10px; text-decoration: none; margin-top: 1.5rem; }
    </style>
</head>
<body>
    <div class="card">
        <div style="font-size: 3rem; margin-bottom: 1rem;">❌</div>
        <h1>Payment Cancelled</h1>
        <p style="color: #94a3b8;">No charges were made. You can try again anytime.</p>
        <a href="/">← Back to Dashboard</a>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html)


# ── Stripe Webhook ───────────────────────────────────────────────────────────

@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    """Process Stripe webhook events (payment confirmations)."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        if STRIPE_WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        else:
            event = json.loads(payload)
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        logger.error("Webhook error: %s", str(e))
        return JSONResponse(status_code=400, content={"error": str(e)})

    if event.get("type") == "checkout.session.completed":
        session = event["data"]["object"]
        session_id = session["id"]

        if session_id not in PENDING_SESSIONS or PENDING_SESSIONS[session_id].get("status") != "completed":
            amount = int(session.get("metadata", {}).get("credit_amount_usd", "10"))
            num_calls = int(amount / PRICE_PER_CALL)
            api_key = _generate_api_key()

            API_KEY_BALANCES[api_key] = {
                "balance_usd": float(amount),
                "total_calls": 0,
                "total_spent": 0.0,
            }

            PENDING_SESSIONS[session_id] = {
                "status": "completed",
                "api_key": api_key,
                "amount_usd": amount,
                "num_calls": num_calls,
            }

            logger.info("🔔  Webhook: Payment confirmed for session %s — $%d (%d calls)", session_id, amount, num_calls)

    return JSONResponse(content={"received": True})


# ── Balance Check Endpoint ───────────────────────────────────────────────────

@app.get("/balance")
async def check_balance(request: Request):
    """Check API key balance. Pass key via Authorization header or ?key= query param."""
    api_key = request.query_params.get("key", "")
    if not api_key:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            api_key = auth_header[7:].strip()
        api_key = api_key or request.headers.get("x-api-key", "")

    if not api_key or api_key not in API_KEY_BALANCES:
        return JSONResponse(status_code=404, content={
            "error": "API key not found",
            "message": "Provide a valid key via '?key=YOUR_KEY' or 'Authorization: Bearer YOUR_KEY' header.",
            "buy_credits": f"{BASE_URL}/buy",
        })

    account = API_KEY_BALANCES[api_key]
    calls_remaining = int(account["balance_usd"] / PRICE_PER_CALL)
    return JSONResponse(content={
        "api_key": f"{api_key[:16]}…{'*' * 8}",
        "balance_usd": round(account["balance_usd"], 2),
        "calls_remaining": calls_remaining,
        "price_per_call_usd": PRICE_PER_CALL,
        "total_calls_made": account["total_calls"],
        "total_spent_usd": round(account["total_spent"], 2),
        "top_up": f"{BASE_URL}/buy",
    })


# ── Health Check ─────────────────────────────────────────────────────────────

@app.api_route("/health", methods=["GET", "POST", "HEAD", "OPTIONS"])
async def health_check():
    """Public JSON health-check endpoint."""
    return {
        "status": "healthy",
        "service": "fiat-monetized-mcp-server",
        "price_per_call_usd": PRICE_PER_CALL,
        "payment_method": "stripe_checkout",
        "stripe_connected": bool(STRIPE_SECRET_KEY and not STRIPE_SECRET_KEY.startswith("sk_test_place")),
        "buy_credits": f"{BASE_URL}/buy",
        "endpoints": {
            "health": "GET  /health",
            "dashboard": "GET  /",
            "buy_credits": "GET  /buy?amount=10",
            "check_balance": "GET  /balance?key=YOUR_KEY",
            "server_card": "GET  /.well-known/mcp/server-card.json",
            "mcp_sse": "GET  /mcp/sse",
            "rest_tool_call": "POST /mcp/tools/call",
            "stripe_webhook": "POST /stripe/webhook",
        },
    }


# ── Smithery Server Card ────────────────────────────────────────────────────

@app.api_route("/.well-known/mcp/server-card.json", methods=["GET", "POST", "HEAD", "OPTIONS"])
@app.api_route("/.well-known/mcp.json", methods=["GET", "POST", "HEAD", "OPTIONS"])
async def server_card():
    """Smithery.ai server metadata card for automated indexing."""
    return {
        "$schema": "https://smithery.ai/docs/mcp-server-card.schema.json",
        "name": "x402-mcp-server",
        "title": f"Monetized MCP AI Tools Suite (${PRICE_PER_CALL:.2f} USD)",
        "description": (
            "A suite of premium MCP tools (Synthetic Data Generator, Crypto Market Analytics, "
            f"Web Extractor) with Stripe payments at ${PRICE_PER_CALL:.2f} USD per call."
        ),
        "version": "2.0.0",
        "author": "arifsakib01",
        "icon": "https://raw.githubusercontent.com/arifsakib01/x402-mcp-server/main/icon.png",
        "homepage": f"{BASE_URL}/",
        "repository": "https://github.com/arifsakib01/x402-mcp-server",
        "configSchema": {
            "type": "object",
            "properties": {
                "apiKey": {
                    "type": "string",
                    "description": f"API Key for tool execution (${PRICE_PER_CALL:.2f} USD/call). Buy at {BASE_URL}/buy"
                }
            }
        },
        "payment": {
            "protocol": "stripe_checkout",
            "currency": "USD",
            "amount": PRICE_PER_CALL,
            "buy_credits": f"{BASE_URL}/buy",
        },
        "tools": [
            {
                "name": "generate_synthetic_data",
                "title": "Synthetic Data Generator",
                "description": "Generates high-fidelity synthetic user profiles, blockchain transactions, or IoT sensor streams ($0.50 USD/call).",
                "annotations": {
                    "readOnly": True,
                    "idempotent": True,
                    "readOnlyHint": True,
                    "idempotentHint": True,
                    "destructiveHint": False
                },
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "count": {"type": "integer", "description": "Number of records to generate (1 to 100). Default is 5."},
                        "schema_type": {"type": "string", "description": "Target schema: user_profile, transaction, or iot_sensor."}
                    }
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "metadata": {"type": "object", "description": "Generation metadata and timestamp."},
                        "records": {"type": "array", "description": "List of synthetic data records."}
                    },
                    "required": ["metadata", "records"]
                }
            },
            {
                "name": "crypto_market_analytics",
                "title": "Base Crypto Market Analytics",
                "description": "Base network token analytics, DEX liquidity, 24h volume & sentiment scores ($0.50 USD/call).",
                "annotations": {
                    "readOnly": True,
                    "idempotent": True,
                    "readOnlyHint": True,
                    "idempotentHint": True,
                    "destructiveHint": False
                },
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "token_symbol": {"type": "string", "description": "Ticker symbol on Base (e.g. USDC, WETH, AERO)."}
                    }
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "network": {"type": "string", "description": "Base network identifier."},
                        "token_symbol": {"type": "string", "description": "Token symbol."},
                        "price_usd": {"type": "number", "description": "Current price in USD."},
                        "dex_liquidity_usd": {"type": "number", "description": "Total DEX liquidity in USD."},
                        "sentiment_score": {"type": "number", "description": "Sentiment score."}
                    },
                    "required": ["network", "token_symbol", "price_usd"]
                }
            },
            {
                "name": "web_content_extractor",
                "title": "Web Content Extractor",
                "description": "Clean markdown summaries and JSON metadata extracted from web URLs ($0.50 USD/call).",
                "annotations": {
                    "readOnly": True,
                    "idempotent": True,
                    "readOnlyHint": True,
                    "idempotentHint": True,
                    "destructiveHint": False
                },
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Full HTTPS URL to scrape and summarize."}
                    }
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Extracted URL."},
                        "title": {"type": "string", "description": "Extracted page title."},
                        "summary": {"type": "string", "description": "Clean LLM-optimized summary."},
                        "key_takeaways": {"type": "array", "description": "Key takeaways."}
                    },
                    "required": ["url", "title", "summary"]
                }
            },
        ],
    }


# ══════════════════════════════════════════════════════════════════════════════
# Glassmorphic Landing Dashboard
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def landing_dashboard():
    """Public Glassmorphic Dark-Mode Landing Dashboard with Stripe Buy Buttons."""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Monetized MCP Server — ${PRICE_PER_CALL:.2f} USD / Call</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-color: #0b0f19;
            --card-bg: rgba(22, 28, 45, 0.75);
            --border-color: rgba(255, 255, 255, 0.12);
            --accent-cyan: #00f2fe;
            --accent-blue: #4facfe;
            --accent-purple: #7f00ff;
            --accent-green: #00e676;
            --text-main: #f1f5f9;
            --text-muted: #94a3b8;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; font-family: 'Outfit', sans-serif; }}
        body {{
            background: var(--bg-color);
            background-image: 
                radial-gradient(circle at 15% 15%, rgba(0, 242, 254, 0.1) 0%, transparent 40%),
                radial-gradient(circle at 85% 85%, rgba(127, 0, 255, 0.1) 0%, transparent 40%);
            color: var(--text-main); min-height: 100vh; padding: 2rem 1rem;
        }}
        .container {{ max-width: 1000px; margin: 0 auto; }}
        header {{ text-align: center; margin-bottom: 3rem; }}
        .badge {{
            display: inline-flex; align-items: center; gap: 6px;
            background: rgba(0, 230, 118, 0.15); color: var(--accent-green);
            padding: 6px 14px; border-radius: 20px; border: 1px solid rgba(0, 230, 118, 0.3);
            font-size: 0.85rem; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;
            margin-bottom: 1rem;
        }}
        .pulse-dot {{ width: 8px; height: 8px; background: var(--accent-green); border-radius: 50%; box-shadow: 0 0 8px var(--accent-green); }}
        h1 {{ font-size: 2.8rem; font-weight: 700; background: linear-gradient(135deg, #fff 0%, var(--accent-cyan) 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 0.5rem; }}
        p.subtitle {{ color: var(--text-muted); font-size: 1.1rem; max-width: 650px; margin: 0 auto; }}
        
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.5rem; margin-bottom: 2rem; }}
        .grid-3 {{ grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); }}
        .card {{
            background: var(--card-bg); border: 1px solid var(--border-color); backdrop-filter: blur(12px);
            border-radius: 16px; padding: 1.8rem; position: relative; transition: transform 0.2s, border-color 0.2s;
        }}
        .card:hover {{ transform: translateY(-3px); border-color: rgba(0, 242, 254, 0.4); }}
        .card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }}
        .card-title {{ font-size: 1.2rem; font-weight: 600; color: #fff; }}
        .price-tag {{ font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; background: rgba(0, 242, 254, 0.1); color: var(--accent-cyan); padding: 4px 10px; border-radius: 8px; border: 1px solid rgba(0, 242, 254, 0.2); }}

        .code-box {{
            background: #060911; border: 1px solid var(--border-color); border-radius: 10px; padding: 1rem;
            font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; color: #cbd5e1; overflow-x: auto;
            position: relative; margin-top: 0.8rem; word-break: break-all;
        }}
        
        .btn {{
            display: inline-flex; align-items: center; justify-content: center; gap: 8px;
            background: linear-gradient(135deg, var(--accent-blue) 0%, var(--accent-purple) 100%);
            color: #fff; font-weight: 600; font-size: 0.9rem; border: none; padding: 10px 18px;
            border-radius: 10px; cursor: pointer; transition: opacity 0.2s ease; text-decoration: none;
        }}
        .btn:hover {{ opacity: 0.9; }}
        .btn-green {{ background: linear-gradient(135deg, #00e676, #00c853); }}
        .btn-outline {{ background: transparent; border: 1px solid var(--border-color); color: var(--text-main); }}
        .btn-outline:hover {{ background: rgba(255,255,255,0.08); border-color: var(--accent-cyan); }}

        .buy-section {{ background: rgba(0, 230, 118, 0.05); border: 1px solid rgba(0, 230, 118, 0.2); border-radius: 16px; padding: 2rem; margin-bottom: 2rem; text-align: center; }}
        .buy-grid {{ display: flex; gap: 1rem; justify-content: center; flex-wrap: wrap; margin-top: 1.5rem; }}
        .buy-card {{ background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 12px; padding: 1.5rem; min-width: 160px; text-align: center; transition: all 0.2s; }}
        .buy-card:hover {{ border-color: var(--accent-green); transform: translateY(-2px); }}
        .buy-price {{ font-size: 2rem; font-weight: 700; color: var(--accent-green); }}
        .buy-calls {{ color: var(--text-muted); font-size: 0.9rem; margin: 0.5rem 0 1rem; }}

        .interactive-playground {{
            background: rgba(15, 23, 42, 0.8); border: 1px solid var(--border-color);
            border-radius: 16px; padding: 2rem; margin-top: 2rem; backdrop-filter: blur(12px);
        }}
        select, input {{
            width: 100%; background: #060911; border: 1px solid var(--border-color); color: #fff;
            padding: 10px 14px; border-radius: 8px; font-family: 'JetBrains Mono', monospace; font-size: 0.9rem;
            margin-top: 6px; margin-bottom: 1rem; outline: none;
        }}

        footer {{ text-align: center; color: var(--text-muted); font-size: 0.9rem; margin-top: 3rem; border-top: 1px solid var(--border-color); padding-top: 1.5rem; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="badge"><div class="pulse-dot"></div> Live — Stripe Payments (${PRICE_PER_CALL:.2f} USD/call)</div>
            <h1>Fiat-Monetized MCP AI Tools</h1>
            <p class="subtitle">Pay-per-call Model Context Protocol server. Buy credits via <strong>Stripe</strong>, get an API key, use MCP tools at <strong>${PRICE_PER_CALL:.2f} USD</strong> per call.</p>
        </header>

        <!-- Buy Credits Section -->
        <div class="buy-section">
            <h2 style="font-size: 1.6rem; margin-bottom: 0.3rem;">💳 Buy API Credits</h2>
            <p style="color: var(--text-muted);">Pay with card via Stripe. Get an API key instantly after payment.</p>
            <div class="buy-grid">
                <div class="buy-card">
                    <div class="buy-price">$5</div>
                    <div class="buy-calls">10 tool calls</div>
                    <a href="/buy?amount=5" class="btn btn-green" style="width:100%;">Buy $5</a>
                </div>
                <div class="buy-card" style="border-color: rgba(0,230,118,0.3);">
                    <div class="buy-price">$10</div>
                    <div class="buy-calls">20 tool calls</div>
                    <a href="/buy?amount=10" class="btn btn-green" style="width:100%;">Buy $10</a>
                </div>
                <div class="buy-card">
                    <div class="buy-price">$25</div>
                    <div class="buy-calls">50 tool calls</div>
                    <a href="/buy?amount=25" class="btn btn-green" style="width:100%;">Buy $25</a>
                </div>
                <div class="buy-card">
                    <div class="buy-price">$50</div>
                    <div class="buy-calls">100 tool calls</div>
                    <a href="/buy?amount=50" class="btn btn-green" style="width:100%;">Buy $50</a>
                </div>
            </div>
        </div>

        <div class="grid">
            <div class="card">
                <div class="card-header">
                    <span class="card-title">📡 MCP SSE Endpoint</span>
                    <span class="price-tag">Claude / Cursor</span>
                </div>
                <p style="color: var(--text-muted); font-size: 0.9rem;">SSE Endpoint URL for AI clients:</p>
                <div class="code-box">{BASE_URL}/mcp/sse</div>
                <button class="btn btn-outline" style="margin-top: 10px; width: 100%;" onclick="copyText('{BASE_URL}/mcp/sse', this)">📋 Copy SSE URL</button>
            </div>

            <div class="card">
                <div class="card-header">
                    <span class="card-title">💰 Check Balance</span>
                    <span class="price-tag">${PRICE_PER_CALL:.2f} / call</span>
                </div>
                <p style="color: var(--text-muted); font-size: 0.9rem;">Check remaining credits for your API key:</p>
                <div class="code-box">GET /balance?key=YOUR_API_KEY</div>
                <button class="btn btn-outline" style="margin-top: 10px; width: 100%;" onclick="checkBalance()">🔍 Check My Balance</button>
            </div>
        </div>

        <h2 style="margin-bottom: 1rem; font-weight: 600;">🛠️ Available MCP Tools Suite</h2>
        <div class="grid">
            <div class="card">
                <div class="card-header">
                    <span class="card-title">1. Synthetic Data</span>
                    <span class="price-tag">${PRICE_PER_CALL:.2f} USD</span>
                </div>
                <p style="color: var(--text-muted); font-size: 0.9rem;">Generates high-fidelity synthetic user profiles, transactions, or IoT streams.</p>
                <button class="btn btn-outline" style="margin-top: 12px; width: 100%;" onclick="selectAndTest('generate_synthetic_data')">⚡ Test Execution</button>
            </div>

            <div class="card">
                <div class="card-header">
                    <span class="card-title">2. Crypto Analytics</span>
                    <span class="price-tag">${PRICE_PER_CALL:.2f} USD</span>
                </div>
                <p style="color: var(--text-muted); font-size: 0.9rem;">DEX liquidity pool metrics, 24h volume, price impact & sentiment scores.</p>
                <button class="btn btn-outline" style="margin-top: 12px; width: 100%;" onclick="selectAndTest('crypto_market_analytics')">⚡ Test Execution</button>
            </div>

            <div class="card">
                <div class="card-header">
                    <span class="card-title">3. Web Extractor</span>
                    <span class="price-tag">${PRICE_PER_CALL:.2f} USD</span>
                </div>
                <p style="color: var(--text-muted); font-size: 0.9rem;">Extracts clean markdown summaries and JSON metadata from URLs.</p>
                <button class="btn btn-outline" style="margin-top: 12px; width: 100%;" onclick="selectAndTest('web_content_extractor')">⚡ Test Execution</button>
            </div>
        </div>

        <!-- Interactive Playground -->
        <div class="interactive-playground" id="playground">
            <h3 style="margin-bottom: 0.5rem; font-size: 1.4rem;">🧪 Live API & Authentication Tester</h3>
            <p style="color: var(--text-muted); font-size: 0.9rem; margin-bottom: 1.2rem;">Test execution with your API key (${PRICE_PER_CALL:.2f} USD per call):</p>
            
            <label style="font-size: 0.85rem; font-weight: 600; color: var(--text-muted);">API KEY:</label>
            <input type="text" id="api-key-input" placeholder="Paste your API key here (buy one above ☝️)">

            <label style="font-size: 0.85rem; font-weight: 600; color: var(--text-muted);">SELECT TOOL:</label>
            <select id="tool-select">
                <option value="generate_synthetic_data">generate_synthetic_data (Synthetic Datasets)</option>
                <option value="crypto_market_analytics">crypto_market_analytics (Base Token Analytics)</option>
                <option value="web_content_extractor">web_content_extractor (Web Content Extraction)</option>
            </select>

            <button class="btn" style="width: 100%; margin-bottom: 1rem;" onclick="runTest()">▶ Execute Request (Send POST /mcp/tools/call)</button>

            <label style="font-size: 0.85rem; font-weight: 600; color: var(--text-muted);">LIVE SERVER RESPONSE:</label>
            <div class="code-box" id="response-box" style="min-height: 120px; color: var(--accent-cyan);">Click "Execute Request" above to test API authorization & response...</div>
        </div>

        <footer>
            Powered by <strong>FastAPI</strong> + <strong>mcp SDK</strong> + <strong>Stripe Payments</strong>. Built for machine-to-machine AI economy.
        </footer>
    </div>

    <script>
        function copyText(str, el) {{
            if (navigator.clipboard && window.isSecureContext) {{
                navigator.clipboard.writeText(str).then(() => showCopied(el));
            }} else {{
                let ta = document.createElement('textarea');
                ta.value = str; document.body.appendChild(ta); ta.select();
                document.execCommand('copy'); document.body.removeChild(ta);
                showCopied(el);
            }}
        }}

        function showCopied(el) {{
            let orig = el.innerText;
            el.innerText = '✅ Copied to Clipboard!';
            el.style.borderColor = '#00e676';
            setTimeout(() => {{ el.innerText = orig; el.style.borderColor = ''; }}, 1800);
        }}

        function selectAndTest(toolName) {{
            document.getElementById('tool-select').value = toolName;
            document.getElementById('playground').scrollIntoView({{ behavior: 'smooth' }});
            runTest();
        }}

        function checkBalance() {{
            const apiKey = document.getElementById('api-key-input').value.trim();
            if (!apiKey) {{ alert('Enter your API key in the playground below first!'); return; }}
            fetch('/balance?key=' + encodeURIComponent(apiKey))
                .then(r => r.json())
                .then(data => {{
                    const resBox = document.getElementById('response-box');
                    resBox.innerHTML = '<strong>BALANCE CHECK:</strong><br><br>' + JSON.stringify(data, null, 2);
                    document.getElementById('playground').scrollIntoView({{ behavior: 'smooth' }});
                }});
        }}

        async function runTest() {{
            const tool = document.getElementById('tool-select').value;
            const apiKey = document.getElementById('api-key-input').value.trim();
            const resBox = document.getElementById('response-box');
            resBox.innerText = '⏳ Sending POST request to /mcp/tools/call...';
            
            try {{
                const headers = {{ 'Content-Type': 'application/json' }};
                if (apiKey) {{ headers['Authorization'] = 'Bearer ' + apiKey; }}
                
                const res = await fetch('/mcp/tools/call', {{
                    method: 'POST',
                    headers: headers,
                    body: JSON.stringify({{ tool: tool, arguments: {{ count: 3 }} }})
                }});
                const data = await res.json();
                resBox.innerHTML = '<strong>HTTP STATUS:</strong> ' + res.status + '<br><br>' + 
                                   JSON.stringify(data, null, 2);
            }} catch(err) {{
                resBox.innerText = 'Error: ' + err.message;
            }}
        }}
    </script>
</body>
</html>"""
    return HTMLResponse(content=html)


# ── Mount MCP SSE transport + REST tool endpoint under /mcp ──────────────────

_mcp_sse_app = mcp_server.sse_app(
    sse_path="/sse",
    message_path="/messages/",
)

_combined_routes = list(_mcp_sse_app.routes) + [
    Route("/tools/call", endpoint=handle_rest_tool_call, methods=["GET", "POST", "OPTIONS"]),
    Route("/.well-known/mcp/server-card.json", endpoint=server_card, methods=["GET", "POST", "OPTIONS"]),
    Route("/sse/.well-known/mcp/server-card.json", endpoint=server_card, methods=["GET", "POST", "OPTIONS"]),
]

_mcp_app = Starlette(routes=_combined_routes)

app.mount("/mcp", _mcp_app)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT, log_level=os.getenv("LOG_LEVEL", "info").lower())
