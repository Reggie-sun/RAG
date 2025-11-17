# 使用 Cloudflared + Caddy + Docker Compose 部署 RAG 系统

本文档演示如何用一套 Docker Compose 配置把 GPU RAG 后端、Caddy 反向代理（自动 HTTPS）以及 Cloudflared 隧道串联起来，做到无需暴露主机端口也能通过自己的域名访问服务。

## 架构概览

```
Client (HTTPS)
   │
Cloudflare Edge  ← DNS CNAME rag.example.com ➜ <tunnel-id>.cfargotunnel.com
   │  (TLS terminates here, Zero Trust/WAF 可选)
Cloudflared container (outbound-only tunnel)
   │
Caddy container (Auto HTTPS + reverse proxy)
   │
FastAPI + Celery + Redis (gpu backend stack)
```

- `docker-compose.yml` 负责核心 AI 服务（FastAPI、Celery、Redis、模型卷）。
- `docker-compose.deploy.yml` 作为 overlay 关闭 API 直连端口，并追加 Caddy、Cloudflared 两个服务。
- Caddy 通过 ACME 自动申请 TLS 证书；Cloudflared 把公网流量从 Cloudflare 网络反代到 Caddy，不需要在路由器上做端口转发。

## 前置条件

1. 域名托管在 Cloudflare，并已创建 Zero Trust / Tunnel。
2. 服务器可以访问公网，能够拉取 Docker 镜像，GPU 驱动 + `nvidia-docker` 已配置好。
3. `.env.docker` 中的模型 / API Key / Redis 等参数已按现有部署文档填写。
4. Cloudflared Tunnel：
   - 在 Cloudflare Dashboard → Zero Trust → Networks → Tunnels 创建一个 tunnel，例如 `rag-prod`。
   - 下载 `credentials.json`，并记下 `Tunnel UUID`（形如 `11111111-2222-3333-4444-555555555555`）。
   - CNAME 记录指向 `<TUNNEL_UUID>.cfargotunnel.com`，并把 Hostname 设置为你的域名（例如 `rag.example.com`）。

## 准备文件

1. **Tunnel 凭证**：将下载的 `credentials.json` 保存到 `deploy/cloudflared/credentials/<TUNNEL_UUID>.json`。
2. **环境变量**：在 `.env.docker` 里填写文末新增的几项：
   ```ini
   RAG_DOMAIN=rag.example.com
   CADDY_ACME_EMAIL=ops@example.com
   CLOUDFLARED_TUNNEL_ID=11111111-2222-3333-4444-555555555555
   CLOUDFLARED_UPSTREAM_URL=https://caddy:443   # 若想让 Cloudflared 走 HTTP，可改成 http://caddy:80
   CLOUDFLARED_PROTOCOL=quic                   # quic 更稳定，可改 h2mux
   ```
   > 提示：`RAG_DOMAIN` 会同时写入 Caddy 与 Cloudflared，保持与 DNS 记录一致。

## 构建镜像

```bash
# 生成/更新 rag-system:latest
docker compose build rag-api
```

## 启动核心服务

```bash
# 先把 redis / rag-api / celery 跑起来，方便后面的反代联通性检查
docker compose up -d redis rag-api celery-worker
```

确认 `rag-api` 在内部网络可用：

```bash
docker compose exec rag-api curl -f http://localhost:8000/api/status
```

## 启动 Caddy + Cloudflared Overlay

```bash
docker compose -f docker-compose.yml -f docker-compose.deploy.yml up -d caddy cloudflared
```

- Overlay 文件会把 `rag-api` 的宿主机端口映射清空，只允许通过内部网络访问。
- Caddy 挂载 `deploy/Caddyfile`，默认自动申请 TLS，并把访问日志输出到 `docker compose logs caddy`。
- Cloudflared 使用 `deploy/cloudflared/run.sh` 动态生成配置，读取 `credentials/<TUNNEL_ID>.json` 后运行 `cloudflared tunnel run`。

## 常用验证步骤

1. 查看容器状态
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.deploy.yml ps
   ```
2. 检查证书签发与反代链路
   ```bash
   docker compose logs -f caddy
   docker compose logs -f cloudflared
   ```
3. 从公网验证
   ```bash
   curl -I https://rag.example.com/api/status
   ```
4. 如果仅想局域网访问，可停止 Cloudflared，但保留 Caddy 映射 80/443，或在 DNS 中把记录指向服务器公网 IP。

## 配置调整建议

- **多域名/子路径**：编辑 `deploy/Caddyfile`，复制现有站点块即可；也可以在 Cloudflared 中添加新的 `hostname` 并指向不同的上游。
- **访问控制**：
  - Cloudflare Zero Trust 可对 Tunnel Hostname 做 JWT/MFA；
  - Caddy 可以开启 BasicAuth 或使用 `trusted_proxies`、`client_cert_validation`。
- **自动重启**：`restart: unless-stopped` 已配置，若要配合 systemd，可把 `docker compose` 命令写入 unit。
- **滚动更新**：更新代码后执行
  ```bash
  docker compose build rag-api
  docker compose -f docker-compose.yml -f docker-compose.deploy.yml up -d rag-api celery-worker caddy
  ```
  Cloudflared 会自动复用现有隧道。

## 故障排查

| 现象 | 排查思路 |
| ---- | -------- |
| Caddy 申请证书失败 | 确保 `rag.example.com` 已 CNAME 到 Tunnel，Cloudflared 正常运行，使 ACME 流量能回源。暂时可把 `CLOUDFLARED_UPSTREAM_URL` 设为 `http://caddy:80` 以绕过自签名限制。 |
| Cloudflared 容器退出，提示找不到 credentials | 检查 `deploy/cloudflared/credentials/<TUNNEL_ID>.json` 路径及权限是否正确。 |
| 访问 502 | 用 `docker compose logs caddy` 看上游连接错误，再用 `docker compose exec caddy curl -vk rag-api:8000` 直接调试。 |
| GPU 相关错误 | 和 Caddy/Cloudflared 无关，复用现有 GPU 调试流程即可。 |

完成以上配置后，你就拥有了一套“GPU 服务 → Caddy 自动 HTTPS → Cloudflared 安全外网暴露”的可重复部署方案。EOF
