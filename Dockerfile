# ============================================================
# SIA-TradeX Pro: Production Containerization Dockerfile
# ============================================================
FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8

WORKDIR /app

# Install system dependencies (build-essential, curl for healthchecks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . /app/

# Expose Web Dashboard & WebSocket port
EXPOSE 8080

# Health check to ensure FastAPI & Quant Engine are responsive
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/api/state || exit 1

# Default execution: Paper Trading mode with Web Dashboard
CMD ["python", "run.py", "--paper", "--port", "8080"]
