"""登录体系（M2）：开发模式验证码登录 + JWT + 游客数据迁移"""
import hmac
import logging
import random

from fastapi import APIRouter, Header
from pydantic import BaseModel
from sqlalchemy import select, update

from ..auth import _norm_client_id, create_token, verify_token
from ..config import settings
from ..db import SessionLocal
from ..models import History, Mistake, PracticeSet, Question, User
from ..services.cache import cache

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

# 安全参数：登录失败锁定 / 短信频控
LOGIN_MAX_FAILS = 5        # 验证码错误 5 次
LOGIN_LOCK_SECONDS = 900   # 锁 15 分钟
SMS_MIN_INTERVAL = 60      # 同号 1 条/分钟
SMS_DAILY_LIMIT = 5        # 同号 5 条/天


class SendCodeRequest(BaseModel):
    phone: str


class LoginRequest(BaseModel):
    phone: str
    code: str
    client_id: str | None = None  # 游客 client_id，登录后迁移其数据


def _valid_phone(phone: str) -> bool:
    return len(phone) == 11 and phone.startswith("1") and phone.isdigit()


@router.post("/send_code")
async def send_code(req: SendCodeRequest):
    if not _valid_phone(req.phone):
        return {"ok": False, "message": "手机号格式不正确"}
    # 频控：防刷短信（开发模式同样生效，避免联调时误打真实通道）
    freq = await cache.incr_with_ttl(f"sms:freq:{req.phone}", SMS_MIN_INTERVAL)
    if freq > 1:
        return {"ok": False, "message": "发送太频繁，请 1 分钟后再试"}
    daily = await cache.incr_with_ttl(f"sms:daily:{req.phone}", 86400)
    if daily > SMS_DAILY_LIMIT:
        return {"ok": False, "message": "今日验证码发送次数已达上限，请明天再试"}
    code = "123456" if settings.sms_dev_mode else f"{random.randint(0, 999999):06d}"
    await cache.set_json(f"smscode:{req.phone}", {"code": code}, 300)  # 5 分钟有效
    resp: dict = {"ok": True, "message": "验证码已发送（5 分钟内有效）"}
    if settings.sms_dev_mode:
        resp["dev_code"] = code  # 开发模式直接回显
    return resp


@router.post("/login")
async def login(req: LoginRequest, x_client_id: str = Header(default="default")):
    # 失败锁定：防验证码暴力枚举（6 位码 100 万组合，必须限制尝试次数）
    fails = await cache.incr_with_ttl(f"loginfail:{req.phone}", LOGIN_LOCK_SECONDS)
    if fails > LOGIN_MAX_FAILS:
        return {"ok": False, "message": "尝试次数过多，账号已锁定 15 分钟，请稍后再试"}
    saved = await cache.get_json(f"smscode:{req.phone}")
    # hmac.compare_digest：恒定时间比较，防时序侧信道
    if not saved or not hmac.compare_digest(str(saved.get("code", "")), req.code):
        return {"ok": False, "message": "验证码错误或已过期"}
    await cache.delete(f"loginfail:{req.phone}")  # 成功后清除失败计数

    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(User.phone == req.phone))).scalar_one_or_none()
        if not user:
            user = User(phone=req.phone)
            db.add(user)
            await db.flush()

        # 游客数据迁移：只收编该 client_id 名下尚未归属任何账号的数据（user_id IS NULL）。
        # 若不加此条件，设备换人登录时会把前一账号的数据串给新账号。
        cid = _norm_client_id(req.client_id or x_client_id)
        if cid and cid != "default":
            for model in (Question, PracticeSet, Mistake, History):
                await db.execute(
                    update(model)
                    .where(model.client_id == cid, model.user_id.is_(None))
                    .values(user_id=user.id)
                )
        await db.commit()
        token = create_token(user.id, user.phone)
        return {"ok": True, "token": token, "phone": user.phone, "user_id": user.id, "migrated_client_id": cid}


@router.get("/me")
async def me(authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip()
    payload = verify_token(token)
    if not payload:
        return {"ok": False, "message": "登录已过期"}
    return {"ok": True, "user_id": payload["uid"], "phone": payload["phone"]}
