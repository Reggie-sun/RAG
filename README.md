# RAG 系统启动指南

## ✨ 项目概览

- 支持文档 RAG 检索 + 可选联网搜索  
- 结构化回答（摘要 / 关键结论 / 方法 / 风险），附原文引用  
- 多主题问题并行处理、Rerank/TopK 可调、反馈记忆  
- 前端 React + Vite，后端 FastAPI + Celery + Redis，支持 GPU / CPU 双模式  

---

## 🚀 本地快速启动

> 适合开发调试；默认使用本机的 Ollama / 其他 LLM 服务。

### 1. 安装依赖

```bash
# Python 依赖
pip install -r rag-system/backend/requirements.txt

# Node.js 依赖
cd rag-system/frontend && npm install
```

### 2. 配置 `.env`

在仓库根目录创建或编辑 `.env`：

```env
# 最小必需配置
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5-coder:14b  # 显存足够可以换成 14b

# 向量/设备配置
EMBEDDING_DEVICE=cpu           # 有 GPU 改成 cuda
EMBEDDING_MODEL_PATH=/path/to/your/embedding/model

# 调试选项
DEBUG_ROUTER=true
OLLAMA_TIMEOUT=30

# 队列配置（可选）
# start.sh 默认会在本机自动启动 redis-server
# 如果你要使用自带的 Redis，可以覆盖这些变量：
# MANAGE_REDIS=false
# CELERY_BROKER_URL=redis://your-host:6379/0
# CELERY_RESULT_BACKEND=redis://your-host:6379/1
```

如需联网搜索，可额外配置 Tavily/OpenAI 等 KEY，详见后端配置文件。

### 3. 启动全部服务

```bash
# 清理 MCP 相关环境变量，避免调试残留
unset MCP_DEBUG

# 一键启动：GPU FastAPI + CPU FastAPI + Celery + Redis + 前端
./start.sh
```

### 4. 验证启动

启动成功时终端会看到类似输出：

```text
加载环境变量 .../.env
释放端口 8000
释放端口 8001
释放端口 5173
启动 GPU FastAPI (8000)  PID=xxxx
启动 CPU FastAPI (8001)  PID=xxxx
启动 Celery Worker      PID=xxxx
启动 Vite 前端 (5173)   PID=xxxx
所有服务已启动。按 Ctrl+C 结束。
```

### 5. 访问服务

- 前端界面：<http://localhost:5173>  
- GPU 后端 API 文档：<http://localhost:8000/docs>  
- CPU 后端 API 文档：<http://localhost:8001/docs>

---

## 🐳 Docker 复现 / 部署

> 使用 `docker compose` 一键拉起 **rag-api + Celery Worker + Redis**，适合部署或同事快速复现。

### 1. 前置依赖

1. Docker Engine / Docker Desktop（带 `docker compose` v2）  
2. 如需 GPU：安装 [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)，并确认：

```bash
docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu22.04 nvidia-smi
```

3. 模型准备：
   - 将本地的 bge-m3 / 其他 embedding 模型放到 `./models/bge-m3`
   - 如果需要 Ollama/OpenAI 等服务，请确保宿主机能访问，并在 `.env.docker` 中配置对应 KEY/URL

### 2. 配置 `.env.docker`

```bash
cp .env.docker.example .env.docker
```

根据实际环境调整：

- `EMBEDDING_MODEL_PATH=/app/models/bge-m3`（容器内模型路径）  
- `OLLAMA_BASE_URL`：
  - macOS / Windows：`http://host.docker.internal:11434`
  - Linux 原生 Docker：`http://172.17.0.1:11434`（或你实际的宿主机 IP）  
- `CELERY_BROKER_URL=redis://redis:6379/0`  
- `CELERY_RESULT_BACKEND=redis://redis:6379/1`

### 3. 构建与启动

```bash
# 首次运行或代码有更新时
docker compose build

# 启动（默认 GPU）：
docker compose up -d
```

如果只用 CPU：

1. 在 `.env.docker` 中设置 `ENABLE_GPU=false`  
2. 将 `docker-compose.yml` 中 `deploy.reservations.devices` 删除或注释掉

### 4. 容器内服务说明

- `rag-api`：FastAPI 应用 + 构建好的前端静态资源（默认映射 `8000:8000`）  
- `celery-worker`：后台任务，和 API 共享 `/app/data`、模型缓存  
- `redis`：任务队列 / 结果存储  

所有持久化目录均挂载到宿主机：

- `./rag-system/data` ↔ `/app/data`（索引、日志等）  
- `./models` ↔ `/app/models`（embedding / 自带模型）  
- HuggingFace 缓存放在名为 `hf-cache` 的 Docker volume 中，重复拉起不会重复下载。

验证 / 调试：

- 访问前端/后端：<http://localhost:8000>（rag-api 会同时托管前端）  
- 查看日志：

```bash
docker compose logs -f rag-api
docker compose logs -f celery-worker
```

