from __future__ import annotations

import asyncio
import hashlib
import json
import re
from base64 import b64decode
from collections import deque
from threading import Lock
from typing import Any, Deque, Dict, List, Optional, Set

from Crypto.Cipher import AES
from fastapi import APIRouter, HTTPException

from ..config import settings
from ..services.memory_store import memory_store, render_history
from ..services.providers import get_feishu_client, get_rag_service
from ..services.feishu_client import FeishuConfigError
from ..utils.logger import get_logger

router = APIRouter(prefix="/integrations/feishu", tags=["Feishu"])
logger = get_logger(__name__)

_MENTION_PATTERN = re.compile(r"<at[^>]*?>.*?</at>", re.IGNORECASE)
_EVENT_CACHE: Deque[str] = deque()
_EVENT_CACHE_SET: Set[str] = set()
_EVENT_CACHE_LOCK = Lock()
_EVENT_CACHE_LIMIT = 512
_PREFERRED_POST_LOCALES: tuple[str, ...] = ("zh_cn", "zh-CN", "en_us", "en-US")


class UnsupportedMessageTypeError(RuntimeError):
    def __init__(self, message_type: str) -> None:
        super().__init__(f"Unsupported message type: {message_type}")
        self.message_type = message_type


def _maybe_decrypt_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    encrypt_value = payload.get("encrypt")
    if not encrypt_value:
        return payload

    encrypt_key = (settings.feishu_encrypt_key or "").strip()
    if not encrypt_key:
        logger.error("feishu.encrypt_missing")
        raise HTTPException(status_code=503, detail="Feishu encryption key is not configured")

    try:
        decrypted = _decrypt_event(encrypt_value, encrypt_key)
        data = json.loads(decrypted)
        if not isinstance(data, dict):
            raise ValueError("Decrypted payload is not a JSON object")
    except Exception:
        logger.exception("feishu.decrypt_failed")
        raise HTTPException(status_code=400, detail="Unable to decrypt Feishu payload")

    return data


def _decrypt_event(ciphertext: str, encrypt_key: str) -> str:
    cipher_bytes = b64decode(ciphertext)
    key = hashlib.sha256(encrypt_key.encode("utf-8")).digest()
    cipher = AES.new(key, AES.MODE_CBC, key[: AES.block_size])
    decrypted = cipher.decrypt(cipher_bytes)
    unpadded = _strip_pkcs7_padding(decrypted)
    return unpadded.decode("utf-8")


def _strip_pkcs7_padding(data: bytes) -> bytes:
    if not data:
        raise ValueError("Invalid padding")
    pad = data[-1]
    if isinstance(pad, str):  # pragma: no cover - defensive, bytes expected
        pad = ord(pad)
    if pad < 1 or pad > AES.block_size:
        raise ValueError("Invalid padding")
    return data[:-pad]


@router.post("/events")
async def handle_feishu_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = _maybe_decrypt_payload(payload)
    event_type = payload.get("type")
    if event_type == "url_verification":
        if not _is_valid_token(payload.get("token")):
            raise HTTPException(status_code=403, detail="Invalid verification token")
        return {"challenge": payload.get("challenge", "")}

    header = payload.get("header") or {}
    if not _is_valid_token(header.get("token") or payload.get("token")):
        raise HTTPException(status_code=403, detail="Invalid verification token")

    resolved_type = header.get("event_type") or event_type
    event_id = header.get("event_id")
    if resolved_type == "im.message.receive_v1":
        if _is_duplicate_event(event_id):
            return {"code": 0, "msg": "duplicate"}
        event_payload = payload.get("event") or {}
        asyncio.create_task(_handle_message_event(event_payload, event_id))
        return {"code": 0, "msg": "ok"}

    logger.info("feishu.event_ignored", extra={"event_type": resolved_type})
    return {"code": 0, "msg": "ignored"}


def _is_valid_token(token: Optional[str]) -> bool:
    expected = (settings.feishu_verification_token or "").strip()
    if not expected:
        return True
    return token == expected


