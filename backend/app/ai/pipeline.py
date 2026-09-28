"""解析/变式/批改管线：LLM 调用 + Pydantic 结构校验 + 带错误反馈的一次重试

重试策略（与 client._chat 的单次调用配合，每个请求最多 2 次 LLM 调用）：
- 校验类失败（ValueError/ValidationError）：把具体错误拼回 prompt，带反馈重试一次
- 网络类失败（LLMError）：SDK 内部已重试过，直接转 SolveFailed 上抛，不叠加等待
"""
import logging

from pydantic import ValidationError

from ..schemas import SolutionOut
from . import prompts
from .client import LLMError

logger = logging.getLogger(__name__)


class SolveFailed(Exception):
    """LLM 两次输出均无法通过校验（或网络异常）。路由层转 422，提示用户换文字输入。"""


def _validate_solution(data: dict, grade_level: str) -> SolutionOut:
    # 宽容处理：字段缺失给默认空值，关键件缺失才报错
    data.setdefault("steps", [])
    data.setdefault("key_points", [])
    data.setdefault("common_mistakes", [])
    data.setdefault("knowledge_points", [])
    if not data.get("answer"):
        raise ValueError("缺少 answer 字段")
    if not data.get("steps"):
        raise ValueError("缺少 steps 字段")
    if not data.get("subject"):
        data["subject"] = "未识别"
    data["grade_level"] = grade_level
    # steps 规范化：容忍 LLM 输出字符串数组或字段缺失
    norm_steps = []
    for s in data["steps"]:
        if isinstance(s, str):
            norm_steps.append({"title": f"步骤 {len(norm_steps) + 1}", "content": s, "latex": True})
        elif isinstance(s, dict):
            norm_steps.append({
                "title": str(s.get("title") or f"步骤 {len(norm_steps) + 1}"),
                "content": str(s.get("content") or ""),
                "latex": bool(s.get("latex", True)),
            })
    data["steps"] = norm_steps
    return SolutionOut(**data)


async def run_solve(content_text: str, grade_level: str) -> tuple[SolutionOut, int]:
    """解析主链：生成 → 校验 →（带错误反馈重试一次）→ 校验。"""
    try:
        data, tokens = await prompts.solve_question(content_text, grade_level)
        try:
            return _validate_solution(data, grade_level), tokens
        except (ValidationError, ValueError) as e:
            err = _first_error(e)
            logger.warning("解析校验失败，带反馈重试: %s", err)
            data, tokens = await prompts.solve_question(content_text, grade_level, retry_with_error=err)
            return _validate_solution(data, grade_level), tokens
    except LLMError as e:
        logger.error("解析 LLM 网络异常: %s", e)
        raise SolveFailed(f"LLM 网络异常: {e}") from e
    except (ValidationError, ValueError) as e:
        logger.error("解析二次校验失败: %s", _first_error(e))
        raise SolveFailed(_first_error(e)) from e


async def run_solve_vision(image_path: str, grade_level: str) -> tuple[SolutionOut, int]:
    """图片直传两段式视觉链：视觉模型转写题干 → 文本模型标准解析（含重试）。

    阶段1 用 llm_vision_model（能读图）做纯文本转写；阶段2 复用 run_solve
    （llm_model 推理 + 可靠 JSON）。转写作为 steps[0]「题目转写」展示，
    solve.py 依赖该约定把它落为 content_text（历史/变式题复用）。
    """
    try:
        question_text, tokens_t = await prompts.transcribe_question_vision(grade_level, image_path)
    except LLMError as e:
        logger.error("视觉转写 LLM 网络异常: %s", e)
        raise SolveFailed(f"LLM 网络异常: {e}") from e
    except ValueError as e:  # 截断等
        logger.error("视觉转写失败: %s", e)
        raise SolveFailed(f"读图转写失败：{e}") from e
    if not question_text or len(question_text.strip()) < 4:
        raise SolveFailed("未能从图片中读出题目，请拍得更清晰些，或改用文字输入")

    solution, tokens_s = await run_solve(question_text, grade_level)  # 内部自带一次带反馈重试
    solution.steps.insert(0, {"title": "题目转写", "content": question_text})
    return solution, tokens_t + tokens_s


