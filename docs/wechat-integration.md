# 微信 / 企业微信接入指南

FastAPI 已经在 `/integrations/wechat` 下暴露了两个回调：

- `/integrations/wechat/official`：微信公众号（订阅号/服务号）
- `/integrations/wechat/wecom`：企业微信自建应用

本文介绍如何在两种渠道完成配置并联通 RAG 系统。

## 1. 微信公众号（Official Account）

1. 登录 [微信公众平台](https://mp.weixin.qq.com/) 创建或选择一个服务号/订阅号。
2. 在 **基本配置 → 服务器配置** 中开启「服务器配置」，填写以下内容：
   - **URL**：`https://你的域名/integrations/wechat/official`
   - **Token**：任意自定义字符串（与 `.env` 中的 `WECHAT_TOKEN` 相同）
   - **EncodingAESKey**：点击生成 43 位字符串，填入 `.env` 的 `WECHAT_ENCODING_AES_KEY`
   - **消息加解密方式**：推荐选择「安全模式（兼容）」或「兼容模式」，后端均已支持
3. 在 `.env`/`.env.docker` 中新增：

   ```ini
   WECHAT_TOKEN=自定义token
   WECHAT_APP_ID=wx1234567890abcd
   WECHAT_ENCODING_AES_KEY=43位字符串
   # WECHAT_APP_SECRET=xxx  # 用于主动发消息时可选
   ```

4. 重启后端，再次在微信后台点击「提交」。若配置正确，会收到「验证成功」。

## 2. 企业微信（WeCom）

1. 登录 [企业微信管理后台](https://work.weixin.qq.com/)，进入 **应用管理 → 自建应用**，创建一个应用。
2. 在应用详情页下方的「接收消息」里填写：
   - **URL**：`https://你的域名/integrations/wechat/wecom`
   - **Token**：自定义并同步到 `.env` 的 `WECOM_TOKEN`
   - **EncodingAESKey**：生成的 43 位 key，同步至 `WECOM_ENCODING_AES_KEY`
3. `.env`/.env.docker 中需要：

   ```ini
   WECOM_TOKEN=your_token
   WECOM_CORP_ID=ww1234567890abcdef
   WECOM_AGENT_ID=1000001
   WECOM_CORP_SECRET=xxxx   # 仅在需要主动发送消息时使用
   WECOM_ENCODING_AES_KEY=43位字符串
   ```

4. 保存配置后，企业微信会携带 `echostr` 调用回调。FastAPI 会自动校验签名、解密并返回，页面提示「修改成功」。

## 3. 本地开发提示

- 微信/企业微信必须能访问你的回调 URL，可使用 `cloudflared`、`ngrok`、`caddy` 等隧道工具把 `http://localhost:8000` 暴露出去。
- 若只想本地测试，可在 hosts 中配置域名 → 本地 IP，并通过内网穿透工具把公网请求转发到本地。

## 4. 支持的消息/功能

- 当前支持消息类型：`text`。其它类型会提示“暂时只支持文本消息”。
- 自动使用 RAG 检索并生成回答，回复中附带引用列表（最多 3 条）。
- 对于加密消息（安全模式），系统自动按照官方 AES-CBC 规范解密和加密，无需额外操作。

配置完成后，即可在微信或企业微信中向机器人发送文字问题，几秒内即可收到 RAG 答案。祝开发顺利！