def _is_duplicate_event(event_id: Optional[str]) -> bool:
    if not event_id:
        return False
    with _EVENT_CACHE_LOCK:
        if event_id in _EVENT_CACHE_SET:
            return True
        _EVENT_CACHE.append(event_id)
        _EVENT_CACHE_SET.add(event_id)
        while len(_EVENT_CACHE) > _EVENT_CACHE_LIMIT:
            old = _EVENT_CACHE.popleft()
            _EVENT_CACHE_SET.discard(old)
    return False


async def _handle_message_event(event: Dict[str, Any], event_id: Optional[str]) -> None:
    try:
        message = (event or {}).get("message") or {}
        sender = (event or {}).get("sender") or {}
        if not message:
            return
        sender_type = str(sender.get("sender_type") or "").lower()
        if sender_type == "bot":
            return
        message_type = message.get("message_type")
        message_id = message.get("message_id")
        chat_id = message.get("chat_id")
        log_ctx = {"event_id": event_id, "chat_id": chat_id, "message_id": message_id}

        try:
            query = _extract_message_text(message)
        except UnsupportedMessageTypeError as exc:
            logger.info(
                "feishu.unsupported_message",
                extra={**log_ctx, "message_type": exc.message_type},
            )
            await _reply_if_possible(
                message,
                f"暂不支持 {exc.message_type} 类型消息，请发送文本或富文本。",
            )
            return
        if not query:
            logger.info("feishu.empty_message", extra={**log_ctx, "message_type": message_type})
            await _reply_if_possible(message, "没有在消息中检测到文字内容，请重新输入。")
            return

        session_id = _build_session_id(chat_id, sender)
        history_block = render_history(memory_store.history(session_id))
        rag_service = get_rag_service()

        try:
            response = await rag_service.answer(
                query=query,
                top_k=settings.retrieval_default_top_k,
                history=history_block,
                allow_web=True,
                session_id=session_id,
            )
        except Exception:
            logger.exception("feishu.answer_failed", extra=log_ctx)
            await _reply_if_possible(message, "抱歉，机器人暂时不可用，请稍后再试。")
            return

        answer_text = (response.get("answer") or "").strip()
        if not answer_text:
            answer_text = "抱歉，暂时没有查询到相关信息。"
        reply_body = _compose_reply(answer_text, response.get("citations") or [])
        sent = await _reply_if_possible(message, reply_body)
        if sent:
            memory_store.append(session_id, query, answer_text)
    except Exception:
        logger.exception("feishu.unhandled_error", extra={"event_id": event_id})


def _extract_message_text(message: Dict[str, Any]) -> str:
    message_type = (message.get("message_type") or "text").lower()
    content_data = _parse_message_content(message.get("content"))

    if message_type in {"", "text"}:
        text = content_data.get("text_without_at_bot") or content_data.get("text") or message.get("text") or ""
        return _clean_text(text)
    if message_type == "post":
        return _clean_text(_extract_post_text(content_data.get("post")))
    if message_type == "interactive":
        card_payload = content_data.get("card") or content_data
        return _clean_text(_extract_card_text(card_payload))

    raise UnsupportedMessageTypeError(message_type)


def _parse_message_content(raw_content: Any) -> Dict[str, Any]:
    if isinstance(raw_content, dict):
        return raw_content
    if not raw_content:
        return {}
    try:
        data = json.loads(raw_content)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _extract_post_text(post_payload: Any) -> str:
    if not isinstance(post_payload, dict):
        return ""
    section = _pick_post_locale_section(post_payload)
    if not section:
        return ""
    lines: List[str] = []
    title = section.get("title")
    if isinstance(title, str) and title.strip():
        lines.append(title.strip())
    for paragraph in section.get("content", []):
        segment_parts = [_render_post_node(node) for node in paragraph if node]
        segment = "".join(part for part in segment_parts if part)
        if segment.strip():
            lines.append(segment.strip())
    return "\n".join(lines)


