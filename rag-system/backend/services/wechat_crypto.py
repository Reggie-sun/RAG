from __future__ import annotations

import base64
import hashlib
import os
import struct
import time
from dataclasses import dataclass
from typing import Optional

from Crypto.Cipher import AES


class WeChatCryptoError(RuntimeError):
    """Generic crypto failure."""


class InvalidSignatureError(WeChatCryptoError):
    """Raised when the request signature does not match."""


class InvalidAppIdError(WeChatCryptoError):
    """Raised when decrypted payload appid/corpid mismatch."""


class MissingConfigError(WeChatCryptoError):
    """Raised when mandatory credentials are missing."""


@dataclass(frozen=True)
class WeChatCredentials:
    token: str
    encoding_aes_key: str
    app_id: str


class WeChatCrypto:
    """Implements the AES-CBC encryption/decryption used by WeChat/WeCom."""

    def __init__(self, credentials: WeChatCredentials) -> None:
        token = credentials.token.strip()
        encoding_key = credentials.encoding_aes_key.strip()
        app_id = credentials.app_id.strip()
        if not token or not encoding_key or not app_id:
            raise MissingConfigError("WeChat credentials are incomplete")
        if len(encoding_key) != 43:
            raise MissingConfigError("EncodingAESKey must be 43 characters long")
        self.token = token
        self.app_id = app_id
        self.aes_key = base64.b64decode(encoding_key + "=")
        self.iv = self.aes_key[:16]

    def verify_plain_signature(self, signature: str, timestamp: str, nonce: str) -> bool:
        return signature == self._sha1(self.token, timestamp, nonce)

    def verify_encrypted_signature(self, signature: str, timestamp: str, nonce: str, encrypt: str) -> bool:
        return signature == self._sha1(self.token, timestamp, nonce, encrypt)

    def decrypt(self, encrypt: str) -> str:
        cipher_data = base64.b64decode(encrypt)
        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.iv)
        decrypted = self._unpad(cipher.decrypt(cipher_data))
        plain = decrypted[16:]
        msg_len = struct.unpack("!I", plain[:4])[0]
        msg = plain[4 : 4 + msg_len]
        from_app = plain[4 + msg_len :].decode("utf-8")
        if from_app != self.app_id:
            raise InvalidAppIdError("AppID mismatch in decrypted payload")
        return msg.decode("utf-8")

    def encrypt(self, plain_text: str, timestamp: Optional[str] = None, nonce: Optional[str] = None) -> tuple[str, str, str]:
        nonce = nonce or self._generate_nonce()
        timestamp = timestamp or str(int(time.time()))
        random_bytes = os.urandom(16)
        msg = plain_text.encode("utf-8")
        msg_len = struct.pack("!I", len(msg))
        full = random_bytes + msg_len + msg + self.app_id.encode("utf-8")
        padded = self._pad(full)
        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.iv)
        encrypted = base64.b64encode(cipher.encrypt(padded)).decode("utf-8")
        signature = self._sha1(self.token, timestamp, nonce, encrypted)
        return encrypted, signature, timestamp

    def build_signature(self, timestamp: str, nonce: str, encrypt: str) -> str:
        return self._sha1(self.token, timestamp, nonce, encrypt)

    def _pad(self, data: bytes) -> bytes:
        block_size = AES.block_size
        amount_to_pad = block_size - (len(data) % block_size)
        pad = bytes([amount_to_pad]) * amount_to_pad
        return data + pad

    def _unpad(self, data: bytes) -> bytes:
        pad = data[-1]
        if pad < 1 or pad > AES.block_size:
            raise WeChatCryptoError("Invalid padding")
        return data[:-pad]

    def _sha1(self, *parts: str) -> str:
        valid_parts = [part for part in parts if part is not None]
        sorted_parts = sorted(valid_parts)
        joined = "".join(sorted_parts)
        return hashlib.sha1(joined.encode("utf-8")).hexdigest()

    @staticmethod
    def _generate_nonce(length: int = 8) -> str:
        alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
        return "".join(alphabet[b % len(alphabet)] for b in os.urandom(length))
