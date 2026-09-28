"""pytest 配置

关键点：
1. 在导入任何 app 模块之前设置 DATABASE_URL 为临时 SQLite——engine 在
   app.db import 时绑定 URL，晚了不生效。
2. 把 engine 换成 NullPool 版：测试里每个用例 asyncio.run 各自新建事件循环，
   QueuePool 复用跨循环的 aiosqlite 连接会报 "attached to a different loop"。
   必须在路由模块导入（from ..db import SessionLocal）之前完成替换。
"""
import asyncio
import os
import tempfile

os.environ.setdefault("LLM_API_KEY", "sk-test-only-for-pytest")
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
# Redis 单测固定走内存降级模式：指向必然拒绝的端口，与开发机是否跑着 Docker Redis 无关。
# （此前依赖「本机无 Redis」的巧合，Docker 起来后单测会连上真库并因跨事件循环复用连接而崩溃）
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"

if not os.environ.get("DATABASE_URL"):
    _tmpdir = tempfile.mkdtemp(prefix="ai_solve_test_")
    os.environ["DATABASE_URL"] = (
        "sqlite+aiosqlite:///" + os.path.join(_tmpdir, "test.db").replace("\\", "/")
    )

from sqlalchemy import delete  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app import db as _db  # noqa: E402

# 测试专用 engine：NullPool，连接用完即弃，跨事件循环安全
_db.engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
_db.SessionLocal = async_sessionmaker(_db.engine, class_=AsyncSession, expire_on_commit=False)

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _create_tables():
    """整个测试会话开始前建表（等价 init_db，但不走 lifespan）。"""
    from app import models  # noqa: F401
    from app.db import Base

    async def _create():
        async with _db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create())
    yield
    asyncio.run(_db.engine.dispose())


@pytest.fixture()
def db_clean():
    """每个用例独立数据：清空业务表（需要 DB 的测试文件里 autouse 引用）。"""
    from app import models

    async def _clean():
        async with _db.engine.begin() as conn:
            for table in (
                models.History, models.Mistake, models.PracticeItem,
                models.PracticeSet, models.Solution, models.Question, models.User,
            ):
                await conn.execute(delete(table))

    asyncio.run(_clean())
    yield
    asyncio.run(_clean())
