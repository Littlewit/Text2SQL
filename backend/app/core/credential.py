"""数据源凭据加密存储（KEY-02、DR-01）。

使用 AES-256-GCM 对称加密；主密钥来自环境变量 CREDENTIAL_KEY（base64 编码的 32 字节），
与数据库分离存放。仓库默认值仅供本地开发，生产必须覆盖。
"""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# 开发默认密钥：32 字节 "0" 的 base64；生产环境必须通过环境变量覆盖（KEY-01）
_DEV_KEY_B64 = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="


def _load_key() -> bytes:
    raw = os.environ.get("CREDENTIAL_KEY", _DEV_KEY_B64)
    key = base64.b64decode(raw)
    if len(key) != 32:
        raise ValueError("CREDENTIAL_KEY 必须是 base64 编码的 32 字节密钥")
    return key


def encrypt_credential(plain: str) -> str:
    """加密凭据，返回 base64(nonce + ciphertext)。每次加密使用随机 nonce。"""
    key = _load_key()
    nonce = os.urandom(12)  # GCM 推荐 96-bit nonce
    ct = AESGCM(key).encrypt(nonce, plain.encode("utf-8"), None)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt_credential(blob: str) -> str:
    """解密凭据；密文损坏或密钥不匹配时抛出异常，由调用方转换为业务错误。"""
    key = _load_key()
    raw = base64.b64decode(blob)
    nonce, ct = raw[:12], raw[12:]
    return AESGCM(key).decrypt(nonce, ct, None).decode("utf-8")
