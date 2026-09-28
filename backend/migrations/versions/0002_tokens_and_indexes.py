"""O-5/O-6：practice_sets 加 tokens_gen/tokens_grade；mistakes/histories 加复合索引

说明：0001 基线用 create_all（按执行时的 models 元数据建表），全新库跑 0001 时
可能已包含本迁移的内容，因此这里全部操作前先探测存在性，幂等执行。

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_COLUMNS = [
    ("practice_sets", "tokens_gen", sa.Integer(), 0),
    ("practice_sets", "tokens_grade", sa.Integer(), 0),
]

_NEW_INDEXES = [
    ("ix_mistakes_client_created", "mistakes", ["client_id", "created_at"]),
    ("ix_mistakes_user_created", "mistakes", ["user_id", "created_at"]),
    ("ix_histories_client_viewed", "histories", ["client_id", "viewed_at"]),
    ("ix_histories_user_viewed", "histories", ["user_id", "viewed_at"]),
]


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    for table, column, col_type, default in _NEW_COLUMNS:
        cols = {c["name"] for c in insp.get_columns(table)}
        if column not in cols:
            op.add_column(table, sa.Column(column, col_type, nullable=False, server_default=str(default)))

    existing_idx = {ix["name"] for ix in insp.get_indexes("mistakes")} | {
        ix["name"] for ix in insp.get_indexes("histories")
    }
    for name, table, columns in _NEW_INDEXES:
        if name not in existing_idx:
            op.create_index(name, table, columns)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    existing_idx = {ix["name"] for ix in insp.get_indexes("mistakes")} | {
        ix["name"] for ix in insp.get_indexes("histories")
    }
    for name, table, _columns in reversed(_NEW_INDEXES):
        if name in existing_idx:
            op.drop_index(name, table_name=table)

    for table, column, _t, _d in reversed(_NEW_COLUMNS):
        cols = {c["name"] for c in insp.get_columns(table)}
        if column in cols:
            op.drop_column(table, column)
