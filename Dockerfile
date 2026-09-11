# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# Install dependencies into a virtual env for clean layer caching
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Copy the virtual env from the builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY mcp_tools.py server.py ./

# Non-root user for security
RUN useradd --create-home appuser
USER appuser

# Railway / Fly.io inject PORT as an env var; default to 8402
ENV PORT=8402
EXPOSE ${PORT}

# Health check against the public / endpoint
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/')" || exit 1

# Run with uvicorn — $PORT is injected by the hosting platform
CMD uvicorn server:app --host 0.0.0.0 --port ${PORT} --log-level info