def _pick_post_locale_section(post_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for locale in _PREFERRED_POST_LOCALES:
        candidate = post_payload.get(locale)
        if isinstance(candidate, dict):
            return candidate
    for value in post_payload.values():
        if isinstance(value, dict):
            return value
    return None


def _render_post_node(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    tag = node.get("tag")
    if tag == "text":
        return node.get("text", "")
    if tag == "a":
        text = node.get("text") or node.get("href") or ""
        href = node.get("href")
        return f"{text} ({href})" if href else text
    if tag == "at":
        name = node.get("user_name") or node.get("text") or node.get("user_id") or ""
        return f"@{name}" if name else "@"
    if tag == "img":
        return "[图片]"
    if tag == "media":
        media_type = node.get("media_type") or "媒体"
        return f"[{media_type}]"
    if tag == "code":
        return node.get("text", "")
    return node.get("text", "")


def _extract_card_text(card_payload: Any) -> str:
    if not isinstance(card_payload, dict):
        return ""
    parts: List[str] = []
    header = card_payload.get("header") or {}
    header_text = ""
    if isinstance(header, dict):
        header_text = _extract_plain_text_component(header.get("title"))
    if header_text.strip():
        parts.append(header_text.strip())
    for element in card_payload.get("elements", []):
        text = _render_card_element(element)
        if text.strip():
            parts.append(text.strip())
    return "\n".join(parts)


def _render_card_element(element: Any) -> str:
    if not isinstance(element, dict):
        return ""
    tag = element.get("tag", "")
    if tag == "div":
        pieces: List[str] = []
        primary = _extract_plain_text_component(element.get("text"))
        if primary:
            pieces.append(primary)
        for field in element.get("fields", []):
            field_text = _extract_plain_text_component(field.get("text"))
            if field_text:
                pieces.append(field_text)
        return "\n".join(pieces)
    if tag in {"markdown", "lark_md"}:
        return element.get("content", "")
    if tag == "note":
        return "\n".join(
            filter(None, (_extract_plain_text_component(item) for item in element.get("elements", [])))
        )
    if tag == "column_set":
        columns: List[str] = []
        for column in element.get("columns", []):
            text = "\n".join(
                filter(None, (_render_card_element(item) for item in column.get("elements", [])))
            )
            if text:
                columns.append(text)
        return "\n".join(columns)
    if tag == "img":
        return "[图片]"
    if tag == "action":
        actions: List[str] = []
        for action in element.get("actions", []):
            actions.append(_extract_plain_text_component(action.get("text")))
        return "\n".join(filter(None, actions))
    return _extract_plain_text_component(element.get("text")) or element.get("content", "")


def _extract_plain_text_component(component: Any) -> str:
    if isinstance(component, str):
        return component
    if isinstance(component, dict):
        content = component.get("content")
        if isinstance(content, str):
            return content
        text = component.get("text")
        if isinstance(text, str):
            return text
    return ""


def _clean_text(value: str) -> str:
    if not value:
        return ""
    return _MENTION_PATTERN.sub("", value).strip()


def _build_session_id(chat_id: Optional[str], sender: Dict[str, Any]) -> str:
    sender_ids = sender.get("sender_id") or {}
    open_id = sender_ids.get("open_id") or sender_ids.get("user_id") or sender_ids.get("union_id")
    base = chat_id or "unknown"
    suffix = open_id or "anonymous"
    return f"feishu:{base}:{suffix}"


def _compose_reply(answer: str, citations: List[Dict[str, Any]], limit: int = 3) -> str:
    answer = answer.strip()
    citation_block = _format_citations(citations, limit)
    if citation_block:
        return f"{answer}\n\n{citation_block}"
    return answer


def _format_citations(citations: List[Dict[str, Any]], limit: int) -> str:
    if not citations:
        return ""
    entries: List[str] = []
    for idx, citation in enumerate(citations[:limit], start=1):
        if not isinstance(citation, dict):
            continue
        title = (citation.get("title") or citation.get("source") or citation.get("url") or "参考来源").strip()
        url = (citation.get("url") or "").strip()
        if url and not title.startswith("http"):
            label = f"{title} {url}"
        else:
            label = title or url
        entries.append(f"{idx}. {label}")

    if not entries:
        return ""
    return "参考资料：\n" + "\n".join(entries)


async def _reply_if_possible(message: Dict[str, Any], text: str) -> bool:
    message_id = message.get("message_id")
    if not message_id:
        return False
    try:
        client = get_feishu_client()
    except FeishuConfigError as exc:
        logger.error("feishu.client_missing", extra={"error": str(exc)})
        return False
    return await client.reply_text(message_id, text)
