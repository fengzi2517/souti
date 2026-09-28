"""client._extract_json 单测：LLM 输出容错解析（纯函数）"""
import pytest

from app.ai.client import _extract_json


def test_plain_json():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_markdown_fenced():
    raw = '```json\n{"a": 1}\n```'
    assert _extract_json(raw) == {"a": 1}


def test_markdown_fenced_no_lang():
    assert _extract_json('```\n{"a": 1}\n```') == {"a": 1}


def test_surrounding_noise():
    raw = '好的，解析如下：{"answer": "42"} 希望有帮助！'
    assert _extract_json(raw) == {"answer": "42"}


def test_nested_braces():
    raw = '前言 {"outer": {"inner": 1}, "tail": true} 后记'
    assert _extract_json(raw)["outer"] == {"inner": 1}


@pytest.mark.parametrize("bad", ["", "完全没有大括号", "{broken json}"])
def test_invalid_raises(bad):
    with pytest.raises(ValueError):
        _extract_json(bad)
