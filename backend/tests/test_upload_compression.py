"""O-2 上传图片压缩测试"""
import io
import random

from fastapi.testclient import TestClient
from PIL import Image

from app.config import settings
from app.main import app

client = TestClient(app)


def _noise_png(w: int, h: int, seed: int = 42) -> bytes:
    """随机噪声图：PNG 几乎不可压缩，用于构造 >1MB 的小尺寸图。"""
    rng = random.Random(seed)
    img = Image.new("RGB", (w, h))
    img.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(w * h)])
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _teardown(image_id: str):
    p = settings.upload_dir / image_id
    if p.exists():
        p.unlink()


def test_big_blob_compressed_to_jpeg():
    data = _noise_png(600, 600)  # ~1.1MB PNG
    assert len(data) > 1024 * 1024
    r = client.post("/api/upload", files={"file": ("big.png", data, "image/png")})
    assert r.status_code == 200
    body = r.json()
    assert body["image_id"].endswith(".jpg")  # 触发压缩转 JPEG
    with Image.open(settings.upload_dir / body["image_id"]) as img:
        assert max(img.size) <= 2048
    _teardown(body["image_id"])


def test_small_image_untouched():
    data = _noise_png(80, 80, seed=7)  # 小图（体积与尺寸都在阈值内）
    r = client.post("/api/upload", files={"file": ("small.png", data, "image/png")})
    assert r.status_code == 200
    body = r.json()
    assert body["image_id"].endswith(".png")  # 原样保存
    _teardown(body["image_id"])


def test_compress_unit_thresholds():
    """_compress_image 纯函数：坏图回退原样。"""
    from app.routers.upload import _compress_image

    bad = b"\x89PNG\r\n\x1a\nnot-really-a-png"
    out, ext = _compress_image(bad, ".png")
    assert out == bad and ext == ".png"
