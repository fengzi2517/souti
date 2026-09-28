"""应用入口：FastAPI 应用组装"""
import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from .ai import ocr
from .config import settings
from .db import SessionLocal, init_db
from .models import Question
from .routers import auth, practice, records, solve, upload
from .services.cache import cache

# ---------- 结构化日志（O-7）：request_id 贯穿一条请求的所有日志 ----------
_request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get()
        return True


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s [%(request_id)s]: %(message)s",
)
_root_handler = logging.getLogger().handlers[0]
_root_handler.addFilter(RequestIdFilter())
logger = logging.getLogger(__name__)

# ---------- uploads 定期清理（防磁盘无限增长） ----------
UPLOAD_MAX_AGE_SECONDS = 7 * 24 * 3600  # 保留期与 cache_ttl_ocr 对齐
UPLOAD_CLEANUP_INTERVAL = 6 * 3600      # 每 6 小时清扫一次


async def _cleanup_uploads_once() -> int:
    """删除超过保留期且未被任何 Question 引用的上传图片，返回删除数量。"""
    async with SessionLocal() as db:
        rows = (await db.execute(select(Question.image_path))).all()
    referenced = {Path(r[0]).name for r in rows if r[0]}
    now = time.time()
    removed = 0
    for p in settings.upload_dir.iterdir():
        if not p.is_file():
            continue
        try:
            if now - p.stat().st_mtime < UPLOAD_MAX_AGE_SECONDS:
                continue
            if p.name in referenced:
                continue
            p.unlink()
            removed += 1
        except OSError:
            logger.warning("清理上传文件失败: %s", p)
    if removed:
        logger.info("uploads 清理：删除 %d 个过期未引用文件", removed)
    return removed


async def _cleanup_uploads_loop():
    while True:
        await asyncio.sleep(UPLOAD_CLEANUP_INTERVAL)
        try:
            await _cleanup_uploads_once()
        except Exception:  # noqa: BLE001  数据库暂不可用等情况，下个周期再试
            logger.exception("uploads 清理任务异常，将在下个周期重试")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # fail-fast：非开发模式（接真实短信）仍用默认 JWT 密钥时直接拒绝启动
    if not settings.sms_dev_mode and settings.jwt_secret == "dev-secret-change-in-production!!":
        raise RuntimeError("JWT_SECRET 仍为默认值，请在 .env 中设置强随机密钥后再上线")
    await init_db()
    cleanup_task = asyncio.create_task(_cleanup_uploads_loop())
    yield
    cleanup_task.cancel()


app = FastAPI(title="AI 解题助手 API", version="0.1.0", lifespan=lifespan)

# 跨域：默认放行本机 dev server；生产通过 CORS_ORIGINS 环境变量收紧为真实域名
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 上传图片静态服务（开发期；生产换 OSS 签名 URL）
app.mount("/uploads", StaticFiles(directory=str(settings.upload_dir)), name="uploads")

app.include_router(auth.router)
app.include_router(upload.router)
app.include_router(solve.router)
app.include_router(practice.router)
app.include_router(records.router)


@app.middleware("http")
async def request_context(request, call_next):
    """注入 request_id（O-7）：日志可按请求聚合，响应头回传便于前端报障定位。"""
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    token = _request_id_var.set(rid)
    start = time.perf_counter()
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        logger.info(
            "%s %s -> %d (%.0fms)",
            request.method, request.url.path, response.status_code,
            (time.perf_counter() - start) * 1000,
        )
        return response
    finally:
        _request_id_var.reset(token)


@app.get("/api/health")
async def health():
    """健康检查（O-8）：DB 挂了返回 503；Redis 降级仅标记（内存兜底业务仍可用）。"""
    out: dict = {"status": "ok", "model": settings.llm_model}
    try:
        async with SessionLocal() as db:
            await db.execute(select(1))
        out["db"] = "ok"
    except Exception:  # noqa: BLE001
        out["db"] = "down"
        out["status"] = "degraded"
    out["redis"] = await cache.health()
    out["ocr_queue"] = ocr.queue_depth()  # OCR 排队深度（O-4）
    out["ocr_engine"] = ocr.engine_name()  # 当前引擎：rapidocr / paddle / null(未安装)
    if out["status"] != "ok":
        return JSONResponse(status_code=503, content=out)
    return out
