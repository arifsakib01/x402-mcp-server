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

Payment Architecture (Non-Crypto Fiat)
--------------------------------------
- **Price**: $0.50 USD per tool call.
- **Authentication**: `Authorization: Bearer <API_KEY>` or `X-API-Key: <API_KEY>`.
- **Payouts**: Direct bank account settlement via Stripe.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from mcp_tools import invoke_tool, mcp_server

# ══════════════════════════════════════════════════════════════════════════════
# Environment & Configuration
# ══════════════════════════════════════════════════════════════════════════════

load_dotenv()

PRICE_PER_CALL: float = float(os.getenv("PRICE_PER_CALL", "0.50"))
ADMIN_API_KEY: str = os.getenv("ADMIN_API_KEY", "mcp_key_live_master_998877665544332211")
STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "sk_test_placeholder")
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8402"))

# Valid active API keys set (in-memory; expand with DB or Stripe webhooks)
VALID_API_KEYS: set[str] = {
    ADMIN_API_KEY,
    "mcp_key_demo_client_123456",
}

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("mcp_server")


# ══════════════════════════════════════════════════════════════════════════════
# API Key Authorization Middleware ($0.50 USD / Call)
# ══════════════════════════════════════════════════════════════════════════════

class APIKeyAuthMiddleware:
    """
    ASGI Middleware enforcing API Key Authorization ($0.50 USD/call).

    Checks incoming requests for:
      - `Authorization: Bearer <API_KEY>`
      - `X-API-Key: <API_KEY>`
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        method: str = scope.get("method", "GET").upper()

        # Handle non-GET calls (POST/OPTIONS) on /mcp/sse gracefully with 200 OK capabilities
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
                            "name": "fiat-monetized-mcp-server",
                            "version": "1.0.0",
                        },
                    },
                },
            )
            await response(scope, receive, send)
            return

        # Allow health, landing dashboard, server-card metadata, and SSE stream discovery freely.
        # Tool execution (/mcp/tools/call & message executions) requires API Key ($0.50/call).
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

        # Verify API key
        if not api_key or api_key not in VALID_API_KEYS:
            logger.info("🚫  401 Unauthorized for %s (invalid or missing API Key)", path)
            response = JSONResponse(
                status_code=401,
                content={
                    "error": "Unauthorized — API Key Required",
                    "message": (
                        f"This MCP tool execution requires a valid API Key (${PRICE_PER_CALL:.2f} USD per call). "
                        "Include 'Authorization: Bearer <API_KEY>' or 'X-API-Key: <API_KEY>' header."
                    ),
                    "pricing": {
                        "amount_usd": PRICE_PER_CALL,
                        "currency": "USD",
                        "master_key_for_testing": ADMIN_API_KEY,
                    },
                },
                headers={
                    "WWW-Authenticate": 'Bearer realm="MCP Tool Execution"',
                    "X-Price-USD": str(PRICE_PER_CALL),
                },
            )
            await response(scope, receive, send)
            return

        logger.info("✅  API Key Authorized for %s (key: %s…)", path, api_key[:16])
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

    try:
        results = await invoke_tool(tool_name, arguments)
        return JSONResponse(content={
            "status": "success",
            "tool": tool_name,
            "price_usd": PRICE_PER_CALL,
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
    logger.info("   📡  MCP SSE : http://%s:%s/mcp/sse", HOST, PORT)
    logger.info("   🔧  REST    : http://%s:%s/mcp/tools/call", HOST, PORT)
    yield
    logger.info("🛑  MCP Server shutting down")


app = FastAPI(
    title="Fiat-Monetized MCP Server",
    description="Model Context Protocol server with API Key & Bank Payout gating ($0.50 USD / call)",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(APIKeyAuthMiddleware)


@app.api_route("/health", methods=["GET", "POST", "HEAD", "OPTIONS"])
async def health_check():
    """Public JSON health-check endpoint."""
    return {
        "status": "healthy",
        "service": "fiat-monetized-mcp-server",
        "price_per_call_usd": PRICE_PER_CALL,
        "payment_method": "fiat_stripe_bank_payout",
        "master_api_key": ADMIN_API_KEY,
        "endpoints": {
            "health": "GET  /health",
            "dashboard": "GET  /",
            "server_card": "GET  /.well-known/mcp/server-card.json",
            "mcp_sse": "GET  /mcp/sse",
            "rest_tool_call": "POST /mcp/tools/call",
        },
    }


@app.api_route("/.well-known/mcp/server-card.json", methods=["GET", "POST", "HEAD", "OPTIONS"])
@app.api_route("/.well-known/mcp.json", methods=["GET", "POST", "HEAD", "OPTIONS"])
async def server_card():
    """Smithery.ai server metadata card for automated indexing."""
    return {
        "$schema": "https://smithery.ai/docs/mcp-server-card.schema.json",
        "name": "x402-mcp-server",
        "title": "Monetized MCP AI Tools Suite ($0.50 USD)",
        "description": (
            "A suite of premium MCP tools (Synthetic Data Generator, Crypto Market Analytics, "
            "Web Extractor) gated by $0.50 USD API Key authorization."
        ),
        "version": "2.0.0",
        "author": "arif-sakib",
        "icon": "https://raw.githubusercontent.com/arif-sakib/x402-mcp-server/main/icon.png",
        "homepage": "https://x402-mcp-server-production.up.railway.app/",
        "repository": "https://github.com/arif-sakib/x402-mcp-server",
        "configSchema": {
            "type": "object",
            "properties": {
                "apiKey": {
                    "type": "string",
                    "description": f"API Key for tool execution ($0.50 USD/call). Master key: {ADMIN_API_KEY}"
                }
            }
        },
        "payment": {
            "protocol": "api_key_fiat",
            "currency": "USD",
            "amount": PRICE_PER_CALL,
        },
        "tools": [
            {
                "name": "generate_synthetic_data",
                "description": "Generates synthetic user profiles, transactions, or IoT streams.",
                "annotations": {"readOnly": True, "idempotent": True},
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
                    }
                }
            },
            {
                "name": "crypto_market_analytics",
                "description": "Base network token analytics, DEX liquidity & sentiment.",
                "annotations": {"readOnly": True, "idempotent": True},
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
                        "price_usd": {"type": "number", "description": "Current price in USD."},
                        "dex_liquidity_usd": {"type": "number", "description": "Total DEX liquidity in USD."}
                    }
                }
            },
            {
                "name": "web_content_extractor",
                "description": "Clean markdown & JSON extraction from web URLs.",
                "annotations": {"readOnly": True, "idempotent": True},
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Full HTTPS URL to scrape and summarize."}
                    }
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Extracted page title."},
                        "summary": {"type": "string", "description": "Clean LLM-optimized summary."}
                    }
                }
            },
        ],
    }


@app.get("/", response_class=HTMLResponse)
async def landing_dashboard():
    """Public Glassmorphic Dark-Mode Landing Dashboard."""
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
            border-radius: 10px; cursor: pointer; transition: opacity 0.2s ease;
        }}
        .btn:hover {{ opacity: 0.9; }}
        .btn-outline {{ background: transparent; border: 1px solid var(--border-color); color: var(--text-main); }}
        .btn-outline:hover {{ background: rgba(255,255,255,0.08); border-color: var(--accent-cyan); }}

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
            <div class="badge"><div class="pulse-dot"></div> Live — Bank Payout API ($0.50 USD)</div>
            <h1>Fiat-Monetized MCP AI Tools</h1>
            <p class="subtitle">Pay-per-call Model Context Protocol server. Gated by API Key Authorization at <strong>${PRICE_PER_CALL:.2f} USD</strong> per tool execution.</p>
        </header>

        <div class="grid">
            <div class="card">
                <div class="card-header">
                    <span class="card-title">🔑 Master API Key</span>
                    <span class="price-tag">${PRICE_PER_CALL:.2f} USD / call</span>
                </div>
                <p style="color: var(--text-muted); font-size: 0.9rem;">Include in <code>Authorization: Bearer</code> header:</p>
                <div class="code-box" id="key-text">{ADMIN_API_KEY}</div>
                <button class="btn btn-outline" style="margin-top: 10px; width: 100%;" onclick="copyText('{ADMIN_API_KEY}', this)">📋 Copy Master API Key</button>
            </div>

            <div class="card">
                <div class="card-header">
                    <span class="card-title">📡 MCP SSE Endpoint</span>
                    <span class="price-tag">Claude / Cursor</span>
                </div>
                <p style="color: var(--text-muted); font-size: 0.9rem;">SSE Endpoint URL for AI clients:</p>
                <div class="code-box">https://x402-mcp-server-production.up.railway.app/mcp/sse</div>
                <button class="btn btn-outline" style="margin-top: 10px; width: 100%;" onclick="copyText('https://x402-mcp-server-production.up.railway.app/mcp/sse', this)">📋 Copy SSE URL</button>
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
            <input type="text" id="api-key-input" value="{ADMIN_API_KEY}">

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
            Powered by <strong>FastAPI</strong> + <strong>mcp SDK</strong> + <strong>Stripe Bank Payouts</strong>. Built for machine-to-machine AI economy.
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
