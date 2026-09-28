"""API 契约模型（Pydantic v2）：与开发规划第 3 章冻结的接口一一对应"""
from pydantic import BaseModel, Field


# ---------- 解析 ----------
class SolveRequest(BaseModel):
    image_id: str | None = None      # 二选一：图片（走 OCR）
    text: str | None = None          # 二选一：文字题干
    grade_level: str = "初中"         # 小学/初中/高中
    subject: str | None = None
    direct_image: bool = False       # 图片直传 LLM 视觉解析（跳过 OCR，公式题保底）


class KnowledgePointOut(BaseModel):
    name: str
    definition: str = ""
    formula: str = ""
    tip: str = ""


class SolutionOut(BaseModel):
    answer: str
    steps: list[dict]                # [{title, content, latex}]
    key_points: list[str]
    common_mistakes: list[str]
    knowledge_points: list[KnowledgePointOut]
    grade_level: str
    subject: str


class SolveResponse(BaseModel):
    question_id: str
    cached: bool = False
    solution: SolutionOut


# ---------- 解析任务轮询（O-1） ----------
class SolveTaskStartResponse(BaseModel):
    """POST /api/solve 立即返回：缓存命中直接 done，否则给 task_id 轮询。"""
    task_id: str | None = None
    status: str                      # done / pending
    question_id: str | None = None   # status=done 时给出
    cached: bool = False


class SolveTaskStatusResponse(BaseModel):
    """GET /api/tasks/{task_id}：pending → running → done / failed。"""
    task_id: str
    status: str                      # pending / running / done / failed
    question_id: str | None = None
    cached: bool = False
    error: str | None = None


# ---------- 变式题 ----------
class VariantGenerateRequest(BaseModel):
    question_id: str
    refresh: bool = False            # 换一套：绕过缓存重新生成


class PracticeItemOut(BaseModel):
    item_id: str
    question: str
    difficulty: str                  # 基础/进阶/挑战
    seq: int


class PracticeSetOut(BaseModel):
    set_id: str
    question_id: str                 # 原题 ID（前端"换一套"要用）
    cached: bool = False             # 命中缓存秒回
    items: list[PracticeItemOut]


class AnswerItem(BaseModel):
    item_id: str
    user_answer: str


class PracticeSubmitRequest(BaseModel):
    set_id: str
    answers: list[AnswerItem]


class GradeResultItem(BaseModel):
    item_id: str
    is_correct: bool
    standard_answer: str
    user_answer: str = ""            # 学生作答回显（结果页展示）
    feedback: str                    # 讲评
    error_cause: str | None = None   # 概念不清/审题偏差/计算失误/方法缺失/为空(答对)


class PracticeSubmitResponse(BaseModel):
    set_id: str
    results: list[GradeResultItem]


class PracticeResultResponse(BaseModel):
    """批改结果回源：题目 + 批改结果（结果页刷新恢复用）"""
    set_id: str
    question_id: str                 # 原题 ID（结果页"换一套"入口）
    items: list[PracticeItemOut]
    results: list[GradeResultItem]


# ---------- 错题本 / 历史 ----------
class MistakeOut(BaseModel):
    id: int
    question_id: str | None
    source: str
    title: str
    content: str
    answer: str | None
    error_cause: str | None
    subject: str | None
    grade_level: str | None
    created_at: str


class MistakeListResponse(BaseModel):
    total: int
    items: list[MistakeOut]


class HistoryItemOut(BaseModel):
    question_id: str
    content_text: str
    subject: str | None
    grade_level: str
    created_at: str


class HistoryListResponse(BaseModel):
    total: int
    items: list[HistoryItemOut]


# ---------- 上传 ----------
class UploadResponse(BaseModel):
    image_id: str
    image_url: str
    image_hash: str
