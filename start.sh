#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
command -v uv >/dev/null || { echo '请先安装 uv: https://docs.astral.sh/uv/'; exit 1; }
command -v npm >/dev/null || { echo '请先安装 Node.js 22 或更高版本'; exit 1; }
uv sync --frozen --python 3.12
if [[ ! -d web/node_modules ]]; then
  npm --prefix web ci
fi
npm --prefix web run build
exec uv run --frozen uvicorn api.main:app --host 127.0.0.1 --port 8000 --no-access-log
