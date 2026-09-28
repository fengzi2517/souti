"""搜题解析核心路由：POST /api/solve（任务化，O-1）+ GET /api/tasks/{task_id}

reasoning 模型解析需 15~60s，一根 HTTP 长连接干等问题多（代理超时、无进度、
断线全丢）。改为：solve 校验+限流后立即返回 task_id，LLM 解析在后台任务中
执行，前端轮询拿进度/结果。缓存命中时仍同步直接返回（秒回）。
"""
import asyncio
import hashlib
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from ..ai import ocr, pipeline
from ..auth import Identity, get_identity
from ..config import settings
from ..db import SessionLocal
from ..models import History, Question, Solution
from ..schemas import (
    SolveRequest,
    SolveTaskStartResponse,
    SolveTaskStatusResponse,
)
from ..services.cache import cache
from .upload import safe_upload_path

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["solve"])

# 任务记录 TTL：完成后保留 1 小时供轮询/回看，过期自动清
_TASK_TTL = 3600


def _cache_key(text: str, grade: str) -> str:
    norm = "".join(text.split())  # 去空白归一化
    return f"solve:v1:{settings.llm_model}:{grade}:{hashlib.sha256(norm.encode()).hexdigest()}"


def _task_key(task_id: str) -> str:
    return f"task:v1:{task_id}"


