ARG CADDY_VERSION=2.8.4
FROM --platform=linux/amd64 alpine:3.20 AS downloader
ARG TARGETARCH=amd64
RUN apk add --no-cache curl tar \
  && curl -fsSL "https://caddyserver.com/api/download?os=linux&arch=${TARGETARCH}&version=v${CADDY_VERSION}&p=github.com/caddy-dns/cloudflare" -o /tmp/caddy.tar.gz \
  && tar -xzf /tmp/caddy.tar.gz -C /tmp

FROM --platform=linux/amd64 caddy:${CADDY_VERSION}-alpine
COPY --from=downloader /tmp/caddy /usr/bin/caddy
