"""举一反三：变式题生成 + 作答批改"""
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from ..ai import pipeline
from ..auth import Identity, get_identity, owns
from ..config import settings
from ..db import SessionLocal
from ..models import Mistake, PracticeItem, PracticeSet, Question, Solution
from ..schemas import (
    PracticeResultResponse,
    PracticeSetOut,
    PracticeSubmitRequest,
    PracticeSubmitResponse,
    VariantGenerateRequest,
)
from ..services.cache import cache

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/practice", tags=["practice"])

# 变式题缓存 TTL：比解析短（题目可能进错题本后重练），7 天足够
_VARIANTS_TTL = 7 * 24 * 3600


def _variants_cache_key(question_id: str) -> str:
    return f"variants:v1:{settings.llm_model}:{question_id}"


async def _load_question_with_solution(db, question_id: str, ident: Identity):
    q = (await db.execute(
        select(Question).where(Question.id == question_id, owns(Question, ident))
    )).scalar_one_or_none()
    if not q:
        # 归属校验：不能拿别人的 question_id 消耗我们的 LLM 配额
        raise HTTPException(404, "原题不存在")
    s = (await db.execute(
        select(Solution).where(Solution.question_id == question_id).order_by(Solution.id.desc())
    )).scalars().first()
    return q, s


@router.post("/generate", response_model=PracticeSetOut)
async def generate(req: VariantGenerateRequest, ident: Identity = Depends(get_identity)):
    async with SessionLocal() as db:
        q, s = await _load_question_with_solution(db, req.question_id, ident)
        key_points = s.key_points if s else []

    # 缓存命中：同一道题的变式题秒回（O-3），refresh=true（换一套）绕过重新生成
    if not req.refresh:
        cached_set = await cache.get_json(_variants_cache_key(q.id))
        if cached_set and cached_set.get("set_id"):
            set_id = cached_set["set_id"]
            async with SessionLocal() as db:
                items = (await db.execute(
                    select(PracticeItem).where(PracticeItem.set_id == set_id).order_by(PracticeItem.seq)
                )).scalars().all()
            if items:
                return PracticeSetOut(
                    set_id=set_id, question_id=q.id, cached=True,
                    items=[{
                        "item_id": it.id, "question": it.variant_question,
                        "difficulty": it.difficulty, "seq": it.seq,
                    } for it in items],
                )
            # 缓存指向的练习集已被清理：走重新生成

    try:
        variants, tokens = await pipeline.run_variants(q.content_text, key_points, q.grade_level)
    except pipeline.SolveFailed as e:
        logger.error("variant gen failed: %s", e)
        raise HTTPException(422, "变式题生成失败，请稍后重试")

    set_id = str(uuid.uuid4())
    items_out = []
    async with SessionLocal() as db:
        db.add(PracticeSet(
            id=set_id, question_id=q.id,
            client_id=ident.client_id, user_id=ident.user_id, status="created",
            tokens_gen=tokens,  # O-5：成本审计
        ))
        await db.flush()  # 确保 practice_sets 先写入
        for i, v in enumerate(variants):
            item_id = str(uuid.uuid4())
            db.add(PracticeItem(
                id=item_id, set_id=set_id, difficulty=v["difficulty"],
                variant_question=v["question"], standard_answer=v["standard_answer"], seq=i + 1,
            ))
            items_out.append({
                "item_id": item_id, "question": v["question"],
                "difficulty": v["difficulty"], "seq": i + 1,
            })
        await db.commit()
    # 生成成功后写入缓存；refresh 生成的新套覆盖旧缓存
    await cache.set_json(_variants_cache_key(q.id), {"set_id": set_id}, _VARIANTS_TTL)
    return PracticeSetOut(set_id=set_id, question_id=q.id, items=items_out)


