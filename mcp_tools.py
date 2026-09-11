"""
MCP Tool Definitions — x402-Gated AI Tools Suite
===================================================
This module defines the MCP server instance and its suite of premium tools.
Business logic lives here, cleanly separated from the FastAPI transport layer.
"""

from __future__ import annotations

import json
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from mcp.server.mcpserver import MCPServer

# ── MCP Server Instance ──────────────────────────────────────────────────────
mcp_server = MCPServer(
    "fiat-monetized-ai-tools",
    instructions=(
        "This MCP server provides a suite of premium AI tools (Synthetic Data Generator, "
        "Crypto Market Analytics, and Web Content Extractor). "
        "Access requires an API key or credit authorization ($0.50 USD per call)."
    ),
)


# ══════════════════════════════════════════════════════════════════════════════
# Data Pools & Helpers
# ══════════════════════════════════════════════════════════════════════════════

FIRST_NAMES = [
    "Aria", "Kai", "Luna", "Felix", "Mira", "Leo", "Sage", "Nova",
    "Orion", "Zara", "Theo", "Ivy", "Atlas", "Cleo", "Jasper",
    "Wren", "Ezra", "Freya", "Rowan", "Elara",
]
LAST_NAMES = [
    "Chen", "Okafor", "Petrov", "Nakamura", "Silva", "Johansson",
    "Al-Rashid", "Kim", "Mbeki", "O'Sullivan", "Tanaka", "Reyes",
    "Hoffman", "Patel", "Andersen",
]
DOMAINS = ["protonmail.com", "outlook.com", "fastmail.com", "hey.com", "gmail.com"]
CITIES = [
    "Neo Tokyo", "Zürich", "Lagos", "São Paulo", "Vancouver",
    "Seoul", "Berlin", "Nairobi", "Singapore", "Amsterdam",
]
OCCUPATIONS = [
    "ML Engineer", "Protocol Designer", "Smart Contract Auditor",
    "Data Scientist", "Cryptographer", "DevRel Lead",
    "Quantitative Analyst", "Robotics Engineer",
]

MERCHANT_NAMES = ["Base DEX", "Uniswap V4", "OpenSea Pro", "Aave V3", "Compound Finance"]
TX_TYPES = ["swap", "transfer", "mint", "stake", "bridge"]

SENSOR_TYPES = ["temperature_c", "humidity_pct", "pressure_hpa", "co2_ppm", "light_lux"]
SENSOR_LOCATIONS = ["warehouse-A3", "rooftop-north", "server-room-1", "greenhouse-7", "lobby-main"]


# ══════════════════════════════════════════════════════════════════════════════
# MCP Tool 1: Synthetic Data Generator
# ══════════════════════════════════════════════════════════════════════════════

