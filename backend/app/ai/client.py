"""LLM 客户端：OpenAI 兼容 SDK，环境变量切换任意模型（当前 SenseNova）
支持纯文本与图片直传（视觉解析）两种调用。
"""
import asyncio
import base64
import json
import logging
import re
from pathlib import Path

from openai import AsyncOpenAI

from ..config import settings

logger = logging.getLogger(__name__)
_client = AsyncOpenAI(
    base_url=settings.llm_base_url,
    api_key=settings.llm_api_key,
    timeout=settings.llm_timeout,
    max_retries=1,  # SDK 内部对网络错误重试 1 次；校验类重试由 pipeline 带 retry_with_error 控制
)


class LLMError(Exception):
    """网络/超时类 LLM 调用异常。区别于输出校验失败：不做带反馈重试，直接上抛。"""


async def _image_data_url(image_path: str) -> str:
    """读图 + base64 放线程池：10MB 图片的同步读盘会阻塞事件循环。"""
    suffix = Path(image_path).suffix.lower().lstrip(".")
    if suffix == "jpg":
        suffix = "jpeg"
    data = await asyncio.to_thread(Path(image_path).read_bytes)  # 绑定方法，不能再传参
    b64 = base64.b64encode(data).decode()
    return f"data:image/{suffix};base64,{b64}"


async def _chat(messages: list, *, retry_with_error: str | None = None, model: str | None = None) -> tuple[dict, int]:
    """单次调用并强制 JSON 输出。

    - retry_with_error：上一次校验失败的错误说明，拼进 prompt 让模型针对性修正
    - 网络/超时异常：抛 LLMError（SDK 内部已重试过一次，这里不再叠加）
    - 输出问题（截断 / JSON 非法）：抛 ValueError，由 pipeline 层带反馈重试
    """
    if retry_with_error:
        messages = [dict(m) for m in messages]
        last = messages[-1]
        extra = f"\n\n【注意】你上一次的输出未通过校验：{retry_with_error}\n请严格修正后重新输出完整 JSON。"
        if isinstance(last["content"], str):
            last["content"] += extra
        else:  # 多模态 content 数组
            last["content"] = last["content"] + [{"type": "text", "text": extra}]

    try:
        resp = await _client.chat.completions.create(
            model=model or settings.llm_model,
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=settings.llm_max_tokens,
            temperature=0.1 if retry_with_error else 0.3,  # 重试时降低随机性
        )
    except Exception as e:  # 超时/网络错误
        logger.warning("LLM 调用异常: %s", e)
        raise LLMError(f"{type(e).__name__}: {e}") from e

    raw = resp.choices[0].message.content or ""
    usage = getattr(resp, "usage", None)
    finish = resp.choices[0].finish_reason
    logger.info("LLM finish=%s tokens=%s retry=%s", finish, usage.total_tokens if usage else "?", bool(retry_with_error))
    if finish == "length":
        logger.warning("输出被截断 finish=length")
        raise ValueError("输出因长度限制被截断，请大幅精简内容（优先精简 steps 与 knowledge_points）后重新输出")
    data = _extract_json(raw)
    if not isinstance(data, dict):
        raise ValueError("顶层不是 JSON 对象")
    return data, (usage.total_tokens if usage else 0)


async def chat_json(system: str, user: str, *, retry_with_error: str | None = None) -> tuple[dict, int]:
    """纯文本调用。"""
    return await _chat([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], retry_with_error=retry_with_error)


async def chat_text_vision(system: str, user: str, image_path: str) -> tuple[str, int]:
    """视觉模型纯文本输出（读图转写用）。

    不走 _chat 的 JSON 强制链：网关上可读图的 flash 级模型对 response_format
    支持不稳（时而输出 markdown 散文），而「看图说话」本身就是它最可靠的任务形态。
    解题 JSON 由文本模型在后续阶段完成（见 pipeline.run_solve_vision 两段式）。
    """
    data_url = await _image_data_url(image_path)
    try:
        resp = await _client.chat.completions.create(
            model=settings.llm_vision_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": user},
                ]},
            ],
            temperature=0.1,
        )
    except Exception as e:  # 超时/网络错误
        logger.warning("LLM 视觉调用异常: %s", e)
        raise LLMError(f"{type(e).__name__}: {e}") from e
    raw = (resp.choices[0].message.content or "").strip()
    usage = getattr(resp, "usage", None)
    if resp.choices[0].finish_reason == "length":
        raise ValueError("视觉转写输出被截断")
    # 容错剥掉模型偶尔加的 markdown 围栏
    m = re.search(r"```(?:\w+)?\s*(.*?)```", raw, re.DOTALL)
    if m:
        raw = m.group(1).strip()
    return raw, (usage.total_tokens if usage else 0)


def _extract_json(raw: str) -> dict:
    """容忍 markdown 代码块包裹 / 前后杂文本。"""
    raw = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    if m:
        raw = m.group(1).strip()
    # 直接解析，失败则截取首个 { 到末个 }
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("输出中未找到 JSON 对象")
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON 语法错误: {e}")
