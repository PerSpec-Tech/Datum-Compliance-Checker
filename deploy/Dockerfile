# Single container (P7.1): Node builds web/dist, then FastAPI serves the API and the static app.
# Build from the repo root:  docker build -f deploy/Dockerfile -t compliance-checker .

FROM node:22.11.0-slim AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12.8-slim AS app
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 \
    APP_DB_PATH=/data/app.sqlite
# Same layout as the repo: config.REPO_ROOT resolves to /app.
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev
COPY schemas/ /app/schemas/
COPY rules/ /app/rules/
COPY fixtures/models/ /app/fixtures/models/
COPY --from=web /app/web/dist /app/web/dist

VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"
CMD ["/app/backend/.venv/bin/uvicorn", "--factory", "compliance.main:app", \
     "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
