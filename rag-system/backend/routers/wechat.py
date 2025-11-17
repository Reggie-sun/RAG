from __future__ import annotations

import hashlib
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, Response

from ..config import settings
from ..services.memory_store import memory_store, render_history
from ..services.providers import (
    get_rag_service,
    get_wechat_official_crypto,
    get_wecom_crypto,
)
from ..services.wechat_crypto import MissingConfigError, WeChatCrypto
from ..utils.logger import get_logger

router = APIRouter(prefix="/integrations/wechat", tags=["WeChat"])
logger = get_logger(__name__)


@router.get("/official")
async def wechat_official_verify(
    signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(""),
    msg_signature: Optional[str] = Query(None),
    encrypt_type: Optional[str] = Query(None),
):
    crypto = _get_optional_crypto(get_wechat_official_crypto)
    token = (settings.wechat_token or "").strip()
    if not token:
        raise HTTPException(status_code=503, detail="WeChat token not configured")

    if encrypt_type == "aes" and msg_signature and crypto:
        if not crypto.verify_encrypted_signature(msg_signature, timestamp, nonce, echostr):
            raise HTTPException(status_code=403, detail="Invalid signature")
        plain = crypto.decrypt(echostr)
        return PlainTextResponse(plain)

    if _compute_plain_signature(token, timestamp, nonce) != signature:
        raise HTTPException(status_code=403, detail="Invalid signature")
    return PlainTextResponse(echostr)


@router.post("/official")
async def wechat_official_messages(
    request: Request,
    signature: Optional[str] = Query(None),
    msg_signature: Optional[str] = Query(None),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    encrypt_type: Optional[str] = Query(None),
):
    crypto = _get_optional_crypto(get_wechat_official_crypto)
    token = (settings.wechat_token or "").strip()
    if not token:
        raise HTTPException(status_code=503, detail="WeChat token not configured")

    body = await request.body()
    payload, was_encrypted = _decode_wechat_body(
        body,
        token,
        crypto,
        signature,
        msg_signature,
        timestamp,
        nonce,
        encrypt_type,
    )
    response_xml = await _process_message(payload, session_prefix="wechat")
    if was_encrypted and crypto:
        nonce_value = WeChatCrypto._generate_nonce()
        encrypted, reply_signature, reply_timestamp = crypto.encrypt(response_xml, nonce=nonce_value)
        envelope = _render_encrypted_response(encrypted, reply_signature, reply_timestamp, nonce_value)
        return Response(content=envelope, media_type="application/xml")
    return Response(content=response_xml, media_type="application/xml")


@router.get("/wecom")
async def wecom_verify(
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
):
    crypto = _require_crypto(get_wecom_crypto)
    if not crypto.verify_encrypted_signature(msg_signature, timestamp, nonce, echostr):
        raise HTTPException(status_code=403, detail="Invalid signature")
    plain = crypto.decrypt(echostr)
    return PlainTextResponse(plain)


@router.post("/wecom")
async def wecom_messages(
    request: Request,
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
):
    crypto = _require_crypto(get_wecom_crypto)
    body = await request.body()
    data = _parse_xml(body)
    encrypt = data.get("Encrypt")
    if not encrypt:
        raise HTTPException(status_code=400, detail="Missing encrypted payload")
    if not crypto.verify_encrypted_signature(msg_signature, timestamp, nonce, encrypt):
        raise HTTPException(status_code=403, detail="Invalid signature")
    plain_xml = crypto.decrypt(encrypt)
    payload = _parse_xml(plain_xml)
    response_xml = await _process_message(payload, session_prefix="wecom")
    nonce_value = WeChatCrypto._generate_nonce()
    encrypted, reply_signature, reply_timestamp = crypto.encrypt(response_xml, nonce=nonce_value)
    envelope = _render_encrypted_response(encrypted, reply_signature, reply_timestamp, nonce_value)
    return Response(content=envelope, media_type="application/xml")


