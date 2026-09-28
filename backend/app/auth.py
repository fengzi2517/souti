"""JWT 工具与数据归属身份：登录态签发/校验 + 全站统一的 identity 依赖

数据归属模型（P0-4/P2-1 重构）：
- 登录态（合法 Bearer token）：数据按 user_id 归属，云端同步跨设备可见
- 游客态（无 token / token 过期）：数据按 client_id 归属，仅本设备可见
- 游客登录时迁移：仅收编 user_id IS NULL 的游客数据，防止设备换人登录时串号
"""
import time
from dataclasses import dataclass

import jwt
from fastapi import Header
from sqlalchemy import ColumnElement, and_

from .config import settings


def create_token(user_id: int, phone: str) -> str:
    payload = {
        "uid": user_id,
        "phone": phone,
        "exp": int(time.time()) + settings.jwt_expire_hours * 3600,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def verify_token(token: str) -> dict | None:
    """返回 payload；无效/过期返回 None。"""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


@dataclass
class Identity:
    """请求身份：数据归属的唯一判定依据。"""
    client_id: str
    user_id: int | None = None  # None = 游客态

    @property
    def is_logged_in(self) -> bool:
        return self.user_id is not None


def _norm_client_id(raw: str | None) -> str:
    """client_id 归一化：空/匿名统一归入 default 命名空间（与历史数据兼容）。"""
    if not raw or raw in ("anonymous", "default"):
        return "default"
    return raw


def get_identity(
    x_client_id: str | None = Header(default=None),
    authorization: str = Header(default=""),
) -> Identity:
    """FastAPI 依赖：从请求头解析数据归属身份。

    token 无效/过期时静默降级为游客（不阻断使用，仅失去云端同步），
    由前端 401 拦截器负责清理本地凭证并引导重新登录。
    """
    cid = _norm_client_id(x_client_id)
    if authorization.startswith("Bearer "):
        payload = verify_token(authorization[7:])
        if payload and payload.get("uid") is not None:
            return Identity(client_id=cid, user_id=int(payload["uid"]))
    return Identity(client_id=cid, user_id=None)


def owns(model, ident: Identity) -> ColumnElement:
    """SQLAlchemy 过滤条件：某行数据是否归属该身份。

    - 登录态：行 user_id 等于当前用户（含登录前迁移过来的本设备/其他设备数据）
    - 游客态：行属于本设备且从未被任何账号收编（user_id IS NULL）——
      已迁移到账号的数据，设备登出后不可见（数据归属于账号而非设备）
    """
    if ident.user_id is not None:
        return model.user_id == ident.user_id
    return and_(model.client_id == ident.client_id, model.user_id.is_(None))