async def run_variants(content_text: str, key_points: list[str], grade_level: str) -> tuple[list[dict], int]:
    try:
        data, tokens = await prompts.generate_variants(content_text, key_points, grade_level)
        try:
            return _validate_variants(data), tokens
        except (ValidationError, ValueError) as e:
            err = _first_error(e)
            logger.warning("变式生成校验失败，带反馈重试: %s", err)
            data, tokens = await prompts.generate_variants(content_text, key_points, grade_level, retry_with_error=err)
            return _validate_variants(data), tokens
    except LLMError as e:
        logger.error("变式生成 LLM 网络异常: %s", e)
        raise SolveFailed(f"LLM 网络异常: {e}") from e
    except (ValidationError, ValueError) as e:
        raise SolveFailed(_first_error(e)) from e


def _validate_variants(data: dict) -> list[dict]:
    items = data.get("items")
    if not isinstance(items, list) or len(items) < 3:
        raise ValueError(f"items 应为 3~5 道题的数组，实际: {type(items).__name__}")
    norm = []
    for i, it in enumerate(items[:5]):
        if not isinstance(it, dict) or not it.get("question"):
            raise ValueError(f"第{i + 1}道变式题缺少 question")
        if not it.get("standard_answer"):
            raise ValueError(f"第{i + 1}道变式题缺少 standard_answer")
        norm.append({
            "difficulty": it.get("difficulty") or "进阶",
            "question": str(it["question"]),
            "standard_answer": str(it["standard_answer"]),
        })
    return norm


async def run_grade(items: list[dict], grade_level: str) -> tuple[list[dict], int]:
    """items: [{seq, question, standard_answer, user_answer}]
    返回 results: [{seq, is_correct, feedback, error_cause}]
    """
    expect_seqs = [it["seq"] for it in items]
    try:
        data, tokens = await prompts.grade_answers(items, grade_level)
        try:
            return _validate_grade(data, expect_seqs), tokens
        except (ValidationError, ValueError) as e:
            err = _first_error(e)
            logger.warning("批改校验失败，带反馈重试: %s", err)
            data, tokens = await prompts.grade_answers(items, grade_level, retry_with_error=err)
            return _validate_grade(data, expect_seqs), tokens
    except LLMError as e:
        logger.error("批改 LLM 网络异常: %s", e)
        raise SolveFailed(f"LLM 网络异常: {e}") from e
    except (ValidationError, ValueError) as e:
        raise SolveFailed(_first_error(e)) from e


def _validate_grade(data: dict, expect_seqs: list[int]) -> list[dict]:
    results = data.get("results")
    if not isinstance(results, list) or len(results) != len(expect_seqs):
        actual = len(results) if isinstance(results, list) else "非数组"
        raise ValueError(f"results 数量应为 {len(expect_seqs)}，实际: {actual}")
    valid_causes = {"概念不清", "审题偏差", "计算失误", "方法缺失"}
    norm = []
    for r in results:
        cause = r.get("error_cause")
        if cause not in valid_causes:
            cause = None
        try:
            seq = int(r.get("seq"))
        except (TypeError, ValueError):
            raise ValueError(f"results 中存在非法 seq: {r.get('seq')!r}")
        norm.append({
            "seq": seq,
            "is_correct": bool(r.get("is_correct")),
            "feedback": str(r.get("feedback") or ""),
            "error_cause": cause if not r.get("is_correct") else None,
        })
    # seq 集合必须与输入题目一一对应，否则路由层 result_map[it.seq] 会 KeyError → 500
    got = sorted(r["seq"] for r in norm)
    if got != sorted(expect_seqs):
        raise ValueError(f"results 的 seq 与题目不匹配: 期望 {sorted(expect_seqs)}，实际 {got}")
    return norm


def _first_error(e: Exception) -> str:
    if isinstance(e, ValidationError):
        return "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()[:3])
    return str(e)
