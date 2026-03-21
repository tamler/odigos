FROM python:3.12-slim AS builder

WORKDIR /build

# System deps for building native extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY odigos/ odigos/
RUN pip install --no-cache-dir --prefix=/install --timeout=300 .

# The sqlite-vec pip package ships a broken 32-bit ARM binary on aarch64.
# Replace with our pre-compiled vec0.so only on ARM (x86_64 pip binary works fine).
COPY vendor/vec0.so /tmp/vec0.so
RUN if [ "$(uname -m)" = "aarch64" ]; then \
      cp /tmp/vec0.so "$(find /install -path '*/sqlite_vec/vec0.so' -print -quit)"; \
    fi

# --- Dashboard build stage ---
FROM node:22-slim AS dashboard-builder

WORKDIR /dashboard
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY dashboard/ .
RUN npm run build

# --- Runtime stage ---
FROM python:3.12-slim

WORKDIR /app

# Runtime system deps: curl for healthcheck, bubblewrap for sandbox isolation
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    bubblewrap \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY odigos/ odigos/
COPY --from=dashboard-builder /dashboard/dist/ dashboard/dist/
COPY migrations/ migrations/
COPY plugins/ plugins/
COPY skills/ skills/
COPY pyproject.toml .

# Create non-root user
RUN groupadd -r odigos && useradd -r -g odigos -d /app -s /sbin/nologin odigos

# Data directory (writable by odigos user)
# Application code stays root-owned (read-only for odigos user)
RUN mkdir -p /app/data /app/data/plugins /app/data/files && \
    chown -R odigos:odigos /app/data

# Pre-download the embedding model as the odigos user so the cache is accessible at runtime.
# HF_HOME ensures the cache lands in /app/.cache/huggingface (odigos user's home).
# TRANSFORMERS_OFFLINE=1 at runtime prevents re-downloading newer Python files on every startup.
ENV HF_HOME=/app/.cache/huggingface
RUN mkdir -p /app/.cache && chown -R odigos:odigos /app/.cache
USER odigos
RUN python -c "\
from sentence_transformers import SentenceTransformer, CrossEncoder; \
SentenceTransformer('nomic-ai/nomic-embed-text-v1.5', trust_remote_code=True); \
CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

# Config file mount point
VOLUME ["/app/data"]

ENV PYTHONUNBUFFERED=1
ENV TRANSFORMERS_OFFLINE=1
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# --no-new-privileges prevents privilege escalation via SUID binaries
ENTRYPOINT ["python", "-m", "uvicorn", "odigos.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
