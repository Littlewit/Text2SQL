"""认证安全原语：密码哈希（argon2id）与 JWT 访问令牌。

- 密码使用 argon2id 加盐哈希（SEC-03）；
- token 使用 HS256 JWT，带过期时间（FR-SEC-40）。
"""

from datetime import datetime, timedelta, timezone

import argon2
import jwt

from app.core.errors import AppError

# 独立实例：PasswordHasher 线程安全且参数固定，全局复用
_password_hasher = argon2.PasswordHasher()

# 错误码（§6.4：401xx 未认证）
CODE_TOKEN_INVALID = 40101


def hash_password(plain: str) -> str:
    """生成 argon2id 哈希（含随机盐）。"""
    return _password_hasher.hash(plain)


def verify_password(password_hash: str, plain: str) -> bool:
    """校验密码；哈希格式非法等情况一律返回 False，不抛异常。"""
    try:
        return _password_hasher.verify(password_hash, plain)
    except argon2.exceptions.VerificationError:
        return False


def create_access_token(user_id: int, secret_key: str, expire_minutes: int) -> str:
    """签发访问令牌。exp 用 UTC 时间戳，避免服务器时区歧义。"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=expire_minutes),
    }
    return jwt.encode(payload, secret_key, algorithm="HS256")


def decode_access_token(token: str, secret_key: str) -> int:
    """校验并解析令牌，返回 user_id；过期/篡改统一抛 40101。"""
    try:
        payload = jwt.decode(token, secret_key, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as e:
        raise AppError(CODE_TOKEN_INVALID, "登录已过期，请重新登录", 401) from e
    except jwt.InvalidTokenError as e:
        raise AppError(CODE_TOKEN_INVALID, "无效的登录凭证", 401) from e
    return int(payload["sub"])
