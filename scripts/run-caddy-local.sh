#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CADDYFILE="${PROJECT_ROOT}/deploy/Caddyfile"

if ! command -v caddy >/dev/null 2>&1; then
  echo "未找到 caddy，请先安装：https://caddyserver.com/docs/install" >&2
  exit 1
fi

export RAG_DOMAIN="${RAG_DOMAIN:-localhost}"
export CADDY_ACME_EMAIL="${CADDY_ACME_EMAIL:-dev@example.com}"
export RAG_UPSTREAM="${RAG_UPSTREAM:-http://127.0.0.1:8000}"

echo "使用 RAG_DOMAIN=${RAG_DOMAIN}，上游=${RAG_UPSTREAM}"
exec caddy run --config "${CADDYFILE}"
