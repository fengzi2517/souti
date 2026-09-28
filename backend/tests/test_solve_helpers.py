"""solve.py 辅助函数单测：_client_ip 代理信任 + singleflight 锁管理"""
import asyncio

from starlette.requests import Request

from app.config import settings
from app.routers.solve import _client_ip, _get_solve_lock, _release_solve_lock, _solve_locks


def _req(headers: dict[str, str] | None = None, client: tuple = ("9.9.9.9", 1234)) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/solve",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": client,
    }
    return Request(scope)


def test_client_ip_direct_default():
    """默认不信任代理头：直连场景 X-Forwarded-For 可被伪造，必须忽略。"""
    settings.trust_proxy = False
    req = _req({"X-Forwarded-For": "1.2.3.4, 5.6.7.8"})
    assert _client_ip(req) == "9.9.9.9"


def test_client_ip_trust_proxy_takes_leftmost():
    settings.trust_proxy = True
    req = _req({"X-Forwarded-For": "1.2.3.4, 10.0.0.1"})
    assert _client_ip(req) == "1.2.3.4"
    settings.trust_proxy = False  # 还原，避免影响其他用例


def test_client_ip_no_header_falls_back():
    settings.trust_proxy = True
    assert _client_ip(_req()) == "9.9.9.9"
    assert _client_ip(_req(client=None)) == "unknown"
    settings.trust_proxy = False


def test_singleflight_lock_reuse_and_cleanup():
    async def run():
        lock = await _get_solve_lock("k1")
        assert await _get_solve_lock("k1") is lock  # 同 key 复用
        await _release_solve_lock("k1", lock)
        assert "k1" not in _solve_locks  # 释放后清理，防 dict 膨胀

    asyncio.run(run())
