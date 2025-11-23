# RAG 系统启动指南

## 🚀 快速启动

> 如果你想用 Docker 一键复现前后端（含 Redis & Celery），请直接查看下方的 **🐳 Docker 复现** 章节。

### 1. 环境准备
确保你已经安装了以下依赖：

```bash
# Python 依赖
pip install -r rag-system/backend/requirements.txt

# Node.js 依赖 (如果还没有安装)
cd rag-system/frontend && npm install
```

### 2. 配置环境变量
编辑 `.env` 文件，确保以下配置正确：

```bash
# 必需配置
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5-coder:14b
TAVILY_API_KEY=your_tavily_api_key_here

# 设备配置
EMBEDDING_DEVICE=cpu  # 或 cuda 如果有GPU
EMBEDDING_MODEL_PATH=/path/to/your/embedding/model

# 调试选项
DEBUG_ROUTER=true
OLLAMA_TIMEOUT=30

# 队列配置（可选）
# start.sh 默认会在本机自动启动 redis-server
# 如果你要使用自带的 Redis，可以覆盖这些变量
# MANAGE_REDIS=false
# CELERY_BROKER_URL=redis://your-host:6379/0
# CELERY_RESULT_BACKEND=redis://your-host:6379/1
```

### 3. 启动系统
现在你可以正常启动 RAG 系统：

```bash
# 清理环境变量并启动
unset MCP_DEBUG
./start.sh
```

### 4. 验证启动
系统应该会显示以下信息：

```
加载环境变量 /home/reggie/vscode_folder/RAG/.env
释放端口 8000
释放端口 8001
释放端口 5173
启动 GPU FastAPI (8000)
  GPU FastAPI (8000) PID=xxxx
启动 CPU FastAPI (8001)
  CPU FastAPI (8001) PID=xxxx
启动 Celery Worker
  Celery Worker PID=xxxx
启动 Vite 前端 (5173)
  Vite 前端 (5173) PID=xxxx
所有服务已启动。按 Ctrl+C 结束。
```

### 5. 访问服务
启动成功后，你可以访问：

- **前端界面**: http://localhost:5173
- **后端 API 文档**: http://localhost:8000/docs
- **CPU 后端 API**: http://localhost:8001/docs

## 🛠️ 服务检查

使用提供的脚本检查服务状态：

```bash
./check_services.sh
```

## 🔄 重启系统

如果需要重启系统：

```bash
# 1. 停止当前服务
pkill -f 'uvicorn\|celery\|vite'

# 2. 重新启动
unset MCP_DEBUG
./start.sh
```

## 🧪 测试系统

系统支持以下类型的查询：

1. **常识问题**: "什么是机器学习？"
2. **方法指导**: "如何安装Python？"
3. **对比分析**: "对比React和Vue的优缺点"
4. **决策建议**: "我应该学习前端还是后端？"
5. **文档分析**: "根据上传的文档分析系统架构"
6. **多主题查询**: "机器学习的基本原理和最新发展趋势"

## ⚠️ 故障排除

### 常见问题：

1. **端口占用**: 如果端口被占用，启动脚本会自动清理
2. **MCP 服务阻塞**: 确保运行 `unset MCP_DEBUG` 来清理环境变量
3. **Ollama 连接失败**: 确保 Ollama 服务正在运行 (`ollama serve`)
4. **嵌入模型路径**: 检查 `EMBEDDING_MODEL_PATH` 是否正确指向模型文件
5. **Redis 连接失败**: start.sh 会在检测到本地 Redis 不可用时自动启动 `redis-server`。如果你希望连接外部 Redis，请设置 `MANAGE_REDIS=false` 并在 `.env` 中提供 `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND`。

### 日志查看：
- 前端日志：在终端中可以看到 Vite 的实时日志
- 后端日志：FastAPI 服务会在终端显示请求日志
- 调试模式：设置 `DEBUG_ROUTER=true` 获取详细的路由信息

## 🐳 Docker 复现

Docker 方案会一次性拉起 **GPU FastAPI + 前端静态资源 + Celery Worker + Redis**，完全复现当前代码状态。

### 1. 前置依赖
1. Docker Engine / Docker Desktop（带 `docker compose` v2）
2. GPU 环境请安装 [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)，并确认 `docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu22.04 nvidia-smi` 能看到显卡
3. 准备权重/Embedding 模型：
   - 将本地的 bge-m3（或其它模型）放到 `./models/bge-m3`
   - 如果你需要 Ollama/OpenAI 等服务，请至少保证宿主机可以访问并在 `.env.docker` 中配置对应 KEY/URL

### 2. 配置环境变量
```bash
cp .env.docker.example .env.docker
```

