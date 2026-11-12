FROM node:24-bookworm-slim AS frontend
WORKDIR /web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY --from=frontend /usr/local/bin/node /usr/local/bin/node
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg chromium libstdc++6 ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY api/ ./api/
COPY --from=frontend /web/dist/ ./web/dist/
RUN chmod -R a+rX /app/api && useradd --uid 10001 --create-home liuying && mkdir -p /data/jobs && chown -R liuying:liuying /data
USER liuying
ENV LIUYING_DATA_DIR=/data PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
