"""OCR 抽象层：双引擎（RapidOCR 默认 / PaddleOCR 备选），子进程隔离，未安装/失败时抛 OCRUnavailable。

引擎选择（.env 的 OCR_ENGINE，见 config.py）：
- auto（默认）：优先 RapidOCR（onnxruntime CPU 推理，快 1~2 个数量级，模型打包在包内），
  未安装再退 PaddleOCR；都未装则不可用
- rapidocr / paddle：强制指定（未安装该引擎则不可用）

注意：必须用 asyncio.create_subprocess_exec（而非线程 + t.join），否则同步 join 会阻塞
整个事件循环，识别期间所有请求（含 /api/health）都会挂起。
"""
import asyncio
import importlib.util
import json
import logging
import os
import sys

from ..config import settings

# paddlex 在 import paddleocr 时（模块级）就会创建 ~/.paddlex 缓存骨架目录，
# 必须在任何 import 发生前把缓存重定向到 D 盘，否则会在 C 盘留垃圾。
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", settings.paddle_cache_dir)

logger = logging.getLogger(__name__)

# OCR 子进程内存开销大，限 1 并发排队（后续可按机器配置调整）
_ocr_sem = asyncio.Semaphore(1)
# 队列深度（正在识别 + 排队等待），供 /api/health 暴露给运维/前端提示（O-4/O-8）
_ocr_queue = 0


class OCRUnavailable(Exception):
    pass


def queue_depth() -> int:
    """当前 OCR 队列深度：>1 说明有请求在排队。"""
    return _ocr_queue


# ---------- 引擎选择 ----------

_engine: str | None = None


def _importable(mod: str) -> bool:
    """只探测包是否已安装（find_spec 不执行模块代码）。

    切勿用 __import__：paddleocr 的 import 会加载整个 paddle（GB 级内存）并在
    ~/.paddlex 建缓存骨架，主进程只做探测付不起这个代价（实测会让 OCR worker
    因双份引擎内存陷入 swap，简单图从 ~20s 劣化到 ~170s）。
    """
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def engine_name() -> str | None:
    """解析当前引擎：rapidocr / paddle / None（不可用）。结果进程内缓存。"""
    global _engine
    if _engine is None:
        want = settings.ocr_engine.strip().lower()
        if want == "rapidocr":
            _engine = "rapidocr" if _importable("rapidocr") else None
        elif want == "paddle":
            _engine = "paddle" if _importable("paddleocr") else None
        else:  # auto：优先 RapidOCR（快），回退 Paddle
            if _importable("rapidocr"):
                _engine = "rapidocr"
            elif _importable("paddleocr"):
                _engine = "paddle"
    return _engine


def is_available() -> bool:
    return engine_name() is not None


# ---------- worker（子进程执行，避免重型库初始化污染主进程内存） ----------

# RapidOCR：本机实测密集大图 ~6s，模型 30MB 打包在包内、无外部缓存
_RAPID_WORKER_CODE = (
    "import json,sys;"
    "from rapidocr import RapidOCR;"
    "r=RapidOCR()(sys.argv[1]);"
    "texts=list(r.txts) if r and r.txts else [];"
    "print(json.dumps({'texts':texts},ensure_ascii=False))"
)

# PaddleOCR：enable_mkldnn=False——Paddle 3.x oneDNN 在部分 Windows CPU 上有 PIR 转换 bug
_PADDLE_WORKER_CODE = (
    "import json,sys;"
    "from paddleocr import PaddleOCR;"
    "ocr=PaddleOCR(use_doc_orientation_classify=False,use_doc_unwarping=False,use_textline_orientation=False,lang='ch',enable_mkldnn=False);"
    "r=ocr.predict(sys.argv[1]);"
    "d=r[0];"
    "texts=list(d['rec_texts']);"
    "print(json.dumps({'texts':texts},ensure_ascii=False))"
)

_WORKER_CODE = {"rapidocr": _RAPID_WORKER_CODE, "paddle": _PADDLE_WORKER_CODE}

# 实测（本机 CPU）：RapidOCR 密集大图 ~6s；Paddle 典型拍题图 ~16s、密集大图可达 ~450s。统一 480s 上限。
_WORKER_TIMEOUT = 480  # 秒

_INSTALL_HINT = "OCR 引擎未安装，请使用文字输入，或执行: pip install -r requirements-ocr.txt"


async def recognize(image_path: str) -> str:
    """识别图片题干文本。不可用/失败时抛 OCRUnavailable，由路由层引导文字输入。"""
    global _ocr_queue
    eng = engine_name()
    if eng is None:
        raise OCRUnavailable(_INSTALL_HINT)

    _ocr_queue += 1
    try:
        return await _recognize_locked(image_path, eng)
    finally:
        _ocr_queue -= 1


async def _recognize_locked(image_path: str, eng: str) -> str:
    async with _ocr_sem:
        # PYTHONIOENCODING=utf-8：确保子进程 stdout 按 UTF-8 输出（Windows 默认 GBK 会乱码）
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        if eng == "paddle":
            # 模型缓存目录由 config.paddle_cache_dir 管理（默认 D 盘，防回写 C 盘 .paddlex）
            env["PADDLE_PDX_CACHE_HOME"] = settings.paddle_cache_dir
            env["DISABLE_MODEL_SOURCE_CHECK"] = "True"
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", _WORKER_CODE[eng], image_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=_WORKER_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise OCRUnavailable("OCR 识别超时")

    if proc.returncode != 0:
        detail = (err or b"ocr worker failed").decode("utf-8", "ignore")[-500:]
        raise OCRUnavailable(f"OCR 识别失败：{detail}")

    # 从 stdout 末尾找 JSON 行（引擎自身日志在前）
    for line in reversed(out.decode("utf-8", "ignore").strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            data = json.loads(line)
            texts = data.get("texts", [])
            # 按行拼接；行序引擎已按版面排序
            return "\n".join(t for t in texts if t and t.strip()).strip()
    raise OCRUnavailable("OCR worker 输出中未找到 JSON")