async def _process_message(payload: Dict[str, str], session_prefix: str) -> str:
    msg_type = (payload.get("MsgType") or "").lower()
    if msg_type != "text":
        return _render_text_reply(payload, "暂时只支持文本消息，请发送文字内容。")

    content = (payload.get("Content") or "").strip()
    if not content:
        return _render_text_reply(payload, "没有检测到消息内容，请重新输入文字。")

    from_user = payload.get("FromUserName") or payload.get("UserID") or "anonymous"
    chat_id = payload.get("ToUserName") or payload.get("AgentID") or "wechat"
    session_id = f"{session_prefix}:{chat_id}:{from_user}"
    history_block = render_history(memory_store.history(session_id))
    rag_service = get_rag_service()

    try:
        result = await rag_service.answer(
            query=content,
            top_k=settings.retrieval_default_top_k,
            history=history_block,
            allow_web=True,
            session_id=session_id,
        )
    except Exception:
        logger.exception("wechat.answer_failed", extra={"session_id": session_id})
        return _render_text_reply(payload, "后台服务暂时不可用，请稍后再试。")

    answer = (result.get("answer") or "").strip() or "抱歉，暂时没有找到相关信息。"
    memory_store.append(session_id, content, answer)
    citations = result.get("citations") or []
    reply = _compose_reply_text(answer, citations)
    return _render_text_reply(payload, reply)


def _render_text_reply(payload: Dict[str, str], content: str) -> str:
    to_user = payload.get("FromUserName") or payload.get("UserID") or ""
    from_user = payload.get("ToUserName") or payload.get("AgentID") or ""
    template = (
        "<xml>"
        "<ToUserName><![CDATA[{to_user}]]></ToUserName>"
        "<FromUserName><![CDATA[{from_user}]]></FromUserName>"
        "<CreateTime>{timestamp}</CreateTime>"
        "<MsgType><![CDATA[text]]></MsgType>"
        "<Content><![CDATA[{content}]]></Content>"
        "</xml>"
    )
    return template.format(to_user=to_user, from_user=from_user, timestamp=int(time.time()), content=content)


def _compose_reply_text(answer: str, citations: Any, limit: int = 3) -> str:
    lines = [answer.strip()]
    entries = []
    for idx, citation in enumerate(citations[:limit], start=1):
        title = ""
        url = ""
        if isinstance(citation, dict):
            title = (citation.get("title") or citation.get("source") or "").strip()
            url = (citation.get("url") or "").strip()
        label = title or url
        if label:
            if url and title:
                label = f"{title} {url}"
            entries.append(f"{idx}. {label}")
    if entries:
        lines.append("参考：" + " ".join(entries))
    return "\n".join(lines)


def _decode_wechat_body(
    body: bytes,
    token: str,
    crypto: Optional[WeChatCrypto],
    signature: Optional[str],
    msg_signature: Optional[str],
    timestamp: str,
    nonce: str,
    encrypt_type: Optional[str],
) -> Tuple[Dict[str, str], bool]:
    data = _parse_xml(body)
    if encrypt_type == "aes":
        if not (crypto and msg_signature):
            raise HTTPException(status_code=503, detail="WeChat encryption config missing")
        encrypt = data.get("Encrypt")
        if not encrypt:
            raise HTTPException(status_code=400, detail="Missing encrypted payload")
        if not crypto.verify_encrypted_signature(msg_signature, timestamp, nonce, encrypt):
            raise HTTPException(status_code=403, detail="Invalid signature")
        plain_xml = crypto.decrypt(encrypt)
        return _parse_xml(plain_xml), True

    if not signature:
        raise HTTPException(status_code=400, detail="Missing signature")
    if _compute_plain_signature(token, timestamp, nonce) != signature:
        raise HTTPException(status_code=403, detail="Invalid signature")
    return data, False


def _parse_xml(raw: Any) -> Dict[str, str]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="ignore")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise HTTPException(status_code=400, detail="Invalid XML payload") from exc
    data: Dict[str, str] = {}
    for child in root:
        data[child.tag] = (child.text or "").strip()
    return data


def _render_encrypted_response(encrypt: str, signature: str, timestamp: str, nonce: str) -> str:
    template = (
        "<xml>"
        "<Encrypt><![CDATA[{encrypt}]]></Encrypt>"
        "<MsgSignature><![CDATA[{signature}]]></MsgSignature>"
        "<TimeStamp>{timestamp}</TimeStamp>"
        "<Nonce><![CDATA[{nonce}]]></Nonce>"
        "</xml>"
    )
    return template.format(encrypt=encrypt, signature=signature, timestamp=timestamp, nonce=nonce)


def _compute_plain_signature(token: str, timestamp: str, nonce: str) -> str:
    parts = sorted([token, timestamp, nonce])
    return hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()


def _get_optional_crypto(factory):
    try:
        return factory()
    except MissingConfigError:
        return None


def _require_crypto(factory) -> WeChatCrypto:
    try:
        return factory()
    except MissingConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
