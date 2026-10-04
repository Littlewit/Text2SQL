"""安全原语单元测试：密码哈希与令牌。"""

import time

import jwt
import pytest

from app.core.errors import AppError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

SECRET = "test-secret"


def test_password_hash_and_verify():
    """哈希含随机盐，同密码两次哈希结果不同但均可校验。"""
    h1 = hash_password("s3cret-pw")
    h2 = hash_password("s3cret-pw")
    assert h1 != h2
    assert verify_password(h1, "s3cret-pw")
    assert verify_password(h2, "s3cret-pw")
    assert not verify_password(h1, "wrong-pw")


def test_token_roundtrip():
    """令牌签发→解析返回正确的 user_id。"""
    token = create_access_token(42, SECRET, expire_minutes=5)
    assert decode_access_token(token, SECRET) == 42


def test_token_expired():
    """过期令牌抛 40101（AppError），不泄露内部细节。"""
    token = create_access_token(1, SECRET, expire_minutes=-1)
    with pytest.raises(AppError) as ei:
        decode_access_token(token, SECRET)
    assert ei.value.code == 40101


def test_token_tampered():
    """篡改签名或错误密钥均视为无效凭证。"""
    token = create_access_token(1, SECRET, expire_minutes=5)
    with pytest.raises(AppError):
        decode_access_token(token, "other-secret")
    # 伪造 payload（未签名）
    forged = jwt.encode({"sub": "1", "exp": int(time.time()) + 999}, "attacker", algorithm="HS256")
    with pytest.raises(AppError):
        decode_access_token(forged, SECRET)
