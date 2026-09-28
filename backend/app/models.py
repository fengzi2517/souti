"""数据模型：对应 PRD 6.1 核心数据模型
注意：游客数据不落库（AC-4），所有 user_id 均关联登录用户。
M1 开发期仅游客模式，questions/practice 等表 user_id 允许 NULL（关联前端 client_id 仅为联调追踪）。
"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Question(Base):
    __tablename__ = "questions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # uuid
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # 游客追踪（联调用）
    image_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    image_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    subject: Mapped[str | None] = mapped_column(String(20))
    grade_level: Mapped[str] = mapped_column(String(10))  # 小学/初中/高中
    content_text: Mapped[str] = mapped_column(Text)  # 题干
    status: Mapped[str] = mapped_column(String(20), default="solved")  # pending/ocr_done/solved/failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Solution(Base):
    __tablename__ = "solutions"
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"), index=True)
    steps_json: Mapped[list] = mapped_column(JSON)          # [{title, content, latex}]
    answer: Mapped[str] = mapped_column(Text)
    key_points: Mapped[list] = mapped_column(JSON)          # [str]
    common_mistakes: Mapped[list] = mapped_column(JSON)     # [str]
    knowledge_points: Mapped[list] = mapped_column(JSON)    # [{name,definition,formula,tip}]
    model: Mapped[str] = mapped_column(String(64))
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PracticeSet(Base):
    __tablename__ = "practice_sets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="created")  # created/submitted
    # LLM 成本审计（O-5）：生成变式题 / 批改各消耗的 tokens，按日汇总可核算
    tokens_gen: Mapped[int] = mapped_column(Integer, default=0)
    tokens_grade: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PracticeItem(Base):
    __tablename__ = "practice_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    set_id: Mapped[str] = mapped_column(ForeignKey("practice_sets.id"), index=True)
    difficulty: Mapped[str] = mapped_column(String(10))     # 基础/进阶/挑战
    variant_question: Mapped[str] = mapped_column(Text)
    standard_answer: Mapped[str | None] = mapped_column(Text, nullable=True)  # 生成时一并产出，作答前不下发
    user_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_cause: Mapped[str | None] = mapped_column(String(20), nullable=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)


class Mistake(Base):
    __tablename__ = "mistakes"
    # 列表页查询 = 归属过滤 + created_at 倒序分页，复合索引避免大表全表排序（O-6）
    __table_args__ = (
        Index("ix_mistakes_client_created", "client_id", "created_at"),
        Index("ix_mistakes_user_created", "user_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    question_id: Mapped[str | None] = mapped_column(ForeignKey("questions.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="manual")  # variant/practice/manual
    title: Mapped[str] = mapped_column(Text)        # 题干摘要
    content: Mapped[str] = mapped_column(Text)      # 完整题干
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_cause: Mapped[str | None] = mapped_column(String(20), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(20))
    grade_level: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class History(Base):
    __tablename__ = "histories"
    # 同 Mistake：列表页按归属过滤 + viewed_at 倒序（O-6）
    __table_args__ = (
        Index("ix_histories_client_viewed", "client_id", "viewed_at"),
        Index("ix_histories_user_viewed", "user_id", "viewed_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"))
    viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    subject: Mapped[str] = mapped_column(String(20))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_points.id"), nullable=True)
