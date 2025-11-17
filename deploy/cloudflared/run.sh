#!/bin/sh
set -euo pipefail

: "${CLOUDFLARED_TUNNEL_ID:?Set CLOUDFLARED_TUNNEL_ID in .env.docker}"
: "${RAG_DOMAIN:?Set RAG_DOMAIN in .env.docker}"
UPSTREAM_URL="${CLOUDFLARED_UPSTREAM_URL:-https://caddy:443}"
PROTOCOL="${CLOUDFLARED_PROTOCOL:-quic}"
CONFIG_PATH="/tmp/cloudflared-config.yml"
CREDENTIALS_FILE="/etc/cloudflared/credentials/${CLOUDFLARED_TUNNEL_ID}.json"

if [ ! -f "$CREDENTIALS_FILE" ]; then
    echo "Missing Cloudflared credentials JSON at $CREDENTIALS_FILE" >&2
    exit 1
fi

cat >"$CONFIG_PATH" <<EOF_CFG
tunnel: ${CLOUDFLARED_TUNNEL_ID}
credentials-file: ${CREDENTIALS_FILE}
protocol: ${PROTOCOL}

ingress:
  - hostname: ${RAG_DOMAIN}
    service: ${UPSTREAM_URL}
    originRequest:
      originServerName: ${RAG_DOMAIN}
      httpHostHeader: ${RAG_DOMAIN}
      http2Origin: true
      connectTimeout: 30s
      tlsTimeout: 10s
  - service: http_status:404
EOF_CFG

exec cloudflared tunnel --config "$CONFIG_PATH" run
