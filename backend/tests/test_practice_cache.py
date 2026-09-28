"""O-3 变式题缓存 + O-5 tokens 审计集成测试（SQLite 测试库）"""
import asyncio
import uuid

import pytest
from starlette.requests import Request

from app.ai import pipeline
from app.auth import Identity
from app.routers import practice as practice_mod
from app.schemas import (
    AnswerItem,
    PracticeSubmitRequest,
    VariantGenerateRequest,
)

pytestmark = pytest.mark.usefixtures("db_clean")


async def _seed_question(qid: str, client_id: str, text: str = "解方程 x^2-4=0") -> None:
    from app.db import SessionLocal
    from app.models import Question

    async with SessionLocal() as db:
        db.add(Question(
            id=qid, client_id=client_id, user_id=None,
            content_text=text, grade_level="初中", status="solved",
        ))
        await db.commit()


async def _fake_variants(text, key_points, grade):
    return [
        {"question": f"变式题{i}", "standard_answer": f"答案{i}", "difficulty": "基础"}
        for i in range(3)
    ], 66


def test_variants_cached_until_refresh(monkeypatch):
    """同题第二次 generate 命中缓存秒回；refresh=true 重新生成一套。"""
    monkeypatch.setattr(pipeline, "run_variants", _fake_variants)
    calls = []
    orig = pipeline.run_variants

    async def _counting(*a, **kw):
        calls.append(1)
        return await orig(*a, **kw)

    monkeypatch.setattr(pipeline, "run_variants", _counting)

    qid = str(uuid.uuid4())
    ident = Identity(client_id="cid-p1", user_id=None)

    async def scenario():
        await _seed_question(qid, "cid-p1")
        r1 = await practice_mod.generate(VariantGenerateRequest(question_id=qid), ident)
        assert r1.cached is False and r1.question_id == qid and len(r1.items) == 3
        r2 = await practice_mod.generate(VariantGenerateRequest(question_id=qid), ident)
        assert r2.cached is True and r2.set_id == r1.set_id  # 秒回同一套
        r3 = await practice_mod.generate(VariantGenerateRequest(question_id=qid, refresh=True), ident)
        assert r3.cached is False and r3.set_id != r1.set_id  # 换一套
        # 之后不带 refresh 再来：命中 r3 的新缓存
        r4 = await practice_mod.generate(VariantGenerateRequest(question_id=qid), ident)
        assert r4.cached is True and r4.set_id == r3.set_id
        assert len(calls) == 2  # 只有首次 + refresh 真正调了 LLM

    asyncio.run(scenario())


def test_generate_records_tokens(monkeypatch):
    """O-5：生成/批改 tokens 落库。"""
    monkeypatch.setattr(pipeline, "run_variants", _fake_variants)

    async def _fake_grade(items, grade):
        results = [
            {"seq": it["seq"], "is_correct": i == 0, "feedback": "讲评", "error_cause": None}
            for i, it in enumerate(items)
        ]
        return results, 88

    monkeypatch.setattr(pipeline, "run_grade", _fake_grade)

    qid = str(uuid.uuid4())
    ident = Identity(client_id="cid-p2", user_id=None)

    async def scenario():
        from sqlalchemy import select

        from app.db import SessionLocal
        from app.models import PracticeSet

        await _seed_question(qid, "cid-p2")
        r = await practice_mod.generate(VariantGenerateRequest(question_id=qid), ident)
        # 提交批改
        sub = await practice_mod.submit(PracticeSubmitRequest(
            set_id=r.set_id,
            answers=[AnswerItem(item_id=it.item_id, user_answer="作答") for it in r.items],
        ), ident)
        assert len(sub.results) == 3

        async with SessionLocal() as db:
            ps = (await db.execute(select(PracticeSet).where(PracticeSet.id == r.set_id))).scalar_one()
            assert ps.tokens_gen == 66
            assert ps.tokens_grade == 88
            assert ps.status == "submitted"

    asyncio.run(scenario())


def test_generate_rejects_foreign_question():
    """归属校验：别人的题目 404（不能白耗 LLM 配额）。"""
    import pytest as _pytest
    from fastapi import HTTPException

    qid = str(uuid.uuid4())
    ident = Identity(client_id="cid-p3", user_id=None)

    async def scenario():
        await _seed_question(qid, "cid-other")
        with _pytest.raises(HTTPException) as ei:
            await practice_mod.generate(VariantGenerateRequest(question_id=qid), ident)
        assert ei.value.status_code == 404

    asyncio.run(scenario())
