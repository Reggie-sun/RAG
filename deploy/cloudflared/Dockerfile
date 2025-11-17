FROM cloudflare/cloudflared:2024.8.2 AS upstream

FROM alpine:3.20
RUN apk add --no-cache ca-certificates bash
COPY --from=upstream /usr/local/bin/cloudflared /usr/local/bin/cloudflared
COPY run.sh /usr/local/bin/run-cloudflared.sh
RUN chmod +x /usr/local/bin/run-cloudflared.sh
ENTRYPOINT ["/usr/local/bin/run-cloudflared.sh"]
