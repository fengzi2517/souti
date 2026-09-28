"""pipeline.py 单测：解析/变式/批改的输出校验（纯函数，不触 LLM/DB）"""
import pytest

from app.ai.pipeline import _first_error, _validate_grade, _validate_solution, _validate_variants
from pydantic import ValidationError


# ---------- _validate_solution ----------

def _solution_payload(**over):
    base = {
        "answer": "42",
        "steps": [{"title": "审题", "content": "略", "latex": True}],
        "key_points": ["一元二次方程"],
        "common_mistakes": ["漏掉负根"],
        "knowledge_points": [],
        "subject": "数学",
    }
    base.update(over)
    return base


def test_validate_solution_ok():
    out = _validate_solution(_solution_payload(), "初中")
    assert out.grade_level == "初中"
    assert out.answer == "42"


def test_validate_solution_missing_answer():
    with pytest.raises((ValueError, ValidationError)):
        _validate_solution(_solution_payload(answer=""), "初中")


def test_validate_solution_missing_steps():
    with pytest.raises((ValueError, ValidationError)):
        _validate_solution(_solution_payload(steps=[]), "初中")


def test_validate_solution_normalizes_string_steps():
    """LLM 偶尔输出字符串数组形式的 steps，应被规范化而非报错。"""
    out = _validate_solution(_solution_payload(steps=["第一步...", "第二步..."]), "高中")
    assert out.steps[0]["title"] == "步骤 1"
    assert out.steps[0]["content"] == "第一步..."


def test_validate_solution_fills_defaults():
    out = _validate_solution({"answer": "1", "steps": [{"title": "t", "content": "c"}]}, "小学")
    assert out.key_points == [] and out.common_mistakes == []
    assert out.subject == "未识别"


# ---------- _validate_variants ----------

def test_validate_variants_ok():
    data = {"items": [
        {"question": f"题{i}", "standard_answer": f"答{i}", "difficulty": "基础"}
        for i in range(3)
    ]}
    norm = _validate_variants(data)
    assert len(norm) == 3 and norm[0]["difficulty"] == "基础"


def test_validate_variants_too_few():
    with pytest.raises(ValueError, match="items"):
        _validate_variants({"items": [{"question": "q", "standard_answer": "a"}]})


def test_validate_variants_missing_answer():
    data = {"items": [{"question": "q", "standard_answer": "a"} for _ in range(3)]}
    data["items"][1] = {"question": "只有题干"}
    with pytest.raises(ValueError, match="standard_answer"):
        _validate_variants(data)


def test_validate_variants_caps_at_five():
    data = {"items": [
        {"question": f"q{i}", "standard_answer": f"a{i}"} for i in range(8)
    ]}
    assert len(_validate_variants(data)) == 5


# ---------- _validate_grade ----------

def test_validate_grade_ok_unordered():
    results = _validate_grade(
        {"results": [
            {"seq": 2, "is_correct": False, "feedback": "f", "error_cause": "概念不清"},
            {"seq": 1, "is_correct": True, "feedback": "ok"},
        ]},
        [1, 2],
    )
    assert sorted(r["seq"] for r in results) == [1, 2]
    # 答对题的 error_cause 强制清空
    assert results[1]["error_cause"] is None


@pytest.mark.parametrize("bad,label", [
    ({"results": [
        {"seq": 0, "is_correct": True, "feedback": ""},
        {"seq": 2, "is_correct": True, "feedback": ""},
    ]}, "seq 越界"),
    ({"results": [
        {"seq": 1, "is_correct": True, "feedback": ""},
        {"seq": 1, "is_correct": True, "feedback": ""},
    ]}, "seq 重复"),
    ({"results": [{"seq": "x", "is_correct": True, "feedback": ""}]}, "seq 非数字"),
    ({"results": [{"seq": 1, "is_correct": True, "feedback": ""}]}, "数量不符"),
    ({"results": "not-a-list"}, "results 非数组"),
])
def test_validate_grade_rejects(bad, label):
    with pytest.raises(ValueError):
        _validate_grade(bad, [1, 2])


def test_validate_grade_invalid_cause_nulled():
    results = _validate_grade(
        {"results": [{"seq": 1, "is_correct": False, "feedback": "f", "error_cause": "胡说八道"}]},
        [1],
    )
    assert results[0]["error_cause"] is None


# ---------- _first_error ----------

def test_first_error_validation_error_readable():
    try:
        _validate_solution({"answer": ""}, "初中")
        raise AssertionError("should have raised")
    except (ValueError, ValidationError) as e:
        msg = _first_error(e)
        assert msg  # 非空即可
