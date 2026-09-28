"""图片上传路由：POST /api/upload + POST /api/ocr —— 开发期存本地 uploads/，生产切 OSS"""
import asyncio
import hashlib
import re
import uuid

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel

from ..config import settings
from ..schemas import UploadResponse

router = APIRouter(prefix="/api", tags=["upload"])

ALLOWED_TYPES = {"image/jpeg": ".jpg", "image/png": ".png"}

# 上传文件名固定为 uuid4 + .png/.jpg，拒绝一切其他形态（防路径穿越）
_SAFE_IMAGE_NAME = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(png|jpg)$")

# 压缩阈值：长边超过该值或体积超过 1MB 才压缩，小图保持原样（省 CPU）
_MAX_LONG_EDGE = 2048
_COMPRESS_THRESHOLD_BYTES = 1024 * 1024


def _compress_image(data: bytes, ext: str) -> tuple[bytes, str]:
    """大图压缩：长边缩到 2048、JPEG 质量 85（O-2）。

    直接影响视觉解析成本——原图 base64 后体积 +33%，10MB 手机照片发给 LLM
    既慢又贵。PNG 透明通道垫白底。解码失败/压完更大时回退原图，不影响主流程。
    """
    from io import BytesIO

    from PIL import Image

    try:
        img = Image.open(BytesIO(data))
        img.load()  # 提前触发解码，坏图在这里抛
    except Exception:
        return data, ext

    if max(img.size) <= _MAX_LONG_EDGE and len(data) <= _COMPRESS_THRESHOLD_BYTES:
        return data, ext

    img.thumbnail((_MAX_LONG_EDGE, _MAX_LONG_EDGE), Image.LANCZOS)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")

    out = BytesIO()
    img.save(out, "JPEG", quality=85, optimize=True)
    compressed = out.getvalue()
    if len(compressed) >= len(data):
        return data, ext  # 压缩无收益（如本身已高度压缩的 JPEG）
    return compressed, ".jpg"


def safe_upload_path(image_id: str) -> Path:
    """校验 image_id 合法性并返回安全路径；非法直接抛 422。"""
    if not image_id or not _SAFE_IMAGE_NAME.match(image_id):
        raise HTTPException(422, "非法的图片标识")
    p = (settings.upload_dir / image_id).resolve()
    # 纵深防御：确保解析后的路径仍在 uploads 目录内
    if not p.is_relative_to(settings.upload_dir.resolve()):
        raise HTTPException(422, "非法的图片标识")
    return p


@router.post("/upload", response_model=UploadResponse)
async def upload_image(file: UploadFile):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(415, "仅支持 JPG/PNG 图片")
    data = await file.read()
    if len(data) > settings.max_image_size:
        raise HTTPException(413, "图片超过 10MB 限制，请压缩后重试")
    if not data:
        raise HTTPException(422, "空文件")

    # 大图压缩（CPU 密集，放线程池）：长边 2048 / JPEG 85，显著降低 LLM 视觉成本
    data, ext = await asyncio.to_thread(_compress_image, data, ALLOWED_TYPES[file.content_type])

    image_id = str(uuid.uuid4()) + ext
    path = settings.upload_dir / image_id
    await asyncio.to_thread(path.write_bytes, data)  # 写盘放线程池，避免阻塞事件循环
    image_hash = hashlib.sha256(data).hexdigest()
    return UploadResponse(
        image_id=image_id,
        image_url=f"/uploads/{image_id}",
        image_hash=image_hash,
    )


class OcrRequest(BaseModel):
    image_id: str


class OcrResponse(BaseModel):
    text: str
    image_url: str


@router.post("/ocr", response_model=OcrResponse)
async def run_ocr(req: OcrRequest):
    """图片确认页：先识别文本供用户编辑确认（带哈希缓存）"""
    from ..ai import ocr as ocr_mod
    from ..services.cache import cache

    p = safe_upload_path(req.image_id)  # 白名单校验，防路径穿越
    if not p.exists():
        raise HTTPException(404, "图片不存在或已过期，请重新上传")
    image_hash = hashlib.sha256(await asyncio.to_thread(p.read_bytes)).hexdigest()
    cached = await cache.get_json(f"ocr:v1:{image_hash}")
    if cached:
        return OcrResponse(text=cached.get("text", ""), image_url=f"/uploads/{req.image_id}")
    try:
        text = await ocr_mod.recognize(str(p))
    except ocr_mod.OCRUnavailable as e:
        raise HTTPException(422, f"图片识别暂不可用：{e}")
    if not text:
        raise HTTPException(422, "未能识别出文字，请拍得更清晰些，或改用文字输入")
    await cache.set_json(f"ocr:v1:{image_hash}", {"text": text}, settings.cache_ttl_ocr)
    return OcrResponse(text=text, image_url=f"/uploads/{req.image_id}")
