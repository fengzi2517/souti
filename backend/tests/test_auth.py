"""auth.py 单测：身份解析、归一化、归属过滤条件"""
import time

import jwt as pyjwt

from app.auth import Identity, _norm_client_id, create_token, get_identity, owns
from app.config import settings
from app.models import History, Mistake


def test_norm_client_id():
    assert _norm_client_id(None) == "default"
    assert _norm_client_id("") == "default"
    assert _norm_client_id("anonymous") == "default"
    assert _norm_client_id("default") == "default"
    assert _norm_client_id("cid-123") == "cid-123"


def test_identity_no_token():
    ident = get_identity(x_client_id="cid-1", authorization="")
    assert ident == Identity(client_id="cid-1", user_id=None)
    assert not ident.is_logged_in


def test_identity_valid_token():
    token = create_token(42, "13800000001")
    ident = get_identity(x_client_id="cid-1", authorization=f"Bearer {token}")
    assert ident.user_id == 42 and ident.is_logged_in


def test_identity_forged_token_degrades_to_guest():
    ident = get_identity(x_client_id="cid-1", authorization="Bearer not-a-jwt")
    assert ident.user_id is None


def test_identity_expired_token_degrades_to_guest():
    expired = pyjwt.encode(
        {"uid": 42, "phone": "x", "exp": int(time.time()) - 10},
        settings.jwt_secret, algorithm="HS256",
    )
    ident = get_identity(x_client_id="cid-1", authorization=f"Bearer {expired}")
    assert ident.user_id is None


def test_owns_guest_requires_null_user_id():
    """游客态：本设备且未被任何账号收编的数据才可见。"""
    cond = owns(Mistake, Identity(client_id="cid-A"))
    sql = str(cond.compile(compile_kwargs={"literal_binds": True}))
    assert "user_id IS NULL" in sql
    assert "cid-A" in sql


def test_owns_logged_in_ignores_client_id():
    """登录态：只按 user_id，跨设备可见。"""
    cond = owns(History, Identity(client_id="cid-A", user_id=7))
    sql = str(cond.compile(compile_kwargs={"literal_binds": True}))
    assert "= 7" in sql
    assert "client_id" not in sql
