"""initial schema：9 张核心表

等价于 init_db 的 create_all，作为迁移链的基线。
已有表的环境执行 `alembic stamp head` 打标即可，全新环境 `alembic upgrade head`。

Revision ID: 0001
Revises:
Create Date: 2026-09-09
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 基线建表直接按当前 models 元数据执行，保证与代码零漂移；
    # 之后的表结构变更一律走 `alembic revision --autogenerate` 生成增量迁移。
    from app import models  # noqa: F401
    from app.db import Base
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from app import models  # noqa: F401
    from app.db import Base
    Base.metadata.drop_all(bind=op.get_bind())