# singleflight：同 cache key 的并发请求只跑一次 LLM，其余等锁后命中缓存（双检）。
# 进程内去重，单 worker 部署足够；多实例再考虑 Redis 分布式锁。
_solve_locks: dict[str, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


async def _get_solve_lock(key: str) -> asyncio.Lock:
    async with _locks_guard:
        lock = _solve_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _solve_locks[key] = lock
        return lock


async def _release_solve_lock(key: str, lock: asyncio.Lock) -> None:
    """用完后移除，避免 _solve_locks 随 key 无限增长。"""
    async with _locks_guard:
        if _solve_locks.get(key) is lock and not lock.locked():
            del _solve_locks[key]


def _client_ip(request: Request) -> str:
    """取真实客户端 IP：仅在明确部署于可信反向代理后（TRUST_PROXY=true）才信任
    X-Forwarded-For（取最左侧的原始客户端）；否则直连时该头可被伪造绕过限流。"""
    if settings.trust_proxy:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# 后台任务强引用：避免 asyncio.create_task 的返回值被 GC 导致任务中途消失
_running_tasks: set[asyncio.Task] = set()


async def _solve_core(
    ck: str,
    content_text: str,
    grade_level: str,
    ident: Identity,
    image_path: str | None,
    direct_image: bool,
    image_hash: str | None,
) -> str | None:
    """解析主流程（在后台任务中执行）：singleflight + 缓存双检 + LLM + 落库。"""
    lock = await _get_solve_lock(ck)
    try:
        async with lock:
            cached = await cache.get_json(ck)
            if cached:
                return cached.get("question_id")

            # LLM 解析（内部含一次带错误反馈的重试；网络异常直接失败不重试）
            if direct_image and image_path:
                solution, tokens = await pipeline.run_solve_vision(image_path, grade_level)
            else:
                solution, tokens = await pipeline.run_solve(content_text, grade_level)

            # 落库（视觉直传时用模型转写的题干作为 content_text，便于历史/变式题复用）
            final_text = content_text
            if direct_image and image_path and solution.steps and solution.steps[0].get("title") == "题目转写":
                final_text = solution.steps[0]["content"]
            qid = str(uuid.uuid4())
            async with SessionLocal() as db:
                db.add(Question(
                    id=qid, client_id=ident.client_id, user_id=ident.user_id,
                    image_path=image_path, image_hash=image_hash,
                    subject=solution.subject, grade_level=grade_level,
                    content_text=final_text, status="solved",
                ))
                db.add(Solution(
                    question_id=qid, steps_json=[s for s in solution.steps],
                    answer=solution.answer, key_points=solution.key_points,
                    common_mistakes=solution.common_mistakes,
                    knowledge_points=[kp.model_dump() for kp in solution.knowledge_points],
                    model=settings.llm_model, tokens=tokens,
                ))
                await db.flush()  # 确保 questions 先写入，避免 histories 外键冲突
                db.add(History(client_id=ident.client_id, user_id=ident.user_id, question_id=qid))
                await db.commit()

            await cache.set_json(ck, {"question_id": qid, "solution": solution.model_dump()}, settings.cache_ttl_solve)
            return qid
    finally:
        await _release_solve_lock(ck, lock)


async def _run_solve_task(
    task_id: str,
    ck: str,
    content_text: str,
    grade_level: str,
    ident: Identity,
    image_path: str | None,
    direct_image: bool,
    image_hash: str | None,
) -> None:
    """后台任务壳：推进任务状态（pending → running → done/failed）。"""
    async def _save(**fields):
        rec = await cache.get_json(_task_key(task_id)) or {}
        rec.update(fields)
        await cache.set_json(_task_key(task_id), rec, _TASK_TTL)

    try:
        await _save(status="running")

        # OCR 分支的题干在后台补齐（Paddle 冷启动可能要 10s+，不能占住 HTTP 请求）
        if image_path and not direct_image and content_text == "":
            ocr_cache_key = f"ocr:v1:{image_hash}"
            cached_text = await cache.get_json(ocr_cache_key)
            if cached_text:
                content_text = cached_text.get("text", "")
            else:
                content_text = await ocr.recognize(image_path)
                if not content_text:
                    await _save(status="failed", error="未能从图片中识别出文字，请拍得更清晰些，或改用文字输入")
                    return
                await cache.set_json(ocr_cache_key, {"text": content_text}, settings.cache_ttl_ocr)
            ck = _cache_key(content_text, grade_level)  # OCR 后才能确定最终缓存 key

        qid = await _solve_core(ck, content_text, grade_level, ident, image_path, direct_image, image_hash)
        await _save(status="done", question_id=qid)
    except pipeline.SolveFailed as e:
        logger.error("solve task %s failed: %s", task_id, e)
        await _save(status="failed", error="AI 暂时无法解析这道题，请尝试用文字重新输入题干，或稍后再试")
    except ocr.OCRUnavailable as e:
        logger.error("solve task %s ocr failed: %s", task_id, e)
        await _save(status="failed", error=f"图片识别暂不可用：{e}")
    except Exception:  # noqa: BLE001  兜底：任何异常都要让轮询方看到 failed 而非永久 pending
        logger.exception("solve task %s crashed", task_id)
        await _save(status="failed", error="解析服务内部错误，请稍后再试")


def _owns_task(task: dict, ident: Identity) -> bool:
    """任务归属：登录态按 user_id；游客按 client_id 且未被账号收编。"""
    if task.get("user_id") is not None:
        return ident.user_id == task["user_id"]
    return ident.user_id is None and ident.client_id == task.get("client_id")


@router.post("/solve", response_model=SolveTaskStartResponse)
async def solve(req: SolveRequest, request: Request, ident: Identity = Depends(get_identity)):
    # 0. 参数校验
    if not req.image_id and not (req.text and req.text.strip()):
        raise HTTPException(422, "请提供图片或文字题干")
    if req.grade_level not in ("小学", "初中", "高中"):
        raise HTTPException(422, "学段必须是 小学/初中/高中")

    # 1. 限流：登录用户按账号计（跨设备共享额度），游客按 IP 计
    rate_key = f"u:{ident.user_id}" if ident.user_id is not None else _client_ip(request)
    allowed, remaining = await cache.check_rate(rate_key)
    if not allowed:
        raise HTTPException(429, f"今日解析次数已达上限（{settings.rate_limit_daily} 次），明天再来吧")

    content_text = (req.text or "").strip()
    image_path = None
    image_hash = None

    # 2. 图片分支：direct_image=视觉直传（跳过 OCR）；否则 OCR 转文字（在后台任务里做）
    if req.image_id:
        p = safe_upload_path(req.image_id)  # 白名单校验，防路径穿越
        if not p.exists():
            raise HTTPException(404, "图片不存在或已过期，请重新上传")
        # 大图读取放到线程池，避免阻塞事件循环
        image_hash = hashlib.sha256(await asyncio.to_thread(p.read_bytes)).hexdigest()
        image_path = str(p)

        if req.direct_image:
            # 视觉解析：题干留占位说明，真实内容在 LLM 读图时获取
            content_text = f"[图片直传解析，学段：{req.grade_level}]"
        else:
            content_text = ""  # OCR 后台补齐，缓存 key 也就绪后才能定

    # 3. 解析结果缓存：key 可同步确定时（文字题/视觉直传）先查一次，命中秒回
    #    视觉直传时 content_text 是占位符，key 必须带 image_hash，否则同学段所有直传请求会互相串缓存
    if content_text:
        ck = _cache_key(content_text, req.grade_level) + (f":vis:{image_hash}" if (req.direct_image and req.image_id) else "")
        cached = await cache.get_json(ck)
        if cached:
            return SolveTaskStartResponse(
                status="done", question_id=cached.get("question_id"), cached=True,
            )
    else:
        ck = ""  # OCR 完成后由后台任务计算

    # 4. 创建后台任务，立即返回 task_id（前端轮询 GET /api/tasks/{task_id}）
    task_id = str(uuid.uuid4())
    await cache.set_json(_task_key(task_id), {
        "status": "pending", "question_id": None, "error": None,
        "user_id": ident.user_id, "client_id": ident.client_id,
    }, _TASK_TTL)
    task = asyncio.create_task(_run_solve_task(
        task_id, ck, content_text, req.grade_level, ident, image_path,
        req.direct_image, image_hash,
    ))
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)
    return SolveTaskStartResponse(task_id=task_id, status="pending")


@router.get("/tasks/{task_id}", response_model=SolveTaskStatusResponse)
async def get_task(task_id: str, ident: Identity = Depends(get_identity)):
    """轮询解析任务状态：pending → running → done / failed。"""
    # 任务 ID 形态校验（防任意 key 探测）+ 记录读取
    if not task_id or len(task_id) > 64:
        raise HTTPException(404, "任务不存在或已过期")
    task = await cache.get_json(_task_key(task_id))
    if not task:
        raise HTTPException(404, "任务不存在或已过期")
    if not _owns_task(task, ident):
        raise HTTPException(404, "任务不存在或已过期")  # 不透露存在性
    return SolveTaskStatusResponse(
        task_id=task_id,
        status=task.get("status", "pending"),
        question_id=task.get("question_id"),
        cached=False,
        error=task.get("error"),
    )
