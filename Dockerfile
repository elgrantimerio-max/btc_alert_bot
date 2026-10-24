# Multi-stage lightweight Python runtime for BTC Quant Daemon
FROM python:3.11-slim

# Prevent Python from writing .pyc and buffer logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TZ=UTC

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application codebase
COPY . .

# Healthcheck to verify process health
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD python -c "import engine.quant_core; print('Health OK')" || exit 1

# Launch real-time WebSocket daemon
CMD ["python", "daemon_ws_bot.py"]
