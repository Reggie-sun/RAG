项目：智能 RAG 问答系统    地址：www.srj666.com   
技术栈：FastAPI、Python、Celery、Redis、FAISS/BM25、React + TypeScript、Vite、Docker、Ollama/OpenAI、Cloudflare Tunnel、Caddy、Feishu/微信集成
项目要点示例：

设计并实现基于 FastAPI 的 RAG 服务，结合 FAISS/BM25 向量检索与 Tavily 联网搜索，实现多文档知识问答与多主题复杂问题拆解。
利用 Celery + Redis 将重型嵌入/检索任务异步化，并按 GPU/CPU 分流请求，降低高并发下的尾延迟。
使用 Docker 与 docker-compose 编排 GPU/CPU 后端、前端、Celery、Redis 等服务，实现一键部署。
基于 Cloudflare Tunnel + Caddy 搭建公网安全访问方案，配置反向代理和自动 HTTPS 证书管理，将本地 RAG 服务稳定暴露到互联网。
完成 Feishu / 微信 / 企业微信 机器人接入，处理事件回调与加密消息，使用户可以在 IM 聊天窗口直接查询知识库。
