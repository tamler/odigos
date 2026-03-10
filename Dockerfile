FROM python:3.12-slim AS builder

WORKDIR /build

# System deps for building native extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install .

# --- Runtime stage ---
FROM python:3.12-slim

WORKDIR /app

# Runtime system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY odigos/ odigos/
COPY dashboard/ dashboard/
COPY migrations/ migrations/
COPY plugins/ plugins/
COPY skills/ skills/
COPY pyproject.toml .

# Default data and config directories
RUN mkdir -p /app/data /app/data/plugins /app/data/chroma

# Config file mount point
VOLUME ["/app/data"]

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["python", "-m", "uvicorn", "odigos.main:app", "--host", "0.0.0.0", "--port", "8000"]
