"""O-1 任务轮询架构集成测试：solve → task_id → 轮询 → done（直接函数调用，
所有协程共享同一个 asyncio.run 的事件循环，后台任务才能推进）。"""
import asyncio

import pytest
from starlette.requests import Request

from app.ai import pipeline
from app.auth import Identity
from app.routers import solve as solve_mod
from app.schemas import SolutionOut, SolveRequest

pytestmark = pytest.mark.usefixtures("db_clean")


def _http_request() -> Request:
    return Request({
        "type": "http", "headers": [], "method": "POST",
        "path": "/api/solve", "client": ("1.1.1.1", 1234),
    })


async def _fake_solve(text: str, grade: str):
    sol = SolutionOut(
        answer="42",
        steps=[{"title": "审题", "content": "略", "latex": True}],
        key_points=["方程"], common_mistakes=[], knowledge_points=[],
        grade_level=grade, subject="数学",
    )
    return sol, 123


async def _wait_task(task_id: str, ident: Identity, timeout: float = 5.0) -> solve_mod.SolveTaskStatusResponse:
    for _ in range(int(timeout / 0.01)):
        st = await solve_mod.get_task(task_id, ident)
        if st.status in ("done", "failed"):
            return st
        await asyncio.sleep(0.01)
    raise AssertionError("任务未在超时时间内完成")


def test_solve_task_full_flow(monkeypatch):
    """首次解析走后台任务，结果落库（Question/Solution/History）。"""
    monkeypatch.setattr(pipeline, "run_solve", _fake_solve)

    async def scenario():
        ident = Identity(client_id="cid-t1", user_id=None)
        resp = await solve_mod.solve(
            SolveRequest(text="1+1=?", grade_level="初中"), _http_request(), ident,
        )
        assert resp.status == "pending" and resp.task_id
        return await _wait_task(resp.task_id, ident), resp.task_id

    st, task_id = asyncio.run(scenario())
    assert st.status == "done" and st.question_id

    async def check_db():
        from sqlalchemy import select

        from app.db import SessionLocal
        from app.models import History, Question, Solution

        async with SessionLocal() as db:
            q = (await db.execute(select(Question).where(Question.id == st.question_id))).scalar_one()
            assert q.content_text == "1+1=?" and q.client_id == "cid-t1" and q.user_id is None
            s = (await db.execute(select(Solution).where(Solution.question_id == st.question_id))).scalar_one()
            assert s.tokens == 123 and s.model
            h = (await db.execute(select(History).where(History.question_id == st.question_id))).scalar_one()
            assert h.client_id == "cid-t1"

    asyncio.run(check_db())


def test_solve_cache_hit_returns_done_immediately(monkeypatch):
    """同题第二次请求：不再创建任务，直接 done + cached（秒回）。"""
    monkeypatch.setattr(pipeline, "run_solve", _fake_solve)

    async def scenario():
        ident = Identity(client_id="cid-t2", user_id=None)
        r1 = await solve_mod.solve(SolveRequest(text="2+2=?", grade_level="初中"), _http_request(), ident)
        assert r1.status == "pending"
        await _wait_task(r1.task_id, ident)
        r2 = await solve_mod.solve(SolveRequest(text="2+2=?", grade_level="初中"), _http_request(), ident)
        assert r2.status == "done" and r2.cached is True
        assert r2.question_id
        assert r2.task_id is None
        # 学段不同 → 缓存不命中，另起任务
        r3 = await solve_mod.solve(SolveRequest(text="2+2=?", grade_level="高中"), _http_request(), ident)
        assert r3.status == "pending"

    asyncio.run(scenario())


def test_task_poll_ownership_enforced(monkeypatch):
    """游客 B 不能轮询游客 A 的任务（404，不透露存在性）。"""
    import pytest as _pytest
    from fastapi import HTTPException

    monkeypatch.setattr(pipeline, "run_solve", _fake_solve)

    async def scenario():
        ident_a = Identity(client_id="cid-a", user_id=None)
        ident_b = Identity(client_id="cid-b", user_id=None)
        resp = await solve_mod.solve(SolveRequest(text="3+3=?", grade_level="初中"), _http_request(), ident_a)
        with _pytest.raises(HTTPException) as ei:
            await solve_mod.get_task(resp.task_id, ident_b)
        assert ei.value.status_code == 404
        # 属主自己可查
        st = await solve_mod.get_task(resp.task_id, ident_a)
        assert st.status in ("pending", "running", "done")

    asyncio.run(scenario())


def test_task_failed_status(monkeypatch):
    """LLM 解析失败：任务状态 failed + 用户可读错误。"""
    async def _boom(text, grade):
        raise pipeline.SolveFailed("模型输出无法解析")

    monkeypatch.setattr(pipeline, "run_solve", _boom)

    async def scenario():
        ident = Identity(client_id="cid-t3", user_id=None)
        resp = await solve_mod.solve(SolveRequest(text="4+4=?", grade_level="初中"), _http_request(), ident)
        st = await _wait_task(resp.task_id, ident)
        assert st.status == "failed"
        assert st.error and "解析" in st.error

    asyncio.run(scenario())
