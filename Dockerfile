# ---- Stage 1: build the React SPA ----
FROM node:20-alpine AS web
WORKDIR /web
COPY app/ui/web/package.json app/ui/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY app/ui/web/ ./
RUN npm run build

# ---- Stage 2: Python runtime ----
FROM python:3.11-slim
WORKDIR /app

# curl for HEALTHCHECK; build-essential isn't needed (all deps wheel-only).
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Install Python deps first for layer caching; only copy code after.
COPY pyproject.toml README.md ./
COPY app/ ./app/
RUN pip install --no-cache-dir -e .

# Pull the prebuilt SPA into the location FastAPI serves it from.
COPY --from=web /web/dist/ /app/app/ui/web/dist/

# Defaults that point at the host's IB Gateway. The compose file pins these,
# but baking the defaults here means `docker run` works without -e flags.
ENV IBKR_HOST=host.docker.internal \
    IBKR_PORT=7497 \
    IBKR_CLIENT_ID=12 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