@router.post("/submit", response_model=PracticeSubmitResponse)
async def submit(req: PracticeSubmitRequest, ident: Identity = Depends(get_identity)):
    # 1) 读：校验并加载数据后立即关闭会话（LLM 调用绝不能放在事务/连接内，
    #    否则批改的 20~40s 会占住连接，几个并发即可耗尽连接池）
    async with SessionLocal() as db:
        ps = (await db.execute(
            select(PracticeSet).where(PracticeSet.id == req.set_id, owns(PracticeSet, ident))
        )).scalar_one_or_none()
        if not ps:
            raise HTTPException(404, "练习集不存在")
        if ps.status == "submitted":
            raise HTTPException(409, "该练习已提交过批改，不能重复提交")
        items = (await db.execute(
            select(PracticeItem).where(PracticeItem.set_id == req.set_id).order_by(PracticeItem.seq)
        )).scalars().all()
        if len(items) != len(req.answers):
            raise HTTPException(422, "作答数量与题目数量不一致")
        ans_map = {a.item_id: a.user_answer for a in req.answers}
        if set(ans_map.keys()) != {it.id for it in items}:
            raise HTTPException(422, "作答题目 ID 不匹配")
        q = (await db.execute(select(Question).where(Question.id == ps.question_id))).scalar_one()
        grade_items = [{
            "seq": it.seq, "question": it.variant_question,
            "standard_answer": it.standard_answer, "user_answer": ans_map[it.id],
        } for it in items]

    # 2) 算：LLM 批改（会话外，不占数据库连接）
    try:
        results, tokens_grade = await pipeline.run_grade(grade_items, q.grade_level)
    except pipeline.SolveFailed as e:
        logger.error("grade failed: %s", e)
        raise HTTPException(422, "AI 批改失败，请稍后重试")

    # 3) 写：新会话写回结果
    result_map = {r["seq"]: r for r in results}
    out_items = []
    async with SessionLocal() as db:
        # 重读状态再校验一次，防两个请求并发提交同一练习集
        ps2 = (await db.execute(select(PracticeSet).where(PracticeSet.id == req.set_id))).scalar_one()
        if ps2.status == "submitted":
            raise HTTPException(409, "该练习已提交过批改，不能重复提交")
        fresh_items = (await db.execute(
            select(PracticeItem).where(PracticeItem.set_id == req.set_id).order_by(PracticeItem.seq)
        )).scalars().all()
        for it in fresh_items:
            r = result_map[it.seq]
            it.user_answer = ans_map[it.id]
            it.is_correct = r["is_correct"]
            it.feedback = r["feedback"]
            it.error_cause = r["error_cause"]
            out_items.append({
                "item_id": it.id, "is_correct": r["is_correct"],
                "standard_answer": it.standard_answer, "user_answer": ans_map[it.id],
                "feedback": r["feedback"], "error_cause": r["error_cause"],
            })
            # 答错自动入错题本
            if not r["is_correct"]:
                db.add(Mistake(
                    client_id=ident.client_id, user_id=ident.user_id, source="variant",
                    title=it.variant_question[:80], content=it.variant_question,
                    answer=it.standard_answer, error_cause=r["error_cause"],
                    subject=q.subject, grade_level=q.grade_level,
                ))
        ps2.status = "submitted"
        ps2.tokens_grade = tokens_grade  # O-5：批改成本审计
        await db.commit()
    return PracticeSubmitResponse(set_id=req.set_id, results=out_items)


@router.get("/{set_id}/result", response_model=PracticeResultResponse)
async def get_result(set_id: str, ident: Identity = Depends(get_identity)):
    """批改结果回源：结果页刷新后从数据库恢复（数据都在库里，不依赖 sessionStorage）。"""
    async with SessionLocal() as db:
        ps = (await db.execute(
            select(PracticeSet).where(PracticeSet.id == set_id, owns(PracticeSet, ident))
        )).scalar_one_or_none()
        if not ps:
            raise HTTPException(404, "练习集不存在")
        if ps.status != "submitted":
            raise HTTPException(409, "该练习尚未提交批改")
        items = (await db.execute(
            select(PracticeItem).where(PracticeItem.set_id == set_id).order_by(PracticeItem.seq)
        )).scalars().all()
        results = [{
            "item_id": it.id, "is_correct": bool(it.is_correct),
            "standard_answer": it.standard_answer, "user_answer": it.user_answer or "",
            "feedback": it.feedback or "", "error_cause": it.error_cause,
        } for it in items]
        items_out = [{
            "item_id": it.id, "question": it.variant_question,
            "difficulty": it.difficulty, "seq": it.seq,
        } for it in items]
        return PracticeResultResponse(
            set_id=set_id, question_id=ps.question_id, items=items_out, results=results,
        )
