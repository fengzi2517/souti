"""Prompt 模板：按学段三档分流，避免全学段互相干扰（PRD 风险对策）"""
from .client import chat_json, chat_text_vision

_SOLVE_SCHEMA = """{
  "answer": "最终答案（简洁，含关键过程结论）",
  "steps": [{"title": "步骤名", "content": "推导内容，数学公式用 LaTeX 语法写在 $...$ 中", "latex": true}],
  "key_points": ["考点1", "考点2"],
  "common_mistakes": ["易错点1", "易错点2"],
  "knowledge_points": [{"name": "知识点名", "definition": "定义", "formula": "核心公式(LaTeX)", "tip": "一句话记忆点"}],
  "subject": "数学/物理/化学/语文/英语/其他"
}"""

_GRADE_TONE = {
    "小学": "面向小学生：口语化、亲切，用生活化比喻讲解，避免专业术语，步骤要非常细（不跳步），公式尽量少用。",
    "初中": "面向初中生：清晰规范，适度使用术语，分步推导完整，关键步骤说明'为什么这么做'。",
    "高中": "面向高中生：规范化学术表达，推导严谨高效，可指出多种思路，术语和符号使用规范。",
}


async def solve_question(content_text: str, grade_level: str, *, retry_with_error: str | None = None) -> tuple[dict, int]:
    """生成结构化解析。返回 (solution_dict, tokens)，字段经 pipeline 校验。"""
    system = f"""你是一位经验丰富的{grade_level}全科教师，负责给学生讲解题目。{_GRADE_TONE.get(grade_level, _GRADE_TONE['初中'])}

要求：
1. 严格输出如下 JSON（紧凑格式，不要换行缩进；不要输出任何 JSON 以外的内容）：
{_SOLVE_SCHEMA}
2. steps 至少 2 步，每步 content 中的数学公式必须用 $...$ 包裹的 LaTeX 语法（例如 $x^2+1$、\\frac{{a}}{{b}}）。
3. key_points 提炼 1~4 个核心考点；common_mistakes 指出学生最容易犯的 1~3 个错误。
4. knowledge_points 覆盖本题主要知识点（1~3 个），definition/formula/tip 均不可为空。
5. 若题目信息不足或有歧义，在 answer 中说明假设，仍按最合理理解完整解答。
6. 讲解目标是"教会学生"，不是只给答案。"""
    data, tokens = await chat_json(system, f"请解析这道{grade_level}题目：\n\n{content_text}", retry_with_error=retry_with_error)
    return data, tokens


async def transcribe_question_vision(grade_level: str, image_path: str) -> tuple[str, int]:
    """视觉模型把图中题目转写为纯文本（LaTeX）。只转写不解题——解题交给文本模型。

    两段式设计的依据：网关上 glm-5.2 等推理模型不读图（传入图片会被静默忽略并
    幻觉作答），而能读图的 sensenova-6.8-flash-lite 输出 JSON 不稳；故让视觉
    模型干「看图转写」、文本模型干「结构化解题」，各用所长。
    """
    system = f"你是经验丰富的{grade_level}教辅排版专家，负责把题目图片精准转写为文本。"
    user = """把图片中的题目完整转写为文本，要求：
1. 数学公式用 $...$ 包裹的 LaTeX（分式 \\frac{}{}，上下标 ^ 和 _），几何符号、单位原样保留。
2. 保留题号与所有小问；选择题连同选项一起转写。
3. 若图中有多道题，只转写标号最小/最上方的一道。
4. 只输出题目文本本身，不要输出任何解答、解释或备注。"""
    return await chat_text_vision(system, user, image_path)


async def generate_variants(content_text: str, key_points: list[str], grade_level: str, *, retry_with_error: str | None = None) -> tuple[dict, int]:
    """生成同考点变式题：基础1 / 进阶1~2 / 挑战1，禁止原题原数。"""
    points = "、".join(key_points) if key_points else "本题考点"
    system = f"""你是{grade_level}命题老师。基于原题生成同考点变式题用于举一反三训练。

严格输出 JSON（紧凑单行格式，字段结构为：{{"items":[{{"difficulty":"基础|进阶|挑战","question":"题干","standard_answer":"标准答案与关键步骤"}}]}}，共 4 项）：

规则：
1. 共 4 道：基础 1 道（直接套用考点）、进阶 2 道（换问法或综合一点）、挑战 1 道（迁移情境或加深）。
2. 【禁止】出现与原题相同的数字和问法；变式方式包括换数值、换问法、换情境。
3. 变式题必须与原题考点（{points}）直接相关，难度适合{grade_level}学生。
4. standard_answer 要完整，含判定对错的依据，供后续 AI 批改使用。
5. 数学公式用 LaTeX 写在 $...$ 中。"""
    data, tokens = await chat_json(
        system,
        f"原题（{grade_level}）：\n{content_text}\n\n原题考点：{points}",
        retry_with_error=retry_with_error,
    )
    return data, tokens


async def grade_answers(items: list[dict], grade_level: str, *, retry_with_error: str | None = None) -> tuple[dict, int]:
    """批量批改：items = [{seq, question, standard_answer, user_answer}]
    返回 {results: [{seq, is_correct, feedback, error_cause}]}
    """
    system = f"""你是{grade_level}阅卷老师，批改学生的作答。对每道题判定对错并给出讲评。

严格输出 JSON（紧凑单行格式）：{{"results":[{{"seq":1,"is_correct":true,"feedback":"讲评：为什么对/错，正确思路是什么","error_cause":null}}]}}

规则：
1. results 数量与输入题目数量一致，seq 一一对应。
2. is_correct 判定标准：最终答案正确且思路无明显错误。答案等价形式（如分数与小数）视为正确。
3. error_cause 仅在答错时填写，四选一：概念不清 / 审题偏差 / 计算失误 / 方法缺失。答对填 null。
4. feedback 用鼓励性语气，先指出问题再讲正确思路，数学公式用 LaTeX 写在 $...$ 中。"""
    user_lines = []
    for it in items:
        user_lines.append(
            f"第{it['seq']}题：\n题目：{it['question']}\n标准答案：{it['standard_answer']}\n学生作答：{it['user_answer']}"
        )
    data, tokens = await chat_json(system, "\n\n".join(user_lines), retry_with_error=retry_with_error)
    return data, tokens
