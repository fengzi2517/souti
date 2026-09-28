"""错题本与历史记录路由（按 Identity 归属：登录态 user_id / 游客态 client_id）"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, func, select

from ..auth import Identity, get_identity, owns
from ..db import SessionLocal
from ..models import History, Mistake, Question
from ..schemas import (
    HistoryItemOut,
    HistoryListResponse,
    MistakeListResponse,
    MistakeOut,
)

router = APIRouter(prefix="/api", tags=["records"])


# ---------- 错题本 ----------
class MistakeAddRequest(BaseModel):
    question_id: str | None = None
    title: str
    content: str
    answer: str | None = None
    error_cause: str | None = None
    subject: str | None = None
    grade_level: str | None = None


@router.get("/mistakes", response_model=MistakeListResponse)
async def list_mistakes(
    ident: Identity = Depends(get_identity),
    subject: str | None = None,
    error_cause: str | None = None,
    offset: int = 0,
    limit: int = Query(default=50, le=100),
):
    async with SessionLocal() as db:
        stmt = select(Mistake).where(owns(Mistake, ident))
        if subject:
            stmt = stmt.where(Mistake.subject == subject)
        if error_cause:
            stmt = stmt.where(Mistake.error_cause == error_cause)
        total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar()
        rows = (await db.execute(
            stmt.order_by(Mistake.created_at.desc()).offset(offset).limit(limit)
        )).scalars().all()
        items = [MistakeOut(
            id=m.id, question_id=m.question_id, source=m.source, title=m.title,
            content=m.content, answer=m.answer, error_cause=m.error_cause,
            subject=m.subject, grade_level=m.grade_level,
            created_at=m.created_at.isoformat() if m.created_at else "",
        ) for m in rows]
    return MistakeListResponse(total=total, items=items)


@router.post("/mistakes", response_model=MistakeOut)
async def add_mistake(req: MistakeAddRequest, ident: Identity = Depends(get_identity)):
    async with SessionLocal() as db:
        # 双写：登录态数据归属账号（跨设备可见），client_id 保留作设备追踪
        m = Mistake(client_id=ident.client_id, user_id=ident.user_id, source="manual", **req.model_dump())
        db.add(m)
        await db.commit()
        await db.refresh(m)
        return MistakeOut(
            id=m.id, question_id=m.question_id, source=m.source, title=m.title,
            content=m.content, answer=m.answer, error_cause=m.error_cause,
            subject=m.subject, grade_level=m.grade_level,
            created_at=m.created_at.isoformat() if m.created_at else "",
        )


@router.delete("/mistakes/{mistake_id}")
async def remove_mistake(mistake_id: int, ident: Identity = Depends(get_identity)):
    async with SessionLocal() as db:
        res = await db.execute(
            delete(Mistake).where(Mistake.id == mistake_id, owns(Mistake, ident))
        )
        await db.commit()
        if res.rowcount == 0:
            raise HTTPException(404, "错题不存在")
    return {"ok": True}


# ---------- 历史 ----------
@router.get("/history", response_model=HistoryListResponse)
async def list_history(
    ident: Identity = Depends(get_identity),
    offset: int = 0,
    limit: int = Query(default=50, le=100),
):
    async with SessionLocal() as db:
        base = (
            select(History, Question)
            .join(Question, History.question_id == Question.id)
            .where(owns(History, ident))
        )
        total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar()
        rows = (await db.execute(
            base.order_by(History.viewed_at.desc()).offset(offset).limit(limit)
        )).all()
        items = [HistoryItemOut(
            question_id=q.id, content_text=q.content_text[:200],
            subject=q.subject, grade_level=q.grade_level,
            created_at=h.viewed_at.isoformat() if h.viewed_at else "",
        ) for h, q in rows]
    return HistoryListResponse(total=total, items=items)


@router.get("/questions/{question_id}")
async def get_question(question_id: str, ident: Identity = Depends(get_identity)):
    """解析页刷新/分享时回源完整数据（仅数据归属者可访问，防越权读取）"""
    from ..models import Solution
    async with SessionLocal() as db:
        q = (await db.execute(select(Question).where(Question.id == question_id))).scalar_one_or_none()
        if not q or not _can_access_question(q, ident):
            # 404 而非 403：不向无权者确认资源存在
            raise HTTPException(404, "题目不存在")
        s = (await db.execute(
            select(Solution).where(Solution.question_id == question_id).order_by(Solution.id.desc())
        )).scalars().first()
        if not s:
            raise HTTPException(404, "解析不存在")
        return {
            "question_id": q.id,
            "content_text": q.content_text,
            "subject": q.subject,
            "grade_level": q.grade_level,
            "solution": {
                "answer": s.answer, "steps": s.steps_json, "key_points": s.key_points,
                "common_mistakes": s.common_mistakes, "knowledge_points": s.knowledge_points,
                "grade_level": q.grade_level, "subject": q.subject,
            },
        }


def _can_access_question(q: Question, ident: Identity) -> bool:
    """题目归属判定（与 auth.owns 一致的语义，Question 对象已加载时用这个避免再查库）。"""
    if ident.user_id is not None:
        return q.user_id == ident.user_id
    return q.user_id is None and q.client_id == ident.client_id