根据需要修改：
- `EMBEDDING_MODEL_PATH=/app/models/bge-m3`（容器中的映射路径）
- `OLLAMA_BASE_URL`：在 macOS/Windows 使用 `http://host.docker.internal:11434`；Linux 原生 Docker 可用 `http://172.17.0.1:11434`
- `CELERY_BROKER_URL=redis://redis:6379/0` 与 `CELERY_RESULT_BACKEND=redis://redis:6379/1` 默认即可
- 其余 API KEY 视需求填写

### 3. 构建与启动
```bash
# 首次运行或代码有更新时
docker compose build

# 需要 GPU 时直接 up（docker compose 会携带 nvidia runtime）
docker compose up -d
```

命令会启动三个核心服务：
- `rag-api`：FastAPI + 前端静态资源（映射端口 `8000:8000`）
- `celery-worker`：后台任务，与 API 共享 `/app/data`、模型缓存
- `redis`：任务队列/结果存储

## 🤖 飞书对接

想把机器人接入飞书？项目已经内置 `/integrations/feishu/events` 回调接口：

1. 在飞书开放平台创建自建应用，开启机器人能力和 `im.message.receive_v1` 事件。
2. 将 `.env` / `.env.docker` 中的 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_VERIFICATION_TOKEN`（如需加密再填 `FEISHU_ENCRYPT_KEY`）设为开放平台给出的值。
3. 在事件订阅里把回调 URL 填成 `https://你的域名/integrations/feishu/events`，保存即可通过 `challenge` 校验。

- 如果控制台开启了“事件加密”，只需同时配置 `FEISHU_ENCRYPT_KEY`，服务端会自动解密 `encrypt` 字段。
- 机器人当前支持 `text`、`post`（富文本）、`interactive`（卡片）三类消息，会自动抽取文字内容再触发 RAG 检索。

详细步骤与常见问题见 `docs/feishu-integration.md`。

## 📱 微信 / 企业微信对接

1. 微信公众号：在「服务器配置」里把 URL 指向 `https://你的域名/integrations/wechat/official`，并把 `WECHAT_TOKEN`、`WECHAT_APP_ID`、`WECHAT_ENCODING_AES_KEY` 写入 `.env`。
2. 企业微信：在自建应用的「接收消息」中填写 `https://你的域名/integrations/wechat/wecom`，并同步 `WECOM_TOKEN`、`WECOM_CORP_ID`、`WECOM_ENCODING_AES_KEY`（安全模式必须配置）。
3. 若使用安全模式/加密，服务会自动按官方规范解密/加密；只需保证 `.env` 里的 key 与控制台一致。

👉 详细图文步骤与常见问题见 `docs/wechat-integration.md`。

所有持久化目录均挂载到宿主机：
- `./rag-system/data` ↔ `/app/data`（FAISS、BM25、日志等）
- `./models` ↔ `/app/models`（embedding/自带模型）
- 嵌入及 HF 缓存放在名为 `hf-cache` 的 Docker volume 中，重复拉起不会重新下载

### 4. 验证/调试
- 访问前端/后端：`http://localhost:8000`
- 查看日志：`docker compose logs -f rag-api` / `docker compose logs -f celery-worker`
- 停止服务：`docker compose down`

> 如果需要 CPU 模式，将 `.env.docker` 中 `ENABLE_GPU=false` 并删除 compose 文件里的 `deploy.reservations.devices`（或手动在运行时添加 `--gpus all`）。

## 🎯 功能特性

✅ **智能意图分析** - 自动识别问题类型
✅ **混合检索** - 文档搜索 + 联网搜索
✅ **多主题处理** - 并行处理复杂查询
✅ **实时反馈** - 进度指示器和诊断信息
✅ **引用管理** - 清确的来源归属


## 🧑‍💼 客服系统对接

如果后续项目里的客服或机器人需要直接调用 RAG 服务，可以使用内置的对接接口：

- **Endpoint**：`POST /integrations/customer-service/ask`
- **认证方式**：在 `.env` 中设置 `CUSTOMER_SERVICE_API_KEY=xxxx`，客户端通过 HTTP Header `X-Customer-Service-Token: xxxx` 访问。若未设置 KEY，则接口默认免认证（仅建议在内网/开发环境使用）。
- **伙伴标识**：可选 Header `X-Customer-Service-Partner: partner_name` 用于区分不同渠道；若不传，则服务端会基于 token 派生匿名 ID。
- **速率限制**：通过 `CUSTOMER_SERVICE_RATE_LIMIT_PER_MINUTE`（默认 60 req/min）控制每个 partner/token 的限流，超限会返回 HTTP 429。
- **请求体示例**：

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

返回内容包含 `answer`、`citations`、`suggestions`、`sources` 以及回传的 `metadata`，方便客服端贴合上下文展示。如果透传反馈（`feedback` + `feedback_tags` 字段），系统也会自动写入反馈存储，后续检索同一会话会记住历史问答。服务器会自动记录每个 partner 的请求/响应日志，便于排查问题。
✅ **性能优化** - 异步处理和智能缓存

享受你的混合检索 RAG 系统！🎉
