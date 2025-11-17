# 飞书对接指南

该项目内置了一个 `/integrations/feishu/events` 回调接口，可以把 RAG 问答服务接入飞书自建机器人。下面按照步骤配置即可：

## 1. 创建应用并获取凭证

1. 登录 [飞书开放平台](https://open.feishu.cn/app) 创建企业自建应用。
2. 启用 **机器人（Bot）** 能力，并在 *安全设置* 中记录 `App ID`、`App Secret` 以及 `Verification Token`/`Encrypt Key`。
3. 在 **权限管理** 中至少勾选：
   - `im:message`（读取消息）
   - `im:message:send_as_bot`（机器人发送消息）
   - 如果需要群聊，记得开启相关群聊权限。

## 2. 配置环境变量

在 `.env` 或 `.env.docker` 中填写以下变量（未启用的可以留空）：

```ini
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_VERIFICATION_TOKEN=veri-xxx
FEISHU_ENCRYPT_KEY=enc-xxx   # 如果未开启事件加密可留空
```

重启后台服务后，FastAPI 会自动加载新的路由。

> 已支持官方 AES-CBC 事件加解密：一旦在开放平台启用「事件加密」，并在 `.env` 中配置 `FEISHU_ENCRYPT_KEY`，后端会自动用相同 key 解密 `encrypt` 字段，无需额外改动。

## 3. 配置回调地址

1. 在飞书应用的 「事件订阅」 中启用订阅功能，URL 填写：
   ```
   https://你的域名或公网地址/integrations/feishu/events
   ```
2. 事件列表勾选 `im.message.receive_v1`，保存即可。首次保存时飞书会发送 `url_verification` 请求，后端会直接返回 `challenge` 完成绑定。

> **提示**：如果后端部署在内网，可通过 `cloudflared`、`ngrok`、`caddy` 等方式暴露公网地址，使飞书可以访问。

## 4. 使用方式

- 飞书用户在私聊或群组中 @ 机器人并输入文本问题，后端会启动 RAG 检索、结合聊天上下文生成答案，并自动以文本形式回复。
- 支持 `text`、`post`（富文本）、`interactive`（卡片）等消息类型，会自动拉平为纯文本后进行检索。
- 回复中会附带最多 3 条“参考资料”，方便定位文档或网页来源。
- 每个会话的上下文以 `chat_id + user_id` 作为 session，互不影响；如需清空上下文，可在后台删除内存或重启服务。

## 5. 常见问题

| 现象 | 可能原因 | 处理建议 |
| --- | --- | --- |
| 飞书提示 `token verification failed` | `.env` 中的 `FEISHU_VERIFICATION_TOKEN` 与开放平台不一致 | 重新复制 `Verification Token` 并重启后台 |
| 消息无法发送 | `App ID/App Secret` 填写错误，或未授予 `im:message:send_as_bot` 权限 | 在开放平台重新检查权限并重新发布应用 |
| 机器人不在线 | 事件推送未到后台（公网不可达） | 确保公网可以访问 `/integrations/feishu/events`，或使用 `cloudflared` 等隧道工具 |

配置完成后，就可以在飞书中直接提问，后端会复用现有的检索、意图识别与引用能力，无需额外部署。祝使用顺利！
