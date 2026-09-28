"""API 冒烟测试：不进入 lifespan（不连 DB），仅验证路由注册与鉴权依赖注入。

注意：TestClient 不用 with 语句，避免触发 lifespan 里的 init_db（本机无 PG）。
"""
from fastapi.testclient import TestClient

from app.auth import create_token
from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_me_without_token():
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_me_with_valid_token():
    token = create_token(42, "13800000001")
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["user_id"] == 42


def test_solve_rejects_empty_request():
    """参数校验前置：空请求 422，且不触 LLM。"""
    r = client.post("/api/solve", json={"grade_level": "初中"})
    assert r.status_code == 422


def test_solve_rejects_bad_grade():
    r = client.post("/api/solve", json={"text": "1+1=?", "grade_level": "大学"})
    assert r.status_code == 422
