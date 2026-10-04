"""凭据加密与登录锁定单元测试。"""

import pytest

from app.core import login_guard
from app.core.credential import decrypt_credential, encrypt_credential
from app.core.errors import AppError


def test_credential_roundtrip():
    """AES-GCM 加密可逆；不同次加密因随机 nonce 密文不同。"""
    c1 = encrypt_credential("pg-pass-123")
    c2 = encrypt_credential("pg-pass-123")
    assert c1 != c2  # 随机 nonce
    assert decrypt_credential(c1) == "pg-pass-123"
    assert decrypt_credential(c2) == "pg-pass-123"
    assert "pg-pass-123" not in c1  # 明文不出现在密文中


def test_credential_tampered():
    """密文被篡改时解密必须失败（GCM 完整性校验）。"""
    import base64

    from cryptography.exceptions import InvalidTag

    raw = bytearray(base64.b64decode(encrypt_credential("secret")))
    raw[-1] ^= 0xFF
    tampered = base64.b64encode(bytes(raw)).decode("ascii")
    with pytest.raises(InvalidTag):
        decrypt_credential(tampered)


@pytest.fixture(autouse=True)
def _clear_guard():
    """每个用例前清空锁定状态，避免用例间干扰。"""
    login_guard._failed.clear()
    yield
    login_guard._failed.clear()


def test_lockout_after_threshold():
    """连续失败达到阈值后登录被拒（FR-SEC-40、P-32 默认 5 次）。"""
    for _ in range(5):
        login_guard.record_failure("alice", threshold=5)
    with pytest.raises(AppError) as ei:
        login_guard.check_locked("alice", threshold=5)
    assert ei.value.code == 40103


def test_lockout_resets_on_success():
    """失败后成功登录清除计数。"""
    login_guard.record_failure("bob", threshold=5)
    login_guard.record_success("bob")
    login_guard.check_locked("bob", threshold=5)  # 不抛异常即通过