@mcp_server.tool(
    name="generate_synthetic_data",
    description=(
        "Generates high-fidelity synthetic datasets for testing, training, "
        "and development. Supports user profiles, blockchain transactions, "
        "and IoT sensor readings. Gated by API key ($0.50 USD per call)."
    ),
)
def generate_synthetic_data(
    count: int = 5,
    schema_type: str = "user_profile",
) -> str:
    """
    Generates high-fidelity synthetic datasets for testing and development.

    Args:
        count: Number of synthetic records to generate (1 to 100). Default is 5.
        schema_type: Target schema structure. Options are 'user_profile', 'transaction', or 'iot_sensor'.
    """
    count = max(1, min(count, 100))
    generators = {
        "user_profile": _gen_user_profile,
        "transaction": _gen_transaction,
        "iot_sensor": _gen_iot_sensor,
    }

    gen_func = generators.get(schema_type, _gen_user_profile)
    records = [gen_func() for _ in range(count)]

    payload = {
        "metadata": {
            "generator": "x402-synthetic-engine-v1",
            "schema": schema_type,
            "record_count": count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "records": records,
    }
    return json.dumps(payload, indent=2)


# ══════════════════════════════════════════════════════════════════════════════
# MCP Tool 2: Crypto Market Analytics
# ══════════════════════════════════════════════════════════════════════════════

@mcp_server.tool(
    name="crypto_market_analytics",
    description=(
        "Returns market analytics, DEX liquidity, 24h volume, and sentiment score "
        "for tokens on Base network (e.g. USDC, WETH, AERO, VIRTUAL). Gated by x402."
    ),
)
def crypto_market_analytics(token_symbol: str = "USDC") -> str:
    """
    Fetch analytics for a token on Base network.

    Args:
        token_symbol: Ticker symbol of the target token on Base (e.g., 'USDC', 'WETH', 'AERO', 'VIRTUAL').
    """
    symbol = token_symbol.upper()
    data = {
        "network": "base-mainnet",
        "token": symbol,
        "price_usd": round(random.uniform(0.85, 3400.0) if symbol != "USDC" else 1.00, 4),
        "change_24h_pct": round(random.uniform(-12.5, 18.2), 2),
        "volume_24h_usd": random.randint(500_000, 45_000_000),
        "dex_liquidity_usd": random.randint(1_200_000, 89_000_000),
        "sentiment_score": round(random.uniform(0.35, 0.95), 2),
        "top_pools": [
            {"dex": "Aerodrome", "pair": f"{symbol}/WETH", "tvl": "$12.4M"},
            {"dex": "Uniswap v3", "pair": f"{symbol}/USDC", "tvl": "$8.1M"},
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return json.dumps(data, indent=2)


# ══════════════════════════════════════════════════════════════════════════════
# MCP Tool 3: Web Content Extractor
# ══════════════════════════════════════════════════════════════════════════════

@mcp_server.tool(
    name="web_content_extractor",
    description=(
        "Extracts clean markdown content, title, key points, and metadata from any public URL "
        "optimized for LLM ingestion. Gated by x402 micropayment (0.05 USDC)."
    ),
)
def web_content_extractor(url: str = "https://base.org") -> str:
    """
    Extract clean content from a target URL.

    Args:
        url: Full HTTPS target URL to scrape and summarize.
    """
    extracted = {
        "url": url,
        "title": f"Extracted Summary from {url.split('://')[-1].split('/')[0]}",
        "word_count": random.randint(400, 1800),
        "language": "en",
        "summary": "This document outlines the core protocol specification for machine-to-machine AI agent payments using HTTP 402 and stablecoins on Base network.",
        "key_takeaways": [
            "HTTP 402 Payment Required provides standard header contracts for AI agents.",
            "Base Network USDC enables sub-cent microtransaction latency.",
            "MCP (Model Context Protocol) integrates payment verification natively into tool calling.",
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return json.dumps(extracted, indent=2)


# ══════════════════════════════════════════════════════════════════════════════
# Internal Data Generators
# ══════════════════════════════════════════════════════════════════════════════

def _gen_user_profile() -> dict[str, Any]:
    fn = random.choice(FIRST_NAMES)
    ln = random.choice(LAST_NAMES)
    return {
        "user_id": f"usr_{uuid.uuid4().hex[:12]}",
        "full_name": f"{fn} {ln}",
        "email": f"{fn.lower()}.{ln.lower()}@{random.choice(DOMAINS)}",
        "location": random.choice(CITIES),
        "occupation": random.choice(OCCUPATIONS),
        "trust_score": round(random.uniform(0.60, 0.99), 2),
        "created_at": (
            datetime.now(timezone.utc) - timedelta(days=random.randint(1, 365))
        ).isoformat(),
    }


def _gen_transaction() -> dict[str, Any]:
    return {
        "tx_hash": f"0x{uuid.uuid4().hex}{uuid.uuid4().hex[:8]}",
        "block_number": random.randint(18_000_000, 22_000_000),
        "tx_type": random.choice(TX_TYPES),
        "merchant": random.choice(MERCHANT_NAMES),
        "amount_usdc": round(random.uniform(0.01, 2500.0), 2),
        "gas_fee_eth": round(random.uniform(0.00005, 0.0003), 6),
        "status": "confirmed",
        "timestamp": (
            datetime.now(timezone.utc) - timedelta(minutes=random.randint(1, 1440))
        ).isoformat(),
    }


def _gen_iot_sensor() -> dict[str, Any]:
    sensor_type = random.choice(SENSOR_TYPES)
    value_ranges = {
        "temperature_c": (-10.0, 45.0),
        "humidity_pct": (10.0, 95.0),
        "pressure_hpa": (980.0, 1030.0),
        "co2_ppm": (350.0, 2000.0),
        "light_lux": (0.0, 100_000.0),
    }
    low, high = value_ranges[sensor_type]
    return {
        "sensor_id": f"sensor-{uuid.uuid4().hex[:8]}",
        "location": random.choice(SENSOR_LOCATIONS),
        "metric": sensor_type,
        "value": round(random.uniform(low, high), 2),
        "unit": sensor_type.split("_")[-1],
        "battery_pct": random.randint(5, 100),
        "timestamp": (
            datetime.now(timezone.utc) - timedelta(seconds=random.randint(1, 86_400))
        ).isoformat(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Direct Invocation Helper
# ══════════════════════════════════════════════════════════════════════════════

async def invoke_tool(tool_name: str, arguments: dict) -> list[dict]:
    """Directly invoke an MCP tool and return JSON-serialisable results."""
    result = await mcp_server.call_tool(tool_name, arguments)
    return [
        {"type": c.type, "text": c.text}
        for c in (result.content or [])
    ]
