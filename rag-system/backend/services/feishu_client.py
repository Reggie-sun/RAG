from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict

import httpx

from ..utils.logger import get_logger


class FeishuConfigError(RuntimeError):
    """Raised when Feishu credentials are missing or invalid."""


class FeishuClient:
    """Lightweight client for Feishu (Lark) Open Platform APIs."""

    BASE_URL = "https://open.feishu.cn/open-apis"
    TOKEN_URL = f"{BASE_URL}/auth/v3/tenant_access_token/internal/"
    MESSAGE_REPLY_URL = f"{BASE_URL}/im/v1/messages/{{message_id}}/reply"
    MAX_CONTENT_LENGTH = 4500

    def __init__(self, app_id: str, app_secret: str, timeout: float = 10.0) -> None:
        if not app_id or not app_secret:
            raise FeishuConfigError("Feishu app_id/app_secret are required")
        self.app_id = app_id
        self.app_secret = app_secret
        self.logger = get_logger(__name__)
        self._tenant_token: str | None = None
        self._token_expire_at: float = 0.0
        self._token_lock = asyncio.Lock()
        self._http_timeout = httpx.Timeout(timeout, connect=min(timeout, 5.0))

    async def reply_text(self, message_id: str, text: str) -> bool:
        """Reply to a Feishu message with plain text."""
        if not message_id:
            return False
        token = await self._ensure_tenant_token()
        payload = {
            "msg_type": "text",
            "content": json.dumps({"text": self._coerce_text(text)}, ensure_ascii=False),
        }
        return await self._post(
            self.MESSAGE_REPLY_URL.format(message_id=message_id),
            payload,
            token,
            log_ctx={"message_id": message_id},
        )

    async def _ensure_tenant_token(self) -> str:
        """Fetch a tenant access token, caching it until expiration."""
        now = time.time()
        if self._tenant_token and now < (self._token_expire_at - 60):
            return self._tenant_token

        async with self._token_lock:
            if self._tenant_token and now < (self._token_expire_at - 60):
                return self._tenant_token
            token, expires_in = await self._fetch_tenant_token()
            self._tenant_token = token
            # Keep a safety margin to refresh proactively.
            self._token_expire_at = time.time() + max(60.0, float(expires_in) - 60.0)
            return token

    async def _fetch_tenant_token(self) -> tuple[str, int]:
        payload = {"app_id": self.app_id, "app_secret": self.app_secret}
        try:
            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                response = await client.post(self.TOKEN_URL, json=payload)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:  # ValueError for .json()
            raise RuntimeError("Failed to request Feishu tenant token") from exc

        if data.get("code") != 0:
            raise RuntimeError(f"Feishu token API error: {data}")

        token = data.get("tenant_access_token")
        if not token:
            raise RuntimeError("Feishu token response is missing tenant_access_token")
        expires_in = int(data.get("expire", 3600))
        return token, expires_in

    async def _post(
        self,
        url: str,
        payload: Dict[str, Any],
        token: str,
        log_ctx: Dict[str, Any] | None = None,
    ) -> bool:
        headers = {"Authorization": f"Bearer {token}"}
        log_data = log_ctx or {}
        try:
            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            self.logger.error("feishu.http_error", exc_info=True, extra=log_data)
            if exc.response is not None and exc.response.status_code == 401:
                await self._invalidate_token()
            return False
        except (httpx.HTTPError, ValueError):
            self.logger.error("feishu.request_failed", exc_info=True, extra=log_data)
            return False

        if data.get("code") != 0:
            self.logger.warning("feishu.api_error", extra={**log_data, "response": data})
            if data.get("code") in {99991663, 99991668, 99991675}:
                await self._invalidate_token()
            return False

        return True

    async def _invalidate_token(self) -> None:
        async with self._token_lock:
            self._tenant_token = None
            self._token_expire_at = 0.0

    def _coerce_text(self, value: str) -> str:
        if value is None:
            value = ""
        text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
        if len(text) <= self.MAX_CONTENT_LENGTH:
            return text
        return text[: self.MAX_CONTENT_LENGTH - 3].rstrip() + "..."