- 停止服务：

```bash
docker compose down
```

---

## 🧪 测试与使用场景

系统支持多种问题类型，例如：

1. **常识问题**：`什么是机器学习？`  
2. **方法指导**：`写一个排查 Linux CPU 飙高的步骤`  
3. **对比分析**：`对比 React 和 Vue 的优缺点`  
4. **决策建议**：`我应该先做文档知识库还是 BI 报表？`  
5. **文档分析**：`根据上传的 PDF 总结核心发现和行动项`  
6. **多主题查询**：`解释一下 CPPS，并给出放松练习方法`  

---

## 🤖 飞书对接（可选）

项目内置了 `/integrations/feishu/events` 回调接口，可直接接入飞书机器人：

1. 在飞书开放平台创建自建应用，开启机器人能力和 `im.message.receive_v1` 事件。  
2. 在 `.env` / `.env.docker` 中填入：
   - `FEISHU_APP_ID`  
   - `FEISHU_APP_SECRET`  
   - `FEISHU_VERIFICATION_TOKEN`  
   - 如启用加密：`FEISHU_ENCRYPT_KEY`
3. 在事件订阅里将回调 URL 配置为：  
   `https://你的域名/integrations/feishu/events`

支持 `text`、`post`（富文本）、`interactive`（卡片）三类消息，会自动抽取文字并触发 RAG 检索。  
详细步骤见 `docs/feishu-integration.md`。

---

## 📱 微信 / 企业微信对接（可选）

1. **微信公众号**：  
   - 在「服务器配置」里把 URL 指向：`https://你的域名/integrations/wechat/official`  
   - 在 `.env` 中配置：`WECHAT_TOKEN`、`WECHAT_APP_ID`、`WECHAT_ENCODING_AES_KEY`

2. **企业微信**：  
   - 在自建应用的「接收消息」中填：`https://你的域名/integrations/wechat/wecom`  
   - 在 `.env` 中配置：`WECOM_TOKEN`、`WECOM_CORP_ID`、`WECOM_ENCODING_AES_KEY`

系统会按照微信官方规范自动解密/加密，保证消息往返安全。  
详细说明参见 `docs/wechat-integration.md`。

---

## 🧑‍💼 客服 / 业务系统对接

如果后续项目中的客服系统或机器人需要直接调用 RAG 服务，可以使用内置接口：

- **Endpoint**：`POST /integrations/customer-service/ask`  
- **认证**：在 `.env` 中设置 `CUSTOMER_SERVICE_API_KEY=xxx`，客户端通过 Header `X-Customer-Service-Token: xxx` 访问（未设置时默认免认证，仅建议开发环境）  
- **可选标识**：`X-Customer-Service-Partner: partner_name` 用于区分渠道  
- **速率限制**：`CUSTOMER_SERVICE_RATE_LIMIT_PER_MINUTE`（默认 60 req/min）

请求示例：

```json
{
  "question": "你们的 GPU 配置？",
  "session_id": "customer:vip001",
  "allow_web": true,
  "doc_only": false,
  "filters": {
    "source": ["产品资料", "FAQ"]
  },
  "metadata": {
    "channel": "web_chat",
    "customer_tier": "VIP"
  }
}
```

响应会包含 `answer`、`citations`、`suggestions`、`sources` 以及回传的 `metadata`，方便前端直接使用。

---

## ⚠️ 常见问题 & 排查

1. **端口占用**  
   - `start.sh` 会自动释放 8000 / 8001 / 5173  
   - 如仍失败，可手动执行：`lsof -i:8000` / `lsof -i:5173`

2. **Ollama 连接失败 / 500**  
   - 确认 `ollama serve` 正常运行（`curl http://localhost:11434/api/version`）  
   - 优先使用 7B 模型，显存不足时 14B 容易 OOM  
   - 适当调小 `OLLAMA_TIMEOUT`

3. **Redis 连接失败**  
   - 本地模式：`start.sh` 会自动启动 `redis-server`  
   - 外部 Redis：设置 `MANAGE_REDIS=false` 并正确配置 `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND`

4. **文本乱码 / PDF 抽取异常**  
   - 后端针对已知前缀和噪声做了清洗  
   - 前端在原文摘录区域增加了“乱码识别 + 屏蔽”逻辑

5. **GPU 资源不足 / 进程被杀**  
   - 换用更小模型（如 qwen2.5-coder:7b）  
   - 减小上下文 / TopK / Rerank 配置

---

## 🎯 功能特性总结

✅ 智能意图分析：自动判断是常识、文档抽取、对比还是多主题  
✅ 混合检索：文档 + 可选联网，按策略融合  
✅ 结构化回答：摘要、结论、方法、风险模块化展示  
✅ 引用管理：每条结论都可追溯到原文片段  
✅ 性能优化：异步、任务队列、向量缓存、多主题并行  

享受你的混合检索 RAG 系统！🎉
