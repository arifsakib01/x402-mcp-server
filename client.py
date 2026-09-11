"""
Fiat-Monetized MCP Client Demo ($0.50 USD / Call)
=================================================
An asynchronous Python client demonstrating tool execution against the MCP server
using API Key authentication ($0.50 USD/call) and Stripe settlement backend.

Execution Flow
--------------
1. Client POSTs a tool-call request without an API key.
2. Server responds with HTTP 401 Unauthorized.
3. Client retries with valid API Key header ('Authorization: Bearer <API_KEY>').
4. Server verifies key, accounts for $0.50 USD charge, and executes the MCP tool.
5. Client receives and displays the tool output.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

# Ensure UTF-8 output on Windows consoles
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")

import httpx

# ══════════════════════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════════════════════

# Use local server if target is specified or fallback to production
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8402")
TOOL_ENDPOINT = f"{SERVER_URL}/mcp/tools/call"
API_KEY = os.getenv("ADMIN_API_KEY", "mcp_key_live_master_998877665544332211")

# Choose tool via command line argument or default to generate_synthetic_data
selected_tool = sys.argv[1] if len(sys.argv) > 1 else "generate_synthetic_data"

TOOL_REQUESTS = {
    "generate_synthetic_data": {
        "tool": "generate_synthetic_data",
        "arguments": {"count": 3, "schema_type": "user_profile"},
    },
    "crypto_market_analytics": {
        "tool": "crypto_market_analytics",
        "arguments": {"token_symbol": "USDC"},
    },
    "web_content_extractor": {
        "tool": "web_content_extractor",
        "arguments": {"url": "https://stripe.com"},
    },
}

TOOL_REQUEST: dict = TOOL_REQUESTS.get(selected_tool, TOOL_REQUESTS["generate_synthetic_data"])

DIVIDER = "═" * 72


async def main() -> None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        print(f"\n{DIVIDER}")
        print("   Fiat-Monetized MCP Client — $0.50 USD API Key Demo")
        print(DIVIDER)
        print(f"   Target Server : {SERVER_URL}")
        print(f"   Tool Name     : {TOOL_REQUEST['tool']}")
        print(f"   Price         : $0.50 USD / Call")

        # ── Step 1: Initial request (no API Key) ─────────────────────────
        print(f"\n──── Step 1: Request MCP tool (No Authorization Header) ────")
        print(f"   → POST {TOOL_ENDPOINT}")
        print(f"   → Body: {json.dumps(TOOL_REQUEST)}")

        try:
            response = await client.post(TOOL_ENDPOINT, json=TOOL_REQUEST)
            print(f"   ← Status: {response.status_code}")

            if response.status_code == 401:
                print("   ← Server responded with HTTP 401 Unauthorized (Auth Required)  ✓")
                print(f"   ← Error detail: {response.json().get('detail', response.text)}")
            else:
                print(f"   ℹ️ Server returned status {response.status_code}")
        except httpx.ConnectError:
            print(f"   ⚠️ Could not connect to {SERVER_URL}. Trying local server http://localhost:8402 ...")

        # ── Step 2: Retry request with API Key ───────────────────────────
        print(f"\n──── Step 2: Retry request with API Key ────")
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        print(f"   → Authorization: Bearer {API_KEY[:15]}...")

        response = await client.post(TOOL_ENDPOINT, json=TOOL_REQUEST, headers=headers)
        print(f"   ← Status: {response.status_code}")

        if response.status_code != 200:
            print(f"   ❌ Execution failed: {response.text}")
            return

        print("   ← Server authenticated key, charged $0.50 USD, and executed tool!  ✓")

        # ── Step 3: Display tool output ──────────────────────────────────
        print(f"\n──── Step 3: Tool Execution Result ────")
        result = response.json()
        print(json.dumps(result, indent=2))

        print(f"\n{DIVIDER}")
        print("   MCP Tool Call successfully completed with $0.50 USD API Key Auth")
        print(f"{DIVIDER}\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
